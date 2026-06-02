"""Filter predicates for narrowing down the charms a run will touch.

Each filter is a callable taking a charm path and returning either
``None`` (charm passes) or a short human-readable string explaining why
it was skipped. Callers compose them by short-circuiting on the first
non-``None`` reason and recording it alongside the skipped path.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable

SkipReason = str | None
Filter = Callable[[pathlib.Path], SkipReason]


def regex_filter(pattern: str) -> Filter:
    """Skip charms whose folder name does not match ``pattern`` (case-insensitive)."""
    compiled = re.compile(pattern, re.IGNORECASE)

    def _filter(repo: pathlib.Path) -> SkipReason:
        if compiled.match(repo.name):
            return None
        return f'name does not match {pattern!r}'

    return _filter


def ignore_filter(ignore: dict[str, list[str]], *, base: pathlib.Path) -> Filter:
    """Skip charms listed in the TOML ``[ignore]`` table.

    ``ignore`` maps category -> list of charm paths (relative to ``base``).
    The returned reason is the category, since each category encodes a
    different kind of "why this is skipped" (expensive, manual, etc.).
    """
    by_path: dict[str, str] = {}
    for category, items in ignore.items():
        for item in items:
            by_path[item] = category

    def _filter(repo: pathlib.Path) -> SkipReason:
        try:
            rel = str(repo.relative_to(base))
        except ValueError:
            return None
        category = by_path.get(rel) or by_path.get(repo.name)
        if category is None:
            return None
        return f'ignored ({category})'

    return _filter


def not_legacy(repo: pathlib.Path) -> SkipReason:
    """Skip reactive / classic hook-based charms.

    Reactive charms have a ``reactive/`` directory; classic hook charms
    have a ``hooks/`` directory. Both predate ``ops`` and are out of
    scope for ``hyrum``.
    """
    if (repo / 'reactive').exists() or (repo / 'hooks').exists():
        return 'legacy (reactive/hooks) charm'
    return None


def has_runnable_target(repo: pathlib.Path) -> SkipReason:
    """Skip charms with neither ``tox.ini`` nor ``Makefile``.

    The runner layer will refine this further (e.g. detecting a specific
    tox env or make target), but this catches charms that obviously
    cannot be driven by any supported runner.
    """
    if (repo / 'tox.ini').exists() or (repo / 'Makefile').exists():
        return None
    return 'no tox.ini or Makefile'
