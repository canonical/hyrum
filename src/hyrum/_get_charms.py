"""Bulk clone or update charm repositories listed in a CSV.

Reads ``charm-list/charms.csv`` (or another path given via ``--source``) and
ensures each row has an up-to-date checkout in ``--dest``: missing
repositories are cloned (shallow, single-branch), existing ones are pulled.
Network work runs concurrently via ``asyncio``.

The ``git`` CLI is invoked as a subprocess, so it inherits whatever
authentication the calling shell has configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import shutil
import signal
import typing

logger = logging.getLogger(__name__)


_GIT_ENV = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/true'}
"""Environment for git subprocesses: never prompt for credentials.

Without this, a single private/moved repo on a tty would block on getpass
and stall the whole TaskGroup.
"""


CharmRow = typing.TypedDict(
    'CharmRow',
    {
        'Repository': str,
        'Branch (if not the default)': typing.NotRequired[str],
    },
)
"""Expected shape of a row in the charms CSV."""


DEFAULT_SOURCE_CANDIDATES = (
    pathlib.Path('charms.csv'),
    pathlib.Path('charm-list/charms.csv'),
)


DEFAULT_WORKERS = 16
"""Cap concurrent git subprocesses so a large charm list can't blow ``ulimit -n``.

Each in-flight ``git clone`` holds several fds (asyncio pipes + git's own
network/pack fds); a Multipass VM's default 1024-fd limit is trivially
exceeded when running unbounded across ~700 charms.
"""


DEFAULT_TIMEOUT = 300.0
"""Seconds before a single ``git`` invocation is abandoned.

Git applies no wall-clock deadline of its own, so a forge that accepts the
connection but never finishes the ref advertisement holds a worker slot
indefinitely. Launchpad has been observed doing this intermittently: it sends
the ``# service=git-upload-pack`` header and then stalls for minutes before
either recovering or never answering. With ``DEFAULT_WORKERS`` slots, enough
concurrent stalls park every worker and the run stops making progress.

Sized well above a legitimate slow clone -- Launchpad's larger charms need
20-30s for the ref advertisement alone -- so it only fires on a real stall.
"""


def find_default_source() -> pathlib.Path | None:
    """Return the first existing default candidate, or ``None`` if none exist."""
    for candidate in DEFAULT_SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


async def process_rows(
    rows: typing.Iterable[CharmRow],
    dest: pathlib.Path,
    *,
    workers: int = DEFAULT_WORKERS,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Clone or pull each repository row concurrently.

    ``workers`` caps how many ``git`` subprocesses run at once so a large
    charm list can't exhaust the process file-descriptor limit. ``timeout``
    bounds each individual ``git`` invocation so one unresponsive forge can't
    park a worker for the rest of the run; pass ``0`` to disable it.
    """
    sem = asyncio.Semaphore(max(1, workers))

    async def _pull_bounded(repo_path: pathlib.Path, name: str) -> bool:
        async with sem:
            return await _pull(repo_path, name, timeout=timeout)

    async def _clone_bounded(
        repo_path: pathlib.Path, name: str, repository: str, branch: str | None
    ) -> bool:
        async with sem:
            return await _clone(repo_path, name, repository, branch, timeout=timeout)

    tasks: list[tuple[str, asyncio.Task[bool]]] = []
    async with asyncio.TaskGroup() as tg:
        for row in rows:
            if not row.get('Repository'):
                logger.warning('Skipping row without Repository: %r', row)
                continue
            repository = row['Repository'].rstrip('/')
            name = _repo_label(repository)
            branch = row.get('Branch (if not the default)') or None
            repo_path = repo_folder(dest, repository, branch)
            if repo_path.exists():
                tasks.append((name, tg.create_task(_pull_bounded(repo_path, name))))
            else:
                tasks.append((
                    name,
                    tg.create_task(_clone_bounded(repo_path, name, repository, branch)),
                ))

    failures = [name for name, task in tasks if not task.result()]
    succeeded = len(tasks) - len(failures)
    logger.info('get-charms: %d succeeded, %d failed.', succeeded, len(failures))
    if failures:
        logger.warning('Failed: %s', ', '.join(failures))


def _repo_label(repository: str) -> str:
    """Return ``owner/name`` from a repository URL, for display in logs."""
    parts = repository.rstrip('/').rsplit('/', 2)
    return f'{parts[-2]}/{parts[-1]}'


def repo_folder(dest: pathlib.Path, repository: str, branch: str | None) -> pathlib.Path:
    """Return the directory inside ``dest`` for ``repository``, namespaced by owner."""
    parts = repository.rstrip('/').rsplit('/', 2)
    owner, base_name = parts[-2], parts[-1]
    leaf = f'{base_name}-{branch}' if branch else base_name
    return dest / owner / leaf


class _TimeoutError(Exception):
    """Raised internally when a ``git`` invocation outlives its deadline."""


async def _run_git(argv: list[str], cwd: pathlib.Path, *, timeout: float) -> tuple[int, bytes]:
    """Run ``git`` and return ``(returncode, stderr)``.

    Raises ``_TimeoutError`` if the process outlives ``timeout``. A non-positive
    ``timeout`` waits indefinitely.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env=_GIT_ENV,
        # Put git in its own process group so a timeout can take down its
        # transport helpers too -- see _terminate.
        start_new_session=True,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout if timeout > 0 else None
        )
    except TimeoutError:
        await _terminate(proc)
        raise _TimeoutError from None
    return proc.returncode or 0, stderr


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Kill ``proc``'s whole process group and reap it.

    Killing only ``proc`` is not enough: ``git clone`` delegates the transfer
    to a ``git remote-http`` helper that inherits the stderr pipe. Killing the
    parent alone reparents that helper to init, where it keeps the pipe open
    against an unresponsive server -- and the event loop then blocks forever
    waiting for the pipe to close. Signalling the group closes both.
    """
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()  # Fall back to the direct child if the group is gone.
    with contextlib.suppress(Exception):
        await proc.wait()


async def _pull(dest: pathlib.Path, name: str, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Fast-forward ``dest`` to its upstream. Returns True on success."""
    logger.info('Pulling %s in %s', name, dest)
    try:
        returncode, stderr = await _run_git(
            ['git', 'pull', '--quiet'], dest.resolve(), timeout=timeout
        )
    except _TimeoutError:
        logger.warning('Timed out after %gs pulling %s; skipping', timeout, name)
        return False
    if returncode != 0:
        logger.warning('Could not pull %s: %r', name, _decode_stderr(stderr))
        return False
    return True


async def _clone(
    dest: pathlib.Path,
    name: str,
    repository: str,
    branch: str | None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Shallow-clone ``repository`` into ``dest``. Returns True on success."""
    logger.info('Cloning %s from %s into %s', name, repository, dest)
    argv = [
        'git',
        'clone',
        '--depth=1',
        '--shallow-submodules',
        '--single-branch',
        '--no-tags',
        '--quiet',
    ]
    if branch:
        argv.extend(['--branch', branch])
    argv.extend([repository, str(dest.resolve())])
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        returncode, stderr = await _run_git(argv, dest.parent, timeout=timeout)
    except _TimeoutError:
        logger.error('Timed out after %gs cloning %s from %s; skipping', timeout, name, repository)
        _discard_partial_clone(dest, name)
        return False
    if returncode != 0:
        logger.error('Could not clone %s from %s: %r', name, repository, _decode_stderr(stderr))
        return False
    return True


def _discard_partial_clone(dest: pathlib.Path, name: str) -> None:
    """Remove a half-written clone so the next run retries instead of pulling.

    ``process_rows`` decides clone-vs-pull purely on whether the directory
    exists, so an abandoned clone left on disk would be treated as a valid
    checkout forever after.
    """
    if not dest.exists():
        return
    try:
        shutil.rmtree(dest)
    except OSError as exc:
        logger.warning('Could not remove partial clone for %s at %s: %s', name, dest, exc)


def _decode_stderr(stderr: bytes | None) -> str:
    if not stderr:
        return 'git exited non-zero with no stderr'
    return stderr.decode('utf-8', errors='replace').strip() or 'git exited non-zero with no stderr'
