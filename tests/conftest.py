"""Shared fixtures for hyrum tests."""

from __future__ import annotations

import pathlib

import pytest


def _make_charm(root: pathlib.Path, *, tox: bool = True, makefile: bool = False) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text('type: charm\n')
    if tox:
        (root / 'tox.ini').write_text('[tox]\nenvlist = unit\n')
    if makefile:
        (root / 'Makefile').write_text('unit:\n\techo ok\n')
    return root


@pytest.fixture
def make_charm():
    return _make_charm


@pytest.fixture
def charm_cache(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    return cache
