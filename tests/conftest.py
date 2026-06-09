"""Shared fixtures for hyrum tests."""

from __future__ import annotations

import pathlib

import pytest


def make_charm(
    root: pathlib.Path,
    *,
    tox: bool = True,
    makefile: bool = False,
    requirements: bool = False,
    python: bool = True,
) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text('type: charm\n')
    if python:
        (root / 'src').mkdir(exist_ok=True)
        (root / 'src' / 'charm.py').write_text('# placeholder for has_python filter\n')
    if tox:
        (root / 'tox.ini').write_text('[tox]\nenvlist = unit\n')
    if makefile:
        (root / 'Makefile').write_text('unit:\n\techo ok\n')
    if requirements:
        (root / 'requirements.txt').write_text('ops>=2.10\n')
    return root


@pytest.fixture
def charm_cache(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    return cache
