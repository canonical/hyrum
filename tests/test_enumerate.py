from __future__ import annotations

import logging
import pathlib

import pytest

from hyrum import _enumerate

from .conftest import make_charm


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


def test_monorepo_charms_nested_deeper_than_one_level(charm_cache: pathlib.Path):
    """Charms below the first directory level are found, not silently dropped."""
    mono = charm_cache / 'operators'
    make_charm(mono / 'charms' / 'controller')
    make_charm(mono / 'stacks' / 'observability' / 'agent')
    found = sorted(p.name for p in _enumerate.iter_charm_repos(charm_cache))
    assert found == ['agent', 'controller']


def test_single_charm_in_a_subdirectory(charm_cache: pathlib.Path):
    """A charm tucked into a subdirectory of a larger repo is found."""
    make_charm(charm_cache / 'some-project' / 'charm')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['charm']


def test_recursion_stops_at_the_depth_bound(charm_cache: pathlib.Path):
    make_charm(charm_cache / 'deep' / 'a' / 'b' / 'c' / 'too-far')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == []


def test_recursion_does_not_descend_into_a_found_charm(charm_cache: pathlib.Path):
    """A charm is yielded whole; its own nested charm dirs are not walked."""
    outer = charm_cache / 'repo' / 'outer'
    make_charm(outer)
    make_charm(outer / 'tests' / 'integration' / 'fixture')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['outer']


def test_pruned_directories_are_not_searched(charm_cache: pathlib.Path):
    make_charm(charm_cache / 'repo' / 'lib' / 'charms' / 'vendored')
    make_charm(charm_cache / 'repo' / 'tests' / 'fixture')
    make_charm(charm_cache / 'repo' / 'charms' / 'real')
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['real']


def test_symlinked_directories_are_not_followed(charm_cache: pathlib.Path):
    repo = charm_cache / 'repo'
    make_charm(repo / 'charms' / 'real')
    (repo / 'loop').symlink_to(repo, target_is_directory=True)
    found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['real']


def test_repo_with_no_charms_is_logged(
    charm_cache: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    (charm_cache / 'not-a-charm' / 'docs').mkdir(parents=True)
    make_charm(charm_cache / 'alpha')
    with caplog.at_level(logging.WARNING, logger='hyrum._enumerate'):
        found = [p.name for p in _enumerate.iter_charm_repos(charm_cache)]
    assert found == ['alpha']
    assert 'No charm found in' in caplog.text
    assert 'not-a-charm' in caplog.text
