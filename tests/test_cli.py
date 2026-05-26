from __future__ import annotations

import pathlib

from click import testing

from hyrum import cli, runners
from hyrum.runners import tox


def _make_charm(root: pathlib.Path, *, tox_ini: bool = True) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text('type: charm\n')
    if tox_ini:
        (root / 'tox.ini').write_text('[tox]\nenvlist = unit\n')
    (root / 'requirements.txt').write_text('ops>=2.10\n')
    return root


def test_cli_end_to_end_with_stubbed_runner(monkeypatch, tmp_path: pathlib.Path):
    """Drives the full CLI: enumerate -> patch -> stub runner -> render."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    _make_charm(cache / 'alpha')
    _make_charm(cache / 'beta')

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
    _make_charm(cache / 'alpha')

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
    _make_charm(cache / 'alpha')

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
    _make_charm(cache / 'alpha')

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
    _make_charm(cache / 'alpha')

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
    _make_charm(cache / 'alpha')

    result = testing.CliRunner().invoke(
        cli.main,
        ['unit', '--cache-folder', str(cache), '--no-patch', '--quiet', '--verbose'],
    )
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output
