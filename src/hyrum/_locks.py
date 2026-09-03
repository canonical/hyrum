"""Per-charm exclusion between hyrum runs that share a charm cache.

Patching a charm is snapshot, rewrite, run, restore, and the charm's own
working tree is the medium. Two runs over one cache therefore interleave:
A snapshots, A patches, B snapshots (and takes A's patched tree for the
original), B patches, A runs against B's dependency. Nothing fails, and A's
results silently describe B's patch.

An advisory lock per charm, held for the whole window, makes the second run
wait for the charm rather than join it. Locks live in a directory inside the
cache, so they travel with the thing they protect and a name starting with a
dot keeps them out of charm enumeration.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import pathlib
from collections.abc import Generator

logger = logging.getLogger(__name__)

LOCK_DIR_NAME = '.hyrum-locks'


def lock_root_for(charms_dir: pathlib.Path) -> pathlib.Path:
    """Return the directory holding the lock files for ``charms_dir``."""
    return charms_dir / LOCK_DIR_NAME


def lock_path(
    repo: pathlib.Path, *, lock_root: pathlib.Path, base: pathlib.Path | None
) -> pathlib.Path:
    """Return the lock file for ``repo``.

    Named from the repo's path relative to the cache so that monorepo
    subcharms lock separately, with ``/`` flattened because the locks live in
    one flat directory.
    """
    try:
        rel = repo.relative_to(base) if base is not None else repo
    except ValueError:
        rel = pathlib.Path(repo.name)
    return lock_root / (str(rel).replace('/', '__') + '.lock')


@contextlib.contextmanager
def charm_lock(
    repo: pathlib.Path,
    *,
    lock_root: pathlib.Path | None,
    base: pathlib.Path | None = None,
) -> Generator[None, None, None]:
    """Hold an exclusive lock on ``repo`` for the duration of the block.

    ``lock_root`` of ``None`` disables locking, which is what a caller that
    owns its charms directory outright wants.

    A filesystem that cannot lock (some network mounts) is reported once and
    then run through unlocked: refusing to run at all would be a worse answer
    than the race the lock is there to prevent, which needs a second
    concurrent run before it can bite.
    """
    if lock_root is None:
        yield
        return

    path = lock_path(repo, lock_root=lock_root, base=base)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open('w')
    except OSError as exc:
        logger.warning('Could not create the lock file %s (%s); continuing unlocked', path, exc)
        yield
        return

    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Worth saying: from the outside this looks like the run having
            # stalled on one charm for no reason.
            logger.info('Waiting for another hyrum run to finish with %s', repo)
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError as exc:
            logger.warning('Could not lock %s (%s); continuing unlocked', path, exc)
            yield
            return
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
