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
import re
import shlex
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

# Matches ANSI CSI escape sequences (the `ESC[…<final>` family pytest and
# friends emit for colour). tox sets PY_COLORS=1 for its subprocesses and
# charms hard-code the same in their tox.ini, so we can't reliably disable
# colour at the source — strip it from the captured bytes instead.
_ANSI_CSI_RE = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')


def strip_ansi(data: bytes) -> bytes:
    """Remove ANSI CSI escape sequences from captured runner output."""
    return _ANSI_CSI_RE.sub(b'', data)


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
