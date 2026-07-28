from __future__ import annotations

import io
import pathlib

import pytest

from hyrum import _compare
from hyrum import _pool as pool


def _o(name: str, status: str, summary: str = '') -> pool.Outcome:
    return pool.Outcome(repo=pathlib.Path(f'/cache/{name}'), status=status, summary=summary)


def test_diff_new_failure_detected():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'failed')]
    result = _compare.diff(base, cur)
    assert result.new_failures == ['/cache/alpha']
    assert result.resolved == []
    assert result.new_errors == []


def test_diff_resolved_detected():
    base = [_o('alpha', 'failed')]
    cur = [_o('alpha', 'passed')]
    result = _compare.diff(base, cur)
    assert result.new_failures == []
    assert result.resolved == ['/cache/alpha']


def test_diff_new_error_from_clean_baseline():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'patcher_error')]
    result = _compare.diff(base, cur)
    assert result.new_errors == ['/cache/alpha']
    # A patcher_error after passing is also not a "failed" transition.
    assert result.new_failures == []


def test_diff_persistent_error_not_re_flagged():
    base = [_o('alpha', 'timeout')]
    cur = [_o('alpha', 'timeout')]
    result = _compare.diff(base, cur)
    assert result.new_errors == []


def test_pass_rate_calc_ignores_skipped_and_errored():
    base = [
        _o('a', 'passed'),
        _o('b', 'passed'),
        _o('c', 'failed'),
        _o('d', 'skipped'),
        _o('e', 'patcher_error'),
    ]
    cur = [
        _o('a', 'passed'),
        _o('b', 'failed'),
        _o('c', 'failed'),
        _o('d', 'skipped'),
        _o('e', 'patcher_error'),
    ]
    result = _compare.diff(base, cur)
    # passed + failed + timeout count toward "ran"; skipped/patcher_error don't.
    assert result.baseline_ran == 3
    assert result.baseline_passed == 2
    assert result.current_ran == 3
    assert result.current_passed == 1
    assert result.baseline_pass_rate == pytest.approx(2 / 3)
    assert result.current_pass_rate == pytest.approx(1 / 3)


def test_pass_rate_none_when_no_runs():
    result = _compare.diff([], [])
    assert result.baseline_pass_rate is None
    assert result.current_pass_rate is None


def test_render_quiet_when_no_diffs():
    buf = io.StringIO()
    result = _compare.diff([_o('a', 'passed')], [_o('a', 'passed')])
    _compare.render(result, file=buf)
    assert 'No changes' in buf.getvalue()


def test_render_shows_new_failures():
    buf = io.StringIO()
    result = _compare.diff([_o('alpha', 'passed')], [_o('alpha', 'failed')])
    _compare.render(result, file=buf)
    output = buf.getvalue()
    assert 'NEW FAILURES' in output
    assert 'alpha' in output


def test_markdown_render_omits_all_passing_charms():
    buf = io.StringIO()
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'passed')]
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '_No non-passing charms in either run._' in output
    assert 'alpha' not in output.split('_No')[0].split('Current pass rate')[1]


def test_markdown_render_includes_summaries_and_collapses_identical():
    base = [
        _o('alpha', 'failed', summary='3 failed; ValueError: bad'),
        _o('beta', 'passed'),
        _o('gamma', 'patcher_error', summary='patcher: lock failed'),
    ]
    cur = [
        _o('alpha', 'failed', summary='3 failed; ValueError: bad'),
        _o('beta', 'failed', summary='1 failed; KeyError: x'),
        _o('gamma', 'patcher_error', summary='patcher: lock failed'),
    ]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '| Charm | Baseline | Current |' in output
    # alpha: same failure both sides → current cell is "same".
    alpha_row = next(line for line in output.splitlines() if '| cache/alpha ' in line)
    assert '| same |' in alpha_row
    assert '3 failed; ValueError: bad' in alpha_row
    # beta: a brand-new failure; both sides differ.
    beta_row = next(line for line in output.splitlines() if '| cache/beta ' in line)
    assert 'passed' in beta_row
    assert 'KeyError: x' in beta_row
    # gamma: persistent patcher_error → "same" too.
    gamma_row = next(line for line in output.splitlines() if '| cache/gamma ' in line)
    assert '| same |' in gamma_row


def test_markdown_escapes_pipes_in_summary():
    buf = io.StringIO()
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'failed', summary='a | b')]
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert 'a \\| b' in output


def test_markdown_render_handles_charms_missing_from_one_side():
    buf = io.StringIO()
    base = [_o('alpha', 'failed', summary='oops')]
    cur: list[pool.Outcome] = []
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '| _absent_ |' in output


def test_markdown_render_shows_new_failures_resolved_and_errors_sections():
    base = [
        _o('alpha', 'passed'),
        _o('beta', 'failed'),
        _o('gamma', 'passed'),
    ]
    cur = [
        _o('alpha', 'failed'),
        _o('beta', 'passed'),
        _o('gamma', 'patcher_error'),
    ]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '## New failures\n\n- cache/alpha' in output
    assert '## Resolved\n\n- cache/beta' in output
    assert '## New errors\n\n- cache/gamma' in output


def test_markdown_render_omits_empty_sections():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'failed')]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '## New failures' in output
    assert '## Resolved' not in output
    assert '## New errors' not in output


def test_diff_tracks_charms_present_in_only_one_run():
    base = [_o('alpha', 'passed'), _o('beta', 'passed')]
    cur = [_o('alpha', 'passed'), _o('gamma', 'passed')]
    result = _compare.diff(base, cur)
    assert result.only_in_baseline == ['/cache/beta']
    assert result.only_in_current == ['/cache/gamma']
    assert result.common == 1
    assert not result.disjoint


def test_diff_disjoint_when_no_charms_shared():
    result = _compare.diff([_o('alpha', 'passed')], [_o('beta', 'passed')])
    assert result.disjoint


def test_diff_not_disjoint_when_one_run_is_empty():
    # An empty run is a degenerate comparison, not a mismatched charm set:
    # there is nothing to warn the user about re-keying.
    assert not _compare.diff([], [_o('alpha', 'passed')]).disjoint
    assert not _compare.diff([_o('alpha', 'passed')], []).disjoint


def test_diff_new_charm_erroring_is_not_a_new_error():
    # A charm the baseline never ran cannot have regressed against it.
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'passed'), _o('beta', 'timeout')]
    result = _compare.diff(base, cur)
    assert result.new_errors == []
    assert result.only_in_current == ['/cache/beta']


def test_render_warns_when_runs_are_disjoint():
    buf = io.StringIO()
    _compare.render(_compare.diff([_o('alpha', 'passed')], [_o('beta', 'passed')]), file=buf)
    output = buf.getvalue()
    assert 'no charms in common' in output
    assert 'No changes between runs.' not in output


def test_render_notes_charm_set_drift():
    base = [_o('alpha', 'passed'), _o('beta', 'passed')]
    cur = [_o('alpha', 'passed'), _o('gamma', 'passed')]
    buf = io.StringIO()
    _compare.render(_compare.diff(base, cur), file=buf)
    assert '1 charm only in baseline, 1 only in current' in buf.getvalue()


def test_render_omits_drift_note_when_charm_sets_match():
    buf = io.StringIO()
    _compare.render(_compare.diff([_o('alpha', 'passed')], [_o('alpha', 'passed')]), file=buf)
    assert 'only in baseline' not in buf.getvalue()


def test_render_delta_is_in_percentage_points_with_one_decimal():
    base = [_o(f'c{i}', 'passed') for i in range(1000)]
    cur = [
        *(_o(f'c{i}', 'passed') for i in range(996)),
        *(_o(f'c{i}', 'failed') for i in range(996, 1000)),
    ]
    buf = io.StringIO()
    _compare.render(_compare.diff(base, cur), file=buf)
    # A 0.4-point drop must not round away to '+0%'.
    assert 'delta -0.4 pts' in buf.getvalue()


def test_render_delta_is_n_a_when_a_run_had_nothing_to_measure():
    buf = io.StringIO()
    _compare.render(_compare.diff([], [_o('alpha', 'passed')]), file=buf)
    assert 'delta n/a' in buf.getvalue()


def test_diff_recovery_from_infrastructure_error_is_resolved():
    # new_errors counts entering an error state, so leaving one must be
    # reported too — otherwise fixing a patcher bug reads as "no changes".
    for broken in ('failed', 'timeout', 'patcher_error'):
        result = _compare.diff([_o('alpha', broken)], [_o('alpha', 'passed')])
        assert result.resolved == ['/cache/alpha'], broken
        assert result.new_errors == []


def test_diff_charm_that_started_running_is_not_resolved():
    # Never-ran -> passed is charm-set drift, not a fix.
    for absent in ('skipped', 'no_target'):
        assert _compare.diff([_o('alpha', absent)], [_o('alpha', 'passed')]).resolved == []


def test_render_shortens_absolute_keys_from_older_results_files():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'failed')]
    buf = io.StringIO()
    _compare.render(_compare.diff(base, cur), file=buf)
    assert '  cache/alpha' in buf.getvalue()
    assert '/cache/alpha' not in buf.getvalue()


def test_render_pluralises_a_single_new_failure():
    buf = io.StringIO()
    _compare.render(_compare.diff([_o('a', 'passed')], [_o('a', 'failed')]), file=buf)
    assert '(1 new failure,' in buf.getvalue()


def test_markdown_render_warns_when_runs_are_disjoint():
    # The stderr warning is lost when stdout is redirected into a PR comment,
    # so the markdown body has to carry it too.
    base = [_o('alpha', 'failed')]
    cur = [_o('beta', 'failed')]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    assert '> **Warning:** the two runs have no charms in common' in buf.getvalue()


def test_markdown_render_notes_charm_set_drift():
    base = [_o('alpha', 'failed'), _o('beta', 'passed')]
    cur = [_o('alpha', 'failed'), _o('gamma', 'passed')]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    assert '> **Note:** 1 charm only in baseline, 1 only in current' in buf.getvalue()


def test_markdown_render_omits_drift_note_when_charm_sets_match():
    base = [_o('alpha', 'failed')]
    cur = [_o('alpha', 'failed')]
    buf = io.StringIO()
    _compare.render_markdown(base, cur, _compare.diff(base, cur), file=buf)
    output = buf.getvalue()
    assert '**Note:**' not in output
    assert '**Warning:**' not in output


def test_as_dict_includes_computed_properties():
    result = _compare.diff([_o('alpha', 'passed')], [_o('beta', 'passed')])
    assert result.as_dict()['disjoint'] is True
