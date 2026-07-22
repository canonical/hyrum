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
_RESET = '\033[0m'
_STATUS_COLOURS: dict[str, str] = {
    'passed': '\033[32m',  # green
    'failed': '\033[31m',  # red
    'no_target': '\033[33m',  # yellow
    'timeout': '\033[35m',  # magenta
    'runner_error': '\033[91m',  # bright red
    'patcher_error': '\033[91m',  # bright red
    'skipped': '\033[2m',  # dim
}
_BOLD = '\033[1m'


def _relative(repo: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return str(repo.relative_to(base))
    except ValueError:
        return str(repo)


def _use_colour(stream: TextIO) -> bool:
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
            status_cell = f'{_BOLD}{status_cell}{_RESET}'
            count_cell = f'{_BOLD}{count_cell}{_RESET}'
            pct_cell = f'{_BOLD}{pct_cell}{_RESET}'
        elif use_colour and row[0] in colour_for_first:
            colour = colour_for_first[row[0]]
            status_cell = f'{colour}{status_cell}{_RESET}'
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
    use_colour = _use_colour(stream)

    counts = collections.Counter(o.status for o in outcomes)
    total = len(outcomes)
    ran = sum(counts.get(s, 0) for s in ('passed', 'failed', 'timeout'))

    title = f'hyrum: {target}'
    print(f'{_BOLD}{title}{_RESET}' if use_colour else title, file=stream)

    rows: list[tuple[str, str, str]] = []
    for status in pool.OUTCOME_STATUSES:
        count = counts.get(status, 0)
        pct = f'{(count / total * 100):.0f}%' if total else '—'
        rows.append((status, str(count), pct))
        if status == 'skipped' and count:
            skip_kinds: collections.Counter[str] = collections.Counter(
                o.skip_reason_kind.value for o in outcomes if o.skip_reason_kind is not None
            )
            for kind, kind_count in sorted(skip_kinds.items()):
                kind_pct = f'{(kind_count / total * 100):.0f}%' if total else '—'
                rows.append((f'  {kind}', str(kind_count), kind_pct))
    table = _format_table(
        rows,
        headers=None if no_headers else ('STATUS', 'COUNT', '%'),
        colour_for_first=_STATUS_COLOURS,
        use_colour=use_colour,
    )
    print(table, file=stream)

    if ran:
        passed_n = counts.get('passed', 0)
        pct = (passed_n / ran) * 100

        def emph(text: str) -> str:
            return f'{_BOLD}{text}{_RESET}' if use_colour else text

        not_run = total - ran
        breakdown_parts = [
            f'{counts.get(s, 0)} {s}'
            for s in ('skipped', 'no_target', 'runner_error', 'patcher_error')
            if counts.get(s, 0)
        ]
        breakdown = f' ({", ".join(breakdown_parts)})' if breakdown_parts else ''
        print(
            f'{emph(str(passed_n))} of {emph(str(ran))} runs passed '
            f'({emph(f"{pct:.0f}%")}); {not_run} not run{breakdown}.',
            file=stream,
        )
    else:
        print('No runs executed.', file=stream)

    if verbose:
        for status in ('failed', 'runner_error', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            heading = f'\n{status}:'
            print(f'{_BOLD}{heading}{_RESET}' if use_colour else heading, file=stream)
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' — {detail}' if detail else ''
                print(f'  {_relative(outcome.repo, base)}{trailer}', file=stream)

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            heading = '\nskipped:'
            print(f'{_BOLD}{heading}{_RESET}' if use_colour else heading, file=stream)
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                reason = outcome.skip_reason or ''
                print(f'  {_relative(outcome.repo, base)} — {reason}', file=stream)
