"""Run-to-run diff: compare two sets of hyrum results."""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import TextIO

from hyrum import _pool as pool
from hyrum import _report as report

_ERROR_STATUSES: frozenset[str] = frozenset({'patcher_error', 'timeout'})
_RAN_STATUSES: frozenset[str] = frozenset({'passed', 'failed', 'timeout'})


@dataclasses.dataclass
class CompareResult:
    """Status-level diff between two hyrum runs."""

    new_failures: list[str]
    resolved: list[str]
    new_errors: list[str]
    only_in_baseline: list[str]
    only_in_current: list[str]
    common: int
    baseline_pass_rate: float
    current_pass_rate: float
    baseline_passed: int
    baseline_ran: int
    current_passed: int
    current_ran: int

    @property
    def disjoint(self) -> bool:
        """Both runs have charms but none in common — the compare is meaningless."""
        return self.common == 0 and bool(self.only_in_baseline) and bool(self.only_in_current)


def diff(baseline: list[pool.Outcome], current: list[pool.Outcome]) -> CompareResult:
    """Compute the status-level diff between *baseline* and *current* run results."""
    base_by_key = {str(o.repo): o for o in baseline}
    cur_by_key = {str(o.repo): o for o in current}

    new_failures: list[str] = []
    resolved: list[str] = []
    new_errors: list[str] = []

    for key in sorted(cur_by_key):
        cur = cur_by_key[key]
        base = base_by_key.get(key)
        base_status = base.status if base is not None else None
        cur_status = cur.status

        if base_status == 'passed' and cur_status == 'failed':
            new_failures.append(key)
        elif base_status == 'failed' and cur_status == 'passed':
            resolved.append(key)
        elif cur_status in _ERROR_STATUSES and base_status not in _ERROR_STATUSES:
            new_errors.append(key)

    base_ran = sum(1 for o in baseline if o.status in _RAN_STATUSES)
    cur_ran = sum(1 for o in current if o.status in _RAN_STATUSES)
    base_passed = sum(1 for o in baseline if o.status == 'passed')
    cur_passed = sum(1 for o in current if o.status == 'passed')

    return CompareResult(
        new_failures=new_failures,
        resolved=resolved,
        new_errors=new_errors,
        only_in_baseline=sorted(set(base_by_key) - set(cur_by_key)),
        only_in_current=sorted(set(cur_by_key) - set(base_by_key)),
        common=len(set(base_by_key) & set(cur_by_key)),
        baseline_pass_rate=base_passed / base_ran if base_ran else 0.0,
        current_pass_rate=cur_passed / cur_ran if cur_ran else 0.0,
        baseline_passed=base_passed,
        baseline_ran=base_ran,
        current_passed=cur_passed,
        current_ran=cur_ran,
    )


def _section(file: TextIO, title: str, charms: list[str], color: str, use_color: bool) -> None:
    if not charms:
        return
    width = max(len(title), max(len(c) for c in charms))
    bar = '─' * width
    bold = report.BOLD if use_color else ''
    tint = color if use_color else ''
    reset = report.RESET if use_color else ''
    print(file=file)
    print(f'{bold}{title}{reset}', file=file)
    print(bar, file=file)
    for charm in charms:
        print(f'  {tint}{charm}{reset}', file=file)


def render(result: CompareResult, *, file: TextIO | None = None) -> None:
    """Print a plain-text diff summary of *result* to *file* (defaults to stdout)."""
    out: TextIO = file if file is not None else sys.stdout
    use_color = report.use_colour(out)
    bold = report.BOLD if use_color else ''
    green = report.GREEN if use_color else ''
    reset = report.RESET if use_color else ''

    delta_pct = (result.current_pass_rate - result.baseline_pass_rate) * 100
    n_new = len(result.new_failures)
    n_resolved = len(result.resolved)
    sign = '+' if delta_pct >= 0 else ''
    failure_word = 'failure' if n_new == 1 else 'failures'
    print(
        f'Pass rate: {bold}{result.current_pass_rate * 100:.0f}%{reset} '
        f'(was {result.baseline_pass_rate * 100:.0f}%) '
        f'delta {bold}{sign}{delta_pct:.0f}%{reset} '
        f'({n_new} new {failure_word}, {n_resolved} resolved)',
        file=out,
    )

    _section(out, 'New failures', result.new_failures, report.RED, use_color)
    _section(out, 'Resolved', result.resolved, report.GREEN, use_color)
    _section(out, 'New errors', result.new_errors, report.BRIGHT_RED, use_color)

    if result.disjoint:
        red = report.BRIGHT_RED if use_color else ''
        print(
            f'{red}Warning: the two runs have no charms in common — '
            f'this comparison is meaningless.{reset}',
            file=out,
        )
    elif not result.new_failures and not result.resolved and not result.new_errors:
        print(f'{green}No changes between runs.{reset}', file=out)

    if result.only_in_baseline or result.only_in_current:
        print(
            f'Note: {len(result.only_in_baseline)} charm(s) only in baseline, '
            f'{len(result.only_in_current)} only in current — '
            f'these are excluded from the totals above.',
            file=out,
        )


_NON_PASSING = frozenset({'failed', 'timeout', 'patcher_error'})


def _short(repo: str) -> str:
    """Shorten a charm key for the table.

    Keys saved by current hyrum are already charms-dir-relative
    (``owner/charm``) and pass through unchanged. Absolute paths from older
    results files keep their last two segments so different owners' charms
    of the same name stay distinguishable.
    """
    path = pathlib.PurePosixPath(repo)
    if not path.is_absolute():
        return repo
    return '/'.join(path.parts[-2:]) if len(path.parts) > 2 else repo


def _md_escape(s: str) -> str:
    return s.replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _cell(outcome: pool.Outcome | None) -> str:
    if outcome is None:
        return '_absent_'
    if outcome.status == 'passed':
        return 'passed'
    if outcome.status == 'skipped':
        return f'skipped ({outcome.skip_reason})' if outcome.skip_reason else 'skipped'
    if outcome.status == 'no_target':
        return 'no target'
    detail = outcome.summary or outcome.error or ''
    return f'{outcome.status}: {detail}' if detail else outcome.status


def render_markdown(
    baseline: list[pool.Outcome],
    current: list[pool.Outcome],
    *,
    file: TextIO | None = None,
    title: str = 'hyrum run comparison',
) -> None:
    """Print a markdown table comparing the two runs, one row per non-passing charm."""
    out: TextIO = file if file is not None else sys.stdout
    base_by_key = {str(o.repo): o for o in baseline}
    cur_by_key = {str(o.repo): o for o in current}
    keys = sorted(set(base_by_key) | set(cur_by_key))

    def is_interesting(key: str) -> bool:
        b = base_by_key.get(key)
        c = cur_by_key.get(key)
        return (b is not None and b.status in _NON_PASSING) or (
            c is not None and c.status in _NON_PASSING
        )

    rows = sorted((k for k in keys if is_interesting(k)), key=_short)
    result = diff(baseline, current)

    print(f'# {title}', file=out)
    print(file=out)
    print(
        f'Baseline pass rate: **{result.baseline_pass_rate * 100:.0f}%** '
        f'({result.baseline_passed}/{result.baseline_ran}). '
        f'Current pass rate: **{result.current_pass_rate * 100:.0f}%** '
        f'({result.current_passed}/{result.current_ran}). '
        f'{len(result.new_failures)} new failure(s), '
        f'{len(result.resolved)} resolved, '
        f'{len(result.new_errors)} new error(s).',
        file=out,
    )
    print(file=out)

    if not rows:
        print('_No non-passing charms in either run._', file=out)
        return

    print('| Charm | Baseline | Current |', file=out)
    print('| --- | --- | --- |', file=out)
    for key in rows:
        b = base_by_key.get(key)
        c = cur_by_key.get(key)
        baseline_cell = _cell(b)
        current_cell = (
            'same' if b is not None and c is not None and baseline_cell == _cell(c) else _cell(c)
        )
        print(
            f'| {_md_escape(_short(key))} '
            f'| {_md_escape(baseline_cell)} '
            f'| {_md_escape(current_cell)} |',
            file=out,
        )
