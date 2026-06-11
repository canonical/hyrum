"""Tests for hyrum.get_charms."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import pathlib

import pytest
from click import testing

from hyrum import get_charms


@dataclasses.dataclass
class FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process for git operations."""

    returncode: int = 0

    async def wait(self) -> int:
        return self.returncode


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


# ---- repository_url ---------------------------------------------------------


def test_repository_url_strips_trailing_slash():
    assert (
        get_charms.repository_url('https://github.com/canonical/foo/', use_ssh=False)
        == 'https://github.com/canonical/foo'
    )


def test_repository_url_swaps_github_to_ssh():
    assert (
        get_charms.repository_url('https://github.com/canonical/foo', use_ssh=True)
        == 'git@github.com:canonical/foo'
    )


def test_repository_url_leaves_non_github_alone_with_ssh():
    # SSH swap should only fire for github.com URLs.
    assert (
        get_charms.repository_url('https://opendev.org/openstack/charm-aodh', use_ssh=True)
        == 'https://opendev.org/openstack/charm-aodh'
    )


def test_repository_url_passthrough_when_https():
    assert (
        get_charms.repository_url('https://github.com/canonical/foo', use_ssh=False)
        == 'https://github.com/canonical/foo'
    )


# ---- repo_folder ------------------------------------------------------------


def test_repo_folder_uses_basename_when_no_branch(tmp_path: pathlib.Path):
    assert (
        get_charms.repo_folder(tmp_path, 'https://github.com/canonical/foo', None)
        == tmp_path / 'foo'
    )


def test_repo_folder_appends_branch_suffix(tmp_path: pathlib.Path):
    assert (
        get_charms.repo_folder(tmp_path, 'https://github.com/canonical/foo', '24.04')
        == tmp_path / 'foo-24.04'
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
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)

    assert len(fake.calls) == 1
    argv, cwd = fake.calls[0]
    assert argv[0:2] == ('git', 'clone')
    assert 'https://github.com/canonical/foo' in argv
    assert pathlib.Path(cwd) == tmp_path


async def test_process_rows_pulls_existing_destination(tmp_path: pathlib.Path, spawner):
    (tmp_path / 'foo').mkdir()
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)

    assert len(fake.calls) == 1
    argv, cwd = fake.calls[0]
    assert argv[0:2] == ('git', 'pull')
    assert pathlib.Path(cwd) == (tmp_path / 'foo').resolve()


async def test_process_rows_includes_branch_flag_in_clone(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '24.04',
        }
    ]
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)

    argv, _ = fake.calls[0]
    assert '--branch' in argv
    assert argv[argv.index('--branch') + 1] == '24.04'
    # Branch is also reflected in the destination path.
    assert argv[-1] == str((tmp_path / 'foo-24.04').resolve())


async def test_process_rows_skips_rows_without_repository(tmp_path: pathlib.Path, spawner):
    # No procs queued: any subprocess call would fail the FakeSpawner assertion.
    spawner()
    rows = [
        {'Charm Name': '', 'Repository': '', 'Branch (if not the default)': ''},
        {'Charm Name': 'header-only', 'Repository': '', 'Branch (if not the default)': ''},
    ]
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)


async def test_process_rows_uses_ssh_url_when_requested(tmp_path: pathlib.Path, spawner):
    fake = spawner(FakeProc(returncode=0))
    rows = [
        {
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    await get_charms.process_rows(rows, tmp_path, use_ssh=True)

    argv, _ = fake.calls[0]
    assert 'git@github.com:canonical/foo' in argv
    # The HTTPS form must not also be present.
    assert 'https://github.com/canonical/foo' not in argv


async def test_process_rows_handles_missing_branch_column(tmp_path: pathlib.Path, spawner):
    """A CSV without the Branch column shouldn't crash."""
    fake = spawner(FakeProc(returncode=0))
    rows = [{'Charm Name': 'foo', 'Repository': 'https://github.com/canonical/foo'}]
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)

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
    await get_charms.process_rows(rows, tmp_path, use_ssh=False)

    argv, _ = fake.calls[0]
    # The destination is named after the repo basename, not "" from a trailing slash.
    assert argv[-1] == str((tmp_path / 'foo').resolve())


async def test_process_rows_logs_error_on_clone_failure(tmp_path: pathlib.Path, spawner, caplog):
    spawner(FakeProc(returncode=128))
    rows = [
        {
            'Charm Name': 'foo',
            'Repository': 'https://github.com/canonical/foo',
            'Branch (if not the default)': '',
        }
    ]
    with caplog.at_level(logging.ERROR, logger=get_charms.logger.name):
        await get_charms.process_rows(rows, tmp_path, use_ssh=False)
    assert any('Could not clone foo' in r.message for r in caplog.records)


# ---- get-charms CLI ---------------------------------------------------------


def test_get_charms_reports_error_when_csv_missing(tmp_path: pathlib.Path):
    missing = tmp_path / 'does-not-exist.csv'
    result = testing.CliRunner().invoke(
        get_charms.get_charms,
        ['--source', str(missing), '--cache-folder', str(tmp_path / 'c')],
    )
    assert result.exit_code != 0
    assert 'not found' in result.output


def test_get_charms_creates_cache_folder_and_drives_clone(tmp_path: pathlib.Path, spawner):
    csv_path = tmp_path / 'charms.csv'
    csv_path.write_text(
        'Charm Name,Repository,Branch (if not the default)\n'
        'foo,https://github.com/canonical/foo,\n',
        encoding='utf-8',
    )
    cache = tmp_path / 'cache'
    fake = spawner(FakeProc(returncode=0))

    result = testing.CliRunner().invoke(
        get_charms.get_charms,
        ['--source', str(csv_path), '--cache-folder', str(cache)],
    )

    assert result.exit_code == 0, result.output
    assert cache.is_dir()
    argv, _ = fake.calls[0]
    assert argv[:2] == ('git', 'clone')
