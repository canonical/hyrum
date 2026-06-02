from __future__ import annotations

import pathlib

from hyrum import filters

from .conftest import make_charm


def test_regex_filter_keeps_matching(tmp_path: pathlib.Path):
    f = filters.regex_filter(r'.*-k8s-operator$')
    assert f(tmp_path / 'alertmanager-k8s-operator') is None
    skipped = f(tmp_path / 'loki')
    assert skipped is not None
    assert 'does not match' in skipped


def test_regex_is_case_insensitive(tmp_path: pathlib.Path):
    f = filters.regex_filter(r'PROM.*')
    assert f(tmp_path / 'prometheus-k8s-operator') is None


def test_ignore_filter_skips_by_relative_path(charm_cache):
    make_charm(charm_cache / 'expensive-one')
    make_charm(charm_cache / 'cheap-one')
    f = filters.ignore_filter({'expensive': ['expensive-one']}, base=charm_cache)
    assert f(charm_cache / 'expensive-one') == 'ignored (expensive)'
    assert f(charm_cache / 'cheap-one') is None


def test_ignore_filter_skips_by_name_for_monorepo_subcharm(charm_cache):
    mono = charm_cache / 'operators'
    mono.mkdir()
    make_charm(mono / 'inner')
    # Configured under just the charm name; should still skip.
    f = filters.ignore_filter({'manual': ['inner']}, base=charm_cache)
    assert f(mono / 'inner') == 'ignored (manual)'


def test_has_runnable_target_with_tox(charm_cache):
    repo = make_charm(charm_cache / 'a')
    assert filters.has_runnable_target(repo) is None


def test_has_runnable_target_with_makefile(charm_cache):
    repo = make_charm(charm_cache / 'a', tox=False, makefile=True)
    assert filters.has_runnable_target(repo) is None


def test_has_runnable_target_with_neither(charm_cache):
    repo = make_charm(charm_cache / 'a', tox=False)
    assert filters.has_runnable_target(repo) == 'no tox.ini or Makefile'


def test_not_legacy_passes_ops_charm(charm_cache):
    repo = make_charm(charm_cache / 'a')
    assert filters.not_legacy(repo) is None


def test_not_legacy_skips_reactive_charm(charm_cache):
    repo = make_charm(charm_cache / 'a')
    (repo / 'reactive').mkdir()
    assert filters.not_legacy(repo) == 'legacy (reactive/hooks) charm'


def test_not_legacy_skips_classic_hook_charm(charm_cache):
    repo = make_charm(charm_cache / 'a')
    (repo / 'hooks').mkdir()
    assert filters.not_legacy(repo) == 'legacy (reactive/hooks) charm'
