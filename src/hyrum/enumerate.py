"""Walk a folder of cloned charm repositories and yield each charm path.

Handles:
  * flat layouts (one charm per top-level directory),
  * bundles (`bundle.yaml` -> iterate `charms/`),
  * monorepos heuristically detected by the presence of `charmcraft.yaml`
    or `metadata.yaml` in a subdirectory.

Reactive and classic hook-based charms are filtered out — `hyrum`
targets `ops`-based charms.

Charm-collection curation is out of scope for this tool. The cache
folder is assumed to be pre-populated (e.g. by ``get-charms`` or
``git clone`` invoked separately).
"""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _is_charm_dir(path: pathlib.Path) -> bool:
    return (path / 'charmcraft.yaml').exists() or (path / 'metadata.yaml').exists()


def _is_bundle_dir(path: pathlib.Path) -> bool:
    return (path / 'bundle.yaml').exists()


def _iter_bundle(base: pathlib.Path) -> Iterator[pathlib.Path]:
    charms_dir = base / 'charms'
    if not charms_dir.exists():
        logger.warning('Bundle %s has no charms/ directory', base)
        return
    for child in sorted(charms_dir.iterdir()):
        if child.is_dir() and not child.name.startswith('.'):
            yield child


def _iter_monorepo(base: pathlib.Path) -> Iterator[pathlib.Path]:
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith('.'):
            continue
        if _is_charm_dir(child):
            yield child
        elif _is_bundle_dir(child):
            yield from _iter_bundle(child)


def _is_legacy_charm(path: pathlib.Path) -> bool:
    # Reactive charms have a `reactive/` directory; classic hook charms
    # have a `hooks/` directory. Both predate `ops` and are out of scope.
    return (path / 'reactive').exists() or (path / 'hooks').exists()


def iter_charm_repos(base: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield each charm repository under ``base``.

    Each yielded path is the charm's root (the directory containing
    ``charmcraft.yaml`` / ``metadata.yaml`` for single-charm repos, or
    the per-charm subdirectory for bundles/monorepos).
    """
    if not base.exists():
        raise FileNotFoundError(f'Cache folder does not exist: {base}')
    if not base.is_dir():
        raise NotADirectoryError(f'Cache folder is not a directory: {base}')

    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        if _is_bundle_dir(entry):
            candidates = _iter_bundle(entry)
        elif _is_charm_dir(entry):
            candidates = iter([entry])
        else:
            # Treat as a monorepo; if it has no charm subdirs this yields nothing.
            candidates = _iter_monorepo(entry)
        for candidate in candidates:
            if _is_legacy_charm(candidate):
                logger.info('Ignoring legacy (reactive/hooks) charm: %s', candidate)
                continue
            yield candidate
