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
import csv
import logging
import pathlib
import typing

import click

logger = logging.getLogger(__name__)


CharmRow = typing.TypedDict(
    'CharmRow',
    {
        'Charm Name': typing.NotRequired[str],
        'Repository': str,
        'Branch (if not the default)': typing.NotRequired[str],
    },
)
"""Expected shape of a row in the charms CSV."""


DEFAULT_SOURCE_CANDIDATES = (
    pathlib.Path('charms.csv'),
    pathlib.Path('charm-list/charms.csv'),
)


def _default_source() -> pathlib.Path:
    """Return the first existing candidate, falling back to the last for error messages."""
    for candidate in DEFAULT_SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_SOURCE_CANDIDATES[-1]


@click.command('get-charms')
@click.option(
    '--source',
    'source',
    type=click.Path(dir_okay=False, path_type=pathlib.Path),
    default=_default_source,
    show_default=' or '.join(str(p) for p in DEFAULT_SOURCE_CANDIDATES),
    help='Path to the charm list.',
)
@click.option(
    '--dest',
    'dest',
    envvar='HYRUM_CHARMS',
    default=lambda: pathlib.Path('~/.cache/hyrum/charms').expanduser(),
    show_default='~/.cache/hyrum/charms',
    type=click.Path(file_okay=False, path_type=pathlib.Path),
    help='Charms directory to download into. [env: HYRUM_CHARMS]',
)
def get_charms(source: pathlib.Path, dest: pathlib.Path) -> None:
    """Populate the charms directory by cloning or pulling every charm listed in the CSV."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

    if not source.exists():
        raise click.UsageError(f'Charm list not found: {source}')
    dest.mkdir(parents=True, exist_ok=True)

    with source.open(newline='', encoding='utf-8') as f:
        rows: list[CharmRow] = list(csv.DictReader(f))  # type: ignore[arg-type]
    asyncio.run(process_rows(rows, dest))


async def process_rows(
    rows: typing.Iterable[CharmRow],
    dest: pathlib.Path,
) -> None:
    """Clone or pull each repository row concurrently."""
    tasks: list[tuple[str, asyncio.Task[bool]]] = []
    async with asyncio.TaskGroup() as tg:
        for row in rows:
            if not row.get('Repository'):
                logger.warning('Skipping row without Repository: %r', row)
                continue
            name = row.get('Charm Name', '')
            repository = row['Repository'].rstrip('/')
            branch = row.get('Branch (if not the default)') or None
            repo_path = repo_folder(dest, repository, branch)
            if repo_path.exists():
                tasks.append((name, tg.create_task(_pull(repo_path, name))))
            else:
                tasks.append((name, tg.create_task(_clone(repo_path, name, repository, branch))))

    failures = [name for name, task in tasks if not task.result()]
    succeeded = len(tasks) - len(failures)
    logger.info('get-charms: %d succeeded, %d failed.', succeeded, len(failures))
    if failures:
        logger.warning('Failed: %s', ', '.join(failures))


def repo_folder(dest: pathlib.Path, repository: str, branch: str | None) -> pathlib.Path:
    """Return the directory inside ``dest`` for ``repository``, namespaced by owner."""
    parts = repository.rstrip('/').rsplit('/', 2)
    owner, base_name = parts[-2], parts[-1]
    leaf = f'{base_name}-{branch}' if branch else base_name
    return dest / owner / leaf


async def _pull(dest: pathlib.Path, name: str) -> bool:
    """Fast-forward ``dest`` to its upstream. Returns True on success."""
    logger.info('Pulling %s in %s', name, dest)
    proc = await asyncio.create_subprocess_exec(
        'git', 'pull', '--quiet', cwd=dest.resolve(), stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning('Could not pull %s: %r', name, _decode_stderr(stderr))
        return False
    return True


async def _clone(dest: pathlib.Path, name: str, repository: str, branch: str | None) -> bool:
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
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=dest.parent, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            'Could not clone %s from %s: %r', name, repository, _decode_stderr(stderr)
        )
        return False
    return True


def _decode_stderr(stderr: bytes | None) -> str:
    if not stderr:
        return 'git exited non-zero with no stderr'
    return stderr.decode('utf-8', errors='replace').strip() or 'git exited non-zero with no stderr'
