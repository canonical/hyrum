"""Merge discovery candidate CSVs into ``charm-list/charms.csv``.

Reads one or more candidate CSVs (from ``discover_launchpad_charms.py`` or
``discover_github_charms.py``) and appends any repositories that are not
already tracked in ``charms.csv``. New rows are written with
``Source: auto-discover`` so they can be triaged separately from Charmhub
auto-discoveries (``Source: auto``) and human entries (``Source: manual``).

This script is intended for manual / occasional use — there is no CI hook
that runs it automatically.
"""

from __future__ import annotations

import argparse
import csv
import logging
import pathlib
import sys

from update_charm_list import (
    AUTO_DISCOVER_SOURCE,
    normalise_url,
    read_csv,
    validate,
    write_csv,
)

logger = logging.getLogger(__name__)


# Maps the standard Canonical CLI verbosity vocabulary to Python logging levels.
VERBOSITY_LEVELS = {
    'quiet': logging.ERROR,
    'brief': logging.WARNING,
    'verbose': logging.INFO,
    'debug': logging.DEBUG,
    'trace': logging.DEBUG,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv',
        type=pathlib.Path,
        default=pathlib.Path('charm-list/charms.csv'),
        help='Target charm list to merge into.',
    )
    parser.add_argument(
        'candidates',
        nargs='+',
        type=pathlib.Path,
        help='Candidate CSV(s) — output of the discover_* scripts.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the rows that would be added without writing.',
    )
    parser.add_argument(
        '--verbosity',
        choices=VERBOSITY_LEVELS,
        default='brief',
        help='Output verbosity (default: brief).',
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=VERBOSITY_LEVELS[args.verbosity], format='%(levelname)s %(name)s: %(message)s'
    )

    rows = read_csv(args.csv)
    validate(rows)
    seen_urls = {normalise_url(row['Repository']) for row in rows}

    added: list[dict[str, str]] = []
    for path in args.candidates:
        for candidate in read_candidates(path):
            url = candidate['Repository']
            key = normalise_url(url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            added.append({
                'Team': candidate.get('Team', ''),
                'Repository': url,
                'Branch (if not the default)': '',
                'Source': AUTO_DISCOVER_SOURCE,
            })

    if not added:
        print('no new rows', file=sys.stderr)
        return 0
    for row in added:
        print(f'+ {row["Repository"]}')
    if args.dry_run:
        print(f'{len(added)} new row(s) (dry run; not written)', file=sys.stderr)
        return 0
    merged = rows + added
    validate(merged)
    write_csv(args.csv, merged)
    print(f'{len(added)} new row(s) appended to {args.csv}', file=sys.stderr)
    return 0


def read_candidates(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a candidate CSV. Requires at least a ``Repository`` column."""
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        return []
    if 'Repository' not in rows[0]:
        raise ValueError(f'{path}: missing required column: Repository')
    return [{(k or ''): (v or '') for k, v in row.items()} for row in rows]


if __name__ == '__main__':
    sys.exit(main())
