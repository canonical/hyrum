"""Run-to-run diff: compare two sets of hyrum results."""

from __future__ import annotations

import dataclasses

import rich.console
import rich.table

from hyrum import _pool as pool

_ERROR_STATUSES: frozenset[str] = frozenset({'patcher_error', 'timeout'})
_RAN_STATUSES: frozenset[str] = frozenset({'passed', 'failed', 'timeout'})


@dataclasses.dataclass
class CompareResult:
    """Status-level diff between two hyrum runs."""

    new_failures: list[str]
    resolved: list[str]
    new_errors: list[str]
    baseline_pass_rate: float
    current_pass_rate: float
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
        baseline_pass_rate=base_passed / base_ran if base_ran else 0.0,
        current_pass_rate=cur_passed / cur_ran if cur_ran else 0.0,
        baseline_passed=base_passed,
        baseline_ran=base_ran,
        current_passed=cur_passed,
        current_ran=cur_ran,
    )


def render(result: CompareResult, *, console: rich.console.Console | None = None) -> None:
    """Print a Rich diff summary of *result* to *console*."""
    console = console or rich.console.Console()

    delta_pct = (result.current_pass_rate - result.baseline_pass_rate) * 100
    n_new = len(result.new_failures)
    n_resolved = len(result.resolved)
    sign = '+' if delta_pct >= 0 else ''
    failure_word = 'failure' if n_new == 1 else 'failures'
    console.print(
        f'Pass rate: [bold]{result.current_pass_rate * 100:.0f}%[/bold] '
        f'(was {result.baseline_pass_rate * 100:.0f}%) '
        f'delta [bold]{sign}{delta_pct:.0f}%[/bold] '
        f'({n_new} new {failure_word}, {n_resolved} resolved)'
    )

    if result.new_failures:
        table = rich.table.Table(title='New failures', show_lines=False)
        table.add_column('charm', style='red')
        for charm in result.new_failures:
            table.add_row(charm)
        console.print(table)

    if result.resolved:
        table = rich.table.Table(title='Resolved', show_lines=False)
        table.add_column('charm', style='green')
        for charm in result.resolved:
            table.add_row(charm)
        console.print(table)

    if result.new_errors:
        table = rich.table.Table(title='New errors', show_lines=False)
        table.add_column('charm', style='bright_red')
        for charm in result.new_errors:
            table.add_row(charm)
        console.print(table)

    if not result.new_failures and not result.resolved and not result.new_errors:
        console.print('[green]No changes between runs.[/green]')
