from __future__ import annotations

from pathlib import Path

import pytest

from super_tox.enumerate import iter_charm_repos


def test_flat_layout(charm_cache: Path, make_charm):
    make_charm(charm_cache / "alpha")
    make_charm(charm_cache / "beta")
    found = sorted(p.name for p in iter_charm_repos(charm_cache))
    assert found == ["alpha", "beta"]


def test_dotdirs_ignored(charm_cache: Path, make_charm):
    make_charm(charm_cache / "alpha")
    make_charm(charm_cache / ".git")
    found = [p.name for p in iter_charm_repos(charm_cache)]
    assert found == ["alpha"]


def test_bundle_expands_to_inner_charms(charm_cache: Path, make_charm):
    bundle = charm_cache / "my-bundle"
    bundle.mkdir()
    (bundle / "bundle.yaml").write_text("applications: {}\n")
    make_charm(bundle / "charms" / "inner-a")
    make_charm(bundle / "charms" / "inner-b")
    found = sorted(p.name for p in iter_charm_repos(charm_cache))
    assert found == ["inner-a", "inner-b"]


def test_monorepo_with_charm_subdirs(charm_cache: Path, make_charm):
    mono = charm_cache / "operators"
    mono.mkdir()
    make_charm(mono / "controller")
    make_charm(mono / "agent")
    # Bare subdir without charm markers is ignored.
    (mono / "docs").mkdir()
    found = sorted(p.name for p in iter_charm_repos(charm_cache))
    assert found == ["agent", "controller"]


def test_legacy_reactive_charm_skipped(charm_cache: Path, make_charm):
    legacy = make_charm(charm_cache / "legacy")
    (legacy / "reactive").mkdir()
    make_charm(charm_cache / "modern")
    found = [p.name for p in iter_charm_repos(charm_cache)]
    assert found == ["modern"]


def test_missing_cache_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(iter_charm_repos(tmp_path / "missing"))
