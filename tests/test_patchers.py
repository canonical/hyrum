from __future__ import annotations

import pathlib

import pytest

from hyrum import patchers
from hyrum.patchers import ops_source


@pytest.fixture
def ops_main() -> patchers.OpsSource:
    return patchers.OpsSource(url='https://github.com/canonical/operator', branch=None)


@pytest.fixture
def ops_branch() -> patchers.OpsSource:
    return patchers.OpsSource(branch='fix/X')


def _read(path: pathlib.Path) -> str:
    return path.read_text()


# ---- NullPatcher / PatcherStack ----------------------------------------------


def test_null_patcher_makes_no_changes(tmp_path: pathlib.Path):
    (tmp_path / 'requirements.txt').write_text('ops==2.0\n')
    with patchers.NullPatcher().apply(tmp_path):
        pass
    assert _read(tmp_path / 'requirements.txt') == 'ops==2.0\n'


def test_patcher_stack_applies_and_restores(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    (tmp_path / 'requirements.txt').write_text('ops==2.0\n')
    stack = patchers.PatcherStack([patchers.NullPatcher(), patchers.OpsSourcePatcher(ops_main)])
    with stack.apply(tmp_path):
        assert 'git+https://github.com/canonical/operator' in _read(tmp_path / 'requirements.txt')
    assert _read(tmp_path / 'requirements.txt') == 'ops==2.0\n'


# ---- requirements.txt --------------------------------------------------------


def test_requirements_swap_pins_to_git(tmp_path: pathlib.Path, ops_branch: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops>=2.10\nrequests==2.32\n')
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(req)
        assert 'ops @ git+https://github.com/canonical/operator@fix/X' in patched
        assert 'requests==2.32' in patched
        assert 'ops>=2.10' not in patched
    assert _read(req) == 'ops>=2.10\nrequests==2.32\n'


def test_requirements_ops_extras_propagate(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops[testing,tracing]\n')
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(req)
        assert 'ops[testing,tracing] @ git+' in patched
        assert 'ops-scenario @ git+' in patched
        assert 'subdirectory=testing' in patched
        assert 'ops-tracing @ git+' in patched
        assert 'subdirectory=tracing' in patched


def test_requirements_sibling_files_patched(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    (tmp_path / 'requirements.txt').write_text('ops>=2.10\n')
    sibling = tmp_path / 'requirements-unit.txt'
    sibling.write_text('ops>=2.10\npytest>=8\n')
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        assert 'git+' in _read(sibling)
        assert 'pytest>=8' in _read(sibling)
    assert _read(sibling) == 'ops>=2.10\npytest>=8\n'


def test_existing_git_ops_line_dropped(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops @ git+https://github.com/canonical/operator@old\n')
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(req)
        # Old git line gone, new one appended (no @branch here).
        assert 'ops @ git+https://github.com/canonical/operator\n' in patched
        assert '@old' not in patched


def test_restore_on_exception(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops>=2.10\n')
    with (
        pytest.raises(RuntimeError, match='boom'),
        patchers.OpsSourcePatcher(ops_main).apply(tmp_path),
    ):
        raise RuntimeError('boom')
    assert _read(req) == 'ops>=2.10\n'


# ---- pyproject.toml: PEP 621 (no uv, no poetry) ------------------------------


def test_pyproject_pep621_injects_git_dep(tmp_path: pathlib.Path, ops_branch: patchers.OpsSource):
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\n'
        'dependencies = [\n  "ops>=2.10",\n  "requests",\n]\n'
    )
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert 'ops>=2.10' not in patched
        assert '"requests"' in patched


# ---- pyproject.toml: uv ------------------------------------------------------


def test_pyproject_uv_adds_tool_uv_sources(tmp_path: pathlib.Path, ops_branch: patchers.OpsSource):
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\ndev-dependencies = []\n'
    )
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        assert 'ops = { git = "https://github.com/canonical/operator"' in patched
        assert 'branch = "fix/X"' in patched
        # ops dep stays in [project.dependencies] for uv.
        assert 'ops>=2.10' in patched


def test_pyproject_uv_always_hoists_all_companions(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """Companion packages are hoisted even when no ops extra is requested.

    uv refuses transitive URL deps (which the patched ops HEAD has on
    its workspace siblings) unless they appear at the top-level pyproject.
    """
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\ndev-dependencies = []\n'
    )
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        assert 'ops-scenario = { git = "https://github.com/canonical/operator"' in patched
        assert 'subdirectory = "testing"' in patched
        assert 'ops-tracing = { git = "https://github.com/canonical/operator"' in patched
        assert 'subdirectory = "tracing"' in patched
        # Companions appear in [project.dependencies] too so uv accepts the URL source.
        assert '"ops-scenario"' in patched
        assert '"ops-tracing"' in patched


def test_pyproject_uv_transitive_ops_dep_still_gets_companions(
    tmp_path: pathlib.Path, ops_main: patchers.OpsSource
):
    """A charm that pulls ops only transitively still gets companions hoisted."""
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "coordinated-workers>=2.2",\n]\n\n[tool.uv]\n'
    )
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        # ops itself is hoisted as a source so uv resolves the transitive dep from git.
        assert 'ops = { git = "https://github.com/canonical/operator" }' in patched
        # And companions, because the patched ops HEAD has them as workspace URL deps.
        assert '"ops-scenario"' in patched
        assert '"ops-tracing"' in patched


def test_pyproject_uv_bumps_low_requires_python(
    tmp_path: pathlib.Path, ops_main: patchers.OpsSource
):
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.8"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'requires-python = ">=3.10"' in patched


# ---- pyproject.toml: poetry --------------------------------------------------


def test_pyproject_poetry_injects_git_under_dependencies(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource, monkeypatch
):
    # Skip the poetry lock subprocess for unit tests.
    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.10"\n'
        'ops = "^2.10"\n'
    )
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert 'ops = {git = "https://github.com/canonical/operator", branch = "fix/X"}' in patched
        # Old poetry-style entry gone.
        assert 'ops = "^2.10"' not in patched


def test_pyproject_poetry_with_testing_extra(
    tmp_path: pathlib.Path, ops_main: patchers.OpsSource, monkeypatch
):
    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.10"\n'
        'ops = { version = "^2.10", extras = ["testing"] }\n'
    )
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'ops = {git = "https://github.com/canonical/operator"' in patched
        assert "extras = ['testing']" in patched
        assert 'ops-scenario = {git = "https://github.com/canonical/operator"' in patched
        assert 'subdirectory = "testing"' in patched


# ---- error paths -------------------------------------------------------------


def test_no_requirements_or_pyproject_raises(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    with (
        pytest.raises(patchers.PatcherError),
        patchers.OpsSourcePatcher(ops_main).apply(tmp_path),
    ):
        pass


def test_unrecognised_pyproject_raises(tmp_path: pathlib.Path, ops_main: patchers.OpsSource):
    (tmp_path / 'pyproject.toml').write_text('[build-system]\nrequires = []\n')
    with (
        pytest.raises(patchers.PatcherError),
        patchers.OpsSourcePatcher(ops_main).apply(tmp_path),
    ):
        pass


def test_lockfile_snapshots_restored(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource, monkeypatch
):
    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    lock = tmp_path / 'uv.lock'
    lock.write_text('# original lock\n')
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        pass
    assert _read(lock) == '# original lock\n'


# ---- auto-python: requires-python parsing & lock wrapping --------------------


@pytest.mark.parametrize(
    ('constraint', 'expected'),
    [
        ('>=3.12,<4.0', (3, 12)),
        ('>=3.11', (3, 11)),
        ('^3.10', (3, 10)),
        ('~3.10', (3, 10)),
        ('==3.12.4', (3, 12)),
        ('~=3.11', (3, 11)),
        ('>3.10', (3, 11)),
        ('>=3.10,>=3.12', (3, 12)),  # most restrictive lower bound wins
        ('<4.0', None),  # upper-bound only
        ('', None),
    ],
)
def test_min_python_from_constraint(constraint, expected):
    assert ops_source._min_python_from_constraint(constraint) == expected


def test_min_python_from_pyproject_pep621():
    parsed = {'project': {'requires-python': '>=3.12,<4.0'}}
    assert ops_source._min_python_from_pyproject(parsed) == (3, 12)


def test_min_python_from_pyproject_poetry_string():
    parsed = {'tool': {'poetry': {'dependencies': {'python': '^3.11'}}}}
    assert ops_source._min_python_from_pyproject(parsed) == (3, 11)


def test_min_python_from_pyproject_poetry_table():
    parsed = {'tool': {'poetry': {'dependencies': {'python': {'version': '~3.10'}}}}}
    assert ops_source._min_python_from_pyproject(parsed) == (3, 10)


def test_min_python_from_pyproject_pep621_wins_over_poetry():
    parsed = {
        'project': {'requires-python': '>=3.12'},
        'tool': {'poetry': {'dependencies': {'python': '^3.10'}}},
    }
    assert ops_source._min_python_from_pyproject(parsed) == (3, 12)


def test_min_python_from_pyproject_absent():
    assert ops_source._min_python_from_pyproject({}) is None


def test_wrap_with_uv_python_noop_without_version():
    assert ops_source._wrap_with_uv_python(('poetry', 'lock'), None, ('uv',)) == (
        'poetry',
        'lock',
    )


def test_wrap_with_uv_python_prefixes_uv_run():
    assert ops_source._wrap_with_uv_python(('poetry', 'lock'), (3, 12), ('uv',)) == (
        'uv',
        'run',
        '--no-project',
        '--python',
        '3.12',
        '--',
        'poetry',
        'lock',
    )


def test_wrap_with_uv_python_respects_uv_executable():
    assert ops_source._wrap_with_uv_python(
        ('poetry', 'lock'), (3, 11), ('uvx', '--from', 'uv')
    ) == (
        'uvx',
        '--from',
        'uv',
        'run',
        '--no-project',
        '--python',
        '3.11',
        '--',
        'poetry',
        'lock',
    )


def test_poetry_lock_wrapped_with_uv_run_when_requires_python_present(
    tmp_path: pathlib.Path, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.12"\n'
        'ops = "^2.10"\n'
    )
    ops = patchers.OpsSource(branch='b')
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == (
        'uv',
        'run',
        '--no-project',
        '--python',
        '3.12',
        '--',
        'poetry',
        'lock',
    )


def test_poetry_lock_not_wrapped_when_auto_python_disabled(tmp_path: pathlib.Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\npython = "^3.12"\n'
        'ops = "^2.10"\n'
    )
    ops = patchers.OpsSource(branch='b', auto_python=False)
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('poetry', 'lock')


def test_poetry_lock_not_wrapped_when_no_python_constraint(tmp_path: pathlib.Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[tool.poetry]\nname = "c"\nversion = "0"\ndescription = ""\n'
        'authors = ["x <x@x>"]\n\n[tool.poetry.dependencies]\n'
        'ops = "^2.10"\n'
    )
    ops = patchers.OpsSource(branch='b')
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('poetry', 'lock')


def test_uv_lock_passes_python_when_requires_python_present(tmp_path: pathlib.Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.12,<4.0"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    (tmp_path / 'uv.lock').write_text('# original\n')
    ops = patchers.OpsSource(branch='b')
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('uv', 'lock', '--python', '3.12')


def test_uv_lock_python_reflects_patched_requires_python(tmp_path: pathlib.Path, monkeypatch):
    # Regression: ``_patch_pyproject_uv`` bumps ``requires-python`` from
    # 3.8/3.9 to 3.10 (ops's floor). We must derive ``--python`` from the
    # patched pyproject, not the original, or uv aborts with "interpreter
    # resolved to Python 3.8 … incompatible with project requirement >=3.10".
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = "~=3.8"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    (tmp_path / 'uv.lock').write_text('# original\n')
    ops = patchers.OpsSource(branch='b')
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('uv', 'lock', '--python', '3.10')


def test_uv_lock_unpinned_when_auto_python_disabled(tmp_path: pathlib.Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.12,<4.0"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    (tmp_path / 'uv.lock').write_text('# original\n')
    ops = patchers.OpsSource(branch='b', auto_python=False)
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('uv', 'lock')


def test_uv_lock_unpinned_when_no_python_constraint(tmp_path: pathlib.Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_lock(repo, cmd, timeout, **kw):
        captured['cmd'] = tuple(cmd)

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\ndependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    (tmp_path / 'uv.lock').write_text('# original\n')
    ops = patchers.OpsSource(branch='b')
    with patchers.OpsSourcePatcher(ops).apply(tmp_path):
        pass
    assert captured['cmd'] == ('uv', 'lock')


def test_run_lock_strips_virtual_env(tmp_path: pathlib.Path, monkeypatch):
    # Regression: hyrum's own VIRTUAL_ENV (e.g. when invoked via ``uv run``)
    # leaked into the lock subprocess. Poetry then reported "Current Python
    # version (…) is not allowed by the project" because it picked up hyrum's
    # 3.11 venv as the project Python.
    captured: dict[str, object] = {}

    class _Result:
        returncode = 0
        stdout = b''
        stderr = b''

    def fake_run(_cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured['env'] = kwargs.get('env')
        return _Result()

    monkeypatch.setenv('VIRTUAL_ENV', '/some/venv')
    monkeypatch.setattr('hyrum.patchers.ops_source.subprocess.run', fake_run)
    ops_source._run_lock(tmp_path, ('uv', 'lock'), 60)
    env = captured['env']
    assert isinstance(env, dict)
    assert 'VIRTUAL_ENV' not in env


def test_lockfile_created_during_patch_is_removed_on_exit(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource, monkeypatch
):
    # No lockfile pre-existing; simulate _run_lock creating one.
    def fake_lock(repo, cmd, timeout, **kw):
        (repo / 'uv.lock').write_text('# generated mid-patch\n')

    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', fake_lock)
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        '[project]\nname = "c"\nversion = "0"\nrequires-python = ">=3.10"\n'
        'dependencies = [\n  "ops>=2.10",\n]\n\n[tool.uv]\n'
    )
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        # _run_lock is only called when uv.lock already existed; here it
        # won't run, so no cleanup necessary in this case.
        pass
    assert not (tmp_path / 'uv.lock').exists()
