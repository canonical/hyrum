from __future__ import annotations

import os
import pathlib

import pytest

from hyrum import _cli as cli
from hyrum import _runners as runners
from hyrum._runners import tox

from .conftest import make_charm


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


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


@pytest.mark.parametrize(
    ('arg', 'expected'),
    [
        (
            'requests==2.31.0',
            {'pkg_name': 'requests', 'version': '==2.31.0'},
        ),
        (
            'requests>=1.2,<2',
            {'pkg_name': 'requests', 'version': '<2,>=1.2'},
        ),
        (
            'requests @ git+https://github.com/psf/requests@main',
            {
                'pkg_name': 'requests',
                'url': 'https://github.com/psf/requests',
                'branch': 'main',
            },
        ),
        (
            'requests @ git+https://github.com/psf/requests',
            {
                'pkg_name': 'requests',
                'url': 'https://github.com/psf/requests',
                'branch': None,
            },
        ),
        (
            'mylib @ git+https://example.com/repo@dev#subdirectory=pkg',
            {
                'pkg_name': 'mylib',
                'url': 'https://example.com/repo',
                'branch': 'dev',
                'subdir': 'pkg',
            },
        ),
    ],
)
def test_parse_dep_source(arg: str, expected: dict[str, str | None]):
    assert cli._parse_dep_source(arg) == expected


def test_parse_dep_source_file_url(tmp_path: pathlib.Path):
    parsed = cli._parse_dep_source(f'mylib @ file://{tmp_path}')
    assert parsed == {'pkg_name': 'mylib', 'path': str(tmp_path)}


def test_parse_dep_source_rejects_bare_name():
    with pytest.raises(Exception, match='must include a version specifier'):
        cli._parse_dep_source('requests')


def test_parse_dep_source_rejects_unknown_url_scheme():
    with pytest.raises(Exception, match='unsupported URL scheme'):
        cli._parse_dep_source('requests @ https://example.com/repo')


def test_parse_dep_source_rejects_garbage():
    with pytest.raises(Exception, match='cannot parse'):
        cli._parse_dep_source('!!! not a requirement')


def test_cli_end_to_end_with_stubbed_runner(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    """Drives the full CLI: enumerate -> patch -> stub runner -> render."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    make_charm(cache / 'beta', requirements=True)

    async def fake_run(self, repo, target):  # noqa: RUF029
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',  # skip the real patcher to keep this unit-test pure
        '--workers',
        '2',
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.out + captured.err
    assert 'passed' in captured.out


async def _fail_run(self, repo, target):  # noqa: RUF029
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

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch'])
    assert rc == 1


def test_cli_no_fail_forces_exit_zero(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.setattr(tox.ToxRunner, 'run', _fail_run)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--no-fail'])
    assert rc == 0


def test_cli_quiet_suppresses_report(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
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

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet'])
    captured = capsys.readouterr()
    assert rc == 0
    assert 'passed' not in captured.out
    assert 'hyrum:' not in captured.out


def test_cli_quiet_reports_failure_to_stderr(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    monkeypatch.setattr(tox.ToxRunner, 'run', _fail_run)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet'])
    captured = capsys.readouterr()
    assert rc == 1
    assert 'did not pass' in captured.err


def test_cli_verbosity_flags_are_mutually_exclusive(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--quiet',
        '--verbose',
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert 'not allowed with argument' in captured.err


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

    async def fake_run(self, repo, target):  # noqa: RUF029
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--no-host-env-defaults',
    ])
    assert rc == 0
    assert 'PYO3_USE_ABI3_FORWARD_COMPATIBILITY' not in os.environ
    assert 'TOX_OVERRIDE' not in os.environ
