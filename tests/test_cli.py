from __future__ import annotations

import os
import pathlib
import sys

import pytest

from hyrum import _cli as cli
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


def test_cli_save_writes_json(monkeypatch, tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    make_charm(cache / 'alpha', requirements=True)

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

    async def fake_run(self, repo, target):  # noqa: RUF029 — async to satisfy Runner protocol
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
    assert rc != 0
    assert 'schema version' in captured.err
