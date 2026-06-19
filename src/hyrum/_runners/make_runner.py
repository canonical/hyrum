"""``make`` backend.

GNU make has no dedicated exit code for "target does not exist": it
emits exit code 2 along with ``No rule to make target '<target>'`` on
stderr, which is the same exit code it uses for other errors. We
detect the "no such target" case from the stderr message so the tool
can record it as a skip rather than a failure — matching tox's 254
behaviour.

We probe targets with ``make -nq <target>`` (dry-run, question-mode)
before invoking the real recipe: it has no side effects, returns 2 if
the target does not exist, and lets us distinguish that case cleanly
even when the Makefile is non-trivial.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time
from collections.abc import Sequence

from hyrum._runners import base

logger = logging.getLogger(__name__)

_NO_RULE_MARKERS = (
    b'No rule to make target',
    b'no rule to make target',
)


class MakeRunner:
    """Run a target via ``make <target>``."""

    name = 'make'

    def __init__(
        self,
        *,
        executable: str | Sequence[str] = 'make',
        timeout: int = 1800,
    ):
        self._executable = base.split_executable(executable)
        self._timeout = timeout

    @classmethod
    def detect(cls, repo: pathlib.Path) -> bool:
        """Return True if ``repo`` has a Makefile (either case)."""
        return (repo / 'Makefile').exists() or (repo / 'makefile').exists()

    async def run(self, repo: pathlib.Path, target: str) -> base.RunResult:
        """Probe with ``-nq`` for the target, then invoke make and capture."""
        if await self._target_missing(repo, target):
            return base.RunResult(
                repo=repo,
                runner=self.name,
                target=target,
                status=base.RunStatus.NO_TARGET,
                returncode=None,
                duration_s=0.0,
            )

        argv = [*self._executable, target]
        logger.info('make %s in %s', target, repo)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=repo.resolve(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError:
            await _kill_and_drain(proc, repo)
            return base.RunResult(
                repo=repo,
                runner=self.name,
                target=target,
                status=base.RunStatus.TIMEOUT,
                returncode=None,
                duration_s=time.monotonic() - started,
            )

        duration = time.monotonic() - started
        rc = proc.returncode
        if rc == 0:
            status = base.RunStatus.PASSED
        elif _looks_like_missing_target(stderr):
            status = base.RunStatus.NO_TARGET
        else:
            status = base.RunStatus.FAILED
        return base.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=status,
            returncode=rc,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
        )

    async def _target_missing(self, repo: pathlib.Path, target: str) -> bool:
        """Return True if ``make -nq <target>`` reports the target unknown."""
        argv = [*self._executable, '-nq', target]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=repo.resolve(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            # No make installed; let the real invocation report it.
            return False
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except TimeoutError:
            await _kill_and_drain(proc, repo)
            return False
        return _looks_like_missing_target(stderr)


def _looks_like_missing_target(stderr: bytes) -> bool:
    return any(marker in stderr for marker in _NO_RULE_MARKERS)


async def _kill_and_drain(proc: asyncio.subprocess.Process, repo: pathlib.Path) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        logger.error('make in %s did not exit after kill()', repo)
