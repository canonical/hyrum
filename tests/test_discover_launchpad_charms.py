"""Tests for tools/discover_launchpad_charms.py."""

from __future__ import annotations

from tools import discover_launchpad_charms as uut


class FakeClient:
    """Stand-in for LaunchpadClient.head with a canned remote -> HEAD table."""

    def __init__(self, heads: dict[str, str | None]):
        self.heads = heads
        self.calls: list[str] = []

    def head(self, repository: str) -> str | None:
        self.calls.append(repository)
        return self.heads.get(repository)


LP = 'https://git.launchpad.net/charm-keystone'
OD = 'https://opendev.org/openstack/charm-keystone'


def test_prefers_opendev_when_the_mirror_is_identical():
    client = FakeClient({LP: 'abc123', OD: 'abc123'})
    assert uut.prefer_opendev_mirror(LP, client) == OD


def test_keeps_launchpad_when_opendev_lacks_the_repo():
    client = FakeClient({LP: 'abc123'})  # opendev returns None
    assert uut.prefer_opendev_mirror(LP, client) == LP


def test_keeps_launchpad_when_the_mirrors_disagree():
    """A diverged mirror must never be silently substituted."""
    client = FakeClient({LP: 'abc123', OD: 'def456'})
    assert uut.prefer_opendev_mirror(LP, client) == LP


def test_keeps_launchpad_when_launchpad_is_unreachable():
    client = FakeClient({OD: 'abc123'})  # launchpad returns None
    assert uut.prefer_opendev_mirror(LP, client) == LP


def test_non_charm_repos_are_left_alone_without_probing():
    """Only ``charm-`` repos are OpenStack charms; skip the network otherwise."""
    url = 'https://git.launchpad.net/content-cache-charm'
    client = FakeClient({})
    assert uut.prefer_opendev_mirror(url, client) == url
    assert client.calls == []


def test_discover_emits_the_opendev_url(monkeypatch):
    """The rewrite is applied to the rows discover() returns."""
    monkeypatch.setattr(uut, 'first_marker', lambda *a, **k: 'charmcraft.yaml')

    class Client(FakeClient):
        def team_repositories(self, team: str):
            yield {'git_https_url': LP, 'default_branch': 'refs/heads/main'}

    client = Client({LP: 'abc123', OD: 'abc123'})
    rows = uut.discover(client, ['openstack-charmers'])

    assert [r['Repository'] for r in rows] == [OD]
