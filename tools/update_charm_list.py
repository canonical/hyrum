"""Refresh ``charm-list/charms.csv`` from Charmhub.

Three changes can be made by a run:

* New charms published on Charmhub whose source URL is not yet in the CSV are
  appended with ``Source`` set to ``auto``.
* Rows whose ``Repository`` is a GitHub URL that now 404s, or whose repo is
  marked archived on GitHub, are dropped.
* Auto-added rows (``Source`` is ``auto``) whose Charmhub-reported source URL
  has changed are rewritten. Manual rows are never rewritten, but URL drift
  against them is logged as a warning so a human can investigate.

Charmhub packages with no recorded source URL are written to
``charm-list/charms-no-source.csv`` each run so they can drive follow-up work
(e.g. opening issues asking charm owners to add source metadata).

The script is intentionally stdlib-only so that the weekly GitHub Action does
not have to install anything beyond Python.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import pathlib
import sys
import typing
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


CHARMHUB_PACKAGES_URL = 'https://charmhub.io/packages.json'
CHARMHUB_INFO_URL = 'https://api.charmhub.io/v2/charms/info'
GITHUB_REPO_URL = 'https://api.github.com/repos'

AUTO_SOURCE = 'auto'
MANUAL_SOURCE = 'manual'
VALID_SOURCES = frozenset({AUTO_SOURCE, MANUAL_SOURCE})

CSV_FIELDS = (
    'Team',
    'Charm Name',
    'Repository',
    'Branch (if not the default)',
    'Source',
)

NO_SOURCE_CSV_FIELDS = ('Charm Name',)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv',
        type=pathlib.Path,
        default=pathlib.Path('charm-list/charms.csv'),
        help='Path to the CSV to update.',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Validate the existing CSV (no network, no writes) and exit.',
    )
    parser.add_argument(
        '--github-token',
        default=os.environ.get('GITHUB_TOKEN'),
        help='GitHub token for the archive/404 probes. Defaults to $GITHUB_TOKEN.',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        help='Python logging level (DEBUG, INFO, WARNING).',
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format='%(levelname)s %(name)s: %(message)s')
    if args.check:
        try:
            validate(read_csv(args.csv))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    changed = run(
        args.csv,
        charmhub=CharmhubClient(),
        github=GitHubClient(token=args.github_token),
    )
    print('changed' if changed else 'unchanged')
    return 0


def run(csv_path: pathlib.Path, *, charmhub: CharmhubClient, github: GitHubClient) -> bool:
    """Update ``csv_path`` in place. Returns True iff the CSV changed.

    The no-source sidecar at ``no_source_csv_path(csv_path)`` is also written
    each run; the workflow detects sidecar changes via ``git diff``.
    """
    original = csv_path.read_bytes()
    rows = read_csv(csv_path)
    validate(rows)
    discovered, incomplete = discover_charmhub_urls(charmhub)
    updated = merge(rows, discovered, github)
    write_csv(csv_path, updated)
    write_no_source_csv(no_source_csv_path(csv_path), incomplete)
    return csv_path.read_bytes() != original


def validate(rows: list[dict[str, str]]) -> None:
    """Raise ``ValueError`` if ``rows`` violate the file's invariants.

    Checked invariants: every row has a non-empty ``Charm Name`` and
    ``Repository``, ``Source`` is one of ``VALID_SOURCES``, and no two rows
    share a ``Repository`` after URL normalisation.
    """
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(rows, start=2):  # +1 header, +1 1-indexed
        name = (row.get('Charm Name') or '').strip()
        url = (row.get('Repository') or '').strip()
        source = (row.get('Source') or '').strip()
        if not name:
            errors.append(f'row {index}: missing Charm Name')
        if not url:
            errors.append(f'row {index}: missing Repository')
        if source not in VALID_SOURCES:
            valid = ', '.join(repr(s) for s in sorted(VALID_SOURCES))
            errors.append(f'row {index}: Source must be one of {valid}, got {source!r}')
        if not url:
            continue
        key = normalise_url(url)
        if key in seen:
            errors.append(f'row {index}: duplicate Repository {url!r} (also row {seen[key]})')
        else:
            seen[key] = index
    if errors:
        raise ValueError('charm list is invalid:\n  ' + '\n  '.join(errors))


def discover_charmhub_urls(client: CharmhubClient) -> tuple[dict[str, str], list[str]]:
    """Return ``(complete, incomplete)`` from Charmhub.

    ``complete`` maps each Charmhub package name with a known source URL to
    that URL. ``incomplete`` is the sorted list of package names with no
    recorded source URL — captured so they can drive follow-up work.
    """
    packages = client.packages()
    complete: dict[str, str] = {}
    incomplete: list[str] = []
    for pkg in packages:
        name = pkg.get('name')
        if not name:
            continue
        url = client.source_url(name)
        if url:
            complete[name] = url
        else:
            incomplete.append(name)
    return complete, sorted(incomplete)


def merge(
    existing: list[dict[str, str]],
    charmhub: dict[str, str],
    github: GitHubClient,
) -> list[dict[str, str]]:
    """Return the updated row list given the existing CSV and Charmhub state.

    ``existing`` is assumed to have passed ``validate``: every row has a
    non-empty Repository, Source is one of VALID_SOURCES, and URLs are unique.
    """
    by_url: dict[str, dict[str, str]] = {}
    rows_in_order: list[dict[str, str]] = []
    for row in existing:
        url = row['Repository'].strip()
        by_url[normalise_url(url)] = row
        rows_in_order.append(row)

    # URL drift for auto-added rows. Done first so the dedup map stays in sync
    # before we consider archival of the *new* URL. Manual rows are never
    # rewritten, but drift is logged so a human can investigate.
    for row in rows_in_order:
        name_match = charmhub_charm_name(row.get('Repository', ''))
        if not name_match or name_match not in charmhub:
            continue
        new_url = charmhub[name_match]
        old_url = row['Repository']
        if normalise_url(new_url) == normalise_url(old_url):
            continue
        if not is_auto_added(row):
            logger.warning(
                'URL drift for manual row %s: %s -> %s (Charmhub); leaving row unchanged',
                name_match,
                old_url,
                new_url,
            )
            continue
        logger.info('URL drift for %s: %s -> %s', name_match, old_url, new_url)
        del by_url[normalise_url(old_url)]
        row['Repository'] = new_url
        by_url[normalise_url(new_url)] = row

    # Archive / 404 removal for github.com rows.
    survivors: list[dict[str, str]] = []
    for row in rows_in_order:
        url = row['Repository'].strip()
        owner_repo = github_owner_repo(url)
        if owner_repo is None:
            survivors.append(row)
            continue
        owner, repo = owner_repo
        status = github.status(owner, repo)
        if status == 'ok':
            survivors.append(row)
        else:
            logger.info('Dropping %s/%s: %s', owner, repo, status)
            by_url.pop(normalise_url(url), None)
    rows_in_order = survivors

    # Names already covered by some existing row, so we don't append a second
    # row for the same charm when a manual entry uses a different URL than
    # Charmhub now reports. Matching is case-insensitive against the Charm
    # Name column — auto-added rows use the charmhub package name verbatim,
    # and manual rows for charmhub-published charms generally do too (e.g.
    # the "kafka" row at canonical/kafka-operator).
    existing_names = {(row.get('Charm Name') or '').strip().lower() for row in rows_in_order}

    # Append brand-new Charmhub charms.
    for name, url in sorted(charmhub.items()):
        key = normalise_url(url)
        if key in by_url:
            continue
        if name.lower() in existing_names:
            logger.info('Skipping new charm %s: name already present in the CSV', name)
            continue
        # If the new charm points at a github repo that is *already* archived
        # or missing, don't add it — we'd just delete it on the next run.
        owner_repo = github_owner_repo(url)
        if owner_repo and github.status(*owner_repo) != 'ok':
            logger.info('Skipping new charm %s: %s is already archived/missing', name, url)
            continue
        new_row = {
            'Team': '',
            'Charm Name': name,
            'Repository': url,
            'Branch (if not the default)': '',
            'Source': AUTO_SOURCE,
        }
        rows_in_order.append(new_row)
        by_url[key] = new_row

    # No reordering: keeping the input order is the only way to produce a
    # clean diff against a CSV that's been edited by humans over time.
    return rows_in_order


def normalise_url(url: str) -> str:
    """Return a canonical form of ``url`` for dedup comparisons.

    Strips trailing slashes, lowercases scheme/host, and drops a ``.git`` suffix.
    Leaves the path otherwise intact so case-sensitive forges (e.g. opendev.org)
    are still distinguishable.
    """
    parsed = urllib.parse.urlsplit(url.strip())
    path = parsed.path.rstrip('/')
    if path.endswith('.git'):
        path = path[: -len('.git')]
    return urllib.parse.urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        '',
        '',
    ))


def charmhub_charm_name(url: str) -> str | None:
    """Return the charmhub package name from a source URL, or ``None``.

    Used purely to fill the ``Charm Name`` column for new auto-added rows. The
    URL-to-name mapping is best-effort: for canonical/foo-operator it's "foo",
    elsewhere we fall back to the trailing path component.
    """
    parsed = urllib.parse.urlsplit(url)
    parts = [p for p in parsed.path.split('/') if p]
    if not parts:
        return None
    name = parts[-1]
    if name.endswith('.git'):
        name = name[: -len('.git')]
    return name


def is_auto_added(row: dict[str, str]) -> bool:
    """Return whether ``row`` was originally appended by this script."""
    return (row.get('Source') or '').strip() == AUTO_SOURCE


def github_owner_repo(url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a ``github.com`` URL, else ``None``."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower() not in {'github.com', 'www.github.com'}:
        return None
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.endswith('.git'):
        repo = repo[: -len('.git')]
    return owner, repo


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read ``path`` and return rows with every CSV_FIELDS key populated."""
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        return [{field: (row.get(field) or '') for field in CSV_FIELDS} for row in reader]


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    """Write ``rows`` to ``path`` with LF line endings."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, '') for field in CSV_FIELDS})
    path.write_text(buffer.getvalue(), encoding='utf-8', newline='')


def write_no_source_csv(path: pathlib.Path, names: list[str]) -> None:
    """Write the Charmhub charms with no source URL to a sidecar CSV."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=NO_SOURCE_CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for name in sorted(names):
        writer.writerow({'Charm Name': name})
    path.write_text(buffer.getvalue(), encoding='utf-8', newline='')


def no_source_csv_path(csv_path: pathlib.Path) -> pathlib.Path:
    """Return the sidecar CSV path that lives alongside ``csv_path``."""
    return csv_path.with_name('charms-no-source.csv')


class CharmhubClient:
    """Thin wrapper around the Charmhub HTTP API.

    Pulled out so tests can substitute a fake without monkeypatching urllib
    globally.
    """

    def __init__(self, *, timeout: float = 30.0):
        self.timeout = timeout

    def packages(self) -> list[dict[str, typing.Any]]:
        """Return the published-packages list from ``charmhub.io/packages.json``."""
        logger.info('Fetching the list of published charms')
        with urllib.request.urlopen(CHARMHUB_PACKAGES_URL, timeout=self.timeout) as response:
            data = json.loads(response.read().decode())
        return data['packages']

    def source_url(self, charm: str) -> str | None:
        """Return the source URL recorded for ``charm`` on Charmhub, if any.

        Falls back to ``bugs-url`` when ``source`` is absent — that matches
        what ``canonical/operator``'s ``update-published-charms-tests-workflow.py``
        does and recovers a useful fraction of older charms.
        """
        for field, accessor in (
            ('result.links', lambda d: d['result']['links']['source'][0]),
            ('result.bugs-url', lambda d: d['result']['bugs-url']),
        ):
            url = f'{CHARMHUB_INFO_URL}/{charm}?fields={field}'
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as response:  # noqa: S310
                    data = json.loads(response.read().decode())
                return accessor(data)
            except (urllib.error.HTTPError, KeyError, IndexError):
                continue
        logger.info('No source URL on Charmhub for %s', charm)
        return None


class GitHubClient:
    """GitHub liveness check for the rows already in the CSV.

    Uses an unauthenticated request when ``GITHUB_TOKEN`` is unset — fine for
    local dry-runs but rate-limited; the CI workflow always provides a token.
    """

    def __init__(self, *, token: str | None = None, timeout: float = 30.0):
        self.token = token
        self.timeout = timeout

    def status(self, owner: str, repo: str) -> typing.Literal['ok', 'archived', 'missing']:
        """Report whether the repo is live, archived, or gone.

        Network/transient errors are reported as ``ok`` deliberately: a flaky
        GitHub API run should never cause us to drop a row.
        """
        url = f'{GITHUB_REPO_URL}/{owner}/{repo}'
        request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json'})  # noqa: S310
        if self.token:
            request.add_header('Authorization', f'Bearer {self.token}')
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                data = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 'missing'
            logger.warning('GitHub %s/%s HTTP %s; treating as live', owner, repo, exc.code)
            return 'ok'
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning('GitHub %s/%s probe failed (%s); treating as live', owner, repo, exc)
            return 'ok'
        if data.get('archived'):
            return 'archived'
        return 'ok'


if __name__ == '__main__':
    sys.exit(main())
