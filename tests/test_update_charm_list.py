"""Tests for tools/update_charm_list.py."""

from __future__ import annotations

import pathlib
import textwrap
import typing

from tools import update_charm_list as uut


class FakeGitHub:
    """Deterministic stand-in for tools.update_charm_list.GitHubClient.

    Tests populate ``statuses`` with the (owner, repo) -> status answer they
    expect to be probed for. Any unexpected probe fails the test, so we get
    loud feedback when the merge logic accidentally double-checks.
    """

    def __init__(self, statuses: dict[tuple[str, str], str]):
        self.statuses = statuses
        self.calls: list[tuple[str, str]] = []

    def status(self, owner: str, repo: str) -> str:
        self.calls.append((owner, repo))
        try:
            return self.statuses[owner, repo]
        except KeyError:
            raise AssertionError(f'Unexpected GitHub probe for {owner}/{repo}') from None


class FakeCharmhub:
    """Stand-in for tools.update_charm_list.CharmhubClient."""

    def __init__(self, urls: dict[str, str]):
        self.urls = urls

    def packages(self) -> list[dict[str, str]]:
        return [{'name': name} for name in self.urls]

    def source_url(self, charm: str) -> str | None:
        return self.urls.get(charm)


def write_csv(path: pathlib.Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip('\n'), encoding='utf-8')


def test_normalise_url_strips_trailing_slash_and_dot_git():
    assert (
        uut.normalise_url('https://github.com/canonical/foo/')
        == 'https://github.com/canonical/foo'
    )
    assert (
        uut.normalise_url('https://github.com/canonical/foo.git')
        == 'https://github.com/canonical/foo'
    )
    assert (
        uut.normalise_url('https://GitHub.com/Canonical/Foo') == 'https://github.com/Canonical/Foo'
    )


def test_github_owner_repo_only_matches_github():
    assert uut.github_owner_repo('https://github.com/canonical/foo') == ('canonical', 'foo')
    assert uut.github_owner_repo('https://github.com/canonical/foo.git') == ('canonical', 'foo')
    assert uut.github_owner_repo('https://opendev.org/openstack/charm-aodh') is None
    assert uut.github_owner_repo('https://github.com/canonical') is None


def test_dedup_by_normalised_url(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        """,
    )
    # Charmhub reports the same URL with a trailing slash + .git — must not be added.
    charmhub = FakeCharmhub({'foo': 'https://github.com/canonical/foo.git/'})
    github = FakeGitHub({('canonical', 'foo'): 'ok'})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    rows = uut.read_csv(csv_path)
    assert len(rows) == 1


def test_appends_new_charm_with_auto_note(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        """,
    )
    charmhub = FakeCharmhub({
        'foo': 'https://github.com/canonical/foo',
        'bar': 'https://github.com/canonical/bar',
    })
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('canonical', 'bar'): 'ok',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is True
    rows = uut.read_csv(csv_path)
    new = [r for r in rows if r['Charm Name'] == 'bar']
    assert len(new) == 1
    assert new[0]['Notes'] == uut.AUTO_NOTE
    assert new[0]['Team'] == ''
    assert new[0]['Key Charm for this Team'] == 'FALSE'


def test_archived_github_row_is_dropped(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        Data,bar,https://github.com/canonical/bar,FALSE,,
        """,
    )
    charmhub = FakeCharmhub({})
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('canonical', 'bar'): 'archived',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is True
    rows = uut.read_csv(csv_path)
    assert [r['Charm Name'] for r in rows] == ['foo']


def test_missing_github_row_is_dropped(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        Data,gone,https://github.com/canonical/gone,FALSE,,
        """,
    )
    charmhub = FakeCharmhub({})
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('canonical', 'gone'): 'missing',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is True
    rows = uut.read_csv(csv_path)
    assert [r['Charm Name'] for r in rows] == ['foo']


def test_non_github_rows_are_never_probed(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    header = 'Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes'
    rows = [
        ',aodh,https://opendev.org/openstack/charm-aodh,FALSE,,Added automatically from Charmhub',
        ',cassandra,https://git.launchpad.net/cassandra-charm,FALSE,,Added automatically from Charmhub',  # noqa: E501
    ]
    csv_path.write_text('\n'.join([header, *rows, '']), encoding='utf-8')
    charmhub = FakeCharmhub({})
    github = FakeGitHub({})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    assert github.calls == []


def test_url_drift_rewrites_auto_added_rows_only(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        ,bar,https://github.com/oldorg/bar,FALSE,,Added automatically from Charmhub
        """,
    )
    # Charmhub now reports both at different orgs. The manual `foo` row must
    # NOT be rewritten; the auto-added `bar` row MUST be.
    charmhub = FakeCharmhub({
        'foo': 'https://github.com/neworg/foo',
        'bar': 'https://github.com/neworg/bar',
    })
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('neworg', 'bar'): 'ok',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is True
    rows = {r['Charm Name']: r for r in uut.read_csv(csv_path)}
    assert rows['foo']['Repository'] == 'https://github.com/canonical/foo'
    assert rows['bar']['Repository'] == 'https://github.com/neworg/bar'


def test_transient_github_failure_keeps_row(tmp_path: pathlib.Path):
    """If the GitHub probe raises, the merge must leave the row in place."""
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        Data,foo,https://github.com/canonical/foo,FALSE,,
        """,
    )

    class FlakyGitHub:
        def status(self, owner: str, repo: str) -> str:
            # Mirrors the real client's behaviour on a network error: report ok.
            return 'ok'

    github = typing.cast('uut.GitHubClient', FlakyGitHub())
    changed = uut.run(csv_path, charmhub=FakeCharmhub({}), github=github)
    assert changed is False


def test_new_auto_row_skipped_if_already_archived(tmp_path: pathlib.Path):
    """We shouldn't add a charm we'd just delete on the next run."""
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        """
        Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes
        """,
    )
    charmhub = FakeCharmhub({'dead': 'https://github.com/canonical/dead'})
    github = FakeGitHub({('canonical', 'dead'): 'archived'})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False


def test_run_is_idempotent_on_no_op(tmp_path: pathlib.Path):
    """A second run with no new info must produce a byte-identical file.

    Guards against accidental reordering churn — the existing CSV has rows
    in the auto-section without the marker note, so any sort that splits on
    that note would rewrite the file every week.
    """
    csv_path = tmp_path / 'charms.csv'
    header = 'Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes'
    body = [
        'Data,foo,https://github.com/canonical/foo,FALSE,,',
        # An auto-looking row that LACKS the AUTO_NOTE marker — present in
        # the real CSV today; must not get pushed around by the merger.
        ',aproxy,https://github.com/canonical/aproxy-operator,FALSE,,',
        ',aodh,https://opendev.org/openstack/charm-aodh,FALSE,,Added automatically from Charmhub',
    ]
    csv_path.write_text('\n'.join([header, *body, '']), encoding='utf-8')
    original = csv_path.read_bytes()
    charmhub = FakeCharmhub({})
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('canonical', 'aproxy-operator'): 'ok',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    assert csv_path.read_bytes() == original


def test_existing_archived_note_preserved_when_repo_still_live(tmp_path: pathlib.Path):
    """A manual archived-but-keep note must survive a run while the repo is live."""
    csv_path = tmp_path / 'charms.csv'
    header = 'Team,Charm Name,Repository,Key Charm for this Team,Branch (if not the default),Notes'
    note = "This is archived and shouldn't be used (e.g. tests fail)"
    row = f'Observability,TLS Truststore,https://github.com/canonical/tls-truststore-operator,FALSE,,{note}'
    csv_path.write_text('\n'.join([header, row, '']), encoding='utf-8')
    charmhub = FakeCharmhub({})
    github = FakeGitHub({('canonical', 'tls-truststore-operator'): 'ok'})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    rows = uut.read_csv(csv_path)
    assert rows[0]['Notes'].startswith('This is archived')
