from __future__ import annotations

import io
import pathlib

import pytest
import rich.console

from hyrum import _compare as compare_mod
from hyrum import _pool as pool


def _o(name: str, status: str) -> pool.Outcome:
    return pool.Outcome(repo=pathlib.Path(f'/cache/{name}'), status=status)


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
    console = rich.console.Console(file=io.StringIO(), width=80)
    result = compare_mod.diff([_o('a', 'passed')], [_o('a', 'passed')])
    compare_mod.render(result, console=console)
    output = console.file.getvalue()
    assert 'No changes' in output


def test_render_shows_new_failures():
    console = rich.console.Console(file=io.StringIO(), width=80)
    result = compare_mod.diff([_o('alpha', 'passed')], [_o('alpha', 'failed')])
    compare_mod.render(result, console=console)
    output = console.file.getvalue()
    assert 'New failures' in output
    assert 'alpha' in output
