"""Plain-text summary of a hyrum run."""

from __future__ import annotations

import collections
import os
import pathlib
import sys
from collections.abc import Iterable
from typing import TextIO

from hyrum import pool

_RESET = '\x1b[0m'
_BOLD = '\x1b[1m'

_STATUS_STYLES = {
    'passed': '\x1b[32m',
    'failed': '\x1b[31m',
    'no_target': '\x1b[33m',
    'timeout': '\x1b[35m',
    'patcher_error': '\x1b[91m',
    'skipped': '\x1b[2m',
}


def _use_colour(out: TextIO) -> bool:
    if os.environ.get('NO_COLOR'):
        return False
    return hasattr(out, 'isatty') and out.isatty()


def _relative(repo: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return str(repo.relative_to(base))
    except ValueError:
        return str(repo)


def render(
    outcomes: Iterable[pool.Outcome],
    *,
    base: pathlib.Path,
    target: str,
    verbose: bool = False,
    no_headers: bool = False,
    out: TextIO | None = None,
) -> None:
    """Print a tally of ``outcomes`` plus an optional verbose offender list."""
    outcomes = list(outcomes)
    stream: TextIO = out if out is not None else sys.stdout
    colour = _use_colour(stream)

    def bold(text: str) -> str:
        return f'{_BOLD}{text}{_RESET}' if colour else text

    counts = collections.Counter(o.status for o in outcomes)
    total = len(outcomes)
    ran = sum(counts.get(s, 0) for s in ('passed', 'failed', 'timeout'))

    print(bold(f'hyrum: {target}'), file=stream)
    rows: list[tuple[str, str, str]] = []
    for status in pool.OUTCOME_STATUSES:
        count = counts.get(status, 0)
        pct = f'{count / total * 100:.0f}%' if total else '-'
        rows.append((status, str(count), pct))
    headers = ('STATUS', 'COUNT', '%')
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)]
    if not no_headers:
        print(
            bold('  '.join(h.ljust(w) for h, w in zip(headers, widths, strict=True))), file=stream
        )
    for status, count, pct in rows:
        status_cell = status.ljust(widths[0])
        if colour and status in _STATUS_STYLES:
            status_cell = f'{_STATUS_STYLES[status]}{status_cell}{_RESET}'
        print(
            f'{status_cell}  {count.rjust(widths[1])}  {pct.rjust(widths[2])}'.rstrip(),
            file=stream,
        )

    if ran:
        passed_n = counts.get('passed', 0)
        pct = (passed_n / ran) * 100
        print(
            f'{bold(str(passed_n))} of {bold(str(ran))} runs passed '
            f'({bold(f"{pct:.0f}%")}); {total - ran} skipped or errored.',
            file=stream,
        )
    else:
        print('No runs executed.', file=stream)

    if verbose:
        for status in ('failed', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            print(f'\n{bold(f"{status}:")}', file=stream)
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' — {detail}' if detail else ''
                print(f'  {_relative(outcome.repo, base)}{trailer}', file=stream)

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            print(f'\n{bold("skipped:")}', file=stream)
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                reason = outcome.skip_reason or ''
                print(f'  {_relative(outcome.repo, base)} — {reason}', file=stream)
