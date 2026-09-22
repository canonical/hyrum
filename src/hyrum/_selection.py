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

import dataclasses
import logging
import pathlib
from collections.abc import Iterable

from hyrum import _filters as filt
from hyrum import _pool as pool
from hyrum import _results as results

logger = logging.getLogger(__name__)

STATUS_GROUPS: tuple[str, ...] = ('failing', 'not-passing')
"""``--status`` group names, in addition to the ``pool.OUTCOME_STATUSES`` themselves."""

# "failing" is the complement of pool.BENIGN_STATUSES rather than an
# enumerated list, and reads the same set pool.passed() does, so a status added
# to OUTCOME_STATUSES lands in the right group by being put in that set or not.


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
            selected |= frozenset(pool.OUTCOME_STATUSES) - pool.BENIGN_STATUSES
        elif name == 'not-passing':
            selected |= frozenset(pool.OUTCOME_STATUSES) - {'passed'}
        else:
            selected.add(name)
    return frozenset(selected)


@dataclasses.dataclass(frozen=True)
class Selection:
    """A results-file selection: the filter, plus what the file named."""

    filter: filt.Filter
    """Excludes any charm the file does not name with a wanted status."""

    keys: frozenset[str]
    """Every ``owner/name`` identity the file names, whatever its status."""

    statuses: frozenset[str]
    """The statuses that were asked for, expanded from ``--status``."""

    source: pathlib.Path
    """The file it all came from, for error messages."""


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
) -> Selection:
    """Load *path* and return a :class:`Selection` over *cache*.

    Raises ``ValueError`` if *path* is unreadable or malformed, with
    :func:`hyrum._results.load`'s message naming the file: this is a library
    function, so reporting and the exit code belong to the caller, the way
    ``hyrum compare`` already does it.

    Selecting nothing is not detected here. A file can name charms the cache
    does not have, or carry no charm with a wanted status, or be empty, and
    all three are the same thing to the caller - no charm ran - so the check
    belongs where the filtered list exists. See :func:`unmatched`.
    """
    loaded = results.load(path)
    outcomes_by_key = {str(o.repo): o for o in loaded.outcomes}
    return Selection(
        filter=from_results_filter(outcomes_by_key, statuses, base=cache, source=path),
        keys=frozenset(outcomes_by_key),
        statuses=statuses,
        source=path,
    )


def unmatched(
    selection: Selection,
    cached: Iterable[pathlib.Path],
    *,
    base: pathlib.Path,
) -> frozenset[str]:
    """Return the identities *selection* names that are not in *cached*.

    ``cached`` is every charm the cache holds, run and skipped alike, so the
    caller can pass what it already enumerated rather than walking the cache a
    second time.
    """
    return selection.keys - {results._identity(repo, base) for repo in cached}
