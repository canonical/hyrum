from __future__ import annotations

import pathlib
import textwrap

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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        dependencies = [
          "ops>=2.10",
          "requests",
        ]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert 'ops>=2.10' not in patched
        assert '"requests"' in patched


# ---- pyproject.toml: PEP 621 optional-dependencies (temporal-style) ----------


def test_pyproject_pep621_optional_deps_rewritten(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """Charms without ``[project.dependencies]`` but with ops in an extra."""
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"

        [project.optional-dependencies]
        charm = [
          "ops==2.21.1",
          "requests",
        ]
        unit = [
          "ops[testing]==2.21.1",
        ]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert '"ops[testing] @ git+https://github.com/canonical/operator@fix/X"' in patched
        # Non-ops entries unchanged.
        assert '"requests"' in patched
        # Pinned versions gone.
        assert '"ops==2.21.1"' not in patched
        assert '"ops[testing]==2.21.1"' not in patched


def test_pyproject_pep735_dependency_groups_rewritten(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """Charms using PEP 735 ``[dependency-groups]`` (pgbouncer-style)."""
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"

        [dependency-groups]
        charm = [
          "ops==2.23.1",
          "jinja2==3.1.6",
        ]
        libs = [
          "ops>=2.23.1",
        ]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert '"jinja2==3.1.6"' in patched
        assert '"ops==2.23.1"' not in patched
        assert '"ops>=2.23.1"' not in patched


def test_pyproject_pep621_keywords_ops_not_rewritten(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """``keywords = ["ops"]`` under [project] must not be misidentified as a dep."""
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        keywords = ["ops", "charm"]
        dependencies = [
          "ops==2.10",
        ]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        # keywords entry preserved verbatim.
        assert 'keywords = ["ops", "charm"]' in patched
        # The real dep was rewritten.
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched
        assert '"ops==2.10"' not in patched


# ---- pyproject.toml: uv ------------------------------------------------------


def test_pyproject_uv_adds_tool_uv_sources(tmp_path: pathlib.Path, ops_branch: patchers.OpsSource):
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
        dev-dependencies = []
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        assert 'ops = { git = "https://github.com/canonical/operator"' in patched
        assert 'branch = "fix/X"' in patched
        # The version-pinned ops dep is rewritten in-place to the git URL so
        # hard pins (``ops==X.Y``) don't conflict with HEAD ops.
        assert 'ops>=2.10' not in patched
        assert '"ops @ git+https://github.com/canonical/operator@fix/X"' in patched


def test_pyproject_uv_always_hoists_all_companions(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """Companion packages are hoisted even when no ops extra is requested.

    uv refuses transitive URL deps (which the patched ops HEAD has on
    its workspace siblings) unless they appear at the top-level pyproject.
    """
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
        dev-dependencies = []
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "coordinated-workers>=2.2",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.8"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'requires-python = ">=3.10"' in patched


def test_pyproject_uv_dep_groups_recognised_and_hoisted(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource
):
    """PEP 735 [dependency-groups]-only pyproject is patched as uv flavour.

    Mirrors the pgbouncer-operator layout: minimal [project] metadata, ops
    declared in two named dep-groups, [tool.uv] marker present. Companions
    must end up in both ops-bearing groups, plus the source block.
    """
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        [dependency-groups]
        charm = [
          "ops==2.23.1",
          "jinja2==3.1.6",
        ]
        libs = [
          "ops>=2.23.1",
          "cosl",
        ]
        lint = [
          "codespell",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        assert 'ops = { git = "https://github.com/canonical/operator"' in patched
        # Companions injected into each ops-bearing group.
        charm_block = patched.split('charm = [', 1)[1].split(']', 1)[0]
        assert '"ops-scenario"' in charm_block
        assert '"ops-tracing"' in charm_block
        libs_block = patched.split('libs = [', 1)[1].split(']', 1)[0]
        assert '"ops-scenario"' in libs_block
        assert '"ops-tracing"' in libs_block
        # lint group has no ops, so companions don't leak into it.
        lint_block = patched.split('lint = [', 1)[1].split(']', 1)[0]
        assert 'ops-scenario' not in lint_block
        assert 'ops-tracing' not in lint_block
    assert 'ops==2.23.1' in _read(py)
    assert 'codespell' in _read(py)


def test_pyproject_uv_dep_groups_without_project_dependencies(
    tmp_path: pathlib.Path, ops_main: patchers.OpsSource
):
    """A pure PEP 735 layout (no [project.dependencies] at all) still patches."""
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        [dependency-groups]
        charm = [
          "ops==2.23.1",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        charm_block = patched.split('charm = [', 1)[1].split(']', 1)[0]
        assert '"ops-scenario"' in charm_block
        assert '"ops-tracing"' in charm_block


# ---- pyproject.toml: poetry --------------------------------------------------


def test_pyproject_poetry_injects_git_under_dependencies(
    tmp_path: pathlib.Path, ops_branch: patchers.OpsSource, monkeypatch
):
    # Skip the poetry lock subprocess for unit tests.
    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        python = "^3.10"
        ops = "^2.10"
    """))
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
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        python = "^3.10"
        ops = { version = "^2.10", extras = ["testing"] }
    """))
    with patchers.OpsSourcePatcher(ops_main).apply(tmp_path):
        patched = _read(py)
        assert 'ops = {git = "https://github.com/canonical/operator"' in patched
        assert "extras = ['testing']" in patched
        assert 'ops-scenario = {git = "https://github.com/canonical/operator"' in patched
        assert 'subdirectory = "testing"' in patched


# ---- OpsSource: PyPI version mode -------------------------------------------


@pytest.fixture
def ops_pypi() -> patchers.OpsSource:
    return patchers.OpsSource(version='2.17.0')


@pytest.fixture
def ops_path(tmp_path: pathlib.Path) -> patchers.OpsSource:
    return patchers.OpsSource(path=str(tmp_path / 'operator'))


def test_ops_source_rejects_multiple_kinds():
    with pytest.raises(ValueError, match='at most one'):
        patchers.OpsSource(version='2.17.0', path='/x')


def test_ops_source_kind_property():
    assert patchers.OpsSource().kind == 'git'
    assert patchers.OpsSource(version='2.17.0').kind == 'pypi'
    assert patchers.OpsSource(path='/x').kind == 'path'


def test_requirements_pypi_pins_version_and_leaves_companions(
    tmp_path: pathlib.Path, ops_pypi: patchers.OpsSource
):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops>=2.10\nops-scenario>=7\nrequests==2.32\n')
    with patchers.OpsSourcePatcher(ops_pypi).apply(tmp_path):
        patched = _read(req)
        assert 'ops==2.17.0' in patched
        assert 'git+' not in patched
        # Companion left untouched — PyPI ops resolves companions from PyPI.
        assert 'ops-scenario>=7' in patched
        assert 'requests==2.32' in patched
    assert _read(req) == 'ops>=2.10\nops-scenario>=7\nrequests==2.32\n'


def test_requirements_path_uses_file_url(tmp_path: pathlib.Path, ops_path: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops>=2.10\n')
    with patchers.OpsSourcePatcher(ops_path).apply(tmp_path):
        patched = _read(req)
        assert f'ops @ file://{tmp_path / "operator"}' in patched


def test_requirements_pypi_carries_extras(tmp_path: pathlib.Path, ops_pypi: patchers.OpsSource):
    req = tmp_path / 'requirements.txt'
    req.write_text('ops[testing,tracing]\n')
    with patchers.OpsSourcePatcher(ops_pypi).apply(tmp_path):
        patched = _read(req)
        assert 'ops[testing,tracing]==2.17.0' in patched


def test_pyproject_uv_pypi_rewrites_dependency(
    tmp_path: pathlib.Path, ops_pypi: patchers.OpsSource
):
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_pypi).apply(tmp_path):
        patched = _read(py)
        # No source block, no companion hoisting.
        assert '[tool.uv.sources]' not in patched
        assert 'ops-scenario' not in patched
        assert '"ops==2.17.0"' in patched
        assert 'ops>=2.10' not in patched


def test_pyproject_poetry_pypi_uses_version_string(
    tmp_path: pathlib.Path, ops_pypi: patchers.OpsSource, monkeypatch
):
    monkeypatch.setattr('hyrum.patchers.ops_source._run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        python = "^3.10"
        ops = "^2.10"
    """))
    with patchers.OpsSourcePatcher(ops_pypi).apply(tmp_path):
        patched = _read(py)
        assert 'ops = "==2.17.0"' in patched
        assert 'git = ' not in patched
        assert 'ops = "^2.10"' not in patched


def test_pyproject_uv_path_emits_path_source(tmp_path: pathlib.Path, ops_path: patchers.OpsSource):
    py = tmp_path / 'pyproject.toml'
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_path).apply(tmp_path):
        patched = _read(py)
        assert f'ops = {{ path = "{tmp_path / "operator"}" }}' in patched
        # Companions still hoisted with the same path + subdirectory.
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        python = "^3.12"
        ops = "^2.10"
    """))
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
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        python = "^3.12"
        ops = "^2.10"
    """))
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
    py.write_text(textwrap.dedent("""\
        [tool.poetry]
        name = "c"
        version = "0"
        description = ""
        authors = ["x <x@x>"]

        [tool.poetry.dependencies]
        ops = "^2.10"
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.12,<4.0"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = "~=3.8"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.12,<4.0"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
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
    py.write_text(textwrap.dedent("""\
        [project]
        name = "c"
        version = "0"
        requires-python = ">=3.10"
        dependencies = [
          "ops>=2.10",
        ]

        [tool.uv]
    """))
    with patchers.OpsSourcePatcher(ops_branch).apply(tmp_path):
        # _run_lock is only called when uv.lock already existed; here it
        # won't run, so no cleanup necessary in this case.
        pass
    assert not (tmp_path / 'uv.lock').exists()
