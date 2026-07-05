"""Shared fixtures for hyrum tests."""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_root_logging() -> Iterator[None]:
    """Undo the CLI's _configure_logging after each test.

    CLI tests replace the root logger's handlers with a StreamHandler bound
    to pytest's per-test capture stream; once that stream is closed, any
    later test that logs would blow up writing to it.
    """
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


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
        (root / 'src' / 'charm.py').write_text('# placeholder src charm\n')
        (root / 'pyproject.toml').write_text(
            '[project]\nname = "c"\nversion = "0"\ndependencies = ["ops>=2.10"]\n'
        )
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
