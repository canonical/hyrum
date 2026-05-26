"""Rich-formatted summary of a hyrum run."""

from __future__ import annotations

import collections
import pathlib
from collections.abc import Iterable

import rich.console
import rich.table

from hyrum import pool

_STATUS_STYLES = {
    'passed': 'green',
    'failed': 'red',
    'no_target': 'yellow',
    'timeout': 'magenta',
    'patcher_error': 'bright_red',
    'skipped': 'dim',
}


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
    console: rich.console.Console | None = None,
) -> None:
    """Print a Rich tally of ``outcomes`` plus an optional verbose offender list."""
    outcomes = list(outcomes)
    console = console or rich.console.Console()

    counts = collections.Counter(o.status for o in outcomes)
    total = len(outcomes)
    ran = sum(counts.get(s, 0) for s in ('passed', 'failed', 'timeout'))

    table = rich.table.Table(
        title=f'hyrum: {target}',
        show_lines=False,
        show_header=not no_headers,
        header_style='bold',
    )
    table.add_column('STATUS')
    table.add_column('COUNT', justify='right')
    table.add_column('%', justify='right')
    for status in pool.outcome_statuses():
        count = counts.get(status, 0)
        pct = f'{(count / total * 100):.0f}%' if total else '—'
        style = _STATUS_STYLES.get(status, '')
        table.add_row(f'[{style}]{status}[/{style}]' if style else status, str(count), pct)
    console.print(table)

    if ran:
        passed_n = counts.get('passed', 0)
        pct = (passed_n / ran) * 100
        console.print(
            f'[bold]{passed_n}[/bold] of [bold]{ran}[/bold] runs passed '
            f'([bold]{pct:.0f}%[/bold]); {total - ran} skipped or errored.'
        )
    else:
        console.print('No runs executed.')

    if verbose:
        for status in ('failed', 'patcher_error', 'timeout'):
            offenders = [o for o in outcomes if o.status == status]
            if not offenders:
                continue
            console.print(f'\n[bold]{status}:[/bold]')
            for outcome in sorted(offenders, key=lambda o: str(o.repo)):
                detail = outcome.error or outcome.skip_reason or ''
                trailer = f' — {detail}' if detail else ''
                console.print(f'  {_relative(outcome.repo, base)}{trailer}')

        skipped = [o for o in outcomes if o.status == 'skipped']
        if skipped:
            console.print('\n[bold]skipped:[/bold]')
            for outcome in sorted(skipped, key=lambda o: str(o.repo)):
                console.print(f'  {_relative(outcome.repo, base)} — {outcome.skip_reason}')
