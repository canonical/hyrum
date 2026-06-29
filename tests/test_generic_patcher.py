from __future__ import annotations

import pathlib
import textwrap

import pytest

from hyrum import _patchers as patchers


def _read(path: pathlib.Path) -> str:
    return path.read_text()


# ---- DepSource validation ----------------------------------------------------


def test_dep_source_requires_exactly_one_source_kind():
    with pytest.raises(ValueError, match='set exactly one'):
        patchers.DepSource(pkg_name='requests')
    with pytest.raises(ValueError, match='set exactly one'):
        patchers.DepSource(pkg_name='requests', version='==1', url='https://x')


def test_dep_source_branch_only_with_url():
    with pytest.raises(ValueError, match='only apply when `url`'):
        patchers.DepSource(pkg_name='requests', version='==1', branch='main')
    with pytest.raises(ValueError, match='only apply when `url`'):
        patchers.DepSource(pkg_name='requests', path='/x', subdir='a')


def test_dep_source_kind():
    assert patchers.DepSource(pkg_name='r', version='==1').kind == 'pypi'
    assert patchers.DepSource(pkg_name='r', url='https://x').kind == 'git'
    assert patchers.DepSource(pkg_name='r', path='/x').kind == 'path'


# ---- pep621 path -------------------------------------------------------------


_PEP621_TEMPLATE = textwrap.dedent("""\
    [project]
    name = "c"
    version = "0"
    dependencies = [
      "requests==2.30.0",
      "ops>=2.10",
    ]
""")


def test_pep621_version_swap(tmp_path: pathlib.Path):
    py = tmp_path / 'pyproject.toml'
    py.write_text(_PEP621_TEMPLATE)
    source = patchers.DepSource(pkg_name='requests', version='==2.32.0')
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests==2.32.0' in patched
        assert 'requests==2.30.0' not in patched
        # Untouched neighbour still present.
        assert 'ops>=2.10' in patched
    assert _read(py) == _PEP621_TEMPLATE


def test_pep621_git_swap(tmp_path: pathlib.Path):
    py = tmp_path / 'pyproject.toml'
    py.write_text(_PEP621_TEMPLATE)
    source = patchers.DepSource(
        pkg_name='requests', url='https://github.com/psf/requests', branch='main'
    )
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests @ git+https://github.com/psf/requests@main' in patched
        assert 'requests==2.30.0' not in patched
    assert _read(py) == _PEP621_TEMPLATE


def test_pep621_path_swap(tmp_path: pathlib.Path):
    py = tmp_path / 'pyproject.toml'
    py.write_text(_PEP621_TEMPLATE)
    source = patchers.DepSource(pkg_name='requests', path='/abs/requests')
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests @ file:///abs/requests' in patched
    assert _read(py) == _PEP621_TEMPLATE


# ---- uv path -----------------------------------------------------------------


_UV_TEMPLATE = textwrap.dedent("""\
    [project]
    name = "c"
    version = "0"
    requires-python = ">=3.10"
    dependencies = [
      "requests==2.30.0",
    ]

    [tool.uv]
""")


def test_uv_version_drops_existing_source(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setattr('hyrum._patchers.generic.run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    (tmp_path / 'uv.lock').write_text('')
    py.write_text(
        _UV_TEMPLATE
        + textwrap.dedent("""
            [tool.uv.sources]
            requests = { git = "https://example/requests", branch = "old" }
            other = { path = "/x" }
        """)
    )
    source = patchers.DepSource(pkg_name='requests', version='==2.32.0')
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests==2.32.0' in patched
        assert 'requests = { git' not in patched
        # Other sources untouched.
        assert 'other = { path = "/x" }' in patched


def test_uv_git_adds_source_block(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setattr('hyrum._patchers.generic.run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    (tmp_path / 'uv.lock').write_text('')
    py.write_text(_UV_TEMPLATE)
    source = patchers.DepSource(
        pkg_name='requests', url='https://github.com/psf/requests', branch='main'
    )
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert '[tool.uv.sources]' in patched
        assert 'requests = { git = "https://github.com/psf/requests", branch = "main" }' in patched


# ---- poetry path -------------------------------------------------------------


_POETRY_TEMPLATE = textwrap.dedent("""\
    [tool.poetry]
    name = "c"
    version = "0"

    [tool.poetry.dependencies]
    python = "^3.10"
    requests = "^2.30"
""")


def test_poetry_version_swap(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setattr('hyrum._patchers.generic.run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(_POETRY_TEMPLATE)
    source = patchers.DepSource(pkg_name='requests', version='==2.32.0')
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests = "==2.32.0"' in patched
        assert '"^2.30"' not in patched
    assert _read(py) == _POETRY_TEMPLATE


def test_poetry_git_swap(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setattr('hyrum._patchers.generic.run_lock', lambda *a, **kw: None)
    py = tmp_path / 'pyproject.toml'
    py.write_text(_POETRY_TEMPLATE)
    source = patchers.DepSource(
        pkg_name='requests', url='https://github.com/psf/requests', branch='main'
    )
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests = {git = "https://github.com/psf/requests", branch = "main"}' in patched


# ---- extras preserved --------------------------------------------------------


def test_extras_preserved_on_version_swap(tmp_path: pathlib.Path):
    py = tmp_path / 'pyproject.toml'
    py.write_text(
        textwrap.dedent("""\
            [project]
            name = "c"
            version = "0"
            dependencies = [
              "requests[security]==2.30.0",
            ]
        """)
    )
    source = patchers.DepSource(pkg_name='requests', version='==2.32.0')
    with patchers.GenericDepPatcher(source).apply(tmp_path):
        patched = _read(py)
        assert 'requests[security]==2.32.0' in patched


# ---- errors ------------------------------------------------------------------


def test_missing_pyproject_skips(tmp_path: pathlib.Path):
    source = patchers.DepSource(pkg_name='requests', version='==1')
    with (
        pytest.raises(patchers.PatcherSkip, match=r'not a dependency'),
        patchers.GenericDepPatcher(source).apply(tmp_path),
    ):
        pass


def test_dep_not_declared_skips(tmp_path: pathlib.Path):
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["click"]\n'
    )
    source = patchers.DepSource(pkg_name='requests', version='==1')
    with (
        pytest.raises(patchers.PatcherSkip, match=r'not a declared dependency'),
        patchers.GenericDepPatcher(source).apply(tmp_path),
    ):
        pass


def test_unparseable_pyproject_raises(tmp_path: pathlib.Path):
    (tmp_path / 'pyproject.toml').write_text('not = valid = toml = at all\n')
    source = patchers.DepSource(pkg_name='requests', version='==1')
    with (
        pytest.raises(patchers.PatcherError, match='could not parse'),
        patchers.GenericDepPatcher(source).apply(tmp_path),
    ):
        pass
