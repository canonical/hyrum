"""Walk a folder of cloned charm repositories and yield each charm path.

Handles:
  * flat layouts (one charm per top-level directory),
  * bundles (`bundle.yaml` -> iterate `charms/`),
  * monorepos heuristically detected by the presence of `charmcraft.yaml`
    or `metadata.yaml` in a subdirectory, at any depth up to
    :data:`_MAX_DEPTH`.

Reactive and classic hook-based charms are dropped by the ``not_legacy``
filter at the application layer — ``hyrum`` targets ``ops``-based charms.

Charm-collection curation is out of scope for this tool. The cache
folder is assumed to be pre-populated (e.g. by ``get-charms`` or
``git clone`` invoked separately).
"""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# How far below a repository root to look for charms. Genuine multi-charm
# monorepos nest their charms a level or two below the root (``charms/foo``,
# ``operators/foo/bar``), and a single charm is sometimes tucked into a
# ``charm/`` subdirectory of a larger project. Beyond three levels the
# directories that turn up are test fixtures and vendored trees rather than
# charms anyone wants to run.
_MAX_DEPTH = 3

# Directory names never worth descending into: build output, virtualenvs,
# vendored dependencies, the charm libraries under ``lib/charms/`` (which are
# other people's charms, not this repository's), and the test trees where a
# ``charmcraft.yaml`` belongs to a fixture rather than to a charm anyone wants
# to run.
_PRUNED_DIRS = frozenset({
    '__pycache__',
    'build',
    'dist',
    'docs',
    'lib',
    'node_modules',
    'site-packages',
    'test',
    'tests',
    'venv',
    'vendor',
})


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


def _iter_monorepo(base: pathlib.Path, depth: int) -> Iterator[pathlib.Path]:
    """Yield the charms nested under the non-charm directory ``base``.

    Recurses until a charm is found on a branch or ``depth`` runs out,
    whichever comes first: a directory that is itself a charm is yielded
    whole rather than descended into, so a charm's own ``tests/`` and
    ``src/`` trees never get walked.
    """
    if depth <= 0:
        return
    for child in sorted(base.iterdir()):
        # Symlinked directories are skipped rather than followed: they are how
        # a walk of a charm repository turns into a cycle.
        if not child.is_dir() or child.is_symlink():
            continue
        if child.name.startswith('.') or child.name in _PRUNED_DIRS:
            continue
        if _is_charm_dir(child):
            yield child
        elif _is_bundle_dir(child):
            yield from _iter_bundle(child)
        else:
            yield from _iter_monorepo(child, depth - 1)


def iter_charm_repos(base: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield each charm repository under ``base``.

    Each yielded path is the charm's root (the directory containing
    ``charmcraft.yaml`` / ``metadata.yaml`` for single-charm repos, or
    the per-charm subdirectory for bundles/monorepos).

    A repository that contributes no charms is logged rather than passed
    over silently, so the collection's effective size stays visible.
    """
    if not base.exists():
        raise FileNotFoundError(f'Cache folder does not exist: {base}')
    if not base.is_dir():
        raise NotADirectoryError(f'Cache folder is not a directory: {base}')

    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        if _is_bundle_dir(entry):
            children = _iter_bundle(entry)
        elif _is_charm_dir(entry):
            yield entry
            continue
        else:
            children = _iter_monorepo(entry, _MAX_DEPTH)
        found = False
        for charm in children:
            found = True
            yield charm
        if not found:
            logger.warning(
                'No charm found in %s (no charmcraft.yaml or metadata.yaml '
                'within %d directory levels)',
                entry,
                _MAX_DEPTH,
            )
