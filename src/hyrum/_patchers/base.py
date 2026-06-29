"""Patcher protocol and helpers used by every concrete patcher."""

from __future__ import annotations

import contextlib
import pathlib
from collections.abc import Generator, Sequence
from typing import Protocol, runtime_checkable


class PatcherError(RuntimeError):
    """Raised when a patcher cannot apply its changes.

    Distinct from a runner failure so callers can attribute the outcome
    to the patching step rather than the underlying tox/make invocation.
    """


class PatcherSkip(Exception):  # noqa: N818 — not an error; signals a no-op skip
    """Raised when a patcher has nothing to do for this repo.

    Distinct from :class:`PatcherError`: this is not a failure, it just
    means the charm doesn't use the thing being swapped (e.g. doesn't
    vendor the targeted library), so the run is skipped rather than
    reported as a patcher_error.
    """


@runtime_checkable
class Patcher(Protocol):
    """A reversible mutation of one charm repo's source tree."""

    def apply(self, repo: pathlib.Path) -> contextlib.AbstractContextManager[None]:
        """Apply the patch to ``repo``; restore on context exit.

        Implementations must restore every file they touched on exit,
        whether the body completed normally or raised — the cache must
        not be polluted across repos.
        """
        ...


class NullPatcher:
    """No-op patcher, used when nothing needs swapping out."""

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Yield without making any changes."""
        yield


class PatcherStack:
    """Compose multiple patchers; unwind in reverse on exit."""

    def __init__(self, patchers: Sequence[Patcher]):
        self._patchers = list(patchers)

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Apply each patcher in order; unwind in reverse on exit."""
        with contextlib.ExitStack() as stack:
            for patcher in self._patchers:
                stack.enter_context(patcher.apply(repo))
            yield
