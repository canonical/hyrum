"""``tox`` backend."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time
from collections.abc import Sequence

from hyrum.runners import base

logger = logging.getLogger(__name__)

# `tox -e <env>` returns this when the requested environment does not exist
# in the charm's tox.ini. We treat it as a skip, not a failure.
_TOX_NO_ENV_RETURNCODE = 254


class ToxRunner:
    """Run a target via ``tox -e <target>``."""

    name = 'tox'

    def __init__(
        self,
        *,
        executable: str | Sequence[str] = 'tox',
        timeout: int = 1800,
    ):
        self._executable = base.split_executable(executable)
        self._timeout = timeout

    @classmethod
    def detect(cls, repo: pathlib.Path) -> bool:
        """Return True if ``repo`` has a ``tox.ini``."""
        return (repo / 'tox.ini').exists()

    async def run(self, repo: pathlib.Path, target: str) -> base.RunResult:
        """Invoke ``tox -e <target>`` in ``repo`` and capture the result."""
        argv = [*self._executable, '-e', target]
        logger.info('tox %s in %s', target, repo)
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
        elif rc == _TOX_NO_ENV_RETURNCODE:
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


async def _kill_and_drain(proc: asyncio.subprocess.Process, repo: pathlib.Path) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        logger.error('tox in %s did not exit after kill()', repo)
