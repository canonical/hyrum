from __future__ import annotations

import os
import pathlib

import pytest
from click import testing

from hyrum import cli, runners
from hyrum.runners import tox

from .conftest import make_charm


@pytest.mark.parametrize(
    ('arg', 'expected'),
    [
        # GitHub owner:branch shorthand.
        (
            'tonyandrewmeyer:docs-debug-k8s',
            {
                'url': 'https://github.com/tonyandrewmeyer/operator',
                'branch': 'docs-debug-k8s',
            },
        ),
        (
            'owner:feature/my-branch',
            {'url': 'https://github.com/owner/operator', 'branch': 'feature/my-branch'},
        ),
        # Bare URL.
        (
            'https://github.com/canonical/operator',
            {'url': 'https://github.com/canonical/operator', 'branch': None},
        ),
        # URL with explicit branch.
        (
            'https://github.com/canonical/operator@main',
            {'url': 'https://github.com/canonical/operator', 'branch': 'main'},
        ),
        # `git+` prefix is accepted and stripped (so users can paste the
        # form pip / uv prints verbatim).
        (
            'git+https://github.com/canonical/operator@fix/X',
            {'url': 'https://github.com/canonical/operator', 'branch': 'fix/X'},
        ),
        (
            'git+https://github.com/canonical/operator',
            {'url': 'https://github.com/canonical/operator', 'branch': None},
        ),
        # PyPI version specifiers.
        ('2.17.0', {'version': '2.17.0'}),
        ('2.17', {'version': '2.17'}),
    ],
)
def test_parse_ops_source(arg: str, expected: dict[str, str | None]):
    assert cli._parse_ops_source(arg) == expected


def test_parse_ops_source_file_url(tmp_path: pathlib.Path):
    parsed = cli._parse_ops_source(f'file://{tmp_path}')
    assert parsed == {'path': str(tmp_path)}


def test_parse_ops_source_bare_path(tmp_path: pathlib.Path):
    parsed = cli._parse_ops_source(str(tmp_path))
    assert parsed == {'path': str(tmp_path)}


def test_parse_ops_source_home_path(monkeypatch, tmp_path: pathlib.Path):
    monkeypatch.setenv('HOME', str(tmp_path))
    parsed = cli._parse_ops_source('~/operator')
    assert parsed == {'path': str(tmp_path / 'operator')}


def test_parse_ops_source_rejects_garbage():
    with pytest.raises(Exception, match='cannot parse'):
        cli._parse_ops_source('definitely not a version or url')


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
            'check',
            'unit',
            '--charms-dir',
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
            'check',
            'unit',
            '--charms-dir',
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
            'check',
            'unit',
            '--charms-dir',
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
        ['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet'],
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
        ['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet'],
    )
    assert result.exit_code == 1
    assert 'did not pass' in result.stderr


def test_cli_verbosity_flags_are_mutually_exclusive(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    result = testing.CliRunner().invoke(
        cli.main,
        ['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet', '--verbose'],
    )
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output


def test_apply_host_env_defaults_sets_pyo3_and_tox_override():
    env: dict[str, str] = {}
    cli._apply_host_env_defaults('unit', env)
    assert env['PYO3_USE_ABI3_FORWARD_COMPATIBILITY'] == '1'
    assert 'testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY' in env['TOX_OVERRIDE']


def test_apply_host_env_defaults_respects_existing_values():
    env: dict[str, str] = {'PYO3_USE_ABI3_FORWARD_COMPATIBILITY': '0'}
    cli._apply_host_env_defaults('unit', env)
    assert env['PYO3_USE_ABI3_FORWARD_COMPATIBILITY'] == '0'


def test_apply_host_env_defaults_appends_to_existing_tox_override():
    env: dict[str, str] = {'TOX_OVERRIDE': 'testenv.set_env+=FOO=bar'}
    cli._apply_host_env_defaults('lint', env)
    # ';' is tox's documented TOX_OVERRIDE entry separator (tox splits on it);
    # newlines would be folded into the preceding override's value.
    assert env['TOX_OVERRIDE'] == (
        'testenv.set_env+=FOO=bar;testenv:lint.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
    )


def test_apply_host_env_defaults_uses_target_in_override():
    env: dict[str, str] = {}
    cli._apply_host_env_defaults('static', env)
    assert 'testenv:static.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY' in env['TOX_OVERRIDE']


def test_cli_no_host_env_defaults_leaves_env_alone(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.delenv('PYO3_USE_ABI3_FORWARD_COMPATIBILITY', raising=False)
    monkeypatch.delenv('TOX_OVERRIDE', raising=False)

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
            'check',
            'unit',
            '--charms-dir',
            str(cache),
            '--no-patch',
            '--no-host-env-defaults',
        ],
    )
    assert result.exit_code == 0, result.output
    assert 'PYO3_USE_ABI3_FORWARD_COMPATIBILITY' not in os.environ
    assert 'TOX_OVERRIDE' not in os.environ
