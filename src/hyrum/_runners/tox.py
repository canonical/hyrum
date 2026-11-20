"""``tox`` backend."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time
from collections.abc import Sequence

from hyrum import _process
from hyrum._runners import base

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
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=repo.resolve(),
                stdout=asyncio.subprocess.PIPE,
                # Same pipe for both streams so the captured transcript keeps
                # the order tox and its subprocesses actually wrote in.
                stderr=asyncio.subprocess.STDOUT,
                env=base.subprocess_env(),
                # Its own process group, so a timeout or Ctrl-C can kill what it
                # spawns as well -- see hyrum._process.
                start_new_session=True,
            )
        except OSError as exc:
            logger.error('could not launch %s in %s: %s', argv[0], repo, exc)
            return base.launch_failure(repo, runner=self.name, target=target, argv=argv, exc=exc)
        try:
            output, _ = await _process.communicate(proc, self._timeout)
        except TimeoutError:
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
            output=base.strip_ansi(output),
        )
