from __future__ import annotations

import asyncio
import os
import pathlib
import signal
import subprocess  # ruff: ignore[suspicious-subprocess-import] — for TimeoutExpired
import time

import pytest

from hyrum import _process


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed grandchild is reparented and may sit as a zombie until init
    # reaps it; that's dead for our purposes.
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().split(')')[-1].split()[0] != 'Z'
    except OSError:  # Reaped between the two checks.
        return False


def _wait_until_dead(pid: int, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_run_timeout_kills_grandchildren(tmp_path: pathlib.Path):
    # The shell stands in for a ``uv run ... poetry lock`` wrapper: killing it
    # alone would leave the ``sleep`` running under init.
    pidfile = tmp_path / 'grandchild.pid'
    script = f'sleep 60 & echo $! > {pidfile}; wait'
    with pytest.raises(subprocess.TimeoutExpired):
        _process.run(['sh', '-c', script], timeout=0.5)
    grandchild = int(pidfile.read_text())
    try:
        assert _wait_until_dead(grandchild)
    finally:
        if _alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)
    assert not _process._groups


def test_run_returns_output_and_returncode(tmp_path: pathlib.Path):
    result = _process.run(['sh', '-c', 'echo out; echo err >&2; exit 3'], timeout=10, cwd=tmp_path)
    assert result.returncode == 3
    assert result.stdout == b'out\n'
    assert result.stderr == b'err\n'
    assert not _process._groups


@pytest.fixture
def killed(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record process-group kills instead of sending them."""
    groups: list[int] = []
    monkeypatch.setattr(os, 'killpg', lambda pgid, _sig: groups.append(pgid))
    monkeypatch.setattr(_process, '_groups', set())
    return groups


def test_tracked_kills_the_group_when_the_block_raises(killed: list[int]):
    with pytest.raises(KeyboardInterrupt), _process.tracked(4242):
        raise KeyboardInterrupt
    assert killed == [4242]
    assert not _process._groups


def test_tracked_leaves_the_group_alone_on_success(killed: list[int]):
    with _process.tracked(4242):
        assert 4242 in _process._groups
    assert killed == []
    assert not _process._groups


async def test_kill_all_on_error_kills_tracked_groups(killed: list[int]):
    # A lock running in a worker thread can't be cancelled, and asyncio.run
    # waits for that thread before returning, so cancelling the pool has to
    # kill the lock's group for Ctrl-C to take effect promptly.
    started = asyncio.Event()

    async def pool() -> None:
        with _process.tracked(4242):
            started.set()
            await asyncio.sleep(3600)

    _process._groups.add(5151)  # As if a lock were running in a worker thread.
    task = asyncio.create_task(_process.kill_all_on_error(pool()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert 5151 in killed
    assert 4242 in killed


def test_cleanup_on_exit_kills_whatever_is_left(killed: list[int]):
    with _process.cleanup_on_exit():
        _process._groups.add(4242)
    assert killed == [4242]


def test_cleanup_on_exit_restores_signal_handlers(killed: list[int]):
    before = signal.getsignal(signal.SIGTERM)
    with _process.cleanup_on_exit():
        assert signal.getsignal(signal.SIGTERM) is not before
    assert signal.getsignal(signal.SIGTERM) is before
