from __future__ import annotations

import io
import pathlib

import pytest

from hyrum import _compare as compare_mod
from hyrum import _pool as pool


def _o(name: str, status: str, summary: str = '') -> pool.Outcome:
    return pool.Outcome(repo=pathlib.Path(f'/cache/{name}'), status=status, summary=summary)


def test_diff_new_failure_detected():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'failed')]
    result = compare_mod.diff(base, cur)
    assert result.new_failures == ['/cache/alpha']
    assert result.resolved == []
    assert result.new_errors == []


def test_diff_resolved_detected():
    base = [_o('alpha', 'failed')]
    cur = [_o('alpha', 'passed')]
    result = compare_mod.diff(base, cur)
    assert result.new_failures == []
    assert result.resolved == ['/cache/alpha']


def test_diff_new_error_from_clean_baseline():
    base = [_o('alpha', 'passed')]
    cur = [_o('alpha', 'patcher_error')]
    result = compare_mod.diff(base, cur)
    assert result.new_errors == ['/cache/alpha']
    # A patcher_error after passing is also not a "failed" transition.
    assert result.new_failures == []


def test_diff_persistent_error_not_re_flagged():
    base = [_o('alpha', 'timeout')]
    cur = [_o('alpha', 'timeout')]
    result = compare_mod.diff(base, cur)
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
    result = compare_mod.diff(base, cur)
    # passed + failed + timeout count toward "ran"; skipped/patcher_error don't.
    assert result.baseline_ran == 3
    assert result.baseline_passed == 2
    assert result.current_ran == 3
    assert result.current_passed == 1
    assert result.baseline_pass_rate == pytest.approx(2 / 3)
    assert result.current_pass_rate == pytest.approx(1 / 3)


def test_pass_rate_zero_when_no_runs():
    result = compare_mod.diff([], [])
    assert result.baseline_pass_rate == pytest.approx(0.0)
    assert result.current_pass_rate == pytest.approx(0.0)


def test_render_quiet_when_no_diffs():
    buf = io.StringIO()
    result = compare_mod.diff([_o('a', 'passed')], [_o('a', 'passed')])
    compare_mod.render(result, file=buf)
    assert 'No changes' in buf.getvalue()


def test_render_shows_new_failures():
    buf = io.StringIO()
    result = compare_mod.diff([_o('alpha', 'passed')], [_o('alpha', 'failed')])
    compare_mod.render(result, file=buf)
    output = buf.getvalue()
    assert 'New failures' in output
    assert 'alpha' in output


def test_markdown_render_omits_all_passing_charms():
    buf = io.StringIO()
    compare_mod.render_markdown([_o('alpha', 'passed')], [_o('alpha', 'passed')], file=buf)
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
    compare_mod.render_markdown(base, cur, file=buf)
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
    compare_mod.render_markdown(
        [_o('alpha', 'passed')],
        [_o('alpha', 'failed', summary='a | b')],
        file=buf,
    )
    output = buf.getvalue()
    assert 'a \\| b' in output


def test_markdown_render_handles_charms_missing_from_one_side():
    buf = io.StringIO()
    compare_mod.render_markdown(
        [_o('alpha', 'failed', summary='oops')],
        [],
        file=buf,
    )
    output = buf.getvalue()
    assert '| _absent_ |' in output
