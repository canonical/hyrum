"""Run-to-run diff: compare two sets of hyrum results."""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import TextIO

from hyrum import _ansi
from hyrum import _pool as pool

_ERROR_STATUSES: frozenset[str] = frozenset({'patcher_error', 'timeout'})
_RAN_STATUSES: frozenset[str] = frozenset({'passed', 'failed', 'timeout'})


@dataclasses.dataclass
class CompareResult:
    """Status-level diff between two hyrum runs."""

    new_failures: list[str]
    resolved: list[str]
    new_errors: list[str]
    baseline_pass_rate: float | None
    current_pass_rate: float | None
    baseline_passed: int
    baseline_ran: int
    current_passed: int
    current_ran: int


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
        baseline_pass_rate=base_passed / base_ran if base_ran else None,
        current_pass_rate=cur_passed / cur_ran if cur_ran else None,
        baseline_passed=base_passed,
        baseline_ran=base_ran,
        current_passed=cur_passed,
        current_ran=cur_ran,
    )


def _section(file: TextIO, title: str, charms: list[str], tint_code: str, use_color: bool) -> None:
    if not charms:
        return
    bold = _ansi.BOLD if use_color else ''
    tint = tint_code if use_color else ''
    reset = _ansi.RESET if use_color else ''
    print(file=file)
    print(f'{bold}{title.upper()}{reset}', file=file)
    print(file=file)
    for charm in charms:
        print(f'  {tint}{charm}{reset}', file=file)


def _fmt_pct(rate: float | None) -> str:
    return 'n/a' if rate is None else f'{rate * 100:.0f}%'


def render(result: CompareResult, *, file: TextIO | None = None) -> None:
    """Print a plain-text diff summary of *result* to *file* (defaults to stdout)."""
    out: TextIO = file if file is not None else sys.stdout
    use_color = _ansi.use_colour(out)
    bold = _ansi.BOLD if use_color else ''
    green = _ansi.GREEN if use_color else ''
    reset = _ansi.RESET if use_color else ''

    n_new = len(result.new_failures)
    n_resolved = len(result.resolved)
    failure_word = 'failure' if n_new == 1 else 'failures'
    current_pct = _fmt_pct(result.current_pass_rate)
    baseline_pct = _fmt_pct(result.baseline_pass_rate)
    if result.current_pass_rate is None or result.baseline_pass_rate is None:
        delta_str = 'n/a'
    else:
        delta_pct = (result.current_pass_rate - result.baseline_pass_rate) * 100
        sign = '+' if delta_pct >= 0 else ''
        delta_str = f'{sign}{delta_pct:.0f}%'
    print(
        f'Pass rate: {bold}{current_pct}{reset} '
        f'(was {baseline_pct}) '
        f'delta {bold}{delta_str}{reset} '
        f'({n_new} new {failure_word}, {n_resolved} resolved)',
        file=out,
    )

    _section(out, 'New failures', result.new_failures, _ansi.RED, use_color)
    _section(out, 'Resolved', result.resolved, _ansi.GREEN, use_color)
    _section(out, 'New errors', result.new_errors, _ansi.BRIGHT_RED, use_color)

    if not result.new_failures and not result.resolved and not result.new_errors:
        print(f'{green}No changes between runs.{reset}', file=out)


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
    result: CompareResult,
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

    print(f'# {title}', file=out)
    print(file=out)
    print(
        f'Baseline pass rate: **{_fmt_pct(result.baseline_pass_rate)}** '
        f'({result.baseline_passed}/{result.baseline_ran}). '
        f'Current pass rate: **{_fmt_pct(result.current_pass_rate)}** '
        f'({result.current_passed}/{result.current_ran}). '
        f'{len(result.new_failures)} new failure(s), '
        f'{len(result.resolved)} resolved, '
        f'{len(result.new_errors)} new error(s).',
        file=out,
    )
    print(file=out)

    for heading, charms in (
        ('New failures', result.new_failures),
        ('Resolved', result.resolved),
        ('New errors', result.new_errors),
    ):
        if not charms:
            continue
        print(f'## {heading}', file=out)
        print(file=out)
        for charm in charms:
            print(f'- {_md_escape(_short(charm))}', file=out)
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
