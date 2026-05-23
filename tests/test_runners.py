from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from super_tox.runners import MakeRunner, RunStatus, ToxRunner, auto, by_name

# ---- fake asyncio subprocess plumbing ----------------------------------------


@dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process."""

    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    raise_timeout: bool = False
    killed: bool = field(default=False, init=False)

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
        self.calls.append((tuple(args), str(kwargs.get("cwd"))))
        if not self._procs:
            raise AssertionError("FakeSpawner exhausted")
        return self._procs.pop(0)


@pytest.fixture
def spawner(monkeypatch):
    procs: list[FakeProc] = []
    fake = FakeSpawner(procs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)

    def _setup(*new_procs: FakeProc) -> FakeSpawner:
        fake._procs.extend(new_procs)
        return fake

    return _setup


# ---- ToxRunner ---------------------------------------------------------------


def test_tox_runner_detects_tox_ini(tmp_path: Path):
    (tmp_path / "tox.ini").write_text("[tox]\n")
    assert ToxRunner.detect(tmp_path)


def test_tox_runner_does_not_detect_without_tox_ini(tmp_path: Path):
    assert not ToxRunner.detect(tmp_path)


async def test_tox_runner_pass(tmp_path: Path, spawner):
    spawner(FakeProc(returncode=0))
    result = await ToxRunner(executable="tox").run(tmp_path, "unit")
    assert result.status is RunStatus.PASSED
    assert result.passed
    assert result.returncode == 0
    assert result.runner == "tox"
    assert result.target == "unit"


async def test_tox_runner_fail(tmp_path: Path, spawner):
    spawner(FakeProc(returncode=1, stderr=b"AssertionError"))
    result = await ToxRunner().run(tmp_path, "unit")
    assert result.status is RunStatus.FAILED
    assert result.stderr == b"AssertionError"


async def test_tox_runner_no_target_when_rc_254(tmp_path: Path, spawner):
    spawner(FakeProc(returncode=254))
    result = await ToxRunner().run(tmp_path, "unit")
    assert result.status is RunStatus.NO_TARGET


async def test_tox_runner_timeout_kills_process(tmp_path: Path, spawner):
    proc = FakeProc(raise_timeout=True)
    spawner(proc)
    result = await ToxRunner(timeout=0).run(tmp_path, "unit")
    assert result.status is RunStatus.TIMEOUT
    assert proc.killed
    assert result.returncode is None


async def test_tox_runner_passes_executable_through(tmp_path: Path, spawner):
    s = spawner(FakeProc(returncode=0))
    await ToxRunner(executable="uvx tox").run(tmp_path, "lint")
    argv, _ = s.calls[0]
    assert argv[:4] == ("uvx", "tox", "-e", "lint")


# ---- MakeRunner --------------------------------------------------------------


def test_make_runner_detects_makefile(tmp_path: Path):
    (tmp_path / "Makefile").write_text("unit:\n\ttrue\n")
    assert MakeRunner.detect(tmp_path)


def test_make_runner_also_detects_lowercase_makefile(tmp_path: Path):
    (tmp_path / "makefile").write_text("unit:\n\ttrue\n")
    assert MakeRunner.detect(tmp_path)


async def test_make_runner_pass(tmp_path: Path, spawner):
    # Probe says target exists (rc 0 or 1 from -nq), then the real run passes.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await MakeRunner().run(tmp_path, "unit")
    assert result.status is RunStatus.PASSED


async def test_make_runner_no_target_via_probe(tmp_path: Path, spawner):
    spawner(FakeProc(returncode=2, stderr=b"make: *** No rule to make target 'unit'.  Stop.\n"))
    result = await MakeRunner().run(tmp_path, "unit")
    assert result.status is RunStatus.NO_TARGET
    # The probe was enough; no real run launched.
    # (Only one fake was queued; if a second had been requested we'd assert.)


async def test_make_runner_failure(tmp_path: Path, spawner):
    spawner(
        FakeProc(returncode=1),  # probe: rule needs work but exists
        FakeProc(returncode=1, stderr=b"FAILED tests"),  # real run: test failure
    )
    result = await MakeRunner().run(tmp_path, "unit")
    assert result.status is RunStatus.FAILED


async def test_make_runner_no_target_from_real_run_stderr(tmp_path: Path, spawner):
    # Edge case: probe couldn't confirm (e.g. weird Makefile), but the real
    # run's stderr is the canonical message.
    spawner(
        FakeProc(returncode=1),  # probe (no marker)
        FakeProc(returncode=2, stderr=b"No rule to make target 'mystery'.  Stop.\n"),
    )
    result = await MakeRunner().run(tmp_path, "mystery")
    assert result.status is RunStatus.NO_TARGET


async def test_make_runner_timeout(tmp_path: Path, spawner):
    spawner(FakeProc(returncode=0), FakeProc(raise_timeout=True))
    result = await MakeRunner(timeout=0).run(tmp_path, "unit")
    assert result.status is RunStatus.TIMEOUT


# ---- by_name + auto ----------------------------------------------------------


def test_by_name_known():
    assert by_name("tox") is ToxRunner
    assert by_name("make") is MakeRunner


def test_by_name_unknown_raises():
    with pytest.raises(ValueError):
        by_name("ninja")


async def test_auto_picks_tox_when_only_tox_present(tmp_path: Path, spawner):
    (tmp_path / "tox.ini").write_text("[tox]\n")
    spawner(FakeProc(returncode=0))
    result = await auto().run(tmp_path, "unit")
    assert result.runner == "tox"
    assert result.status is RunStatus.PASSED


async def test_auto_picks_make_when_only_makefile_present(tmp_path: Path, spawner):
    (tmp_path / "Makefile").write_text("unit:\n\ttrue\n")
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await auto().run(tmp_path, "unit")
    assert result.runner == "make"
    assert result.status is RunStatus.PASSED


async def test_auto_falls_back_to_make_when_tox_lacks_target(
    tmp_path: Path, spawner
):
    (tmp_path / "tox.ini").write_text("[tox]\n")
    (tmp_path / "Makefile").write_text("unit:\n\ttrue\n")
    # tox -e unit returns 254 (no env); make probe + real both succeed.
    spawner(
        FakeProc(returncode=254),  # tox attempt
        FakeProc(returncode=0),  # make probe
        FakeProc(returncode=0),  # make real
    )
    result = await auto().run(tmp_path, "unit")
    assert result.runner == "make"
    assert result.status is RunStatus.PASSED


async def test_auto_reports_no_target_when_no_runner_can_run(tmp_path: Path):
    # No tox.ini, no Makefile.
    result = await auto().run(tmp_path, "unit")
    assert result.status is RunStatus.NO_TARGET
    assert result.runner == "auto"


async def test_auto_prefer_order_respected(tmp_path: Path, spawner):
    (tmp_path / "tox.ini").write_text("[tox]\n")
    (tmp_path / "Makefile").write_text("unit:\n\ttrue\n")
    # When user asks make-first, even with tox.ini present we should hit make.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await auto(prefer=("make", "tox")).run(tmp_path, "unit")
    assert result.runner == "make"
