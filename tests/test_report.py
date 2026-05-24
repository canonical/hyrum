from __future__ import annotations

from io import StringIO
from pathlib import Path

import rich.console

from super_tox.pool import Outcome
from super_tox.report import render


def _render(outcomes, *, base: Path, target: str = 'unit', verbose: bool = False):
    buf = StringIO()
    console = rich.console.Console(file=buf, width=120, force_terminal=False)
    render(outcomes, base=base, target=target, verbose=verbose, console=console)
    return buf.getvalue()


def test_render_shows_all_statuses_with_zero_counts(tmp_path: Path):
    out = _render([], base=tmp_path)
    for status in ('passed', 'failed', 'no_target', 'timeout', 'patcher_error', 'skipped'):
        assert status in out
    assert 'No runs executed.' in out


def test_render_summary_percentage(tmp_path: Path):
    outcomes = [
        Outcome(repo=tmp_path / 'a', status='passed'),
        Outcome(repo=tmp_path / 'b', status='passed'),
        Outcome(repo=tmp_path / 'c', status='failed'),
        Outcome(repo=tmp_path / 'd', status='skipped'),
    ]
    out = _render(outcomes, base=tmp_path)
    # 2 of 3 ran passed (skipped is not counted as a run).
    assert '2' in out and 'of' in out and '3' in out


def test_render_verbose_lists_failures(tmp_path: Path):
    outcomes = [
        Outcome(repo=tmp_path / 'broken', status='failed'),
        Outcome(repo=tmp_path / 'ok', status='passed'),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'broken' in out


def test_render_verbose_includes_error_detail(tmp_path: Path):
    outcomes = [
        Outcome(
            repo=tmp_path / 'borked',
            status='patcher_error',
            error='bad pyproject',
        ),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'borked' in out
    assert 'bad pyproject' in out


def test_render_verbose_lists_skipped(tmp_path: Path):
    outcomes = [
        Outcome(repo=tmp_path / 'x', status='skipped', skip_reason='ignored (manual)'),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'ignored (manual)' in out
