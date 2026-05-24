from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hyrum.cli import main


def _make_charm(root: Path, *, tox: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text('type: charm\n')
    if tox:
        (root / 'tox.ini').write_text('[tox]\nenvlist = unit\n')
    (root / 'requirements.txt').write_text('ops>=2.10\n')
    return root


def test_cli_end_to_end_with_stubbed_runner(monkeypatch, tmp_path: Path):
    """Drives the full CLI: enumerate -> patch -> stub runner -> render."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    _make_charm(cache / 'alpha')
    _make_charm(cache / 'beta')

    # Stub the actual subprocess so we don't shell out to tox.
    from hyrum.runners import RunResult, RunStatus
    from hyrum.runners import tox as tox_mod

    async def fake_run(self, repo, target):  # noqa: RUF029 — async to satisfy Runner protocol
        return RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox_mod.ToxRunner, 'run', fake_run)

    result = CliRunner().invoke(
        main,
        [
            '--cache-folder',
            str(cache),
            '--target',
            'unit',
            '--no-patch',  # skip the real patcher to keep this unit-test pure
            '--workers',
            '2',
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'passed' in result.output


def test_cli_fail_on_regression_exits_nonzero(monkeypatch, tmp_path: Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    _make_charm(cache / 'alpha')

    from hyrum.runners import RunResult, RunStatus
    from hyrum.runners import tox as tox_mod

    async def fake_run(self, repo, target):  # noqa: RUF029 — async to satisfy Runner protocol
        return RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=RunStatus.FAILED,
            returncode=1,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox_mod.ToxRunner, 'run', fake_run)

    result = CliRunner().invoke(
        main,
        [
            '--cache-folder',
            str(cache),
            '--target',
            'unit',
            '--no-patch',
            '--fail-on-regression',
        ],
    )
    assert result.exit_code == 1, result.output
