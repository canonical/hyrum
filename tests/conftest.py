"""Shared fixtures for hyrum tests."""

from __future__ import annotations

import logging
import pathlib

import pytest

from hyrum import _cli


@pytest.fixture(autouse=True)
def _redirect_default_auto_save(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
):
    """Keep the default auto-save directory out of the developer's real ~/.cache."""
    root = tmp_path_factory.mktemp('hyrum-auto-save')
    monkeypatch.setattr(_cli, '_default_auto_save_dir', lambda: root)


@pytest.fixture(autouse=True)
def _reset_root_logging():
    # hyrum._cli._configure_logging replaces root's handlers with a
    # StreamHandler that captures sys.stderr at construction time. Pytest
    # rebinds sys.stderr per test, so a handler left over from an earlier
    # test can end up writing to a closed capture buffer.
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    for h in root.handlers:
        if h not in saved_handlers:
            h.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


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
