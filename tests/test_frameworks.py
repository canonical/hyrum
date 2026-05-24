from __future__ import annotations

import pathlib

import pytest

from hyrum import frameworks


def _make_minimal_charm(root: pathlib.Path) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text('type: charm\n')
    (root / 'tests').mkdir()
    return root


def test_supported_includes_scenario_and_jubilant():
    assert 'scenario' in frameworks.supported_frameworks()
    assert 'jubilant' in frameworks.supported_frameworks()


def test_unknown_framework_raises(tmp_path: pathlib.Path):
    with pytest.raises(ValueError):
        frameworks.uses_framework(tmp_path, 'nope')


def test_scenario_detected_via_ops_testing_extra(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    (repo / 'requirements.txt').write_text('ops[testing]>=2.10\n')
    assert frameworks.uses_framework(repo, 'scenario')
    assert not frameworks.uses_framework(repo, 'jubilant')


def test_scenario_detected_via_ops_scenario_dep(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    (repo / 'requirements.txt').write_text('ops-scenario>=7\n')
    assert frameworks.uses_framework(repo, 'scenario')


def test_jubilant_detected_via_pyproject(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    (repo / 'pyproject.toml').write_text(
        '[project]\nname="x"\nversion="0"\ndependencies = ["jubilant>=1"]\n'
    )
    assert frameworks.uses_framework(repo, 'jubilant')


def test_scenario_detected_via_test_import(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    (repo / 'tests' / 'test_x.py').write_text(
        'from ops.testing import Context\n\ndef test_noop():\n    assert Context\n'
    )
    assert frameworks.uses_framework(repo, 'scenario')


def test_harness_only_does_not_count_as_scenario(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    (repo / 'tests' / 'test_x.py').write_text(
        'from ops.testing import Harness\n\ndef test_noop():\n    assert Harness\n'
    )
    assert not frameworks.uses_framework(repo, 'scenario')


def test_no_framework_when_empty(tmp_path: pathlib.Path):
    repo = _make_minimal_charm(tmp_path / 'c')
    assert not frameworks.uses_framework(repo, 'scenario')
    assert not frameworks.uses_framework(repo, 'jubilant')
