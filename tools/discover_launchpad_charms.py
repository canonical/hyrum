"""Discover public charm repositories on Launchpad.

Walks a hardcoded set of Launchpad teams, lists every git repository they own
via the Launchpad REST API, and probes each repo's default branch for
``charmcraft.yaml`` or ``metadata.yaml``. Repos that look like charms are
written to ``charm-list/launchpad-candidates.csv`` for human triage.

Prototype: the team allowlist is the seed set, not exhaustive. Bazaar branches
(``lp:~team/...``) are out of scope for this first cut — git only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import pathlib
import sys
import typing
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


LP_API = 'https://api.launchpad.net/devel'
LP_GIT_RAW = 'https://git.launchpad.net'

# Seed set. Add teams here as you discover them. The script de-duplicates
# repos that appear under more than one team.
DEFAULT_TEAMS = (
    'canonical-is-charmers',
    'launchpad',
    'launchpad-services',
    'canonical-server',
    'canonical-sysadmins',
    'canonical-bootstack',
    'canonical-kubernetes',
    'charmers',
    'openstack-charmers',
    'containers',
    'prodstack-charmers',
)

CHARM_MARKERS = ('charmcraft.yaml', 'metadata.yaml')

CSV_FIELDS = ('Team', 'Repository', 'Default Branch', 'Marker')


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv',
        type=pathlib.Path,
        default=pathlib.Path('charm-list/launchpad-candidates.csv'),
        help='Output CSV path.',
    )
    parser.add_argument(
        '--team',
        action='append',
        dest='teams',
        help='Launchpad team to scan (repeatable). Defaults to the built-in seed list.',
    )
    parser.add_argument('--log-level', default='INFO')
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format='%(levelname)s %(name)s: %(message)s')

    client = LaunchpadClient()
    teams = tuple(args.teams) if args.teams else DEFAULT_TEAMS
    rows = discover(client, teams)
    write_csv(args.csv, rows)
    print(f'{len(rows)} candidate(s) -> {args.csv}')
    return 0


def discover(client: LaunchpadClient, teams: typing.Iterable[str]) -> list[dict[str, str]]:
    """Return one row per (team, repo) pair that looks like a charm."""
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for team in teams:
        logger.info('Scanning ~%s', team)
        try:
            repos = list(client.team_repositories(team))
        except urllib.error.HTTPError as exc:
            logger.warning('~%s: HTTP %s; skipping', team, exc.code)
            continue
        for repo in repos:
            git_url = repo.get('git_https_url') or ''
            if not git_url or git_url in seen:
                continue
            seen.add(git_url)
            default_branch = strip_ref(repo.get('default_branch'))
            if not default_branch:
                continue
            raw_path = git_url.removeprefix(LP_GIT_RAW).lstrip('/')
            marker = first_marker(raw_path, default_branch)
            if not marker:
                continue
            rows.append({
                'Team': team,
                'Repository': git_url,
                'Default Branch': default_branch,
                'Marker': marker,
            })
    rows.sort(key=lambda r: (r['Team'], r['Repository']))
    return rows


def strip_ref(ref: str | None) -> str:
    """Strip ``refs/heads/`` from a Launchpad default-branch field."""
    if not ref:
        return ''
    prefix = 'refs/heads/'
    return ref[len(prefix) :] if ref.startswith(prefix) else ref


def first_marker(unique_name: str, branch: str) -> str | None:
    """Return the first ``CHARM_MARKERS`` filename present at branch root."""
    for name in CHARM_MARKERS:
        url = f'{LP_GIT_RAW}/{unique_name}/plain/{name}?h={urllib.parse.quote(branch)}'
        request = urllib.request.Request(url, method='HEAD')  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                if 200 <= response.status < 300:
                    return name
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                logger.debug('%s %s: HTTP %s', unique_name, name, exc.code)
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.debug('%s %s: %s', unique_name, name, exc)
    return None


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    """Write ``rows`` to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, '') for field in CSV_FIELDS})
    path.write_text(buffer.getvalue(), encoding='utf-8', newline='')


class LaunchpadClient:
    """Anonymous reader for the Launchpad REST API."""

    def __init__(self, *, timeout: float = 30.0):
        self.timeout = timeout

    def team_repositories(self, team: str) -> typing.Iterator[dict[str, typing.Any]]:
        """Yield every git repository owned by ``~team``."""
        target = urllib.parse.quote(f'/~{team}', safe='')
        url: str | None = f'{LP_API}/+git?ws.op=getRepositories&target={target}'
        while url:
            data = self._get(url)
            yield from data.get('entries', [])
            url = data.get('next_collection_link')

    def _get(self, url: str) -> dict[str, typing.Any]:
        request = urllib.request.Request(  # noqa: S310
            url, headers={'Accept': 'application/json'}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode())


if __name__ == '__main__':
    sys.exit(main())
