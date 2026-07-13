from __future__ import annotations

import asyncio
import dataclasses
import pathlib

import pytest

from hyrum import _runners as runners

# ---- fake asyncio subprocess plumbing ----------------------------------------


@dataclasses.dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process."""

    returncode: int = 0
    stdout: bytes = b''
    stderr: bytes = b''
    raise_timeout: bool = False
    killed: bool = dataclasses.field(default=False, init=False)

    async def communicate(self):
        if self.raise_timeout and not self.killed:
            # Block until the test kills us; then the drain returns immediately.
            await asyncio.sleep(3600)
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True


class FakeSpawner:
    """Hand FakeProc instances to consecutive create_subprocess_exec calls.

    Records each invocation as (argv, cwd) for assertion.
    """

    def __init__(self, procs: list[FakeProc]):
        self._procs = list(procs)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((tuple(args), str(kwargs.get('cwd'))))
        if not self._procs:
            raise AssertionError('FakeSpawner exhausted')
        return self._procs.pop(0)


@pytest.fixture
def spawner(monkeypatch):
    procs: list[FakeProc] = []
    fake = FakeSpawner(procs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake)

    def _setup(*new_procs: FakeProc) -> FakeSpawner:
        fake._procs.extend(new_procs)
        return fake

    return _setup


# ---- ToxRunner ---------------------------------------------------------------


def test_tox_runner_detects_tox_ini(tmp_path: pathlib.Path):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    assert runners.ToxRunner.detect(tmp_path)


def test_tox_runner_does_not_detect_without_tox_ini(tmp_path: pathlib.Path):
    assert not runners.ToxRunner.detect(tmp_path)


async def test_tox_runner_pass(tmp_path: pathlib.Path, spawner):
    spawner(FakeProc(returncode=0))
    result = await runners.ToxRunner(executable='tox').run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.PASSED
    assert result.passed
    assert result.returncode == 0
    assert result.runner == 'tox'
    assert result.target == 'unit'


async def test_tox_runner_fail(tmp_path: pathlib.Path, spawner):
    spawner(FakeProc(returncode=1, stderr=b'AssertionError'))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED
    assert result.stderr == b'AssertionError'


async def test_tox_runner_strips_ansi_from_captured_output(tmp_path: pathlib.Path, spawner):
    # tox sets PY_COLORS=1 for its subprocesses (charms hard-code it too),
    # so pytest emits CSI sequences even when stdout is a pipe. Strip at the
    # runner so log files and the summary extractor see plain text.
    spawner(
        FakeProc(
            returncode=1,
            stdout=b'\x1b[31mFAILED\x1b[0m tests/test_x.py::test_y\n',
            stderr=b'\x1b[1mE\x1b[0m AssertionError\n',
        )
    )
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.stdout == b'FAILED tests/test_x.py::test_y\n'
    assert result.stderr == b'E AssertionError\n'


async def test_tox_runner_strips_ansi_with_intermediate_bytes(tmp_path: pathlib.Path, spawner):
    # CSI sequences may include intermediate bytes (0x20-0x2F) between the
    # parameter and final bytes, e.g. `ESC[1 q` (set cursor style).
    spawner(FakeProc(returncode=0, stdout=b'before\x1b[1 qafter\n'))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.stdout == b'beforeafter\n'



async def test_tox_runner_no_target_when_rc_254(tmp_path: pathlib.Path, spawner):
    spawner(FakeProc(returncode=254))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.NO_TARGET


async def test_tox_runner_timeout_kills_process(tmp_path: pathlib.Path, spawner):
    proc = FakeProc(raise_timeout=True)
    spawner(proc)
    result = await runners.ToxRunner(timeout=0).run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.TIMEOUT
    assert proc.killed
    assert result.returncode is None


async def test_tox_runner_passes_executable_through(tmp_path: pathlib.Path, spawner):
    s = spawner(FakeProc(returncode=0))
    await runners.ToxRunner(executable='uvx tox').run(tmp_path, 'lint')
    argv, _ = s.calls[0]
    assert argv[:4] == ('uvx', 'tox', '-e', 'lint')


# ---- MakeRunner --------------------------------------------------------------


def test_make_runner_detects_makefile(tmp_path: pathlib.Path):
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    assert runners.MakeRunner.detect(tmp_path)


def test_make_runner_also_detects_lowercase_makefile(tmp_path: pathlib.Path):
    (tmp_path / 'makefile').write_text('unit:\n\ttrue\n')
    assert runners.MakeRunner.detect(tmp_path)


async def test_make_runner_pass(tmp_path: pathlib.Path, spawner):
    # Probe says target exists (rc 0 or 1 from -nq), then the real run passes.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.PASSED


async def test_make_runner_no_target_via_probe(tmp_path: pathlib.Path, spawner):
    spawner(FakeProc(returncode=2, stderr=b"make: *** No rule to make target 'unit'.  Stop.\n"))
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.NO_TARGET
    # The probe was enough; no real run launched.
    # (Only one fake was queued; if a second had been requested we'd assert.)


async def test_make_runner_failure(tmp_path: pathlib.Path, spawner):
    spawner(
        FakeProc(returncode=1),  # probe: rule needs work but exists
        FakeProc(returncode=1, stderr=b'FAILED tests'),  # real run: test failure
    )
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED


async def test_make_runner_no_target_from_real_run_stderr(tmp_path: pathlib.Path, spawner):
    # Edge case: probe couldn't confirm (e.g. weird Makefile), but the real
    # run's stderr is the canonical message.
    spawner(
        FakeProc(returncode=1),  # probe (no marker)
        FakeProc(returncode=2, stderr=b"No rule to make target 'mystery'.  Stop.\n"),
    )
    result = await runners.MakeRunner().run(tmp_path, 'mystery')
    assert result.status is runners.RunStatus.NO_TARGET


async def test_make_runner_timeout(tmp_path: pathlib.Path, spawner):
    spawner(FakeProc(returncode=0), FakeProc(raise_timeout=True))
    result = await runners.MakeRunner(timeout=0).run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.TIMEOUT


# ---- by_name + auto ----------------------------------------------------------


def test_by_name_known():
    assert runners.by_name('tox') is runners.ToxRunner
    assert runners.by_name('make') is runners.MakeRunner


def test_by_name_unknown_raises():
    with pytest.raises(ValueError):
        runners.by_name('ninja')


async def test_auto_picks_tox_when_only_tox_present(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    spawner(FakeProc(returncode=0))
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'tox'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_picks_make_when_only_makefile_present(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'make'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_falls_back_to_make_when_tox_lacks_target(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    # tox -e unit returns 254 (no env); make probe + real both succeed.
    spawner(
        FakeProc(returncode=254),  # tox attempt
        FakeProc(returncode=0),  # make probe
        FakeProc(returncode=0),  # make real
    )
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'make'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_reports_no_target_when_no_runner_can_run(tmp_path: pathlib.Path):
    # No tox.ini, no Makefile.
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.NO_TARGET
    assert result.runner == 'auto'


async def test_auto_prefer_order_respected(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    # When user asks make-first, even with tox.ini present we should hit make.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.auto(prefer=('make', 'tox')).run(tmp_path, 'unit')
    assert result.runner == 'make'
