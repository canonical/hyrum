from __future__ import annotations

import pathlib
import textwrap

import pytest

from hyrum import _patchers as patchers

_PYPROJECT = textwrap.dedent("""\
    [project]
    name = "mycharm"
    version = "0"
    dependencies = [
      "ops>=2.10",
    ]
""")

_CHARMCRAFT = textwrap.dedent("""\
    type: charm
    bases:
      - build-on:
          - name: ubuntu
            channel: "22.04"
        run-on:
          - name: ubuntu
            channel: "22.04"
    charm-libs:
      - lib: operator-libs-linux.apt
        version: "0"
      - lib: grafana-k8s.grafana_dashboard
        version: "0"
""")

_SRC_CHARM = textwrap.dedent("""\
    from charms.operator_libs_linux.v0 import apt
    from charms.operator_libs_linux.v0.apt import PackageNotFoundError

    def install():
        apt.update()
        try:
            apt.add_package('foo')
        except PackageNotFoundError:
            pass
""")

_SRC_OTHER = textwrap.dedent("""\
    from charms.grafana_k8s.v0 import grafana_dashboard

    def setup():
        grafana_dashboard.GrafanaDashboardProvider(None)
""")

_TEST_FILE = textwrap.dedent("""\
    import charms.operator_libs_linux.v0.apt as apt_lib

    def test_it():
        assert apt_lib.add_package
""")

_VENDORED_APT = '# vendored apt module\n'
_VENDORED_DASH = '# vendored grafana_dashboard module\n'


def _build_charm(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT)
    (tmp_path / 'charmcraft.yaml').write_text(_CHARMCRAFT)

    lib_apt = tmp_path / 'lib' / 'charms' / 'operator_libs_linux' / 'v0' / 'apt.py'
    lib_apt.parent.mkdir(parents=True)
    lib_apt.write_text(_VENDORED_APT)

    lib_dash = tmp_path / 'lib' / 'charms' / 'grafana_k8s' / 'v0' / 'grafana_dashboard.py'
    lib_dash.parent.mkdir(parents=True)
    lib_dash.write_text(_VENDORED_DASH)

    src = tmp_path / 'src'
    src.mkdir()
    (src / 'charm.py').write_text(_SRC_CHARM)
    (src / 'other.py').write_text(_SRC_OTHER)

    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_charm.py').write_text(_TEST_FILE)
    return tmp_path


def _swap(**overrides) -> patchers.VendoredLibSwap:
    defaults = dict(
        host_charm='operator_libs_linux',
        version=0,
        lib_name='apt',
        source=patchers.DepSource(pkg_name='charmlibs-apt', version='==1.0.0'),
    )
    defaults.update(overrides)
    return patchers.VendoredLibSwap(**defaults)


# ---- happy path --------------------------------------------------------------


def test_apply_removes_vendored_file_and_restores(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    vendored = repo / 'lib/charms/operator_libs_linux/v0/apt.py'

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        assert not vendored.exists()

    assert vendored.exists()
    assert vendored.read_text() == _VENDORED_APT


def test_apply_rewrites_src_imports(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    charm = repo / 'src/charm.py'
    original = charm.read_text()

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        patched = charm.read_text()
        assert 'from charmlibs import apt' in patched
        assert 'from charmlibs.apt import PackageNotFoundError' in patched
        assert 'charms.operator_libs_linux' not in patched

    assert charm.read_text() == original


def test_apply_rewrites_test_imports(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    test_file = repo / 'tests/test_charm.py'

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        patched = test_file.read_text()
        assert 'import charmlibs.apt as apt_lib' in patched
        assert 'charms.operator_libs_linux' not in patched


def test_apply_leaves_unrelated_libs_alone(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    other = repo / 'src/other.py'
    other_lib = repo / 'lib/charms/grafana_k8s/v0/grafana_dashboard.py'

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        assert other.read_text() == _SRC_OTHER
        assert other_lib.exists()
        assert other_lib.read_text() == _VENDORED_DASH


def test_apply_strips_charm_libs_entry(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    charmcraft = repo / 'charmcraft.yaml'

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        patched = charmcraft.read_text()
        assert 'operator-libs-linux.apt' not in patched
        # Unrelated entry remains.
        assert 'grafana-k8s.grafana_dashboard' in patched

    assert charmcraft.read_text() == _CHARMCRAFT


def test_apply_adds_dep_to_pyproject(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    pyproject = repo / 'pyproject.toml'

    with patchers.VendoredLibPatcher(_swap()).apply(repo):
        patched = pyproject.read_text()
        assert 'charmlibs-apt==1.0.0' in patched

    assert pyproject.read_text() == _PYPROJECT


# ---- source kinds ------------------------------------------------------------


def test_git_source_kind(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    swap = _swap(
        source=patchers.DepSource(
            pkg_name='charmlibs-apt',
            url='https://github.com/canonical/charmlibs',
            branch='main',
            subdir='apt',
        ),
    )
    with patchers.VendoredLibPatcher(swap).apply(repo):
        patched = (repo / 'pyproject.toml').read_text()
        assert 'charmlibs-apt @ git+https://github.com/canonical/charmlibs@main' in patched


# ---- custom new_module override ----------------------------------------------


def test_new_module_override(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    swap = _swap(new_module='vendor.apt2')

    with patchers.VendoredLibPatcher(swap).apply(repo):
        patched = (repo / 'src/charm.py').read_text()
        assert 'from vendor import apt2 as apt' in patched
        assert 'from vendor.apt2 import PackageNotFoundError' in patched
        assert 'charms.operator_libs_linux' not in patched


# ---- errors ------------------------------------------------------------------


def test_missing_vendored_file_skips(tmp_path: pathlib.Path):
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT)
    with (
        pytest.raises(patchers.PatcherSkip, match='vendored library'),
        patchers.VendoredLibPatcher(_swap()).apply(tmp_path),
    ):
        pass


def test_restore_on_exception(tmp_path: pathlib.Path):
    repo = _build_charm(tmp_path)
    vendored = repo / 'lib/charms/operator_libs_linux/v0/apt.py'
    src_original = (repo / 'src/charm.py').read_text()
    charmcraft_original = (repo / 'charmcraft.yaml').read_text()
    pyproject_original = (repo / 'pyproject.toml').read_text()

    with (
        pytest.raises(RuntimeError, match='boom'),
        patchers.VendoredLibPatcher(_swap()).apply(repo),
    ):
        raise RuntimeError('boom')

    assert vendored.read_text() == _VENDORED_APT
    assert (repo / 'src/charm.py').read_text() == src_original
    assert (repo / 'charmcraft.yaml').read_text() == charmcraft_original
    assert (repo / 'pyproject.toml').read_text() == pyproject_original
