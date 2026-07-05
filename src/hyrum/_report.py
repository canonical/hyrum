"""Plain-text summary of a hyrum run.

The summary table follows the Canonical CLI standards: two-space column
delimiters, upper-case headers, no line decorations, and ANSI colour only
when stdout is a tty (disabled when ``NO_COLOR`` is set or output is
redirected).
"""

from __future__ import annotations

import collections
import os
import pathlib
import sys
from collections.abc import Iterable
from typing import TextIO

from hyrum import _pool as pool

# ANSI SGR codes, used only when the stream is a tty and NO_COLOR is unset.
# Shared with the compare renderer so both commands colour identically.
RESET = '\033[0m'
BOLD = '\033[1m'
RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
MAGENTA = '\033[35m'
BRIGHT_RED = '\033[91m'
DIM = '\033[2m'
_STATUS_COLOURS: dict[str, str] = {
    'passed': GREEN,
    'failed': RED,
    'no_target': YELLOW,
    'timeout': MAGENTA,
    'patcher_error': BRIGHT_RED,
    'skipped': DIM,
}


def _relative(repo: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return str(repo.relative_to(base))
    except ValueError:
        return str(repo)


def use_colour(stream: TextIO) -> bool:
    """Colourise only when *stream* is a tty and ``NO_COLOR`` is unset."""
    if os.environ.get('NO_COLOR'):
        return False
    return stream.isatty()


def _format_table(
    rows: list[tuple[str, str, str]],
    *,
    headers: tuple[str, str, str] | None,
    colour_for_first: dict[str, str],
    use_colour: bool,
) -> str:
    raw_rows: list[tuple[str, str, str]] = []
    if headers is not None:
        raw_rows.append(headers)
    raw_rows.extend(rows)
    widths = [max(len(r[i]) for r in raw_rows) for i in range(3)]

    def render(row: tuple[str, str, str], *, header: bool = False) -> str:
        status_cell = row[0].ljust(widths[0])
        count_cell = row[1].rjust(widths[1])
        pct_cell = row[2].rjust(widths[2])
        if use_colour and header:
            status_cell = f'{BOLD}{status_cell}{RESET}'
            count_cell = f'{BOLD}{count_cell}{RESET}'
            pct_cell = f'{BOLD}{pct_cell}{RESET}'
        elif use_colour and row[0] in colour_for_first:
            colour = colour_for_first[row[0]]
            status_cell = f'{colour}{status_cell}{RESET}'
        return f'{status_cell}  {count_cell}  {pct_cell}'

    lines: list[str] = []
    if headers is not None:
        lines.append(render(headers, header=True))
    lines.extend(render(r) for r in rows)
    return '\n'.join(lines)


def render(
    outcomes: Iterable[pool.Outcome],
    *,
    base: pathlib.Path,
    target: str,
    verbose: bool = False,
    no_headers: bool = False,
    stream: TextIO | None = None,
) -> None:
    """Print a plain-text tally of ``outcomes`` plus an optional verbose offender list."""
    outcomes = list(outcomes)
    if stream is None:
        stream = sys.stdout
    assert stream is not None
    colour = use_colour(stream)

    counts = collections.Counter(o.status for o in outcomes)
    total = len(outcomes)
    ran = sum(counts.get(s, 0) for s in ('passed', 'failed', 'timeout'))

    title = f'hyrum: {target}'
    print(f'{BOLD}{title}{RESET}' if colour else title, file=stream)

    rows: list[tuple[str, str, str]] = []
    for status in pool.OUTCOME_STATUSES:
        count = counts.get(status, 0)
        pct = f'{(count / total * 100):.0f}%' if total else '—'
        rows.append((status, str(count), pct))
    table = _format_table(
        rows,
        headers=None if no_headers else ('STATUS', 'COUNT', '%'),
        colour_for_first=_STATUS_COLOURS,
        use_colour=colour,
    )
    print(table, file=stream)

    if ran:
        passed_n = counts.get('passed', 0)
        pct = (passed_n / ran) * 100

        def emph(text: str) -> str:
            return f'{BOLD}{text}{RESET}' if colour else text

        print(
            f'{emph(str(passed_n))} of {emph(str(ran))} runs passed '
            f'({emph(f"{pct:.0f}%")}); {total - ran} skipped or errored.',
            file=stream,
        )
    else:
        print('No runs executed.', file=stream)

    if verbose:
        for status in ('failed', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            heading = f'\n{status}:'
            print(f'{BOLD}{heading}{RESET}' if colour else heading, file=stream)
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' — {detail}' if detail else ''
                print(f'  {_relative(outcome.repo, base)}{trailer}', file=stream)

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            heading = '\nskipped:'
            print(f'{BOLD}{heading}{RESET}' if colour else heading, file=stream)
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                reason = outcome.skip_reason or ''
                print(f'  {_relative(outcome.repo, base)} — {reason}', file=stream)
