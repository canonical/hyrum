"""Tests for hyrum.get_charms."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import pathlib

import click
import pytest
from click import testing

from hyrum import get_charms


@dataclasses.dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process for git operations."""

    returncode: int = 0
    stderr_bytes: bytes = b''

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b'', self.stderr_bytes


class FakeSpawner:
    """Records each create_subprocess_exec call and yields queued FakeProcs."""

    def __init__(self) -> None:
        self.procs: list[FakeProc] = []
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((tuple(args), str(kwargs.get('cwd'))))
        if not self.procs:
            raise AssertionError('FakeSpawner exhausted')
        return self.procs.pop(0)


@pytest.fixture
def spawner(monkeypatch):
    fake = FakeSpawner()
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
            'Charm Name': 'foo',
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
            'Charm Name': 'foo',
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
            'Charm Name': 'foo',
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
        {'Charm Name': '', 'Repository': '', 'Branch (if not the default)': ''},
        {'Charm Name': 'header-only', 'Repository': '', 'Branch (if not the default)': ''},
    ]
    with caplog.at_level(logging.WARNING, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert sum('Skipping row without Repository' in r.message for r in caplog.records) == 2


async def test_process_rows_handles_missing_branch_column(tmp_path: pathlib.Path, spawner):
    """A CSV without the Branch column shouldn't crash."""
    fake = spawner(FakeProc(returncode=0))
    rows = [{'Charm Name': 'foo', 'Repository': 'https://github.com/canonical/foo'}]
    await get_charms.process_rows(rows, tmp_path)

    argv, _ = fake.calls[0]
    assert '--branch' not in argv


async def test_process_rows_strips_trailing_slash_from_repository(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Charm Name': 'foo',
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
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    with caplog.at_level(logging.ERROR, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert any(
        'Could not clone foo' in r.message and 'fatal: remote not found' in r.message
        for r in caplog.records
    )
    # %r keeps the message on a single line.
    assert all('\n' not in r.message for r in caplog.records)


async def test_process_rows_logs_summary(tmp_path: pathlib.Path, spawner, caplog):
    spawner(FakeProc(returncode=0), FakeProc(returncode=128))
    rows = [
        {
            'Charm Name': 'good',
            'Repository': 'https://github.com/canonical/good',
            'Branch (if not the default)': '',
        },
        {
            'Charm Name': 'bad',
            'Repository': 'https://github.com/canonical/bad',
            'Branch (if not the default)': '',
        },
    ]
    with caplog.at_level(logging.INFO, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path)
    assert any('1 succeeded, 1 failed' in r.message for r in caplog.records)
    assert any('Failed: bad' in r.message for r in caplog.records)


# ---- _default_source --------------------------------------------------------


def test_default_source_prefers_cwd_charms_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'charms.csv').touch()
    (tmp_path / 'charm-list').mkdir()
    (tmp_path / 'charm-list' / 'charms.csv').touch()
    assert get_charms._default_source() == pathlib.Path('charms.csv')


def test_default_source_falls_back_to_charm_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'charm-list').mkdir()
    (tmp_path / 'charm-list' / 'charms.csv').touch()
    assert get_charms._default_source() == pathlib.Path('charm-list/charms.csv')


def test_default_source_raises_when_none_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(click.UsageError, match='No charm list at default locations'):
        get_charms._default_source()


# ---- get-charms CLI ---------------------------------------------------------


def test_get_charms_reports_error_when_csv_missing(tmp_path: pathlib.Path):
    missing = tmp_path / 'does-not-exist.csv'
    result = testing.CliRunner().invoke(
        get_charms.get_charms,
        ['--source', str(missing), '--dest', str(tmp_path / 'c')],
    )
    assert result.exit_code != 0
    assert 'not found' in result.output


def test_get_charms_creates_dest_and_drives_clone(tmp_path: pathlib.Path, spawner):
    csv_path = tmp_path / 'charms.csv'
    csv_path.write_text(
        'Charm Name,Repository,Branch (if not the default)\n'
        'foo,https://github.com/canonical/foo,\n',
        encoding='utf-8',
    )
    dest = tmp_path / 'dest'
    fake = spawner(FakeProc(returncode=0))

    result = testing.CliRunner().invoke(
        get_charms.get_charms,
        ['--source', str(csv_path), '--dest', str(dest)],
    )

    assert result.exit_code == 0, result.output
    assert dest.is_dir()
    argv, _ = fake.calls[0]
    assert argv[:2] == ('git', 'clone')
