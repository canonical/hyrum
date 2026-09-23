from __future__ import annotations

import pathlib

import pytest

from hyrum import _pool as pool
from hyrum import _results as results
from hyrum import _selection as selection

from .conftest import make_charm


def test_known_selectors_is_statuses_plus_groups():
    assert selection.known_selectors() == frozenset(pool.OUTCOME_STATUSES) | {
        'failing',
        'not-passing',
    }


def test_failing_is_not_benign():
    # Defined by rule (the complement of the benign set), not enumeration:
    # a status added to OUTCOME_STATUSES later lands here unless it is also
    # added to the benign set.
    failing = selection.expand_statuses(['failing'])
    assert failing == {'failed', 'timeout', 'runner_error', 'patcher_error'}
    assert 'passed' not in failing
    assert 'no_target' not in failing
    assert 'skipped' not in failing


def test_not_passing_is_everything_but_passed():
    not_passing = selection.expand_statuses(['not-passing'])
    assert not_passing == frozenset(pool.OUTCOME_STATUSES) - {'passed'}


def test_expand_statuses_passes_through_literal_statuses():
    assert selection.expand_statuses(['failed', 'timeout']) == {'failed', 'timeout'}


def test_expand_statuses_unions_group_and_literal():
    expanded = selection.expand_statuses(['failing', 'skipped'])
    assert expanded == {'failed', 'timeout', 'runner_error', 'patcher_error', 'skipped'}


def test_expand_statuses_unions_repeats():
    # Simulates two --status occurrences plus a comma-separated one, all
    # flattened by the caller before reaching expand_statuses.
    assert selection.expand_statuses(['failed', 'timeout', 'failed']) == {'failed', 'timeout'}


def test_from_results_filter_selects_matching_status(charm_cache: pathlib.Path):
    repo = charm_cache / 'canonical' / 'foo'
    repo.mkdir(parents=True)
    outcomes_by_key = {'canonical/foo': pool.Outcome(repo=repo, status='failed')}
    f = selection.from_results_filter(
        outcomes_by_key, frozenset({'failed'}), base=charm_cache, source=pathlib.Path('run.json')
    )
    assert f(repo) is None


def test_from_results_filter_excludes_wrong_status(charm_cache: pathlib.Path):
    repo = charm_cache / 'canonical' / 'foo'
    repo.mkdir(parents=True)
    outcomes_by_key = {'canonical/foo': pool.Outcome(repo=repo, status='passed')}
    f = selection.from_results_filter(
        outcomes_by_key, frozenset({'failed'}), base=charm_cache, source=pathlib.Path('run.json')
    )
    reason = f(repo)
    assert reason is not None
    assert 'passed' in reason
    assert 'run.json' in reason


def test_from_results_filter_excludes_charm_not_in_file(charm_cache: pathlib.Path):
    repo = charm_cache / 'canonical' / 'foo'
    repo.mkdir(parents=True)
    f = selection.from_results_filter(
        {}, frozenset({'failed'}), base=charm_cache, source=pathlib.Path('run.json')
    )
    reason = f(repo)
    assert reason is not None
    assert 'not in' in reason
    assert 'run.json' in reason


def test_from_results_filter_matches_across_charms_dir_spellings(tmp_path: pathlib.Path):
    """The filter keys on owner/name, not on the literal cache path."""
    # The outcome's repo is the relative identity `_results.save` writes, so
    # nothing in the file records the cache it was saved from.
    outcomes_by_key = {
        'canonical/foo': pool.Outcome(repo=pathlib.Path('canonical/foo'), status='failed')
    }
    other_cache = tmp_path / 'host-b' / 'cache'
    repo = other_cache / 'canonical' / 'foo'
    repo.mkdir(parents=True)
    f = selection.from_results_filter(
        outcomes_by_key, frozenset({'failed'}), base=other_cache, source=pathlib.Path('run.json')
    )
    assert f(repo) is None


def test_load_selection_raises_value_error_on_malformed_file(
    tmp_path: pathlib.Path, charm_cache: pathlib.Path
):
    """The caller decides what a bad file means; the message names the file."""
    bad = tmp_path / 'bad.json'
    bad.write_text('not json')
    with pytest.raises(ValueError) as exc_info:
        selection.load_selection(bad, frozenset({'failed'}), cache=charm_cache)
    assert str(bad) in str(exc_info.value)


def test_unmatched_names_the_charms_the_cache_does_not_have(
    tmp_path: pathlib.Path,
    charm_cache: pathlib.Path,
):
    """The caller reports these, from the charms it has already enumerated."""
    present = make_charm(charm_cache / 'canonical' / 'foo')
    path = tmp_path / 'run.json'
    results.save(
        [
            pool.Outcome(repo=present, status='failed'),
            pool.Outcome(repo=pathlib.Path('canonical/not-cloned'), status='failed'),
        ],
        path,
        base=charm_cache,
    )

    sel = selection.load_selection(path, frozenset({'failed'}), cache=charm_cache)

    assert sel.filter(present) is None
    assert selection.unmatched(sel, [present], base=charm_cache) == frozenset({
        'canonical/not-cloned'
    })


def test_a_disjoint_file_selects_no_charm(tmp_path: pathlib.Path, charm_cache: pathlib.Path):
    """Disjoint is not special: it is one of the ways to select nothing."""
    cached = make_charm(charm_cache / 'canonical' / 'foo')
    path = tmp_path / 'run.json'
    results.save(
        [pool.Outcome(repo=pathlib.Path('someone-else/bar'), status='failed')],
        path,
    )

    sel = selection.load_selection(path, frozenset({'failed'}), cache=charm_cache)

    assert sel.filter(cached) is not None
    assert selection.unmatched(sel, [cached], base=charm_cache) == frozenset({'someone-else/bar'})


def test_load_selection_reading_the_file_a_run_is_about_to_overwrite_is_safe(
    tmp_path: pathlib.Path, charm_cache: pathlib.Path
):
    """Selection reads --from-results before the pool starts and any save rotates it."""
    repo = make_charm(charm_cache / 'canonical' / 'foo')
    path = tmp_path / 'unit.auto.json'
    results.save([pool.Outcome(repo=repo, status='failed')], path, base=charm_cache, target='unit')

    sel = selection.load_selection(path, frozenset({'failed'}), cache=charm_cache)
    assert sel.filter(repo) is None

    # Simulate the rolling save rotating the just-read file away mid-run.
    path.replace(charm_cache.parent / 'unit.auto.prev.json')
    assert not path.exists()
    # The filter already captured the outcomes in memory; it does not re-read.
    assert sel.filter(repo) is None
