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
    parser.add_argument('--log-level', default='INFO')
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format='%(levelname)s %(name)s: %(message)s')

    rows = read_csv(args.csv)
    validate(rows)
    # Dedupe per charm (repo + charm name), so multi-charm monorepos can contribute
    # one row per charm. A row matching by URL alone is also treated as a duplicate
    # to stay backward-compatible with single-charm entries that pre-date this script.
    seen_charms = {(normalise_url(row['Repository']), row['Charm Name']) for row in rows}
    seen_urls = {normalise_url(row['Repository']) for row in rows}

    added: list[dict[str, str]] = []
    for path in args.candidates:
        for candidate in read_candidates(path):
            url = candidate['Repository']
            charm_name = candidate['Charm Name']
            key = (normalise_url(url), charm_name)
            if key in seen_charms:
                continue
            # Skip single-charm repos already tracked under a different name to avoid
            # introducing duplicates when the existing row pre-dates name normalisation.
            # Multi-charm monorepos opt out by setting ``Charm Path``.
            if not candidate.get('Charm Path') and normalise_url(url) in seen_urls:
                continue
            seen_charms.add(key)
            seen_urls.add(normalise_url(url))
            added.append({
                'Team': candidate.get('Team', ''),
                'Charm Name': charm_name,
                'Repository': url,
                'Branch (if not the default)': '',
                'Source': AUTO_DISCOVER_SOURCE,
            })

    if not added:
        print('no new rows')
        return 0
    for row in added:
        print(f'+ {row["Charm Name"]} {row["Repository"]}')
    if args.dry_run:
        print(f'{len(added)} new row(s) (dry run; not written)')
        return 0
    merged = rows + added
    validate(merged)
    write_csv(args.csv, merged)
    print(f'{len(added)} new row(s) appended to {args.csv}')
    return 0


def read_candidates(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a candidate CSV. Requires at least ``Charm Name`` and ``Repository``."""
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        return []
    missing = {'Charm Name', 'Repository'} - set(rows[0].keys())
    if missing:
        raise ValueError(f'{path}: missing required column(s): {sorted(missing)}')
    return [{(k or ''): (v or '') for k, v in row.items()} for row in rows]


if __name__ == '__main__':
    sys.exit(main())
