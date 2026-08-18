"""Tests for hyrum.get_charms."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import pathlib
import typing

import pytest

from hyrum import _cli
from hyrum import _get_charms as get_charms


def _run_get_charms(argv: list[str]) -> int | str:
    try:
        _cli.main(['get-charms', *argv])
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, str) else int(exc.code)
    return 0


@dataclasses.dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process for git operations.

    With ``hang=True`` the process models a forge that accepts the connection
    and then never answers: ``communicate`` blocks until the caller's timeout
    fires and kills it.
    """

    returncode: int | None = 0
    stderr_bytes: bytes = b''
    hang: bool = False
    killed: bool = False
    pid: int = 0

    def __post_init__(self) -> None:
        if self.hang:
            # A live process has no returncode until it is reaped.
            self.returncode = None

    async def wait(self) -> int:
        return self.returncode or 0

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.hang:
            await asyncio.Event().wait()  # Never set: blocks until cancelled.
        return b'', self.stderr_bytes

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeSpawner:
    """Records each create_subprocess_exec call and yields queued FakeProcs."""

    def __init__(self) -> None:
        self.procs: list[FakeProc] = []
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.spawned: list[FakeProc] = []
        self.killed_groups: list[int] = []
        self.kwargs: list[dict[str, object]] = []
        self.on_spawn: typing.Callable[[], None] | None = None

    async def __call__(self, *args, **kwargs):
        self.calls.append((tuple(args), str(kwargs.get('cwd'))))
        self.kwargs.append(dict(kwargs))
        if self.on_spawn is not None:
            self.on_spawn()
        if not self.procs:
            raise AssertionError('FakeSpawner exhausted')
        proc = self.procs.pop(0)
        # Distinct, deliberately negative so a stray real signal can't land on
        # an actual process if the os patches below ever fail to apply.
        proc.pid = -(len(self.spawned) + 1000)
        self.spawned.append(proc)
        return proc


@pytest.fixture(autouse=True)
def no_real_signals(monkeypatch) -> list[int]:
    """Keep process-group kills inside the test.

    Autouse and unconditional: a FakeProc whose pid defaults to 0 would make
    ``os.getpgid(0)`` resolve to *pytest's own* process group, so an unguarded
    ``os.killpg`` takes down the test run.
    """
    killed: list[int] = []
    monkeypatch.setattr(os, 'getpgid', lambda pid: pid)
    monkeypatch.setattr(os, 'killpg', lambda pgid, _sig: killed.append(pgid))
    return killed


@pytest.fixture
def spawner(monkeypatch, no_real_signals):
    fake = FakeSpawner()
    fake.killed_groups = no_real_signals
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake)

    def _setup(*procs: FakeProc) -> FakeSpawner:
        fake.procs.extend(procs)
        return fake

    return _setup


# ---- repo_folder ------------------------------------------------------------


def test_repo_folder_namespaces_by_owner(tmp_path: pathlib.Path):
    assert (
        get_charms.repo_folder(tmp_path, 'https://github.com/canonical/foo', None)
        == tmp_path / 'canonical' / 'foo'
    )


def test_repo_folder_appends_branch_suffix_to_leaf(tmp_path: pathlib.Path):
    assert (
        get_charms.repo_folder(tmp_path, 'https://github.com/canonical/foo', '24.04')
        == tmp_path / 'canonical' / 'foo-24.04'
    )


# ---- process_rows -----------------------------------------------------------


async def test_process_rows_clones_missing_destination(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    await get_charms.process_rows(rows, tmp_path)

    assert len(fake.calls) == 1
    argv, cwd = fake.calls[0]
    assert argv[0:2] == ('git', 'clone')
    assert 'https://github.com/canonical/foo' in argv
    assert pathlib.Path(cwd) == tmp_path / 'canonical'


async def test_process_rows_pulls_existing_destination(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'canonical' / 'foo').mkdir(parents=True)
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    await get_charms.process_rows(rows, tmp_path)

    assert len(fake.calls) == 1
    argv, cwd = fake.calls[0]
    assert argv[0:2] == ('git', 'pull')
    assert pathlib.Path(cwd) == (tmp_path / 'canonical' / 'foo').resolve()


async def test_process_rows_includes_branch_flag_in_clone(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '24.04',
        }
    ]
    await get_charms.process_rows(rows, tmp_path)

    argv, _ = fake.calls[0]
    assert '--branch' in argv
    assert argv[argv.index('--branch') + 1] == '24.04'
    # Branch is also reflected in the destination path.
    assert argv[-1] == str((tmp_path / 'canonical' / 'foo-24.04').resolve())


async def test_process_rows_skips_rows_without_repository(tmp_path: pathlib.Path, spawner, caplog):
    # No procs queued: any subprocess call would fail the FakeSpawner assertion.
    spawner()
    rows = [
        {'Repository': '', 'Branch (if not the default)': ''},
        {'Repository': '', 'Branch (if not the default)': ''},
    ]
    with caplog.at_level(logging.WARNING, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert sum('Skipping row without Repository' in r.message for r in caplog.records) == 2


async def test_process_rows_handles_missing_branch_column(tmp_path: pathlib.Path, spawner):
    """A CSV without the Branch column shouldn't crash."""
    fake = spawner(FakeProc(returncode=0))
    rows = [{'Repository': 'https://github.com/canonical/foo'}]
    await get_charms.process_rows(rows, tmp_path)

    argv, _ = fake.calls[0]
    assert '--branch' not in argv


async def test_process_rows_strips_trailing_slash_from_repository(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Repository': 'https://github.com/canonical/foo/',
            'Branch (if not the default)': '',
        }
    ]
    await get_charms.process_rows(rows, tmp_path)

    argv, _ = fake.calls[0]
    # The destination is named after the repo basename, not "" from a trailing slash.
    assert argv[-1] == str((tmp_path / 'canonical' / 'foo').resolve())


async def test_process_rows_logs_error_on_clone_failure(tmp_path: pathlib.Path, spawner, caplog):
    spawner(FakeProc(returncode=128, stderr_bytes=b'fatal: remote not found\n'))
    rows = [
        {
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    with caplog.at_level(logging.ERROR, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert any(
        'Could not clone canonical/foo' in r.message and 'fatal: remote not found' in r.message
        for r in caplog.records
    )
    # %r keeps the message on a single line.
    assert all('\n' not in r.message for r in caplog.records)


async def test_process_rows_logs_summary(tmp_path: pathlib.Path, spawner, caplog):
    spawner(FakeProc(returncode=0), FakeProc(returncode=128))
    rows = [
        {
            'Repository': 'https://github.com/canonical/good',
            'Branch (if not the default)': '',
        },
        {
            'Repository': 'https://github.com/canonical/bad',
            'Branch (if not the default)': '',
        },
    ]
    with caplog.at_level(logging.INFO, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert any('1 succeeded, 1 failed' in r.message for r in caplog.records)
    assert any('Failed: canonical/bad' in r.message for r in caplog.records)


# ---- timeouts ---------------------------------------------------------------


async def test_process_rows_abandons_a_hanging_clone(tmp_path: pathlib.Path, spawner, caplog):
    proc = FakeProc(hang=True)
    fake = spawner(proc)
    rows = [{'Repository': 'https://git.launchpad.net/charm-keystone'}]

    with caplog.at_level(logging.ERROR, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path, timeout=0.05)

    assert proc.killed
    assert any('Timed out' in r.message for r in caplog.records)
    # The whole group must go: git delegates the transfer to a helper process
    # that keeps the stderr pipe open, and killing only git leaves it orphaned.
    assert fake.killed_groups == [proc.pid]


async def test_git_is_spawned_in_its_own_process_group(tmp_path: pathlib.Path, spawner):
    """Group-killing on timeout only works if git leads its own group."""
    fake = spawner(FakeProc(returncode=0))
    await get_charms.process_rows([{'Repository': 'https://github.com/canonical/foo'}], tmp_path)

    assert fake.kwargs[0]['start_new_session'] is True


async def test_process_rows_abandons_a_hanging_pull(tmp_path: pathlib.Path, spawner, caplog):
    (tmp_path / 'canonical' / 'foo').mkdir(parents=True)
    proc = FakeProc(hang=True)
    spawner(proc)
    rows = [{'Repository': 'https://github.com/canonical/foo'}]

    with caplog.at_level(logging.WARNING, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path, timeout=0.05)

    assert proc.killed
    assert any('Timed out' in r.message for r in caplog.records)


async def test_a_timeout_does_not_stall_the_other_rows(tmp_path: pathlib.Path, spawner, caplog):
    """One unresponsive repo must not stop the rest of the list completing."""
    spawner(FakeProc(hang=True), FakeProc(returncode=0))
    rows = [
        {'Repository': 'https://git.launchpad.net/charm-keystone'},
        {'Repository': 'https://github.com/canonical/good'},
    ]

    with caplog.at_level(logging.INFO, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path, workers=2, timeout=0.05)

    assert any('1 succeeded, 1 failed' in r.message for r in caplog.records)
    assert any('Failed: git.launchpad.net/charm-keystone' in r.message for r in caplog.records)


async def test_timed_out_clone_leaves_no_directory_behind(tmp_path: pathlib.Path, spawner):
    """A partial clone must not be mistaken for a valid checkout next run."""
    repository = 'https://git.launchpad.net/charm-keystone'
    dest = get_charms.repo_folder(tmp_path, repository, None)
    fake = spawner(FakeProc(hang=True))
    # Model git having created the target directory before it stalled.
    fake.on_spawn = lambda: (dest / '.git').mkdir(parents=True, exist_ok=True)

    await get_charms.process_rows([{'Repository': repository}], tmp_path, timeout=0.05)

    assert not dest.exists()


async def test_zero_timeout_waits_indefinitely(tmp_path: pathlib.Path, spawner):
    """``--timeout 0`` restores the old unbounded behaviour."""
    spawner(FakeProc(returncode=0))
    rows = [{'Repository': 'https://github.com/canonical/foo'}]

    await asyncio.wait_for(get_charms.process_rows(rows, tmp_path, timeout=0), timeout=5)


# ---- _default_source --------------------------------------------------------


def test_default_source_prefers_cwd_charms_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'charms.csv').touch()
    (tmp_path / 'charm-list').mkdir()
    (tmp_path / 'charm-list' / 'charms.csv').touch()
    assert get_charms.find_default_source() == pathlib.Path('charms.csv')


def test_default_source_falls_back_to_charm_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'charm-list').mkdir()
    (tmp_path / 'charm-list' / 'charms.csv').touch()
    assert get_charms.find_default_source() == pathlib.Path('charm-list/charms.csv')


def test_default_source_returns_none_when_none_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_charms.find_default_source() is None


# ---- get-charms CLI ---------------------------------------------------------


def test_get_charms_reports_error_when_csv_missing(tmp_path: pathlib.Path):
    missing = tmp_path / 'does-not-exist.csv'
    rc = _run_get_charms(['--source', str(missing), '--dest', str(tmp_path / 'c')])
    assert isinstance(rc, str)
    assert 'not found' in rc


def test_get_charms_creates_dest_and_drives_clone(tmp_path: pathlib.Path, spawner):
    csv_path = tmp_path / 'charms.csv'
    csv_path.write_text(
        'Charm Name,Repository,Branch (if not the default)\n'
        'foo,https://github.com/canonical/foo,\n',
        encoding='utf-8',
    )
    dest = tmp_path / 'dest'
    fake = spawner(FakeProc(returncode=0))

    rc = _run_get_charms(['--source', str(csv_path), '--dest', str(dest)])

    assert rc == 0
    assert dest.is_dir()
    argv, _ = fake.calls[0]
    assert argv[:2] == ('git', 'clone')
