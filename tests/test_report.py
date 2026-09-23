from __future__ import annotations

import io
import pathlib

from hyrum import _patchers as patchers
from hyrum import _pool as pool
from hyrum import _report as report


def _render(
    outcomes,
    *,
    base: pathlib.Path,
    target: str = 'unit',
    list_offenders: bool = False,
    no_headers: bool = False,
):
    buf = io.StringIO()
    report.render(
        outcomes,
        base=base,
        target=target,
        list_offenders=list_offenders,
        no_headers=no_headers,
        stream=buf,
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
    assert '1 not run (1 skipped)' in out


def test_render_summary_itemises_non_run_categories(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'a', status='passed'),
        pool.Outcome(repo=tmp_path / 'b', status='skipped'),
        pool.Outcome(repo=tmp_path / 'c', status='skipped'),
        pool.Outcome(repo=tmp_path / 'd', status='no_target'),
        pool.Outcome(repo=tmp_path / 'e', status='patcher_error'),
    ]
    out = _render(outcomes, base=tmp_path)
    assert '4 not run (2 skipped, 1 no_target, 1 patcher_error)' in out


def test_render_summary_omits_breakdown_when_all_ran(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'a', status='passed'),
        pool.Outcome(repo=tmp_path / 'b', status='failed'),
    ]
    out = _render(outcomes, base=tmp_path)
    assert out.rstrip().endswith('0 not run.')


def test_render_verbose_lists_failures(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'broken', status='failed'),
        pool.Outcome(repo=tmp_path / 'ok', status='passed'),
    ]
    out = _render(outcomes, base=tmp_path, list_offenders=True)
    assert 'broken' in out


def test_render_verbose_includes_error_detail(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(
            repo=tmp_path / 'borked',
            status='patcher_error',
            error='bad pyproject',
        ),
    ]
    out = _render(outcomes, base=tmp_path, list_offenders=True)
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
    out = _render(outcomes, base=tmp_path, list_offenders=True)
    assert '[project]' in out
    assert '[tool.poetry]' in out


def test_render_verbose_lists_skipped(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'x', status='skipped', skip_reason='ignored (manual)'),
    ]
    out = _render(outcomes, base=tmp_path, list_offenders=True)
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


def test_render_floors_small_percentages(tmp_path: pathlib.Path):
    outcomes = [pool.Outcome(repo=tmp_path / 'pass', status='passed')]
    outcomes += [pool.Outcome(repo=tmp_path / f'skip{i}', status='skipped') for i in range(300)]
    out = _render(outcomes, base=tmp_path)
    # 1 in 301 is 0.33%, which must not render as a bare '0%'.
    passed_row = next(line for line in out.splitlines() if line.startswith('passed'))
    assert passed_row.split() == ['passed', '1', '<1%', '100%']


def test_render_labels_the_table_denominator(tmp_path: pathlib.Path):
    out = _render([], base=tmp_path)
    assert '% OF ALL' in out


def test_render_labels_the_summary_denominator(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'a', status='passed'),
        pool.Outcome(repo=tmp_path / 'b', status='skipped'),
    ]
    out = _render(outcomes, base=tmp_path)
    assert '1 of 1 runs passed (100% of runs); 1 not run (1 skipped).' in out


def test_render_reports_both_denominators(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'pass', status='passed'),
        pool.Outcome(repo=tmp_path / 'fail', status='failed'),
    ]
    outcomes += [pool.Outcome(repo=tmp_path / f'skip{i}', status='skipped') for i in range(8)]
    rows = {
        line.split()[0]: line.split()[1:]
        for line in _render(outcomes, base=tmp_path).splitlines()
        if line.split() and line.split()[0] in ('passed', 'failed', 'skipped')
    }
    # One passing charm in ten is 10% of the fleet but half of what ran, and
    # the table now says both rather than leaving the reader to guess which
    # one the column means.
    assert rows['passed'] == ['1', '10%', '50%']
    assert rows['failed'] == ['1', '10%', '50%']
    # A skipped charm never ran, so its share of the runs is not zero, it is
    # undefined.
    assert rows['skipped'] == ['8', '80%', '\u2014']


def test_render_has_no_run_percentages_when_nothing_ran(tmp_path: pathlib.Path):
    outcomes = [pool.Outcome(repo=tmp_path / f'skip{i}', status='skipped') for i in range(3)]
    out = _render(outcomes, base=tmp_path)
    skipped_row = next(line for line in out.splitlines() if line.startswith('skipped'))
    assert skipped_row.split() == ['skipped', '3', '100%', '\u2014']
    assert 'No runs executed.' in out


def test_render_gives_a_skip_kind_sub_row_all_four_cells(tmp_path: pathlib.Path):
    """The sub-rows are the arity the rest of the table is, and say so.

    A skip kind has no share of the runs for the same reason `skipped` has
    none: the charm never ran. It is also the row a forgotten column lands
    on, since it is built separately from the status loop.
    """
    outcomes = [
        pool.Outcome(repo=tmp_path / 'pass', status='passed'),
        pool.Outcome(
            repo=tmp_path / 'skip',
            status='skipped',
            skip_reason='no pyproject.toml',
            skip_reason_kind=patchers.PatcherSkipReason.NO_PYPROJECT,
        ),
    ]
    out = _render(outcomes, base=tmp_path)
    sub_row = next(line for line in out.splitlines() if line.strip().startswith('no_pyproject'))
    assert sub_row.split() == ['no_pyproject', '1', '50%', '\u2014']


def test_render_falls_back_to_ascii_when_the_stream_cannot_encode(tmp_path: pathlib.Path):
    """Losing the whole tally to an encoding error is the worst way to end a run.

    Every ordinary run has a non-run status, so every ordinary run carries the
    marker; before this the table only reached it when nothing ran at all.
    """
    outcomes = [
        pool.Outcome(repo=tmp_path / 'pass', status='passed'),
        pool.Outcome(repo=tmp_path / 'skip', status='skipped', skip_reason='legacy charm'),
    ]
    buf = io.TextIOWrapper(io.BytesIO(), encoding='ascii', errors='strict', newline='')
    report.render(outcomes, base=tmp_path, target='unit', list_offenders=True, stream=buf)
    buf.flush()
    out = buf.buffer.getvalue().decode('ascii')  # pyright: ignore[reportAttributeAccessIssue]
    skipped_row = next(line for line in out.splitlines() if line.startswith('skipped'))
    assert skipped_row.split() == ['skipped', '1', '50%', '-']
    assert '\u2014' not in out


def _render_markdown(
    outcomes,
    *,
    base: pathlib.Path,
    target: str = 'unit',
    verbose: bool = False,
    no_headers: bool = False,
):
    buf = io.StringIO()
    report.render_markdown(
        outcomes,
        base=base,
        target=target,
        list_offenders=verbose,
        no_headers=no_headers,
        stream=buf,
    )
    return buf.getvalue()


def test_render_markdown_titles_with_the_target(tmp_path: pathlib.Path):
    out = _render_markdown([], base=tmp_path, target='lint')
    assert out.startswith('# hyrum: lint')


def test_render_markdown_falls_back_without_a_target(tmp_path: pathlib.Path):
    out = _render_markdown([], base=tmp_path, target='')
    assert out.startswith('# hyrum run')


def test_render_markdown_table_has_one_row_per_status(tmp_path: pathlib.Path):
    outcomes = [pool.Outcome(repo=tmp_path / 'a', status='passed')]
    out = _render_markdown(outcomes, base=tmp_path)
    assert '| Status | Count | % of all | % of runs |' in out
    assert '| passed | 1 |' in out
    assert '| failed | 0 |' in out


def test_render_markdown_no_headers_suppresses_header_row(tmp_path: pathlib.Path):
    out = _render_markdown([], base=tmp_path, no_headers=True)
    assert '| Status | Count | % of all | % of runs |' not in out
    assert '| passed | 0 |' in out


def test_render_markdown_reports_no_runs_executed(tmp_path: pathlib.Path):
    out = _render_markdown([], base=tmp_path)
    assert 'No runs executed.' in out


def test_render_markdown_summary_line(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'a', status='passed'),
        pool.Outcome(repo=tmp_path / 'b', status='failed'),
    ]
    out = _render_markdown(outcomes, base=tmp_path)
    assert '**1** of **2** runs passed' in out
    assert '0 not run.' in out


def test_render_markdown_verbose_lists_offenders_by_status(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'broken', status='failed', error='boom'),
        pool.Outcome(repo=tmp_path / 'slow', status='timeout'),
        pool.Outcome(repo=tmp_path / 'ok', status='passed'),
    ]
    out = _render_markdown(outcomes, base=tmp_path, verbose=True)
    assert '## failed' in out
    assert '- broken — boom' in out
    assert '## timeout' in out
    assert '- slow' in out


def test_render_markdown_verbose_lists_skipped(tmp_path: pathlib.Path):
    outcomes = [
        pool.Outcome(repo=tmp_path / 'x', status='skipped', skip_reason='ignored (manual)'),
    ]
    out = _render_markdown(outcomes, base=tmp_path, verbose=True)
    assert '## skipped' in out
    assert '- x — ignored (manual)' in out


def test_render_markdown_not_verbose_omits_offender_sections(tmp_path: pathlib.Path):
    outcomes = [pool.Outcome(repo=tmp_path / 'broken', status='failed')]
    out = _render_markdown(outcomes, base=tmp_path, verbose=False)
    assert '## failed' not in out
