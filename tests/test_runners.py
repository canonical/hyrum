from __future__ import annotations

import asyncio
import dataclasses
import itertools
import os
import pathlib
import typing

import pytest

from hyrum import _runners as runners

# ---- fake asyncio subprocess plumbing ----------------------------------------


@dataclasses.dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process.

    ``stdout`` and ``stderr`` are what the process writes to each stream. A
    caller that asked for ``stderr=STDOUT`` gets them as one buffer with
    ``None`` for stderr, which is what asyncio does when both descriptors
    share a pipe; ``merged`` overrides the interleaving for callers that care
    about the order lines arrive in.
    """

    returncode: int = 0
    stdout: bytes = b''
    stderr: bytes = b''
    merged: bytes | None = None
    raise_timeout: bool = False
    # Never a real pid: the fake killpg below swallows every signal anyway.
    pid: int = dataclasses.field(default_factory=itertools.count(1_000_000).__next__)
    killed: bool = dataclasses.field(default=False, init=False)
    merge_streams: bool = dataclasses.field(default=False, init=False)

    async def communicate(self):
        if self.raise_timeout and not self.killed:
            # Block until the test kills our group; then the drain returns.
            await asyncio.sleep(3600)
        if self.merge_streams:
            merged = self.stdout + self.stderr if self.merged is None else self.merged
            return merged, None
        return self.stdout, self.stderr


class FakeSpawner:
    """Hand FakeProc instances to consecutive create_subprocess_exec calls.

    A queued exception is raised instead of returned, which is how a missing
    or unexecutable runner binary shows up.

    Records each invocation as (argv, cwd) for assertion, and the full
    keyword arguments in ``kwargs`` so tests can check the stream wiring.
    """

    def __init__(self, procs: list[FakeProc | OSError]):
        self._procs = list(procs)
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.kwargs: list[dict[str, object]] = []
        self.spawned: dict[int, FakeProc] = {}

    async def __call__(self, *args: str, **kwargs: object) -> FakeProc:
        self.calls.append((tuple(args), str(kwargs.get('cwd'))))
        self.kwargs.append(dict(kwargs))
        if not self._procs:
            raise AssertionError('FakeSpawner exhausted')
        proc = self._procs.pop(0)
        if isinstance(proc, OSError):
            raise proc
        proc.merge_streams = kwargs.get('stderr') is asyncio.subprocess.STDOUT
        self.spawned[proc.pid] = proc
        return proc

    def killpg(self, pgid: int, _sig: int) -> None:
        """Stand in for os.killpg: mark the group's leader killed, signal nothing."""
        if pgid in self.spawned:
            self.spawned[pgid].killed = True


class SpawnerFactory(typing.Protocol):
    def __call__(self, *new_procs: FakeProc | OSError) -> FakeSpawner: ...


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> SpawnerFactory:
    procs: list[FakeProc | OSError] = []
    fake = FakeSpawner(procs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake)
    monkeypatch.setattr(os, 'killpg', fake.killpg)

    def _setup(*new_procs: FakeProc | OSError) -> FakeSpawner:
        fake._procs.extend(new_procs)
        return fake

    return _setup


def _missing(program: str) -> FileNotFoundError:
    return FileNotFoundError(2, 'No such file or directory', program)


# ---- ToxRunner ---------------------------------------------------------------


def test_tox_runner_detects_tox_ini(tmp_path: pathlib.Path):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    assert runners.ToxRunner.detect(tmp_path)


def test_tox_runner_does_not_detect_without_tox_ini(tmp_path: pathlib.Path):
    assert not runners.ToxRunner.detect(tmp_path)


async def test_tox_runner_pass(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    spawner(FakeProc(returncode=0))
    result = await runners.ToxRunner(executable='tox').run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.PASSED
    assert result.passed
    assert result.returncode == 0
    assert result.runner == 'tox'
    assert result.target == 'unit'


async def test_tox_runner_fail(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    spawner(FakeProc(returncode=1, stderr=b'AssertionError'))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED
    assert result.output == b'AssertionError'


async def test_tox_runner_merges_stderr_into_stdout(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # Both descriptors must point at the same pipe: the order tox and its
    # subprocesses wrote in is only available at capture time, and a log that
    # sections the two streams cannot recover it.
    transcript = (
        b'py: install_deps> uv sync\n'
        b'Resolved 42 packages\n'  # uv writes this to stderr
        b'== 1 failed, 2 passed in 0.10s ==\n'  # pytest, on stdout
        b'py: exit 1\n'
        b'ERROR: py: commands failed\n'  # tox's summary, on stderr
    )
    s = spawner(FakeProc(returncode=1, merged=transcript))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert s.kwargs[0]['stderr'] is asyncio.subprocess.STDOUT
    assert result.output == transcript


async def test_tox_runner_strips_ansi_from_captured_output(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
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
    assert result.output == b'FAILED tests/test_x.py::test_y\nE AssertionError\n'


async def test_tox_runner_strips_ansi_with_intermediate_bytes(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # CSI sequences may include intermediate bytes (0x20-0x2F) between the
    # parameter and final bytes, e.g. `ESC[1 q` (set cursor style).
    spawner(FakeProc(returncode=0, stdout=b'before\x1b[1 qafter\n'))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.output == b'beforeafter\n'


async def test_tox_runner_no_target_when_rc_254(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    spawner(FakeProc(returncode=254))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.NO_TARGET


async def test_tox_runner_timeout_kills_process(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    proc = FakeProc(raise_timeout=True)
    spawner(proc)
    result = await runners.ToxRunner(timeout=0).run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.TIMEOUT
    assert proc.killed
    assert result.returncode is None


@pytest.mark.parametrize('runner', [runners.ToxRunner, runners.MakeRunner])
async def test_runner_starts_its_own_process_group(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, runner: type[runners.ToxRunner]
):
    # Its own group is what lets a timeout reach the poetry or pytest that tox
    # or make started, rather than leaving them running under init.
    fake = spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    await runner().run(tmp_path, 'unit')
    assert fake.kwargs
    assert all(kw.get('start_new_session') is True for kw in fake.kwargs)


async def test_tox_runner_cancelled_kills_process_group(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # Ctrl-C cancels the pool's tasks; the subprocesses are in their own
    # groups and don't see the SIGINT, so cancelling has to kill them.
    proc = FakeProc(raise_timeout=True)
    spawner(proc)
    task = asyncio.create_task(runners.ToxRunner(timeout=3600).run(tmp_path, 'unit'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed


async def test_tox_runner_missing_executable_is_a_runner_error(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # A missing tox is a host problem, not a charm problem: it must not be
    # reported as `failed` (a test failure) or escape to the pool's catch-all
    # (which records it as a patcher problem).
    spawner(_missing('tox'))
    result = await runners.ToxRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.RUNNER_ERROR
    assert result.returncode is None
    assert b"could not run 'tox'" in result.output


async def test_tox_runner_passes_executable_through(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    s = spawner(FakeProc(returncode=0))
    await runners.ToxRunner(executable='uvx tox').run(tmp_path, 'lint')
    argv, _ = s.calls[0]
    assert argv[:4] == ('uvx', 'tox', '-e', 'lint')


def _env(spawner_call_kwargs: dict[str, object]) -> dict[str, str]:
    env = spawner_call_kwargs['env']
    assert isinstance(env, dict)
    return typing.cast('dict[str, str]', env)


def _tox_overrides(spawner_call_kwargs: dict[str, object]) -> list[str]:
    return _env(spawner_call_kwargs)['TOX_OVERRIDE'].split(';')


async def test_tox_runner_tells_tox_not_to_write_a_venv_redirect(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)
    fake = spawner(FakeProc(returncode=0))
    await runners.ToxRunner().run(tmp_path, 'unit')
    assert _tox_overrides(fake.kwargs[0]) == ['tox.venv_redirect=false']
    assert fake.kwargs[0]['env']['PATH'] == os.environ['PATH']


async def test_tox_runner_keeps_existing_tox_overrides(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('TOX_OVERRIDE', 'testenv:unit.pass_env+=FOO;')
    fake = spawner(FakeProc(returncode=0))
    await runners.ToxRunner().run(tmp_path, 'unit')
    assert _tox_overrides(fake.kwargs[0]) == [
        'testenv:unit.pass_env+=FOO',
        'tox.venv_redirect=false',
    ]


async def test_tox_runner_points_tox_and_uv_at_the_selected_python(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)
    fake = spawner(FakeProc(returncode=0))
    seen: list[pathlib.Path] = []

    def select(repo: pathlib.Path) -> str:
        seen.append(repo)
        return '3.12'

    result = await runners.ToxRunner(python=select).run(tmp_path, 'unit')
    assert seen == [tmp_path]
    assert _tox_overrides(fake.kwargs[0]) == [
        'tox.venv_redirect=false',
        'testenv.base_python=python3.12',
        'testenv:.pkg.base_python=python3.12',
    ]
    assert _env(fake.kwargs[0])['UV_PYTHON'] == '3.12'
    assert result.python == '3.12'


async def test_tox_runner_without_a_selected_python_sets_no_override(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)
    monkeypatch.delenv('UV_PYTHON', raising=False)
    fake = spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.ToxRunner(python=lambda _repo: None).run(tmp_path, 'unit')
    assert _tox_overrides(fake.kwargs[0]) == ['tox.venv_redirect=false']
    assert 'UV_PYTHON' not in _env(fake.kwargs[0])
    assert result.python is None
    await runners.ToxRunner().run(tmp_path, 'unit')
    assert 'UV_PYTHON' not in _env(fake.kwargs[1])


async def test_tox_runner_timeout_records_the_selected_python(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    spawner(FakeProc(raise_timeout=True))
    runner = runners.ToxRunner(timeout=0, python=lambda _repo: '3.10')
    result = await runner.run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.TIMEOUT
    assert result.python == '3.10'


# ---- MakeRunner --------------------------------------------------------------


def test_make_runner_detects_makefile(tmp_path: pathlib.Path):
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    assert runners.MakeRunner.detect(tmp_path)


def test_make_runner_also_detects_lowercase_makefile(tmp_path: pathlib.Path):
    (tmp_path / 'makefile').write_text('unit:\n\ttrue\n')
    assert runners.MakeRunner.detect(tmp_path)


async def test_make_runner_pass(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    # Probe says target exists (rc 0 or 1 from -nq), then the real run passes.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.PASSED


async def test_make_runner_tells_a_nested_tox_not_to_write_a_venv_redirect(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)
    fake = spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    await runners.MakeRunner().run(tmp_path, 'unit')
    assert _tox_overrides(fake.kwargs[1]) == ['tox.venv_redirect=false']


async def test_make_runner_probe_and_run_both_get_the_selected_python(
    tmp_path: pathlib.Path, spawner: SpawnerFactory, monkeypatch: pytest.MonkeyPatch
):
    # A recipe calling uv or tox sees the selection however make was reached,
    # including ``+`` recipe lines that run during the probe.
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)
    fake = spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.MakeRunner(python=lambda _repo: '3.11').run(tmp_path, 'unit')
    for kwargs in fake.kwargs:
        assert _env(kwargs)['UV_PYTHON'] == '3.11'
        assert 'testenv.base_python=python3.11' in _tox_overrides(kwargs)
    assert result.python == '3.11'


async def test_auto_runner_passes_the_selector_to_both_backends(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    fake = spawner(
        FakeProc(returncode=254),  # tox: no such env
        FakeProc(returncode=0),  # make probe
        FakeProc(returncode=0),  # make run
    )
    result = await runners.auto(python=lambda _repo: '3.12').run(tmp_path, 'unit')
    assert result.runner == 'make'
    assert [_env(kwargs)['UV_PYTHON'] for kwargs in fake.kwargs] == ['3.12'] * 3


async def test_make_runner_no_target_via_probe(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    spawner(FakeProc(returncode=2, stderr=b"make: *** No rule to make target 'unit'.  Stop.\n"))
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.NO_TARGET
    # The probe was enough; no real run launched.
    # (Only one fake was queued; if a second had been requested we'd assert.)


async def test_make_runner_failure(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    spawner(
        FakeProc(returncode=1),  # probe: rule needs work but exists
        FakeProc(returncode=1, stderr=b'FAILED tests'),  # real run: test failure
    )
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED


async def test_make_runner_no_target_from_real_run_output(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # Edge case: probe couldn't confirm (e.g. weird Makefile), but the real
    # run's own message is canonical. It arrives on the merged buffer, since
    # the real invocation points stderr at the stdout pipe.
    spawner(
        FakeProc(returncode=1),  # probe (no marker)
        FakeProc(returncode=2, stderr=b"make: *** No rule to make target 'mystery'.  Stop.\n"),
    )
    result = await runners.MakeRunner().run(tmp_path, 'mystery')
    assert result.status is runners.RunStatus.NO_TARGET


async def test_make_runner_marker_in_recipe_output_is_still_a_failure(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # The real invocation merges stderr into stdout, so a recipe that prints
    # the words itself reaches the missing-target check. Without make's own
    # `make:` prefix it is a failing test, not an absent target, and reporting
    # it as absent would drop a broken charm out of the tally entirely.
    spawner(
        FakeProc(returncode=1),  # probe: target exists
        FakeProc(
            returncode=2,
            stdout=b"FAILED tests/test_make.py::test_missing - 'No rule to make target'\n",
        ),
    )
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED


async def test_make_runner_nested_missing_target_is_a_failure(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # A sub-make reporting a missing target says nothing about the target we
    # asked for, which does exist and did run.
    spawner(
        FakeProc(returncode=1),  # probe: target exists
        FakeProc(
            returncode=2,
            stdout=b"make[1]: *** No rule to make target 'inner'.  Stop.\n",
        ),
    )
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.FAILED


async def test_make_runner_probe_keeps_streams_apart_but_run_merges(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # The `-nq` probe reads stderr as a signal, so it keeps its own pipe; the
    # real invocation is captured for a human, so it merges.
    s = spawner(FakeProc(returncode=1), FakeProc(returncode=0))
    await runners.MakeRunner().run(tmp_path, 'unit')
    assert s.kwargs[0]['stderr'] is asyncio.subprocess.PIPE
    assert s.kwargs[1]['stderr'] is asyncio.subprocess.STDOUT


async def test_make_runner_missing_executable_is_a_runner_error(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # The `-nq` probe swallows the launch failure so the real invocation can
    # report it with its own status; both calls raise here.
    spawner(_missing('make'), _missing('make'))
    result = await runners.MakeRunner().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.RUNNER_ERROR
    assert b"could not run 'make'" in result.output


async def test_make_runner_timeout(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    proc = FakeProc(raise_timeout=True)
    spawner(FakeProc(returncode=0), proc)
    result = await runners.MakeRunner(timeout=0).run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.TIMEOUT
    assert proc.killed


# ---- by_name + auto ----------------------------------------------------------


def test_by_name_known():
    assert runners.by_name('tox') is runners.ToxRunner
    assert runners.by_name('make') is runners.MakeRunner


def test_by_name_unknown_raises():
    with pytest.raises(ValueError):
        runners.by_name('ninja')


async def test_auto_picks_tox_when_only_tox_present(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    spawner(FakeProc(returncode=0))
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'tox'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_picks_make_when_only_makefile_present(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'make'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_falls_back_to_make_when_tox_lacks_target(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
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


async def test_auto_falls_back_to_make_when_tox_cannot_launch(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    spawner(
        _missing('tox'),  # tox attempt: not installed
        FakeProc(returncode=0),  # make probe
        FakeProc(returncode=0),  # make real
    )
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'make'
    assert result.status is runners.RunStatus.PASSED


async def test_auto_prefers_launch_failure_over_no_target(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # "tox is not installed" is more actionable than make's "no such target".
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('lint:\n\ttrue\n')
    spawner(
        _missing('tox'),
        FakeProc(returncode=2, stderr=b"make: *** No rule to make target 'unit'.  Stop.\n"),
    )
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.status is runners.RunStatus.RUNNER_ERROR
    assert b"could not run 'tox'" in result.output


async def test_auto_prefer_order_respected(tmp_path: pathlib.Path, spawner: SpawnerFactory):
    (tmp_path / 'tox.ini').write_text('[tox]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    # When user asks make-first, even with tox.ini present we should hit make.
    spawner(FakeProc(returncode=0), FakeProc(returncode=0))
    result = await runners.auto(prefer=('make', 'tox')).run(tmp_path, 'unit')
    assert result.runner == 'make'


async def test_auto_prefers_tox_when_a_charm_has_both(
    tmp_path: pathlib.Path, spawner: SpawnerFactory
):
    # The common real layout: a Makefile that mostly delegates, and a tox.ini
    # that holds the actual environments.
    (tmp_path / 'tox.ini').write_text('[testenv:unit]\n')
    (tmp_path / 'Makefile').write_text('unit:\n\ttrue\n')
    spawner(FakeProc(returncode=0))
    result = await runners.auto().run(tmp_path, 'unit')
    assert result.runner == 'tox'
    assert result.status is runners.RunStatus.PASSED
