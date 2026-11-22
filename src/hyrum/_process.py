"""Run subprocesses so that nothing they start can outlive hyrum.

Every subprocess started here is the leader of its own process group, and
the whole group is killed once the subprocess has finished, whether it
exited, timed out, or its task was cancelled, and when hyrum itself exits.
That includes anything a successful run left behind in the background.

Its own group also means a Ctrl-C at the terminal no longer reaches the
subprocess directly. Instead, a cancelled task sends its group SIGINT and
allows a short grace period before the kill, so a test run can still tear its
fixtures down. :func:`kill_all` covers whatever is left on the way out, and
:func:`cleanup_on_exit` arranges that for the signals that would otherwise end
hyrum without unwinding.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] — this module exists to run subprocesses
from collections.abc import Awaitable, Generator, Mapping, Sequence
from typing import Any, TypeVar

_T = TypeVar('_T')

logger = logging.getLogger(__name__)

# Process groups started and not yet reaped. No lock: kill_all runs from a
# signal handler, which would deadlock on a lock the interrupted code holds.
_groups: set[int] = set()

# How long to wait for a killed process to be reaped before giving up on it.
_REAP_TIMEOUT = 30

# How long an interrupted subprocess gets to clean up before it is killed.
_INTERRUPT_GRACE = 10


def kill_group(pgid: int) -> None:
    """Send SIGKILL to every process in the group ``pgid``.

    A group that has already gone is not an error.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def kill_all() -> None:
    """Kill every process group started through this module and not yet reaped."""
    for pgid in list(_groups):
        kill_group(pgid)


@contextlib.contextmanager
def tracked(pid: int) -> Generator[None]:
    """Track ``pid``'s process group for the duration of the block.

    ``pid`` must lead its own group (``start_new_session=True``), so the
    process id doubles as the group id. The whole group is killed when the
    block exits. If the block raises (a timeout, a cancelled task, a
    KeyboardInterrupt), that happens before the exception propagates. On
    success the leader has already exited, so this only kills anything it
    left running in the background.
    """
    _groups.add(pid)
    try:
        yield
    finally:
        kill_group(pid)
        _groups.discard(pid)


async def communicate(
    proc: asyncio.subprocess.Process, timeout: float | None
) -> tuple[bytes, bytes]:
    """Wait for ``proc`` to exit, killing its whole group if it does not.

    ``proc`` must have been started with ``start_new_session=True``. On a
    timeout the group is killed, the process reaped, and :class:`TimeoutError`
    raised.

    Cancelling the awaiting task sends the group SIGINT, as a Ctrl-C at the
    terminal would, so that tox or make can stop their tests and pytest can
    run fixture teardown. The process then has :data:`_INTERRUPT_GRACE`
    seconds to exit before the group is killed.
    """
    with tracked(proc.pid):
        try:
            return await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            # Kill now so the drain below returns; tracked() kills again on the
            # way out, which is harmless.
            kill_group(proc.pid)
            try:
                await asyncio.wait_for(proc.communicate(), timeout=_REAP_TIMEOUT)
            except TimeoutError:
                logger.error('process %d did not exit after SIGKILL', proc.pid)
            raise
        except asyncio.CancelledError:
            await _interrupt(proc)
            raise


async def _interrupt(proc: asyncio.subprocess.Process) -> None:
    """Send ``proc``'s group SIGINT and wait for ``proc`` to exit, within the grace period.

    Whatever is still running afterwards is left for :func:`tracked` to kill.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGINT)
    # Keep draining the pipes, or output written during teardown could fill
    # them and block the process from exiting. Wait on the process itself,
    # not the drain: a background grandchild can hold the pipes open long
    # after the process has gone.
    drain = asyncio.ensure_future(proc.communicate())
    try:
        await asyncio.wait_for(proc.wait(), timeout=_INTERRUPT_GRACE)
    except TimeoutError:
        logger.warning(
            'process %d did not exit within %ds of SIGINT; killing it',
            proc.pid,
            _INTERRUPT_GRACE,
        )
    finally:
        drain.cancel()


def run(
    cmd: Sequence[str],
    *,
    timeout: float,
    cwd: pathlib.Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Like :func:`subprocess.run`, but a timeout kills the whole process group.

    Output is captured, and the return code is not checked. Raises
    :class:`subprocess.TimeoutExpired` on a timeout, as :func:`subprocess.run`
    does.
    """
    proc = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] — callers pass an argv
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        cwd=cwd,
        env=env,
    )
    with tracked(proc.pid):
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill now so the drain below returns; tracked() kills again on the
            # way out, which is harmless.
            kill_group(proc.pid)
            try:
                proc.communicate(timeout=_REAP_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.error('process %d did not exit after SIGKILL', proc.pid)
            raise
    return subprocess.CompletedProcess(list(cmd), proc.returncode, stdout, stderr)


async def kill_all_on_error(awaitable: Awaitable[_T]) -> _T:
    """Await ``awaitable``, killing every tracked group if it raises.

    That's usually a cancellation from Ctrl-C, but a crash in the pool should
    take its subprocesses with it too.

    Subprocesses run from worker threads (lockfile regeneration) can't be
    cancelled, and :func:`asyncio.run` waits for those threads before it
    returns. Without this, a Ctrl-C during a lock would wait out the lock's
    whole timeout before hyrum exited.
    """
    try:
        return await awaitable
    except BaseException:
        kill_all()
        raise


@contextlib.contextmanager
def cleanup_on_exit() -> Generator[None]:
    """Kill every tracked process group when the block exits, however it exits.

    SIGTERM and SIGHUP -- an ended terminal session, a supervisor stopping
    hyrum -- would otherwise end the process without unwinding, so for the
    duration of the block they kill the tracked groups first and then take
    their default action. SIGINT still raises KeyboardInterrupt, which
    unwinds through the block; the subprocesses do not see it themselves,
    because they are not in the terminal's foreground process group.
    """

    def _handler(signum: int, _frame: object) -> None:
        kill_all()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous: dict[int, Any] = {}
    for signum in (signal.SIGTERM, signal.SIGHUP):
        with contextlib.suppress(ValueError):  # Not the main thread.
            previous[signum] = signal.signal(signum, _handler)
    try:
        yield
    finally:
        kill_all()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
