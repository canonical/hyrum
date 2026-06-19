"""Runner protocol and the dataclass every runner returns.

Runners deliberately do *not* parse their subprocess's stdout/stderr
yet — Phase 5 of the productisation plan will add structured per-test
results, and a runner-level surface area is the right place to plug
that in later. For now a runner reports pass/fail/no-target/timeout
and the captured streams so callers can persist them if they wish.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import shlex
from collections.abc import Sequence
from typing import Protocol, runtime_checkable


class RunStatus(enum.StrEnum):
    """Outcome of one runner invocation in one charm."""

    PASSED = 'passed'
    FAILED = 'failed'
    NO_TARGET = 'no_target'  # tox env or make target does not exist
    TIMEOUT = 'timeout'


@dataclasses.dataclass(frozen=True)
class RunResult:
    """Structured result of running one target in one charm repo."""

    repo: pathlib.Path
    runner: str
    target: str
    status: RunStatus
    returncode: int | None
    duration_s: float
    stdout: bytes = b''
    stderr: bytes = b''

    @property
    def passed(self) -> bool:
        """Return True if the runner exited cleanly."""
        return self.status is RunStatus.PASSED


@runtime_checkable
class Runner(Protocol):
    """A backend that knows how to run one target in one charm repo."""

    name: str

    @classmethod
    def detect(cls, repo: pathlib.Path) -> bool:
        """Return ``True`` if this runner can potentially run in ``repo``."""
        ...

    async def run(self, repo: pathlib.Path, target: str) -> RunResult:
        """Run ``target`` in ``repo`` and return the structured result."""
        ...


def split_executable(executable: str | Sequence[str]) -> list[str]:
    """Accept either a shell-quoted string (``'uvx tox'``) or a list."""
    if isinstance(executable, str):
        return shlex.split(executable)
    return list(executable)
