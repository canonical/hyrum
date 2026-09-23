"""Walk a folder of cloned charm repositories and yield each charm path.

The cache folder is ``<charms-dir>/<owner>/<leaf>``, as ``get-charms``
writes it, so the repositories are the second level down and the depth
budget below is counted from a repository root.

Handles:
  * flat layouts (one charm per repository),
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
    'demo',
    'dist',
    'docs',
    'example',
    'examples',
    'fixtures',
    'lib',
    'node_modules',
    'site-packages',
    'spread',
    'templates',
    'test',
    'tests',
    'venv',
    'vendor',
})


def _walkable(path: pathlib.Path) -> bool:
    """Return whether ``path`` is a directory worth descending into."""
    # Symlinked directories are skipped rather than followed: they are how a
    # walk of a charm repository turns into a cycle.
    return path.is_dir() and not path.is_symlink() and not path.name.startswith('.')


def _is_charm_dir(path: pathlib.Path) -> bool:
    return (path / 'charmcraft.yaml').exists() or (path / 'metadata.yaml').exists()


def _is_bundle_dir(path: pathlib.Path) -> bool:
    return (path / 'bundle.yaml').exists()


def _iter_bundle(base: pathlib.Path, *, warn: bool = True) -> Iterator[pathlib.Path]:
    """Yield the charms of the bundle rooted at ``base``.

    ``warn`` is off for a bundle found part-way down a repository: a
    ``bundle.yaml`` in an archive of past releases has no ``charms/`` and
    nothing is wrong with that, and there can be dozens of them in one
    repository. A repository that is *itself* a bundle and has no
    ``charms/`` is worth a line.
    """
    charms_dir = base / 'charms'
    if not charms_dir.exists():
        logger.log(
            logging.WARNING if warn else logging.DEBUG,
            'Bundle %s has no charms/ directory',
            base,
        )
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
        if not _walkable(child) or child.name in _PRUNED_DIRS:
            continue
        if _is_charm_dir(child):
            yield child
        elif _is_bundle_dir(child):
            yield from _iter_bundle(child, warn=False)
        else:
            yield from _iter_monorepo(child, depth - 1)


def _iter_repos(base: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield the repository directories in the cache folder ``base``.

    ``get-charms`` clones into ``<charms-dir>/<owner>/<leaf>`` (see
    ``_get_charms.repo_folder``), so a repository is two levels down and the
    top level holds owners. Walking the top level as if it held repositories
    spends a level of the depth budget before the repository root, and
    attributes anything said about a repository to its owner instead.

    A top-level entry that is itself a charm or a bundle is yielded as its own
    repository, so a hand-assembled flat cache still enumerates.
    """
    for entry in sorted(base.iterdir()):
        if not _walkable(entry):
            continue
        if _is_charm_dir(entry) or _is_bundle_dir(entry):
            yield entry
            continue
        for child in sorted(entry.iterdir()):
            if _walkable(child):
                yield child


def iter_charm_repos(base: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield each charm under ``base``.

    Each yielded path is the charm's root (the directory containing
    ``charmcraft.yaml`` / ``metadata.yaml`` for single-charm repos, or
    the per-charm subdirectory for bundles/monorepos).

    A repository that contributes no charms is logged rather than passed over
    silently, so the collection's effective size stays visible. The caller
    stops early under ``--limit``, and this is a generator, so on a limited
    run only the repositories actually reached are reported.
    """
    if not base.exists():
        raise FileNotFoundError(f'Cache folder does not exist: {base}')
    if not base.is_dir():
        raise NotADirectoryError(f'Cache folder is not a directory: {base}')

    for repo in _iter_repos(base):
        if _is_charm_dir(repo):
            yield repo
            continue
        if _is_bundle_dir(repo):
            # _iter_bundle says its own piece about a bundle with no charms/.
            yield from _iter_bundle(repo)
            continue
        found = False
        for charm in _iter_monorepo(repo, _MAX_DEPTH):
            found = True
            yield charm
        if not found:
            logger.warning(
                'No charm found in %s (no charmcraft.yaml or metadata.yaml '
                'within %d directory levels)',
                repo,
                _MAX_DEPTH,
            )
