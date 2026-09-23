from __future__ import annotations

import logging
import pathlib

import pytest

from hyrum import _enumerate

from .conftest import make_charm


@pytest.fixture
def cache(tmp_path: pathlib.Path) -> pathlib.Path:
    """A cache folder shaped the way ``get-charms`` writes it."""
    folder = tmp_path / 'cache'
    folder.mkdir()
    return folder


@pytest.fixture
def owner(cache: pathlib.Path) -> pathlib.Path:
    """The owner directory repositories are cloned under."""
    folder = cache / 'canonical'
    folder.mkdir()
    return folder


def test_flat_layout(charm_cache: pathlib.Path):
    make_charm(charm_cache / 'alpha')
    make_charm(charm_cache / 'beta')
    found = sorted(p.name for p in _enumerate.iter_charm_repos(charm_cache))
    assert found == ['alpha', 'beta']


def test_dotdirs_ignored(charm_cache: pathlib.Path):
    make_charm(charm_cache / 'alpha')
    make_charm(charm_cache / '.git')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['alpha']


def test_bundle_expands_to_inner_charms(charm_cache: pathlib.Path):
    bundle = charm_cache / 'my-bundle'
    bundle.mkdir()
    (bundle / 'bundle.yaml').write_text('applications: {}\n')
    make_charm(bundle / 'charms' / 'inner-a')
    make_charm(bundle / 'charms' / 'inner-b')
    found = sorted(p.name for p in _enumerate.iter_charm_repos(charm_cache))
    assert found == ['inner-a', 'inner-b']


def test_monorepo_with_charm_subdirs(charm_cache: pathlib.Path):
    mono = charm_cache / 'operators'
    mono.mkdir()
    make_charm(mono / 'controller')
    make_charm(mono / 'agent')
    # Bare subdir without charm markers is ignored.
    (mono / 'docs').mkdir()
    found = sorted(p.name for p in _enumerate.iter_charm_repos(charm_cache))
    assert found == ['agent', 'controller']


def test_legacy_charms_yielded_for_filter_layer(charm_cache: pathlib.Path):
    """Enumeration is layout-only; the not_legacy filter drops these."""
    legacy = make_charm(charm_cache / 'legacy')
    (legacy / 'reactive').mkdir()
    make_charm(charm_cache / 'modern')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['legacy', 'modern']


def test_missing_cache_raises(tmp_path: pathlib.Path):
    with pytest.raises(FileNotFoundError):
        list(_enumerate.iter_charm_repos(tmp_path / 'missing'))


def test_monorepo_charms_nested_deeper_than_one_level(owner: pathlib.Path, cache: pathlib.Path):
    """Charms below the first directory level are found, not silently dropped."""
    mono = owner / 'operators'
    make_charm(mono / 'charms' / 'controller')
    make_charm(mono / 'stacks' / 'observability' / 'agent')
    found = sorted(p.name for p in _enumerate.iter_charm_repos(cache))
    assert found == ['agent', 'controller']


def test_single_charm_in_a_subdirectory(owner: pathlib.Path, cache: pathlib.Path):
    """A charm tucked into a subdirectory of a larger repo is found."""
    make_charm(owner / 'some-project' / 'charm')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['charm']


def test_depth_is_counted_from_the_repository_root(owner: pathlib.Path, cache: pathlib.Path):
    """_MAX_DEPTH is three levels below a repo, not below the cache folder.

    The cache has an owner level (get-charms clones into <owner>/<leaf>), so
    counting from the cache folder would spend the budget one level early and
    leave this charm - the shape the PR was written for - undiscovered.
    """
    make_charm(owner / 'repo' / 'stacks' / 'observability' / 'agent')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['agent']


def test_recursion_stops_at_the_depth_bound(owner: pathlib.Path, cache: pathlib.Path):
    make_charm(owner / 'deep' / 'a' / 'b' / 'c' / 'too-far')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == []


def test_recursion_does_not_descend_into_a_found_charm(owner: pathlib.Path, cache: pathlib.Path):
    """A charm is yielded whole; its own nested charm dirs are not walked."""
    outer = owner / 'repo' / 'outer'
    make_charm(outer)
    make_charm(outer / 'tests' / 'integration' / 'fixture')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['outer']


def test_pruned_directories_are_not_searched(owner: pathlib.Path, cache: pathlib.Path):
    make_charm(owner / 'repo' / 'lib' / 'charms' / 'vendored')
    make_charm(owner / 'repo' / 'tests' / 'fixture')
    make_charm(owner / 'repo' / 'charms' / 'real')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['real']


@pytest.mark.parametrize('pruned', ['examples', 'demo', 'spread', 'templates', 'fixtures'])
def test_fixture_charms_are_not_run_as_charms(
    pruned: str, owner: pathlib.Path, cache: pathlib.Path
):
    """A charm under examples/ is a fixture, and running lint on it is noise.

    It fails quietly if enumerated: the tally gains a failed charm keyed
    <owner>/<repo>/examples/<name>, and `compare` reads it as charm-set drift
    the next time someone adds or removes a fixture.
    """
    make_charm(owner / 'repo' / pruned / 'fixture')
    make_charm(owner / 'repo' / 'charms' / 'real')
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['real']


def test_symlinked_directories_are_not_followed(owner: pathlib.Path, cache: pathlib.Path):
    repo = owner / 'repo'
    make_charm(repo / 'charms' / 'real')
    (repo / 'loop').symlink_to(repo, target_is_directory=True)
    found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['real']


def test_repo_with_no_charms_is_logged(
    owner: pathlib.Path, cache: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    """The warning names the repository, which is the unit the count is of."""
    (owner / 'not-a-charm' / 'docs').mkdir(parents=True)
    make_charm(owner / 'alpha')
    with caplog.at_level(logging.WARNING, logger='hyrum._enumerate'):
        found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['alpha']
    assert 'No charm found in' in caplog.text
    assert str(owner / 'not-a-charm') in caplog.text


def test_a_charmless_repo_under_a_productive_owner_is_still_logged(
    owner: pathlib.Path, cache: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    """The owner having charms must not hide a repo that has none.

    Nearly every repo in the collection sits under one of a handful of owners,
    so a warning attributed to the owner never fires in practice.
    """
    make_charm(owner / 'has-a-charm')
    (owner / 'has-none' / 'docs').mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger='hyrum._enumerate'):
        list(_enumerate.iter_charm_repos(cache))
    assert 'has-none' in caplog.text


def test_a_nested_bundle_without_charms_is_not_warned_about(
    owner: pathlib.Path, cache: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    """An archive of past releases holds dozens of them, and none is a problem."""
    make_charm(owner / 'repo' / 'charms' / 'real')
    for release in ('1.14', '1.15'):
        old = owner / 'repo' / 'bundle' / 'releases' / release
        old.mkdir(parents=True)
        (old / 'bundle.yaml').write_text('applications: {}\n')
    with caplog.at_level(logging.WARNING, logger='hyrum._enumerate'):
        found = [p.name for p in _enumerate.iter_charm_repos(cache)]
    assert found == ['real']
    assert caplog.text == ''


def test_a_repo_that_is_a_bundle_without_charms_is_warned_about_once(
    owner: pathlib.Path, cache: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    """One line, and it says the bundle has no charms/ rather than guessing."""
    bundle = owner / 'my-bundle'
    bundle.mkdir(parents=True)
    (bundle / 'bundle.yaml').write_text('applications: {}\n')
    with caplog.at_level(logging.WARNING, logger='hyrum._enumerate'):
        assert list(_enumerate.iter_charm_repos(cache)) == []
    assert len(caplog.records) == 1
    assert 'has no charms/ directory' in caplog.text
