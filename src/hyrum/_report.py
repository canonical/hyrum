"""Plain-text summary of a hyrum run.

The summary table follows the Canonical CLI standards: two-space column
delimiters, upper-case headers, no line decorations, and ANSI colour only
when stdout is a tty (disabled when ``NO_COLOR`` is set or output is
redirected).
"""

from __future__ import annotations

import collections
import pathlib
import sys
from collections.abc import Iterable
from typing import NamedTuple, TextIO

from hyrum import _ansi, _percent
from hyrum import _pool as pool

# The statuses that mean the charm's target actually ran, as opposed to the
# charm being skipped or the run falling over before it got that far.
_RAN_STATUSES = ('passed', 'failed', 'timeout')
# Stands in for a percentage that has no meaning, rather than one that is zero.
_NOT_APPLICABLE = '—'
_NOT_APPLICABLE_ASCII = '-'
# Version of the `hyrum show --format json` payload, independent of the
# results-file schema version.
JSON_FORMAT_VERSION = 1

_RESET = _ansi.RESET
_BOLD = _ansi.BOLD
_STATUS_COLOURS: dict[str, str] = {
    'passed': _ansi.GREEN,
    'failed': _ansi.RED,
    'no_target': _ansi.YELLOW,
    'timeout': _ansi.MAGENTA,
    'runner_error': _ansi.BRIGHT_RED,
    'patcher_error': _ansi.BRIGHT_RED,
    'skipped': _ansi.DIM,
}


def _em_dash(stream: TextIO) -> str:
    """Return the em dash, or a hyphen when *stream* cannot encode one.

    The table prints one per non-run status, so every ordinary run carries a
    few. A stream that cannot encode them raises part-way through the report,
    which on a fleet run means losing the tally after hours of work. Gated on
    the stream the way :func:`_ansi.use_colour` is, rather than on a flag.
    """
    encoding = getattr(stream, 'encoding', None)
    if not encoding:
        return _NOT_APPLICABLE
    try:
        _NOT_APPLICABLE.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _NOT_APPLICABLE_ASCII
    return _NOT_APPLICABLE


def _relative(repo: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return str(repo.relative_to(base))
    except ValueError:
        return str(repo)


class _Row(NamedTuple):
    """One line of the tally table.

    Named rather than a bare tuple so that adding a column is a type error at
    every construction site instead of an ``IndexError`` at print time, on
    whichever run happens to have the row that was missed.
    """

    status: str
    # ``charms`` rather than ``count``: a NamedTuple field called ``count``
    # shadows ``tuple.count``.
    charms: str
    of_all: str
    of_runs: str


def _format_table(
    rows: list[_Row],
    *,
    headers: _Row | None,
    colour_for_first: dict[str, str],
    use_colour: bool,
) -> str:
    raw_rows: list[_Row] = []
    if headers is not None:
        raw_rows.append(headers)
    raw_rows.extend(rows)
    widths = [max(len(cell) for cell in column) for column in zip(*raw_rows, strict=True)]

    def render(row: _Row, *, header: bool = False) -> str:
        # The first column is the label, the rest are numbers, so only the
        # first is left-aligned.
        cells = [row[0].ljust(widths[0])]
        cells.extend(cell.rjust(width) for cell, width in zip(row[1:], widths[1:], strict=True))
        if use_colour and header:
            cells = [f'{_BOLD}{cell}{_RESET}' for cell in cells]
        elif use_colour and row[0] in colour_for_first:
            colour = colour_for_first[row[0]]
            cells[0] = f'{colour}{cells[0]}{_RESET}'
        return '  '.join(cells)

    lines: list[str] = []
    if headers is not None:
        lines.append(render(headers, header=True))
    lines.extend(render(r) for r in rows)
    return '\n'.join(lines)


def _counts(outcomes: list[pool.Outcome]) -> tuple[collections.Counter[str], int, int]:
    """Return (status counts, total outcomes, number that actually ran)."""
    counts = collections.Counter(o.status for o in outcomes)
    total = len(outcomes)
    ran = sum(counts.get(s, 0) for s in _RAN_STATUSES)
    return counts, total, ran


def render(
    outcomes: Iterable[pool.Outcome],
    *,
    base: pathlib.Path,
    target: str,
    list_offenders: bool = False,
    no_headers: bool = False,
    stream: TextIO | None = None,
) -> None:
    """Print a plain-text tally of ``outcomes`` plus an optional per-charm offender list."""
    outcomes = list(outcomes)
    if stream is None:
        stream = sys.stdout
    assert stream is not None
    use_colour = _ansi.use_colour(stream)
    not_applicable = _em_dash(stream)

    counts, total, ran = _counts(outcomes)

    title = f'hyrum: {target}'
    print(f'{_BOLD}{title}{_RESET}' if use_colour else title, file=stream)

    def of_all(count: int) -> str:
        return _percent.format_pct(count / total) if total else not_applicable

    def of_runs(status: str, count: int) -> str:
        # Only the statuses that come from a charm actually being run have a
        # share of the runs; for the others the cell would be a category error
        # rather than a zero.
        if status not in _RAN_STATUSES or not ran:
            return not_applicable
        return _percent.format_pct(count / ran)

    rows: list[_Row] = []
    for status in pool.OUTCOME_STATUSES:
        count = counts.get(status, 0)
        rows.append(_Row(status, str(count), of_all(count), of_runs(status, count)))
        if status == 'skipped' and count:
            skip_kinds: collections.Counter[str] = collections.Counter(
                o.skip_reason_kind.value for o in outcomes if o.skip_reason_kind is not None
            )
            for kind, kind_count in sorted(skip_kinds.items()):
                rows.append(_Row(f'  {kind}', str(kind_count), of_all(kind_count), not_applicable))
    table = _format_table(
        rows,
        headers=None if no_headers else _Row('STATUS', 'COUNT', '% OF ALL', '% OF RUNS'),
        colour_for_first=_STATUS_COLOURS,
        use_colour=use_colour,
    )
    print(table, file=stream)

    if ran:
        passed_n = counts.get('passed', 0)
        pct = _percent.format_pct(passed_n / ran)

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
            f'({emph(pct)} of runs); {not_run} not run{breakdown}.',
            file=stream,
        )
    else:
        print('No runs executed.', file=stream)

    if list_offenders:
        for status in ('failed', 'runner_error', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            heading = f'\n{status}:'
            print(f'{_BOLD}{heading}{_RESET}' if use_colour else heading, file=stream)
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' {not_applicable} {detail}' if detail else ''
                print(f'  {_relative(outcome.repo, base)}{trailer}', file=stream)

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            heading = '\nskipped:'
            print(f'{_BOLD}{heading}{_RESET}' if use_colour else heading, file=stream)
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                reason = outcome.skip_reason or ''
                print(f'  {_relative(outcome.repo, base)} {not_applicable} {reason}', file=stream)


def render_markdown(
    outcomes: Iterable[pool.Outcome],
    *,
    base: pathlib.Path,
    target: str,
    list_offenders: bool = False,
    no_headers: bool = False,
    stream: TextIO | None = None,
) -> None:
    """Print a markdown tally of ``outcomes``, mirroring :func:`render`'s text table."""
    outcomes = list(outcomes)
    out: TextIO = stream if stream is not None else sys.stdout

    counts, total, ran = _counts(outcomes)

    print(f'# hyrum: {target}' if target else '# hyrum run', file=out)
    print(file=out)

    if not no_headers:
        print('| Status | Count | % of all | % of runs |', file=out)
        print('| --- | --- | --- | --- |', file=out)
    for status in pool.OUTCOME_STATUSES:
        count = counts.get(status, 0)
        of_all = _percent.format_pct(count / total) if total else _NOT_APPLICABLE
        # Only the statuses that come from a charm actually being run have a
        # share of the runs; for the others the cell would be a category error
        # rather than a zero.
        of_runs = (
            _percent.format_pct(count / ran)
            if status in _RAN_STATUSES and ran
            else _NOT_APPLICABLE
        )
        print(f'| {status} | {count} | {of_all} | {of_runs} |', file=out)

    print(file=out)
    if ran:
        passed_n = counts.get('passed', 0)
        pct = _percent.format_pct(passed_n / ran)
        not_run = total - ran
        print(f'**{passed_n}** of **{ran}** runs passed (**{pct}**); {not_run} not run.', file=out)
    else:
        print('No runs executed.', file=out)

    if list_offenders:
        for status in ('failed', 'runner_error', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            print(file=out)
            print(f'## {status}', file=out)
            print(file=out)
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' — {detail}' if detail else ''
                print(f'- {_relative(outcome.repo, base)}{trailer}', file=out)

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            print(file=out)
            print('## skipped', file=out)
            print(file=out)
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                reason = outcome.skip_reason or ''
                print(f'- {_relative(outcome.repo, base)} — {reason}', file=out)
