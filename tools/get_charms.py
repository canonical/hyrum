#!/usr/bin/env python3
"""Bulk clone or update charm repositories listed in a CSV.

Reads ``charm-list/charms.csv`` (or another path given via ``--csv``) and
ensures each row has an up-to-date checkout in ``--cache-folder``: missing
repositories are cloned (shallow, single-branch), existing ones are pulled.
Network work runs concurrently via ``asyncio``.

The ``git`` CLI is invoked as a subprocess, so it inherits whatever
authentication the calling shell has configured.

The script is intentionally stdlib-only — same constraint as
``tools/update_charm_list.py`` — so it can run without any wheel install.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import pathlib
import sys
import typing

logger = logging.getLogger(__name__)

DEFAULT_CSV = pathlib.Path('charm-list/charms.csv')
DEFAULT_CACHE_FOLDER = pathlib.Path.home() / '.cache' / 'hyrum' / 'charms'


def main(argv: typing.Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv',
        type=pathlib.Path,
        default=DEFAULT_CSV,
        help='Path to the charm CSV (default: %(default)s).',
    )
    parser.add_argument(
        '--cache-folder',
        type=pathlib.Path,
        default=DEFAULT_CACHE_FOLDER,
        help='Destination folder for clones (default: %(default)s).',
    )
    parser.add_argument(
        '--ssh',
        action='store_true',
        help='Use SSH (git@github.com:) instead of HTTPS for GitHub URLs.',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        help='Python logging level (DEBUG, INFO, WARNING).',
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format='%(levelname)s %(name)s: %(message)s')

    if not args.csv.exists():
        logger.error('Charm list not found: %s', args.csv)
        return 1
    args.cache_folder.mkdir(parents=True, exist_ok=True)

    with args.csv.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    asyncio.run(process_rows(rows, args.cache_folder, use_ssh=args.ssh))
    return 0


async def process_rows(
    rows: typing.Iterable[dict[str, str]],
    cache: pathlib.Path,
    *,
    use_ssh: bool,
) -> None:
    """Clone or pull each repository row concurrently."""
    async with asyncio.TaskGroup() as tg:
        for row in rows:
            if not row.get('Repository'):
                continue
            name = row.get('Charm Name', '')
            repository = repository_url(row['Repository'], use_ssh=use_ssh)
            branch = row.get('Branch (if not the default)') or None
            dest = repo_folder(cache, repository, branch)
            if dest.exists():
                # We don't `git switch` here: assume any manual checkout state
                # in the cache is intentional. If the CSV's Branch column has
                # changed since the cache was populated, the user is expected
                # to wipe the stale checkout themselves.
                tg.create_task(pull(dest, name))
            else:
                tg.create_task(clone(dest, name, repository, branch))


def repository_url(raw: str, *, use_ssh: bool) -> str:
    """Strip trailing slashes and optionally switch GitHub URLs to SSH."""
    url = raw.rstrip('/')
    if use_ssh:
        url = url.replace('https://github.com/', 'git@github.com:')
    return url


def repo_folder(cache: pathlib.Path, repository: str, branch: str | None) -> pathlib.Path:
    """Return the destination directory for ``repository`` under ``cache``."""
    base_name = repository.rstrip('/').rsplit('/', 1)[1]
    if branch:
        return cache / f'{base_name}-{branch}'
    return cache / base_name


async def pull(dest: pathlib.Path, name: str) -> None:
    """Fast-forward ``dest`` to its upstream."""
    logger.info('Pulling %s in %s', name, dest)
    proc = await asyncio.create_subprocess_exec('git', 'pull', '--quiet', cwd=dest.resolve())
    await proc.wait()
    if proc.returncode != 0:
        logger.warning('Could not pull %s', name)


async def clone(dest: pathlib.Path, name: str, repository: str, branch: str | None) -> None:
    """Shallow-clone ``repository`` into ``dest``."""
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
    proc = await asyncio.create_subprocess_exec(*argv, cwd=dest.parent)
    await proc.wait()
    if proc.returncode != 0:
        logger.error('Could not clone %s from %s', name, repository)


if __name__ == '__main__':
    sys.exit(main())
