from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] — the git ls-remote preflight is what's under test
import sys

import pytest

from hyrum import _cli as cli
from hyrum import _compare as compare
from hyrum import _config as config_loader
from hyrum import _pool as pool
from hyrum import _results as results
from hyrum import _runners as runners
from hyrum._runners import tox

from .conftest import make_charm


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        # Mimic the interpreter: a string exit code is printed and exits 1.
        print(exc.code, file=sys.stderr)
        return 1
    return 0


@pytest.fixture(autouse=True)
def runners_installed(monkeypatch):
    """Let the runner preflight find tox and make, whatever the host has.

    Without this the suite's result would depend on what happens to be on the
    developer's PATH. Tests that exercise the preflight itself override it.
    """
    monkeypatch.setattr(shutil, 'which', lambda program: f'/usr/bin/{program}')


@pytest.mark.parametrize(
    ('arg', 'expected'),
    [
        # Ops-only owner:branch shorthand.
        (
            'ops @ tonyandrewmeyer:docs-debug-k8s',
            cli.PatchSpec(
                pkg_name='ops',
                url='https://github.com/tonyandrewmeyer/operator',
                branch='docs-debug-k8s',
            ),
        ),
        (
            'ops @ owner:feature/my-branch',
            cli.PatchSpec(
                pkg_name='ops',
                url='https://github.com/owner/operator',
                branch='feature/my-branch',
            ),
        ),
        # Bare URL.
        (
            'ops @ https://github.com/canonical/operator',
            cli.PatchSpec(pkg_name='ops', url='https://github.com/canonical/operator'),
        ),
        # URL with explicit branch.
        (
            'ops @ https://github.com/canonical/operator@main',
            cli.PatchSpec(
                pkg_name='ops',
                url='https://github.com/canonical/operator',
                branch='main',
            ),
        ),
        # `git+` prefix (the form pip / uv prints verbatim).
        (
            'ops @ git+https://github.com/canonical/operator@fix/X',
            cli.PatchSpec(
                pkg_name='ops',
                url='https://github.com/canonical/operator',
                branch='fix/X',
            ),
        ),
        (
            'ops @ git+https://github.com/canonical/operator',
            cli.PatchSpec(pkg_name='ops', url='https://github.com/canonical/operator'),
        ),
        # PyPI version specifiers.
        ('ops==2.17.0', cli.PatchSpec(pkg_name='ops', version='==2.17.0')),
        (
            'requests>=1.2,<2',
            cli.PatchSpec(pkg_name='requests', version='<2,>=1.2'),
        ),
        # Non-ops git source.
        (
            'requests @ git+https://github.com/psf/requests@main',
            cli.PatchSpec(
                pkg_name='requests',
                url='https://github.com/psf/requests',
                branch='main',
            ),
        ),
        # Subdirectory.
        (
            'mylib @ git+https://example.com/repo@dev#subdirectory=pkg',
            cli.PatchSpec(
                pkg_name='mylib',
                url='https://example.com/repo',
                branch='dev',
                subdir='pkg',
            ),
        ),
        # Non-ops bare URL with branch.
        (
            'requests @ https://example.com/repo@dev',
            cli.PatchSpec(
                pkg_name='requests',
                url='https://example.com/repo',
                branch='dev',
            ),
        ),
    ],
)
def test_parse_patch(arg: str, expected: cli.PatchSpec):
    assert cli._parse_patch(arg) == expected


def test_parse_patch_file_url(tmp_path: pathlib.Path):
    parsed = cli._parse_patch(f'mylib @ file://{tmp_path}')
    assert parsed == cli.PatchSpec(pkg_name='mylib', path=str(tmp_path))


def test_parse_patch_bare_path(tmp_path: pathlib.Path):
    parsed = cli._parse_patch(f'ops @ {tmp_path}')
    assert parsed == cli.PatchSpec(pkg_name='ops', path=str(tmp_path))


def test_parse_patch_home_path(monkeypatch, tmp_path: pathlib.Path):
    monkeypatch.setenv('HOME', str(tmp_path))
    parsed = cli._parse_patch('ops @ ~/operator')
    assert parsed == cli.PatchSpec(pkg_name='ops', path=str(tmp_path / 'operator'))


def test_parse_patch_rejects_bare_name():
    with pytest.raises(Exception, match='must include a version specifier'):
        cli._parse_patch('requests')


def test_parse_patch_rejects_shorthand_for_non_ops():
    with pytest.raises(Exception, match='only supported for'):
        cli._parse_patch('requests @ psf:main')


def test_parse_patch_rejects_garbage():
    with pytest.raises(Exception, match='cannot parse'):
        cli._parse_patch('!!! not a requirement')


# ``--patch ops==2.17.0`` used to reach ``OpsSource`` with the operator still
# attached and come out as ``ops====2.17.0``; check the whole path, not just
# the parse.


@pytest.mark.parametrize(
    ('arg', 'expected'),
    [
        ('ops==2.17.0', 'ops==2.17.0'),
        ('ops>=2.17', 'ops>=2.17'),
        ('ops>=2,<3', 'ops<3,>=2'),
    ],
)
def test_ops_pypi_patch_renders_one_operator(arg: str, expected: str):
    spec = cli._parse_patch(arg)
    patcher = cli._build_ops_patcher(
        spec,
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=1,
        auto_python=False,
    )
    assert patcher.ops.pep508_dep('ops') == expected


def test_parse_patch_vendored_swap_pypi():
    parsed = cli._parse_patch('charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0')
    assert parsed == cli.PatchSpec(
        pkg_name='charms.operator_libs_linux.v0.apt',
        vendored_author='operator_libs_linux',
        vendored_version='0',
        vendored_lib='apt',
        vendored_pkg='charmlibs-apt',
        version='==1.0.0',
    )


def test_parse_patch_vendored_swap_git_with_subdir():
    parsed = cli._parse_patch(
        'charms.operator_libs_linux.v0.apt -> '
        'charmlibs-apt @ git+https://github.com/canonical/charmlibs@main#subdirectory=apt'
    )
    assert parsed == cli.PatchSpec(
        pkg_name='charms.operator_libs_linux.v0.apt',
        vendored_author='operator_libs_linux',
        vendored_version='0',
        vendored_lib='apt',
        vendored_pkg='charmlibs-apt',
        url='https://github.com/canonical/charmlibs',
        branch='main',
        subdir='apt',
    )


def test_parse_patch_vendored_rejects_bad_lhs():
    with pytest.raises(Exception, match='vendored dotted form'):
        cli._parse_patch('requests -> charmlibs-apt==1.0.0')


def test_build_patcher_vendored_swap():
    from hyrum import _patchers as patchers

    patcher = cli._build_patcher(
        patches=[
            cli._parse_patch('charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0'),
        ],
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=60,
        auto_python=True,
    )
    assert isinstance(patcher, patchers.VendoredLibPatcher)
    assert patcher.swap.host_charm == 'operator_libs_linux'
    assert patcher.swap.version == 0
    assert patcher.swap.lib_name == 'apt'
    assert patcher.swap.source.pkg_name == 'charmlibs-apt'
    assert patcher.swap.source.version == '==1.0.0'


def test_build_patcher_default_patches_ops():
    """The default ops patch spec builds an OpsSourcePatcher targeting canonical:main."""
    from hyrum import _patchers as patchers

    patcher = cli._build_patcher(
        patches=[cli._DEFAULT_OPS_PATCH],
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=60,
        auto_python=True,
    )
    assert isinstance(patcher, patchers.OpsSourcePatcher)
    assert patcher.ops.url == 'https://github.com/canonical/operator'
    assert patcher.ops.branch == 'main'


def test_build_patcher_empty_patches_returns_null():
    """Empty patch list (e.g. from --no-patch) returns NullPatcher."""
    from hyrum import _patchers as patchers

    patcher = cli._build_patcher(
        patches=[],
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=60,
        auto_python=True,
    )
    assert isinstance(patcher, patchers.NullPatcher)


def test_build_patcher_explicit_patch_does_not_also_patch_ops():
    """--patch for a non-ops package should not implicitly add an ops patcher."""
    from hyrum import _patchers as patchers

    patcher = cli._build_patcher(
        patches=[cli.PatchSpec(pkg_name='requests', version='==2.31.0')],
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=60,
        auto_python=True,
    )
    assert isinstance(patcher, patchers.GenericDepPatcher)
    assert patcher.source.pkg_name == 'requests'


def test_build_patcher_ops_plus_other_stacks():
    from hyrum import _patchers as patchers

    patcher = cli._build_patcher(
        patches=[
            cli.PatchSpec(pkg_name='ops', url='https://github.com/canonical/operator', branch='x'),
            cli.PatchSpec(pkg_name='requests', version='==2.31.0'),
        ],
        poetry_executable='poetry',
        uv_executable='uv',
        lock_timeout=60,
        auto_python=True,
    )
    assert isinstance(patcher, patchers.PatcherStack)


def test_cli_end_to_end_with_stubbed_runner(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    """Drives the full CLI: enumerate -> patch -> stub runner -> render."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    make_charm(cache / 'beta', requirements=True)

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async]
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


async def _fail_run(self, repo, target):  # ruff: ignore[unused-async]
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

    async def pass_run(self, repo, target):  # ruff: ignore[unused-async]
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

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async]
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


def test_cli_save_writes_json(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async] — async to satisfy Runner protocol
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)
    out = tmp_path / 'run.json'

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--save',
        str(out),
    ])
    assert rc == 0
    assert out.exists()

    loaded = results.load(out)
    assert any(o.status == 'passed' for o in loaded.outcomes)
    # Identities are stored relative to the charms dir, not as raw cache paths.
    assert all(not o.repo.is_absolute() for o in loaded.outcomes)
    assert loaded.meta.target == 'unit'


def test_cli_save_bad_directory_fails_before_running(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    calls: list[str] = []

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async] — async to satisfy Runner protocol
        calls.append(str(repo))
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
        '--save',
        str(tmp_path / 'missing-dir' / 'out.json'),
    ])
    captured = capsys.readouterr()
    assert rc != 0
    assert 'does not exist' in captured.err
    assert calls == []  # failed before any charm ran


def test_cli_save_failure_still_renders_report(
    monkeypatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async] — async to satisfy Runner protocol
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)

    def failing_save(*args: object, **kwargs: object) -> None:
        raise OSError('disk full')

    monkeypatch.setattr(results, 'save', failing_save)

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--save',
        str(tmp_path / 'out.json'),
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert 'hyrum: unit' in captured.out  # the report still rendered


def _fake_pass_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(self, repo, target):  # ruff: ignore[unused-async]
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=runners.RunStatus.PASSED,
            returncode=0,
            duration_s=0.01,
        )

    monkeypatch.setattr(tox.ToxRunner, 'run', fake_run)


def test_cli_save_to_existing_directory_writes_timestamped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    out_dir = tmp_path / 'runs'
    out_dir.mkdir()

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--save', str(out_dir)])
    assert rc == 0
    written = list(out_dir.glob('hyrum-*-unit.json'))
    assert len(written) == 1


def test_cli_auto_save_rotates_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    save_dir = tmp_path / 'auto'

    for _ in range(2):
        rc = _run([
            'check',
            'unit',
            '--charms-dir',
            str(cache),
            '--no-patch',
            '--auto-save',
            str(save_dir),
        ])
        assert rc == 0
    assert (save_dir / 'unit.auto.json').exists()
    assert (save_dir / 'unit.auto.prev.json').exists()


def test_cli_no_save_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--no-save'])
    assert rc == 0
    assert not default_dir.exists() or list(default_dir.iterdir()) == []


def test_cli_default_is_auto_save(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch'])
    assert rc == 0
    assert (default_dir / 'unit.auto.json').exists()


def test_cli_reports_default_auto_save_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch'])
    assert rc == 0
    captured = capsys.readouterr()
    assert f'Saved 1 result to {default_dir / "unit.auto.json"}' in captured.err


def test_cli_reports_explicit_save_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    out = tmp_path / 'run.json'

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--save', str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    assert f'Saved 1 result to {out}' in captured.err


def test_cli_reports_auto_save_dir_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    save_dir = tmp_path / 'auto'

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--auto-save',
        str(save_dir),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert f'Saved 1 result to {save_dir / "unit.auto.json"}' in captured.err


def test_cli_reports_timestamped_save_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    out_dir = tmp_path / 'runs'
    out_dir.mkdir()

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--save', str(out_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    written = next(iter(out_dir.glob('hyrum-*-unit.json')))
    assert f'Saved 1 result to {written}' in captured.err


def test_cli_no_save_reports_no_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--no-save'])
    assert rc == 0
    captured = capsys.readouterr()
    assert 'Saved' not in captured.err


def test_cli_quiet_does_not_report_destinations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--quiet'])
    assert rc == 0
    captured = capsys.readouterr()
    assert 'Saved' not in captured.err


def test_cli_reports_log_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    log_dir = tmp_path / 'logs'

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--no-save',
        '--log-dir',
        str(log_dir),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert f'Per-charm logs saved to {log_dir}' in captured.err


def test_cli_does_not_report_log_dir_when_nothing_ran(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    log_dir = tmp_path / 'logs'

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--no-save',
        '--log-dir',
        str(log_dir),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert 'Per-charm logs saved to' not in captured.err


def test_cli_save_flags_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)

    rc = _run([
        'check',
        'unit',
        '--charms-dir',
        str(cache),
        '--no-patch',
        '--save',
        str(tmp_path / 'a.json'),
        '--no-save',
    ])
    assert rc != 0
    assert 'not allowed with' in capsys.readouterr().err


def test_cli_config_save_off_overrides_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)
    config = tmp_path / 'hyrum.toml'
    config.write_text('save = "off"\n')

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--config', str(config)])
    assert rc == 0
    assert not default_dir.exists()


def test_cli_config_save_table_sets_auto_save_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    _fake_pass_runner(monkeypatch)
    default_dir = tmp_path / 'default-auto'
    monkeypatch.setattr(cli, '_default_auto_save_dir', lambda: default_dir)
    save_dir = tmp_path / 'configured'
    config = tmp_path / 'hyrum.toml'
    config.write_text(f'[save]\nmode = "auto"\npath = "{save_dir}"\n')

    rc = _run(['check', 'unit', '--charms-dir', str(cache), '--no-patch', '--config', str(config)])
    assert rc == 0
    assert (save_dir / 'unit.auto.json').exists()
    assert not default_dir.exists()


def test_cli_compare_subcommand_clean(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    a = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='passed')]
    b = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='passed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(a, base_path)
    results.save(b, cur_path)

    rc = _run(['compare', str(base_path), str(cur_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert 'No changes' in captured.out


def test_cli_compare_fail_on_regression_exits_nonzero(tmp_path: pathlib.Path):
    base = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='passed')]
    cur = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='failed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path)
    results.save(cur, cur_path)

    rc = _run(['compare', str(base_path), str(cur_path), '--fail-on-regression'])
    assert rc == 1


def test_cli_compare_detects_regression_across_checkouts(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    """Same charms cached under different roots must still diff."""
    alice = pathlib.Path('/home/alice/.cache/hyrum/charms')
    ci = pathlib.Path('/github/workspace/cache')
    base = [pool.Outcome(repo=alice / 'canonical' / 'foo', status='passed')]
    cur = [pool.Outcome(repo=ci / 'canonical' / 'foo', status='failed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path, base=alice)
    results.save(cur, cur_path, base=ci)

    rc = _run(['compare', str(base_path), str(cur_path), '--fail-on-regression'])
    captured = capsys.readouterr()
    assert rc == 1
    assert 'canonical/foo' in captured.out
    assert 'NEW FAILURES' in captured.out


def test_cli_compare_warns_on_target_mismatch(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    outcomes = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(outcomes, base_path, target='lint')
    results.save(outcomes, cur_path, target='unit')

    rc = _run(['compare', str(base_path), str(cur_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert 'comparing different targets' in captured.err
    assert "'lint'" in captured.err
    assert "'unit'" in captured.err


def test_cli_compare_text_output_includes_run_headers(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    outcomes = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(outcomes, base_path, target='unit', patcher='ops @ x@main')
    results.save(outcomes, cur_path, target='unit', patcher='ops @ x@fix')

    rc = _run(['compare', str(base_path), str(cur_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert f'Baseline: {base_path}' in captured.out
    assert 'target unit' in captured.out
    assert 'patch ops @ x@fix' in captured.out


def test_cli_compare_markdown_title_includes_target(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    outcomes = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='failed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(outcomes, base_path, target='unit')
    results.save(outcomes, cur_path, target='unit')

    rc = _run(['compare', str(base_path), str(cur_path), '--format', 'markdown'])
    captured = capsys.readouterr()
    assert rc == 0
    assert '# hyrum run comparison (unit)' in captured.out


def test_cli_compare_rejects_bad_schema(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    base_path.write_text('{"version": 999, "outcomes": []}')
    cur_path.write_text('{"version": 1, "outcomes": []}')

    rc = _run(['compare', str(base_path), str(cur_path)])
    captured = capsys.readouterr()
    # 2 = bad input, distinct from 1 = the regression gate tripping.
    assert rc == 2
    assert 'schema version' in captured.err


def test_cli_compare_json_format(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    base = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    cur = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='failed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path, target='unit')
    results.save(cur, cur_path, target='unit')

    rc = _run(['compare', str(base_path), str(cur_path), '--format', 'json'])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload['baseline']['path'] == str(base_path)
    assert payload['current']['meta']['target'] == 'unit'
    assert payload['diff']['new_failures'] == ['canonical/foo']
    assert payload['version'] == compare.JSON_FORMAT_VERSION
    assert payload['diff']['disjoint'] is False


def test_cli_compare_disjoint_runs_warn_and_fail_the_gate(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    base = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    cur = [pool.Outcome(repo=pathlib.Path('canonical/bar'), status='passed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path)
    results.save(cur, cur_path)

    rc = _run(['compare', str(base_path), str(cur_path), '--fail-on-regression'])
    captured = capsys.readouterr()
    # Exiting 0 here would green-light a comparison that compared nothing.
    assert rc == 2
    assert 'no charms in common' in captured.err


def test_cli_compare_disjoint_runs_without_the_gate_still_warn_but_exit_zero(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    base = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    cur = [pool.Outcome(repo=pathlib.Path('canonical/bar'), status='passed')]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path)
    results.save(cur, cur_path)

    rc = _run(['compare', str(base_path), str(cur_path)])
    captured = capsys.readouterr()
    # Without the gate, compare only reports: the warning goes to stderr, but
    # exiting non-zero would break callers using it as a plain diff.
    assert rc == 0
    assert 'no charms in common' in captured.err


def test_cli_compare_new_charm_does_not_trip_the_gate(tmp_path: pathlib.Path):
    base = [pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed')]
    cur = [
        pool.Outcome(repo=pathlib.Path('canonical/foo'), status='passed'),
        pool.Outcome(repo=pathlib.Path('canonical/bar'), status='timeout'),
    ]
    base_path = tmp_path / 'a.json'
    cur_path = tmp_path / 'b.json'
    results.save(base, base_path)
    results.save(cur, cur_path)

    rc = _run(['compare', str(base_path), str(cur_path), '--fail-on-regression'])
    assert rc == 0


# ---- preflight: runner executables -------------------------------------------


def _installed(*programs: str):
    return lambda program: f'/usr/bin/{program}' if program in programs else None


def test_available_backends_drops_uninstalled_backend_under_auto(monkeypatch):
    # A fleet with no make-driven charms shouldn't need make installed, so the
    # missing backend is dropped rather than being fatal.
    monkeypatch.setattr(shutil, 'which', _installed('tox'))
    backends = cli._available_backends(
        runners.RunnerChoice.AUTO, tox_executable='tox', make_executable='make'
    )
    assert backends == ('tox',)


def test_available_backends_exits_when_explicit_choice_is_missing(monkeypatch):
    monkeypatch.setattr(shutil, 'which', _installed('tox'))
    with pytest.raises(SystemExit, match='make'):
        cli._available_backends(
            runners.RunnerChoice.MAKE, tox_executable='tox', make_executable='make'
        )


def test_available_backends_exits_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(shutil, 'which', _installed())
    with pytest.raises(SystemExit, match='no runner available'):
        cli._available_backends(
            runners.RunnerChoice.AUTO, tox_executable='tox', make_executable='make'
        )


def test_available_backends_checks_the_program_not_the_whole_command(monkeypatch):
    monkeypatch.setattr(shutil, 'which', _installed('uvx'))
    backends = cli._available_backends(
        runners.RunnerChoice.TOX, tox_executable='uvx tox', make_executable='make'
    )
    assert backends == ('tox',)


# ---- preflight: --patch git refs ---------------------------------------------

_URL = 'https://github.com/canonical/operator'


def _ls_remote(returncode: int, stderr: bytes = b''):
    """Stand in for ``git ls-remote --exit-code``; no network in the unit suite."""
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout=b'', stderr=stderr)

    fake_run.calls = calls
    return fake_run


def test_unresolvable_ref_accepts_a_ref_the_remote_has(monkeypatch):
    fake = _ls_remote(0)
    monkeypatch.setattr(subprocess, 'run', fake)
    assert cli._unresolvable_ref(_URL, 'main') is None
    assert fake.calls == [['git', 'ls-remote', '--exit-code', _URL, 'main']]


def test_unresolvable_ref_rejects_a_typo(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', _ls_remote(2))
    problem = cli._unresolvable_ref(_URL, 'this-branch-does-not-exist')
    assert problem is not None
    assert 'this-branch-does-not-exist' in problem


def test_unresolvable_ref_accepts_a_full_commit_sha(monkeypatch):
    # ls-remote can't see a bare commit, but git can still fetch it.
    monkeypatch.setattr(subprocess, 'run', _ls_remote(2))
    assert cli._unresolvable_ref(_URL, '75525780ea49e8db64d6716c94d02282d7b6ee81') is None


def test_unresolvable_ref_asks_for_the_full_sha_when_abbreviated(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', _ls_remote(2))
    problem = cli._unresolvable_ref(_URL, '7552578')
    assert problem is not None
    assert '40-character' in problem


def test_unresolvable_ref_does_not_block_on_a_remote_it_cannot_reach(monkeypatch):
    # A network or auth failure says nothing about whether the ref exists.
    monkeypatch.setattr(subprocess, 'run', _ls_remote(128, stderr=b'could not read from remote'))
    assert cli._unresolvable_ref(_URL, 'main') is None


def test_unresolvable_ref_does_not_block_when_git_is_missing(monkeypatch):
    def boom(argv, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', 'git')

    monkeypatch.setattr(subprocess, 'run', boom)
    assert cli._unresolvable_ref(_URL, 'main') is None


def test_preflight_patch_refs_checks_each_pair_once(monkeypatch):
    fake = _ls_remote(0)
    monkeypatch.setattr(subprocess, 'run', fake)
    cli._preflight_patch_refs([
        cli.PatchSpec(pkg_name='ops', url=_URL, branch='main'),
        cli.PatchSpec(pkg_name='other', url=_URL, branch='main'),
        cli.PatchSpec(pkg_name='local', path='/x'),
        cli.PatchSpec(pkg_name='pinned', version='==1.0'),
    ])
    assert len(fake.calls) == 1


def test_cli_preflight_rejects_an_unresolvable_ref(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    monkeypatch.setattr(subprocess, 'run', _ls_remote(2))

    # The whole point is that this happens before any charm is touched, so no
    # runner is stubbed here: reaching one would fail the test loudly.
    with pytest.raises(SystemExit, match='this-branch-does-not-exist'):
        cli.main([
            'check',
            'unit',
            '--charms-dir',
            str(cache),
            '--patch',
            'ops @ canonical:this-branch-does-not-exist',
        ])


def test_cli_no_preflight_skips_the_ref_check(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)
    fake = _ls_remote(2)
    monkeypatch.setattr(subprocess, 'run', fake)

    async def fake_run(self, repo, target):  # ruff: ignore[unused-async] — async to satisfy Runner protocol
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
        '--no-preflight',
    ])
    assert rc == 0
    assert fake.calls == []


# ---- --limit ----------------------------------------------------------------

# ``--limit`` used to cap enumeration, before the filter chain ran, so charms
# that were then skipped ate into the cap. The collection is alphabetical and
# opens on a run of legacy charms, so small limits selected nothing at all.


def _limit_cache(charm_cache: pathlib.Path) -> pathlib.Path:
    for name in ('a-legacy', 'b-legacy', 'c-modern', 'd-modern'):
        repo = make_charm(charm_cache / name)
        if name.endswith('-legacy'):
            (repo / 'reactive').mkdir()
    return charm_cache


def test_limit_counts_selected_charms_not_skipped_ones(charm_cache: pathlib.Path):
    repos, skipped = cli._select_repos(
        _limit_cache(charm_cache),
        config=config_loader.Config(),
        repo_re='.*',
        limit=1,
        framework=None,
    )
    assert [p.name for p in repos] == ['c-modern']
    # Charms passed over on the way to the cap still show up as skipped.
    assert [p.name for p, _ in skipped] == ['a-legacy', 'b-legacy']


def test_limit_stops_enumerating_once_it_is_reached(charm_cache: pathlib.Path):
    repos, skipped = cli._select_repos(
        _limit_cache(charm_cache),
        config=config_loader.Config(),
        repo_re='.*',
        limit=2,
        framework=None,
    )
    assert [p.name for p in repos] == ['c-modern', 'd-modern']
    assert [p.name for p, _ in skipped] == ['a-legacy', 'b-legacy']


def test_limit_zero_selects_everything(charm_cache: pathlib.Path):
    repos, _ = cli._select_repos(
        _limit_cache(charm_cache),
        config=config_loader.Config(),
        repo_re='.*',
        limit=0,
        framework=None,
    )
    assert [p.name for p in repos] == ['c-modern', 'd-modern']


def test_limit_above_the_number_available_selects_everything(charm_cache: pathlib.Path):
    repos, _ = cli._select_repos(
        _limit_cache(charm_cache),
        config=config_loader.Config(),
        repo_re='.*',
        limit=99,
        framework=None,
    )
    assert [p.name for p in repos] == ['c-modern', 'd-modern']


def _cache_with_artefacts(tmp_path: pathlib.Path) -> pathlib.Path:
    cache = tmp_path / 'charms'
    repo = cache / 'a-charm'
    (repo / '.git').mkdir(parents=True)
    (repo / 'charmcraft.yaml').write_text('type: charm\n')
    (repo / '.tox').mkdir()
    (repo / '.tox' / 'big').write_bytes(b'x' * 2048)
    return cache


def test_clean_removes_artefacts_and_reports_what_it_reclaimed(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    cache = _cache_with_artefacts(tmp_path)
    assert _run(['clean', '--charms-dir', str(cache)]) == 0
    assert 'Reclaimed 2.0 KiB from 1 artefact.' in capsys.readouterr().out
    assert not (cache / 'a-charm' / '.tox').exists()
    assert (cache / 'a-charm' / 'charmcraft.yaml').exists()


def test_clean_dry_run_removes_nothing(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    cache = _cache_with_artefacts(tmp_path)
    assert _run(['clean', '--charms-dir', str(cache), '--dry-run']) == 0
    assert 'Would reclaim 2.0 KiB from 1 artefact.' in capsys.readouterr().out
    assert (cache / 'a-charm' / '.tox' / 'big').exists()


def test_clean_on_a_missing_charms_dir_is_an_error(tmp_path: pathlib.Path):
    assert _run(['clean', '--charms-dir', str(tmp_path / 'nope')]) != 0
