"""Discover charm repositories on GitHub within a few seed organisations.

Uses GitHub's code-search API to find every public file named ``charmcraft.yaml``
(or ``metadata.yaml``) under one of the seed orgs, then emits one row per
discovered repository. Output is written to
``charm-list/github-candidates.csv`` for human triage.

The check command recurses into each repo to find the charms it contains, so
a multi-charm monorepo is captured by a single row. Hits inside ``tests/``,
``test/``, ``examples/``, or ``example/`` directories are skipped to avoid
treating fixture charms as evidence that a repo is a charm repo.

The code-search endpoint requires authentication. Provide a token via
``$GITHUB_TOKEN``. Search is rate-limited (30 req/min for
authenticated calls) — the script paginates serially and respects the limits
GitHub returns in the response headers.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import logging
import os
import pathlib
import re
import sys
import time
import typing
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


GITHUB_SEARCH_URL = 'https://api.github.com/search/code'

# Seed orgs. Add more as you find them — the script de-duplicates per repo.
DEFAULT_ORGS = (
    'canonical',
    'juju',
    'charmed-kubernetes',
    'jnsgruk',
    'openstack-charmers',
)

# We search for both markers because some older charms ship metadata.yaml only.
CHARM_MARKERS = ('charmcraft.yaml', 'metadata.yaml')

# Repos that match a charm marker but are not consumer charms hyrum should run:
# docs sites that happen to ship metadata.yaml, scaffolding/template charms with
# placeholder code, empty stubs, etc. Anyone reviewing a candidate row can add
# the owner/name pair here to keep it out of future discovery runs.
KNOWN_NON_CHARMS: frozenset[tuple[str, str]] = frozenset({
    ('canonical', 'data-platform-charms-template'),
    ('canonical', 'documentation-style-guide'),
    ('canonical', 'sandbox1'),
    ('canonical', 'sandbox2'),
    ('canonical', 'test-kubeflow-automation'),
    ('juju', 'charm-developer-docs'),
})

# Path segments that flag a hit as a test fixture / example rather than a real charm.
EXCLUDED_PATH_SEGMENTS = frozenset({'tests', 'test', 'examples', 'example'})

CSV_FIELDS = (
    'Org',
    'Repository',
    'Default Branch',
    'Marker',
    'Archived',
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv',
        type=pathlib.Path,
        default=pathlib.Path('charm-list/github-candidates.csv'),
    )
    parser.add_argument(
        '--org',
        action='append',
        dest='orgs',
        help='GitHub org to scan (repeatable). Defaults to the built-in seed list.',
    )
    parser.add_argument(
        '--include-archived',
        action='store_true',
        help='Keep archived repos in the output (default: drop them).',
    )
    parser.add_argument('--log-level', default='INFO')
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format='%(levelname)s %(name)s: %(message)s')

    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print(
            'error: GitHub code search requires a token; set $GITHUB_TOKEN',
            file=sys.stderr,
        )
        return 1

    client = GitHubClient(token=token)
    orgs = tuple(args.orgs) if args.orgs else DEFAULT_ORGS
    rows = discover(client, orgs, include_archived=args.include_archived)
    write_csv(args.csv, rows)
    print(f'{len(rows)} candidate(s) -> {args.csv}')
    return 0


def discover(
    client: GitHubClient, orgs: typing.Iterable[str], *, include_archived: bool
) -> list[dict[str, str]]:
    """Return one row per repository found under ``orgs``.

    A repo qualifies if it contains at least one ``charmcraft.yaml`` or
    ``metadata.yaml`` outside of tests/examples. Multi-charm monorepos are
    represented by a single row — the check command discovers the individual
    charms by walking the cloned tree.
    """
    # (owner, name) -> row. A repo is recorded the first time any non-test
    # marker is seen inside it; later hits only upgrade Marker from
    # metadata.yaml to charmcraft.yaml.
    by_repo: dict[tuple[str, str], dict[str, str]] = {}
    for org in orgs:
        for marker in CHARM_MARKERS:
            logger.info('Searching org:%s filename:%s', org, marker)
            for item in client.search_code(f'filename:{marker} org:{org}'):
                path = item.get('path') or ''
                if not path.endswith(marker):
                    continue
                if _is_excluded_path(path):
                    continue
                repo = item.get('repository') or {}
                owner = (repo.get('owner') or {}).get('login') or ''
                name = repo.get('name') or ''
                if not owner or not name:
                    continue
                if (owner, name) in KNOWN_NON_CHARMS:
                    logger.info('Dropping known-non-charm %s/%s', owner, name)
                    continue
                key = (owner, name)
                existing = by_repo.get(key)
                if existing and existing['Marker'] == 'charmcraft.yaml':
                    continue
                by_repo[key] = {
                    'Org': owner,
                    'Repository': repo.get('html_url') or f'https://github.com/{owner}/{name}',
                    'Default Branch': '',  # filled below
                    'Marker': marker,
                    'Archived': '',
                }

    # Second pass: fetch each repo's metadata to record default branch + archived state.
    repo_info: dict[tuple[str, str], dict[str, typing.Any] | None] = {}
    rows: list[dict[str, str]] = []
    for (owner, name), row in sorted(by_repo.items()):
        if (owner, name) not in repo_info:
            repo_info[owner, name] = client.repo(owner, name)
        info = repo_info[owner, name]
        if info is None:
            continue
        if info.get('archived') and not include_archived:
            logger.info('Dropping archived %s/%s', owner, name)
            continue
        # Code-search runs under the caller's token, so private/internal repos
        # the token can see show up alongside public ones. Drop anything not
        # visible to an anonymous clone — listing internal repo names in a
        # public CSV would leak them.
        if info.get('visibility') != 'public':
            logger.info(
                'Dropping non-public %s/%s (visibility=%s)',
                owner,
                name,
                info.get('visibility') or 'unknown',
            )
            continue
        # GitHub-flagged template repos exist to be forked, not run; they
        # ship with placeholder code that does not lint cleanly.
        if info.get('is_template'):
            logger.info('Dropping template repo %s/%s', owner, name)
            continue
        default_branch = info.get('default_branch') or ''
        # Charm bundles match the discovery filter (they ship charmcraft.yaml)
        # but are not standalone consumer charms — they reference other
        # charms by name. hyrum's enumerator handles bundles separately
        # (iter_bundle), so drop them here to keep the curated list pure.
        if row['Marker'] == 'charmcraft.yaml' and default_branch:
            text = client.file_text(owner, name, 'charmcraft.yaml', default_branch)
            if text and _CHARMCRAFT_TYPE_BUNDLE_RE.search(text):
                logger.info('Dropping bundle %s/%s', owner, name)
                continue
        row['Default Branch'] = default_branch
        row['Archived'] = 'yes' if info.get('archived') else 'no'
        rows.append(row)
    return rows


# Matches `type: bundle` as a top-level YAML key. The regex is anchored at
# start-of-line (multiline mode) to avoid matching e.g. a comment or a value
# embedded in a longer string.
_CHARMCRAFT_TYPE_BUNDLE_RE = re.compile(
    r'^\s*type\s*:\s*bundle\b',
    re.MULTILINE,
)


def _is_excluded_path(path: str) -> bool:
    """Return True if ``path`` lives under a tests/examples directory."""
    return any(segment in EXCLUDED_PATH_SEGMENTS for segment in path.split('/')[:-1])


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    """Write ``rows`` to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Buffer first so a mid-iteration error can't leave a half-written CSV on disk.
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, '') for field in CSV_FIELDS})
    # newline='' disables Windows LF→CRLF translation so the committed file is LF everywhere.
    path.write_text(buffer.getvalue(), encoding='utf-8', newline='')


class GitHubClient:
    """Minimal authenticated GitHub REST client for code search + repo metadata."""

    def __init__(self, *, token: str, timeout: float = 30.0):
        self.token = token
        self.timeout = timeout

    def search_code(self, query: str) -> typing.Iterator[dict[str, typing.Any]]:
        """Yield every search hit for ``query``, paginating until exhausted.

        GitHub caps code search at 1000 results per query (10 pages of 100). If a
        query hits the cap the script logs and stops paginating for that query.
        """
        page = 1
        while page <= 10:
            params = urllib.parse.urlencode({'q': query, 'per_page': 100, 'page': page})
            try:
                data, headers = self._get(f'{GITHUB_SEARCH_URL}?{params}')
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429):
                    wait = int(exc.headers.get('Retry-After') or 60)
                    logger.info('Code search throttled (HTTP %s); sleeping %ds', exc.code, wait)
                    time.sleep(wait)
                    continue
                raise
            items = data.get('items', [])
            yield from items
            if len(items) < 100:
                return
            page += 1
            self._respect_rate_limit(headers)
            time.sleep(2)  # stay under the 30 req/min code-search secondary limit

    def repo(self, owner: str, name: str) -> dict[str, typing.Any] | None:
        """Return repo metadata, or ``None`` on 404."""
        url = f'https://api.github.com/repos/{owner}/{name}'
        try:
            data, _ = self._get(url)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            logger.warning('%s/%s: HTTP %s', owner, name, exc.code)
            return None

    def file_text(self, owner: str, name: str, path: str, ref: str) -> str | None:
        """Return the decoded contents of ``path`` at ``ref``, or ``None`` if absent."""
        url = (
            f'https://api.github.com/repos/{owner}/{name}/contents/'
            f'{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}'
        )
        try:
            data, _ = self._get(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            logger.warning('%s/%s:%s: HTTP %s', owner, name, path, exc.code)
            return None
        content = data.get('content')
        encoding = data.get('encoding')
        if not isinstance(content, str) or encoding != 'base64':
            return None
        try:
            return base64.b64decode(content).decode('utf-8', errors='replace')
        except (ValueError, UnicodeDecodeError):
            return None

    def _get(self, url: str) -> tuple[dict[str, typing.Any], dict[str, str]]:
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                'Accept': 'application/vnd.github+json',
                'Authorization': f'Bearer {self.token}',
                'X-GitHub-Api-Version': '2022-11-28',
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode()), dict(response.headers)

    @staticmethod
    def _respect_rate_limit(headers: dict[str, str]) -> None:
        """Sleep if the search rate limit is nearly exhausted."""
        remaining = headers.get('X-RateLimit-Remaining')
        reset = headers.get('X-RateLimit-Reset')
        if remaining and remaining.isdigit() and int(remaining) <= 1 and reset and reset.isdigit():
            wait = max(0, int(reset) - int(time.time())) + 1
            logger.info('Rate limit reached; sleeping %ds', wait)
            time.sleep(wait)


if __name__ == '__main__':
    sys.exit(main())
