from __future__ import annotations

import io
import pathlib

from hyrum import pool, report


def _render(
    outcomes,
    *,
    base: pathlib.Path,
    target: str = 'unit',
    verbose: bool = False,
    no_headers: bool = False,
):
    buf = io.StringIO()
    report.render(
        outcomes,
        base=base,
        target=target,
        verbose=verbose,
        no_headers=no_headers,
        out=buf,
    )
    return buf.getvalue()


def test_render_shows_all_statuses_with_zero_counts(tmp_path: pathlib.Path):
    out = _render([], base=tmp_path)
    for status in ('passed', 'failed', 'no_target', 'timeout', 'patcher_error', 'skipped'):
        assert status in out
    assert 'No runs executed.' in out


def test_render_summary_percentage(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'a', status='passed'),
        pool.Outcome(repo=tmp_path / 'b', status='passed'),
        pool.Outcome(repo=tmp_path / 'c', status='failed'),
        pool.Outcome(repo=tmp_path / 'd', status='skipped'),
    ]
    out = _render(outcomes, base=tmp_path)
    # 2 of 3 ran passed (skipped is not counted as a run).
    assert '2' in out and 'of' in out and '3' in out


def test_render_verbose_lists_failures(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'broken', status='failed'),
        pool.Outcome(repo=tmp_path / 'ok', status='passed'),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'broken' in out


def test_render_verbose_includes_error_detail(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(
            repo=tmp_path / 'borked',
            status='patcher_error',
            error='bad pyproject',
        ),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'borked' in out
    assert 'bad pyproject' in out


def test_render_verbose_preserves_bracketed_detail(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(
            repo=tmp_path / 'borked',
            status='patcher_error',
            error='pyproject has no recognisable [project] or [tool.poetry] deps',
        ),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert '[project]' in out
    assert '[tool.poetry]' in out


def test_render_verbose_lists_skipped(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'x', status='skipped', skip_reason='ignored (manual)'),
    ]
    out = _render(outcomes, base=tmp_path, verbose=True)
    assert 'ignored (manual)' in out


def test_render_uses_uppercase_headers(tmp_path: pathlib.Path):
    out = _render([], base=tmp_path)
    assert 'STATUS' in out
    assert 'COUNT' in out


def test_render_no_headers_suppresses_header_row(tmp_path: pathlib.Path):
    out = _render([], base=tmp_path, no_headers=True)
    assert 'STATUS' not in out
    assert 'COUNT' not in out
    # The status rows themselves are still present (with zero counts).
    assert 'passed' in out
