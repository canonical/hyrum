from __future__ import annotations

import logging
import pathlib
import shutil

import packaging.specifiers
import pytest

from hyrum import _python as python_select


def _pyproject(repo: pathlib.Path, text: str) -> pathlib.Path:
    (repo / 'pyproject.toml').write_text(text)
    return repo


def _allowed(constraint: str, versions: range = range(8, 16)) -> list[int]:
    specs = [
        packaging.specifiers.SpecifierSet(s) for s in python_select._poetry_to_pep440(constraint)
    ]
    return [minor for minor in versions if python_select._allows(specs, (3, minor))]


# ---- parse_version -----------------------------------------------------------


def test_parse_version():
    assert python_select.parse_version('3.12') == (3, 12)
    assert python_select.parse_version(' 3.8 ') == (3, 8)


@pytest.mark.parametrize('text', ['3', '3.12.1', '2.7', 'python3.12', 'host', ''])
def test_parse_version_rejects_anything_but_3_y(text: str):
    with pytest.raises(ValueError, match='expected a Python version'):
        python_select.parse_version(text)


# ---- Poetry constraints ------------------------------------------------------


@pytest.mark.parametrize(
    ('constraint', 'expected'),
    [
        ('^3.10', [10, 11, 12, 13, 14, 15]),
        ('~3.10', [10]),
        ('~=3.10', [10, 11, 12, 13, 14, 15]),
        ('>=3.8,<3.11', [8, 9, 10]),
        ('>= 3.8, < 3.11', [8, 9, 10]),
        ('>=3.8 <3.11', [8, 9, 10]),
        ('3.10', [10]),
        ('3.10.*', [10]),
        ('^3.8 || ^3.12', [8, 9, 10, 11, 12, 13, 14, 15]),
        ('~3.8 || ~3.12', [8, 12]),
        ('*', [8, 9, 10, 11, 12, 13, 14, 15]),
    ],
)
def test_poetry_constraints(constraint: str, expected: list[int]):
    assert _allowed(constraint) == expected


def test_bounds_inside_a_minor_series_allow_that_series():
    specs = [packaging.specifiers.SpecifierSet('>=3.10.6,<3.12.3')]
    assert [m for m in range(8, 14) if python_select._allows(specs, (3, m))] == [10, 11, 12]


# ---- requires_python ---------------------------------------------------------


def test_requires_python_from_project(tmp_path: pathlib.Path):
    _pyproject(tmp_path, '[project]\nname = "x"\nrequires-python = ">=3.14"\n')
    specs = python_select.requires_python(tmp_path)
    assert specs is not None
    assert [str(s) for s in specs] == ['>=3.14']


def test_requires_python_from_poetry(tmp_path: pathlib.Path):
    _pyproject(tmp_path, '[tool.poetry.dependencies]\npython = "^3.10"\n')
    specs = python_select.requires_python(tmp_path)
    assert specs is not None
    assert specs[0].contains('3.10.0')
    assert not specs[0].contains('4.0.0')


def test_requires_python_from_poetry_table_form(tmp_path: pathlib.Path):
    _pyproject(tmp_path, '[tool.poetry.dependencies]\npython = { version = "~3.10" }\n')
    specs = python_select.requires_python(tmp_path)
    assert specs is not None
    assert not specs[0].contains('3.11.0')


def test_requires_python_prefers_project_over_poetry(tmp_path: pathlib.Path):
    _pyproject(
        tmp_path,
        '[project]\nrequires-python = ">=3.12"\n[tool.poetry.dependencies]\npython = "~3.8"\n',
    )
    specs = python_select.requires_python(tmp_path)
    assert specs is not None
    assert [str(s) for s in specs] == ['>=3.12']


@pytest.mark.parametrize(
    'text',
    [
        None,
        '[project]\nname = "x"\n',
        'not [ toml',
        '[project]\nrequires-python = "three point ten"\n',
        '[tool.poetry.dependencies]\npython = "*"\n',
    ],
)
def test_requires_python_none_when_absent_or_unusable(tmp_path: pathlib.Path, text: str | None):
    if text is not None:
        _pyproject(tmp_path, text)
    assert python_select.requires_python(tmp_path) is None


# ---- choose ------------------------------------------------------------------

_INSTALLED = [(3, 10), (3, 11), (3, 12), (3, 14)]


def _specs(text: str):
    return [packaging.specifiers.SpecifierSet(text)]


def test_choose_preferred_without_a_constraint():
    assert python_select.choose(None, (3, 12), _INSTALLED) == (3, 12)


def test_choose_preferred_when_allowed():
    assert python_select.choose(_specs('>=3.10'), (3, 12), _INSTALLED) == (3, 12)


def test_choose_closest_newer_when_preferred_is_too_old():
    assert python_select.choose(_specs('>=3.13'), (3, 12), _INSTALLED) == (3, 14)


def test_choose_closest_older_when_preferred_is_too_new():
    assert python_select.choose(_specs('>=3.8,<3.12'), (3, 12), _INSTALLED) == (3, 11)


def test_choose_newer_of_two_equally_close():
    assert python_select.choose(_specs('!=3.12.*'), (3, 12), [(3, 11), (3, 13)]) == (3, 13)


def test_choose_closest_when_preferred_is_not_installed():
    assert python_select.choose(None, (3, 12), [(3, 10), (3, 14)]) == (3, 14)


def test_choose_none_when_nothing_installed_is_allowed():
    assert python_select.choose(_specs('>=3.15'), (3, 12), _INSTALLED) is None


# ---- discover and Selector ---------------------------------------------------


def test_discover_finds_versioned_executables(monkeypatch: pytest.MonkeyPatch):
    found = {'python3.10', 'python3.12'}
    monkeypatch.setattr(
        shutil, 'which', lambda name: f'/usr/bin/{name}' if name in found else None
    )
    assert python_select.discover() == ((3, 10), (3, 12))


def test_selector_returns_the_chosen_version(tmp_path: pathlib.Path):
    _pyproject(tmp_path, '[project]\nrequires-python = ">=3.14"\n')
    selector = python_select.Selector((3, 12), _INSTALLED)
    assert selector(tmp_path) == '3.14'


def test_selector_leaves_it_to_the_runner_when_nothing_fits(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    _pyproject(tmp_path, '[project]\nrequires-python = ">=3.15"\n')
    selector = python_select.Selector((3, 12), _INSTALLED)
    with caplog.at_level(logging.WARNING):
        assert selector(tmp_path) is None
    assert 'no installed Python satisfies' in caplog.text
    assert '>=3.15' in caplog.text
