"""Select charms by their outcome in a saved hyrum run.

Shared by ``check --from-results`` and ``prune-charms``: given a saved
results file and a set of wanted statuses, decide which charms in the cache
match.

Matching is on the same relative ``owner/name`` identity
:func:`hyrum._results._identity` writes, not on cache paths, so a run saved
on another host (or with a different ``--charms-dir``) still selects
correctly.
"""

from __future__ import annotations

import logging
import pathlib
import sys
from collections.abc import Iterable

from hyrum import _enumerate as enumerate_mod
from hyrum import _filters as filt
from hyrum import _pool as pool
from hyrum import _results as results

logger = logging.getLogger(__name__)

STATUS_GROUPS: tuple[str, ...] = ('failing', 'not-passing')
"""``--status`` group names, in addition to the ``pool.OUTCOME_STATUSES`` themselves."""

# The statuses pool.passed() treats as not broken: filtered out before the
# patcher/runner ever ran, or run with nothing to check. "failing" below is
# defined as the complement of this set, not as an enumerated list, so a
# status added to OUTCOME_STATUSES later lands in the right group with no
# second decision.
_BENIGN_STATUSES = frozenset({'passed', 'no_target', 'skipped'})


def known_selectors() -> frozenset[str]:
    """Every name ``--status`` accepts: the outcome statuses plus the two groups."""
    return frozenset(pool.OUTCOME_STATUSES) | frozenset(STATUS_GROUPS)


def expand_statuses(tokens: Iterable[str]) -> frozenset[str]:
    """Expand already-validated ``--status`` tokens into concrete status names.

    ``failing`` is "reached the runner or the patcher and did not come out
    clean"; ``not-passing`` is "not passed". Repeats and commas (already
    split by the caller) union together.
    """
    selected: set[str] = set()
    for name in tokens:
        if name == 'failing':
            selected |= frozenset(pool.OUTCOME_STATUSES) - _BENIGN_STATUSES
        elif name == 'not-passing':
            selected |= frozenset(pool.OUTCOME_STATUSES) - {'passed'}
        else:
            selected.add(name)
    return frozenset(selected)


def from_results_filter(
    outcomes_by_key: dict[str, pool.Outcome],
    statuses: frozenset[str],
    *,
    base: pathlib.Path,
    source: pathlib.Path,
) -> filt.Filter:
    """Build a :class:`~hyrum._filters.Filter` selecting charms recorded in *outcomes_by_key*.

    A charm is excluded (with a reason naming *source*) if it is not in the
    file at all, or if its recorded status is not in *statuses*.
    """

    def _filter(repo: pathlib.Path) -> filt.SkipReason:
        key = results._identity(repo, base)
        outcome = outcomes_by_key.get(key)
        if outcome is None:
            return f'not in {source}'
        if outcome.status not in statuses:
            return f'{outcome.status} not selected from {source}'
        return None

    return _filter


def load_selection(
    path: pathlib.Path,
    statuses: frozenset[str],
    *,
    cache: pathlib.Path,
) -> filt.Filter:
    """Load *path* and return a from-results :class:`~hyrum._filters.Filter` over *cache*.

    Exits with an error (code 2, matching ``hyrum compare``'s "bad input"
    convention) if *path* is unreadable or malformed, or if *path* and
    *cache* share no charms at all — the disjoint case ``hyrum compare``
    already warns about; here, running (or pruning) zero charms would
    otherwise look like success.
    """
    try:
        loaded = results.load(path)
    except ValueError as exc:
        print(f'hyrum: error: {exc}', file=sys.stderr)
        sys.exit(2)
    outcomes_by_key = {str(o.repo): o for o in loaded.outcomes}
    cache_keys = {results._identity(r, cache) for r in enumerate_mod.iter_charm_repos(cache)}
    file_keys = set(outcomes_by_key)
    if cache_keys and file_keys and not (cache_keys & file_keys):
        print(
            f'hyrum: warning: --from-results {path} and the charms cached in {cache} have no '
            f'charms in common — different charm collections, or a run saved by a hyrum '
            f'version that stored absolute paths?',
            file=sys.stderr,
        )
        sys.exit(2)
    missing = file_keys - cache_keys
    if missing:
        logger.info(
            '%d charm(s) named in %s are not present in %s (not cloned; see `hyrum get-charms`).',
            len(missing),
            path,
            cache,
        )
    return from_results_filter(outcomes_by_key, statuses, base=cache, source=path)
