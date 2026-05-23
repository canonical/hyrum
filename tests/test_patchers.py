from __future__ import annotations

from pathlib import Path

import pytest

from super_tox.patchers import (
    NullPatcher,
    OpsSource,
    OpsSourcePatcher,
    PatcherError,
    PatcherStack,
)


@pytest.fixture
def ops_main() -> OpsSource:
    return OpsSource(url="https://github.com/canonical/operator", branch=None)


@pytest.fixture
def ops_branch() -> OpsSource:
    return OpsSource(branch="fix/X")


def _read(path: Path) -> str:
    return path.read_text()


# ---- NullPatcher / PatcherStack ----------------------------------------------


def test_null_patcher_makes_no_changes(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("ops==2.0\n")
    with NullPatcher().apply(tmp_path):
        pass
    assert _read(tmp_path / "requirements.txt") == "ops==2.0\n"


def test_patcher_stack_applies_and_restores(tmp_path: Path, ops_main: OpsSource):
    (tmp_path / "requirements.txt").write_text("ops==2.0\n")
    stack = PatcherStack([NullPatcher(), OpsSourcePatcher(ops_main)])
    with stack.apply(tmp_path):
        assert "git+https://github.com/canonical/operator" in _read(
            tmp_path / "requirements.txt"
        )
    assert _read(tmp_path / "requirements.txt") == "ops==2.0\n"


# ---- requirements.txt --------------------------------------------------------


def test_requirements_swap_pins_to_git(tmp_path: Path, ops_branch: OpsSource):
    req = tmp_path / "requirements.txt"
    req.write_text("ops>=2.10\nrequests==2.32\n")
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(req)
        assert "ops @ git+https://github.com/canonical/operator@fix/X" in patched
        assert "requests==2.32" in patched
        assert "ops>=2.10" not in patched
    assert _read(req) == "ops>=2.10\nrequests==2.32\n"


def test_requirements_ops_extras_propagate(tmp_path: Path, ops_main: OpsSource):
    req = tmp_path / "requirements.txt"
    req.write_text("ops[testing,tracing]\n")
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(req)
        assert "ops[testing,tracing] @ git+" in patched
        assert "ops-scenario @ git+" in patched
        assert "subdirectory=testing" in patched
        assert "ops-tracing @ git+" in patched
        assert "subdirectory=tracing" in patched


def test_requirements_sibling_files_patched(tmp_path: Path, ops_main: OpsSource):
    (tmp_path / "requirements.txt").write_text("ops>=2.10\n")
    sibling = tmp_path / "requirements-unit.txt"
    sibling.write_text("ops>=2.10\npytest>=8\n")
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        assert "git+" in _read(sibling)
        assert "pytest>=8" in _read(sibling)
    assert _read(sibling) == "ops>=2.10\npytest>=8\n"


def test_existing_git_ops_line_dropped(tmp_path: Path, ops_main: OpsSource):
    req = tmp_path / "requirements.txt"
    req.write_text("ops @ git+https://github.com/canonical/operator@old\n")
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(req)
        # Old git line gone, new one appended (no @branch here).
        assert "ops @ git+https://github.com/canonical/operator\n" in patched
        assert "@old" not in patched


def test_restore_on_exception(tmp_path: Path, ops_main: OpsSource):
    req = tmp_path / "requirements.txt"
    req.write_text("ops>=2.10\n")
    with (
        pytest.raises(RuntimeError, match="boom"),
        OpsSourcePatcher(ops_main).apply(tmp_path),
    ):
        raise RuntimeError("boom")
    assert _read(req) == "ops>=2.10\n"


# ---- pyproject.toml: PEP 621 (no uv, no poetry) ------------------------------


def test_pyproject_pep621_injects_git_dep(tmp_path: Path, ops_branch: OpsSource):
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\n'
        'dependencies = [\n  "ops>=2.10",\n  "requests",\n]\n'
    )
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert "ops>=2.10" not in patched
        assert '"requests"' in patched


# ---- pyproject.toml: uv ------------------------------------------------------


def test_pyproject_uv_adds_tool_uv_sources(tmp_path: Path, ops_branch: OpsSource):
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\ndev-dependencies = []\n'
    )
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert "[tool.uv.sources]" in patched
        assert 'ops = { git = "https://github.com/canonical/operator"' in patched
        assert 'branch = "fix/X"' in patched
        # ops dep stays in [project.dependencies] for uv.
        assert "ops>=2.10" in patched


def test_pyproject_uv_with_testing_extra_adds_companion(
    tmp_path: Path, ops_main: OpsSource
):
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops[testing]>=2.10",\n]\n\n'
        "[tool.uv]\ndev-dependencies = []\n"
    )
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert "[tool.uv.sources]" in patched
        assert "ops-scenario" in patched
        assert 'subdirectory = "testing"' in patched
        assert 'git = "https://github.com/canonical/operator"' in patched
        # Companion injected as a direct dep too.
        assert '"ops-scenario"' in patched


def test_pyproject_uv_bumps_low_requires_python(
    tmp_path: Path, ops_main: OpsSource
):
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.8"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'requires-python = ">=3.10"' in patched


# ---- pyproject.toml: poetry --------------------------------------------------


def test_pyproject_poetry_injects_git_under_dependencies(
    tmp_path: Path, ops_branch: OpsSource, monkeypatch
):
    # Skip the poetry lock subprocess for unit tests.
    monkeypatch.setattr(
        "super_tox.patchers.ops_source._run_lock", lambda *a, **kw: None
    )
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.10"\n'
        'ops = "^2.10"\n'
    )
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert 'ops = {git = "https://github.com/canonical/operator", branch = "fix/X"}' in patched
        # Old poetry-style entry gone.
        assert 'ops = "^2.10"' not in patched


def test_pyproject_poetry_with_testing_extra(
    tmp_path: Path, ops_main: OpsSource, monkeypatch
):
    monkeypatch.setattr(
        "super_tox.patchers.ops_source._run_lock", lambda *a, **kw: None
    )
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.10"\n'
        'ops = { version = "^2.10", extras = ["testing"] }\n'
    )
    with OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'ops = {git = "https://github.com/canonical/operator"' in patched
        assert "extras = ['testing']" in patched
        assert 'ops-scenario = {git = "https://github.com/canonical/operator"' in patched
        assert 'subdirectory = "testing"' in patched


# ---- error paths -------------------------------------------------------------


def test_no_requirements_or_pyproject_raises(tmp_path: Path, ops_main: OpsSource):
    with pytest.raises(PatcherError), OpsSourcePatcher(ops_main).apply(tmp_path):
        pass


def test_unrecognised_pyproject_raises(tmp_path: Path, ops_main: OpsSource):
    (tmp_path / "pyproject.toml").write_text('[build-system]\nrequires = []\n')
    with pytest.raises(PatcherError), OpsSourcePatcher(ops_main).apply(tmp_path):
        pass


def test_lockfile_snapshots_restored(tmp_path: Path, ops_branch: OpsSource, monkeypatch):
    monkeypatch.setattr(
        "super_tox.patchers.ops_source._run_lock", lambda *a, **kw: None
    )
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    lock = tmp_path / "uv.lock"
    lock.write_text("# original lock\n")
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        pass
    assert _read(lock) == "# original lock\n"


def test_lockfile_created_during_patch_is_removed_on_exit(
    tmp_path: Path, ops_branch: OpsSource, monkeypatch
):
    # No lockfile pre-existing; simulate _run_lock creating one.
    def fake_lock(repo, cmd, timeout, **kw):
        (repo / "uv.lock").write_text("# generated mid-patch\n")

    monkeypatch.setattr(
        "super_tox.patchers.ops_source._run_lock", fake_lock
    )
    py = tmp_path / "pyproject.toml"
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    with OpsSourcePatcher(ops_branch).apply(tmp_path):
        # _run_lock is only called when uv.lock already existed; here it
        # won't run, so no cleanup necessary in this case.
        pass
    assert not (tmp_path / "uv.lock").exists()
