"""Reclaim the build artefacts a ``hyrum check`` run leaves behind in the cache.

A full-collection run leaves a ``.tox`` (or a ``.venv``, or both) plus the
usual assortment of tool caches in every charm it touched, which reaches tens
of gigabytes across a few hundred charms. The alternative to removing them
selectively is deleting the cache and cloning ~600 repositories again, so this
walks each clone and removes only the artefacts, leaving the checkout in place.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import pathlib
import shutil
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Directories a lint or unit run creates inside a charm. Anything here is
# reproducible from the checkout, which is what makes it safe to remove.
ARTEFACT_DIRS = frozenset({
    '.mypy_cache',
    '.nox',
    '.pytest_cache',
    '.ruff_cache',
    '.tox',
    '.venv',
    'htmlcov',
    '__pycache__',
})
# Suffixes matched against a directory name rather than a whole name, for the
# ones that carry the package name (`hyrum.egg-info`).
ARTEFACT_DIR_SUFFIXES = ('.egg-info',)
ARTEFACT_FILES = frozenset({'.coverage'})
# Never descend into these, whatever else is true of them: the checkout is the
# thing being preserved.
PRESERVED_DIRS = frozenset({'.git'})


@dataclasses.dataclass(frozen=True)
class Artefact:
    """One removable path, with the space it is holding."""

    path: pathlib.Path
    size: int
    is_dir: bool


def _is_artefact_dir(name: str) -> bool:
    return name in ARTEFACT_DIRS or name.endswith(ARTEFACT_DIR_SUFFIXES)


def _tree_size(path: pathlib.Path) -> int:
    """Total size of the files under ``path``, not following symlinks."""
    total = 0
    for root, dirs, files in os.walk(path):
        # A symlinked directory's contents are not ours to count: they live
        # somewhere else and are not freed by removing the link.
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            entry = pathlib.Path(root, name)
            if entry.is_symlink():
                continue
            try:
                total += entry.stat().st_size
            except OSError:
                # A file that vanished between the walk and the stat is one we
                # were about to delete anyway.
                continue
    return total


def find_artefacts(base: pathlib.Path) -> Iterator[Artefact]:
    """Yield every removable build artefact under ``base``, outermost first.

    Raises:
        FileNotFoundError: if ``base`` does not exist.
        NotADirectoryError: if ``base`` is not a directory.
    """
    if not base.exists():
        raise FileNotFoundError(f'Cache folder does not exist: {base}')
    if not base.is_dir():
        raise NotADirectoryError(f'Cache folder is not a directory: {base}')

    for root, dirs, files in os.walk(base):
        root_path = pathlib.Path(root)
        keep: list[str] = []
        for name in sorted(dirs):
            if name in PRESERVED_DIRS:
                continue
            path = root_path / name
            if path.is_symlink():
                # Removing the link would not reclaim anything, and following
                # it could take us out of the cache entirely.
                continue
            if _is_artefact_dir(name):
                # Yielded, and not descended into: the whole tree goes.
                yield Artefact(path=path, size=_tree_size(path), is_dir=True)
            else:
                keep.append(name)
        dirs[:] = keep
        for name in sorted(files):
            if name not in ARTEFACT_FILES:
                continue
            path = root_path / name
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            yield Artefact(path=path, size=size, is_dir=False)


def remove(artefact: Artefact) -> bool:
    """Delete ``artefact``, returning whether it went.

    A failure is logged rather than raised: one unreadable charm should not
    stop the rest of the cache being reclaimed.
    """
    try:
        if artefact.is_dir:
            shutil.rmtree(artefact.path)
        else:
            artefact.path.unlink()
    except OSError as exc:
        logger.warning('Could not remove %s: %s', artefact.path, exc)
        return False
    return True


def format_size(size: int) -> str:
    """Render a byte count the way a person would say it."""
    value = float(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if value < 1024 or unit == 'GiB':
            break
        value /= 1024
    if unit == 'B':
        return f'{int(value)} B'
    return f'{value:.1f} {unit}'
