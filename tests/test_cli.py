from __future__ import annotations

import pathlib

from click import testing

from hyrum import cli, runners
from hyrum.runners import tox

from .conftest import make_charm


def test_cli_end_to_end_with_stubbed_runner(monkeypatch, tmp_path: pathlib.Path):
    """Drives the full CLI: enumerate -> patch -> stub runner -> render."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    make_charm(cache / 'beta', requirements=True)

    async def fake_run(self, repo, target):  # noqa: RUF029 — async to satisfy Runner protocol
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)

    result = testing.CliRunner().invoke(
        cli.main,
        [
            'unit',
            '--cache-folder',
            str(cache),
            '--no-patch',  # skip the real patcher to keep this unit-test pure
            '--workers',
            '2',
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'passed' in result.output


async def _fail_run(self, repo, target):  # noqa: RUF029 — async to satisfy Runner protocol
    return runners.RunResult(
        repo=repo,
        runner=self.name,
        target=target,
        status=runners.RunStatus.FAILED,
        returncode=1,
        duration_s=0.01,
    )


def test_cli_exits_nonzero_by_default_on_failure(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.setattr(tox.ToxRunner, 'run', _fail_run)

    result = testing.CliRunner().invoke(
        cli.main,
        [
            'unit',
            '--cache-folder',
            str(cache),
            '--no-patch',
        ],
    )
    assert result.exit_code == 1, result.output


def test_cli_no_fail_forces_exit_zero(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.setattr(tox.ToxRunner, 'run', _fail_run)

    result = testing.CliRunner().invoke(
        cli.main,
        [
            'unit',
            '--cache-folder',
            str(cache),
            '--no-patch',
            '--no-fail',
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_quiet_suppresses_report(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    async def pass_run(self, repo, target):  # noqa: RUF029
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', pass_run)

    result = testing.CliRunner().invoke(
        cli.main,
        ['unit', '--cache-folder', str(cache), '--no-patch', '--quiet'],
    )
    assert result.exit_code == 0, result.output
    assert 'passed' not in result.output
    assert 'hyrum:' not in result.output


def test_cli_quiet_reports_failure_to_stderr(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.setattr(tox.ToxRunner, 'run', _fail_run)

    result = testing.CliRunner().invoke(
        cli.main,
        ['unit', '--cache-folder', str(cache), '--no-patch', '--quiet'],
    )
    assert result.exit_code == 1
    assert 'did not pass' in result.stderr


def test_cli_verbosity_flags_are_mutually_exclusive(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    result = testing.CliRunner().invoke(
        cli.main,
        ['unit', '--cache-folder', str(cache), '--no-patch', '--quiet', '--verbose'],
    )
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output
