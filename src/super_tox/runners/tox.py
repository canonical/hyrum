"""``tox`` backend."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from super_tox.runners.base import RunResult, RunStatus, split_executable

logger = logging.getLogger(__name__)

# `tox -e <env>` returns this when the requested environment does not exist
# in the charm's tox.ini. We treat it as a skip, not a failure.
_TOX_NO_ENV_RETURNCODE = 254


class ToxRunner:
    name = "tox"

    def __init__(
        self,
        *,
        executable: str | Sequence[str] = "tox",
        timeout: int = 1800,
    ):
        self._executable = split_executable(executable)
        self._timeout = timeout

    @classmethod
    def detect(cls, repo: Path) -> bool:
        return (repo / "tox.ini").exists()

    async def run(self, repo: Path, target: str) -> RunResult:
        argv = [*self._executable, "-e", target]
        logger.info("tox %s in %s", target, repo)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=repo.resolve(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except TimeoutError:
            await _kill_and_drain(proc, repo)
            return RunResult(
                repo=repo,
                runner=self.name,
                target=target,
                status=RunStatus.TIMEOUT,
                returncode=None,
                duration_s=time.monotonic() - started,
            )

        duration = time.monotonic() - started
        rc = proc.returncode
        if rc == 0:
            status = RunStatus.PASSED
        elif rc == _TOX_NO_ENV_RETURNCODE:
            status = RunStatus.NO_TARGET
        else:
            status = RunStatus.FAILED
        return RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=status,
            returncode=rc,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
        )


async def _kill_and_drain(proc: asyncio.subprocess.Process, repo: Path) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        logger.error("tox in %s did not exit after kill()", repo)
