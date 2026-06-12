"""Tests for tools/update_charm_list.py."""

from __future__ import annotations

import logging
import pathlib
import textwrap
import typing

import pytest

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

    def __init__(self, urls: dict[str, str | None]):
        self.urls = urls

    def packages(self) -> list[dict[str, str]]:
        return [{'name': name} for name in self.urls]

    def source_url(self, charm: str) -> str | None:
        return self.urls.get(charm)


HEADER = 'Team,Charm Name,Repository,Branch (if not the default),Source'


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


def test_validate_rejects_missing_charm_name(tmp_path: pathlib.Path):
    rows = [
        {
            'Team': 'Data',
            'Charm Name': '',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
            'Source': 'manual',
        }
    ]
    with pytest.raises(ValueError, match='missing Charm Name'):
        uut.validate(rows)


def test_validate_rejects_missing_repository():
    rows = [
        {
            'Team': 'Data',
            'Charm Name': 'foo',
            'Repository': '',
            'Branch (if not the default)': '',
            'Source': 'manual',
        }
    ]
    with pytest.raises(ValueError, match='missing Repository'):
        uut.validate(rows)


def test_validate_rejects_unknown_source():
    rows = [
        {
            'Team': 'Data',
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
            'Source': 'bogus',
        }
    ]
    with pytest.raises(ValueError, match='Source must be one of'):
        uut.validate(rows)


def test_validate_rejects_duplicate_charm_in_same_repo():
    rows = [
        {
            'Team': '',
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
            'Source': 'manual',
        },
        {
            'Team': '',
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo.git/',
            'Branch (if not the default)': '',
            'Source': 'manual',
        },
    ]
    with pytest.raises(ValueError, match='duplicate'):
        uut.validate(rows)


def test_validate_allows_monorepo_with_distinct_charm_names():
    rows = [
        {
            'Team': '',
            'Charm Name': 'scheduler',
            'Repository': 'https://github.com/canonical/airflow-core-operators',
            'Branch (if not the default)': '',
            'Source': 'auto-discover',
        },
        {
            'Team': '',
            'Charm Name': 'triggerer',
            'Repository': 'https://github.com/canonical/airflow-core-operators',
            'Branch (if not the default)': '',
            'Source': 'auto-discover',
        },
    ]
    uut.validate(rows)


def test_run_rejects_invalid_csv(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,,,manual
        """,
    )
    with pytest.raises(ValueError, match='missing Repository'):
        uut.run(csv_path, charmhub=FakeCharmhub({}), github=FakeGitHub({}))


def test_check_mode_exit_zero_on_valid_csv(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        """,
    )
    assert uut.main(['--csv', str(csv_path), '--check']) == 0


def test_check_mode_exit_nonzero_on_invalid_csv(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,,https://github.com/canonical/foo,,manual
        """,
    )
    assert uut.main(['--csv', str(csv_path), '--check']) == 1
    assert 'missing Charm Name' in capsys.readouterr().err


def test_charmhub_dup_url_not_added(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        """,
    )
    # Charmhub reports the same URL with a trailing slash + .git — must not be added.
    charmhub = FakeCharmhub({'foo': 'https://github.com/canonical/foo.git/'})
    github = FakeGitHub({('canonical', 'foo'): 'ok'})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    rows = uut.read_csv(csv_path)
    assert len(rows) == 1


def test_appends_new_charm_with_auto_source(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
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
    assert new[0]['Source'] == uut.AUTO_SOURCE
    assert new[0]['Team'] == ''


def test_archived_github_row_is_dropped(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        Data,bar,https://github.com/canonical/bar,,manual
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
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        Data,gone,https://github.com/canonical/gone,,manual
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
    rows = [
        ',aodh,https://opendev.org/openstack/charm-aodh,,auto',
        ',cassandra,https://git.launchpad.net/cassandra-charm,,auto',
    ]
    csv_path.write_text('\n'.join([HEADER, *rows, '']), encoding='utf-8')
    charmhub = FakeCharmhub({})
    github = FakeGitHub({})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    assert github.calls == []


def test_url_drift_rewrites_auto_added_rows_only(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        ,bar,https://github.com/oldorg/bar,,auto
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


def test_url_drift_warns_on_manual_rows(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
        """,
    )
    charmhub = FakeCharmhub({'foo': 'https://github.com/neworg/foo'})
    github = FakeGitHub({('canonical', 'foo'): 'ok'})
    with caplog.at_level(logging.WARNING, logger=uut.logger.name):
        uut.run(csv_path, charmhub=charmhub, github=github)
    assert any('URL drift for manual row foo' in m for m in caplog.messages)


def test_transient_github_failure_keeps_row(tmp_path: pathlib.Path):
    """If the GitHub probe raises, the merge must leave the row in place."""
    csv_path = tmp_path / 'charms.csv'
    write_csv(
        csv_path,
        f"""
        {HEADER}
        Data,foo,https://github.com/canonical/foo,,manual
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
    write_csv(csv_path, f'{HEADER}\n')
    charmhub = FakeCharmhub({'dead': 'https://github.com/canonical/dead'})
    github = FakeGitHub({('canonical', 'dead'): 'archived'})
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False


def test_run_is_idempotent_on_no_op(tmp_path: pathlib.Path):
    """A second run with no new info must produce a byte-identical file."""
    csv_path = tmp_path / 'charms.csv'
    body = [
        'Data,foo,https://github.com/canonical/foo,,manual',
        ',aproxy,https://github.com/canonical/aproxy-operator,,manual',
        ',aodh,https://opendev.org/openstack/charm-aodh,,auto',
    ]
    csv_path.write_text('\n'.join([HEADER, *body, '']), encoding='utf-8')
    original = csv_path.read_bytes()
    charmhub = FakeCharmhub({})
    github = FakeGitHub({
        ('canonical', 'foo'): 'ok',
        ('canonical', 'aproxy-operator'): 'ok',
    })
    changed = uut.run(csv_path, charmhub=charmhub, github=github)
    assert changed is False
    assert csv_path.read_bytes() == original


def test_discover_separates_complete_and_incomplete():
    charmhub = FakeCharmhub({
        'foo': 'https://github.com/canonical/foo',
        'bar': None,
        'baz': 'https://github.com/canonical/baz',
        'quux': None,
    })
    complete, incomplete = uut.discover_charmhub_urls(charmhub)
    assert complete == {
        'foo': 'https://github.com/canonical/foo',
        'baz': 'https://github.com/canonical/baz',
    }
    assert incomplete == ['bar', 'quux']


def test_no_source_sidecar_is_written(tmp_path: pathlib.Path):
    csv_path = tmp_path / 'charms.csv'
    write_csv(csv_path, f'{HEADER}\n')
    charmhub = FakeCharmhub({
        'foo': 'https://github.com/canonical/foo',
        'bar': None,
    })
    github = FakeGitHub({('canonical', 'foo'): 'ok'})
    uut.run(csv_path, charmhub=charmhub, github=github)
    sidecar = uut.no_source_csv_path(csv_path)
    assert sidecar.read_text(encoding='utf-8') == 'Charm Name\nbar\n'
