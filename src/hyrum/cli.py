"""hyrum CLI."""

from __future__ import annotations

import asyncio
import datetime
import itertools
import logging
import os
import pathlib
import re
import sys

import click
import packaging.version
import rich.logging
import rich.text

import hyrum
from hyrum import config as config_loader
from hyrum import enumerate as enum_mod
from hyrum import filters as filt
from hyrum import frameworks, patchers, pool, report, runners
from hyrum.runners import make_runner, tox

logger = logging.getLogger('hyrum')


def _iso_utc(dt: datetime.datetime) -> rich.text.Text:
    return rich.text.Text(dt.astimezone(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'))


def _configure_logging(level: int) -> None:
    logging.basicConfig(
        level=level,
        format='%(message)s',
        handlers=[rich.logging.RichHandler(show_path=False, log_time_format=_iso_utc)],
    )


def _resolve_log_level(*, quiet: bool, verbose: bool, verbosity: str | None) -> int:
    if quiet:
        return logging.WARNING
    if verbosity in ('debug', 'trace'):
        return logging.DEBUG
    # Brief (default) and verbose both run at INFO; --verbose changes the report shape,
    # not the log level.
    return logging.INFO


# Environment variables hyrum sets by default to dodge well-known host build
# issues that aren't charm regressions. The README's host-prereqs section is
# the source of truth for why each one is here.
_HOST_ENV_DEFAULTS: dict[str, str] = {
    # PyO3 < 0.23 (still pinned by pydantic-core in older charms) refuses to
    # build against Python 3.14 unless the stable-ABI escape hatch is set.
    'PYO3_USE_ABI3_FORWARD_COMPATIBILITY': '1',
}


def _apply_host_env_defaults(target: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """Inject host-env defaults into ``env`` (default: ``os.environ``).

    Returns ``env`` for testability. Existing values are not overwritten —
    a user who has explicitly set ``PYO3_USE_ABI3_FORWARD_COMPATIBILITY=0``
    keeps their value. For tox runs we also append ``pass_env+=`` entries to
    ``TOX_OVERRIDE`` so the testenv's install step actually sees the vars;
    without that, tox's process-isolation strips them. Entries are joined
    with ``;`` per tox's documented ``TOX_OVERRIDE`` grammar — newlines are
    not an entry separator and would be folded into the preceding value.
    """
    env = env if env is not None else os.environ  # type: ignore[assignment]
    assert env is not None
    for key, value in _HOST_ENV_DEFAULTS.items():
        env.setdefault(key, value)
    overrides = [f'testenv:{target}.pass_env+={key}' for key in _HOST_ENV_DEFAULTS]
    existing = env.get('TOX_OVERRIDE', '').strip().rstrip(';')
    if existing:
        env['TOX_OVERRIDE'] = existing + ';' + ';'.join(overrides)
    else:
        env['TOX_OVERRIDE'] = ';'.join(overrides)
    return env


_GITHUB_SHORTHAND_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*):([^\s]+)$')
_URL_WITH_BRANCH_RE = re.compile(r'^(https?://[^@\s]+)@([^@\s]+)$')


def _parse_ops_source(arg: str) -> dict[str, str | None]:
    """Parse ``--ops-source`` into kwargs for :class:`patchers.OpsSource`.

    Accepted forms:

    - ``2.17.0`` — PyPI version (any PEP 440 version specifier).
    - ``git+<url>[@branch]`` — explicit git URL (the form ``pip`` and ``uv`` print).
    - ``<url>[@branch]`` — bare ``https://…`` git URL with optional branch.
    - ``owner:branch`` — GitHub shorthand, expands to
      ``https://github.com/<owner>/operator`` at the given branch.
    - ``file://<path>`` or a bare path (``/abs``, ``./rel``, ``~/x``) — local operator checkout.
    """
    arg = arg.strip()
    if not arg:
        raise click.UsageError('--ops-source: empty value')

    if arg.startswith('git+'):
        url, branch = _split_url_branch(arg.removeprefix('git+'))
        return {'url': url, 'branch': branch}
    if arg.startswith('file://'):
        return {'path': _resolve_path(arg.removeprefix('file://'))}
    if '://' in arg:
        url, branch = _split_url_branch(arg)
        return {'url': url, 'branch': branch}
    if arg.startswith(('/', './', '../', '~')):
        return {'path': _resolve_path(arg)}
    m = _GITHUB_SHORTHAND_RE.match(arg)
    if m and '/' not in m.group(1):
        return {'url': f'https://github.com/{m.group(1)}/operator', 'branch': m.group(2)}
    try:
        packaging.version.Version(arg)
    except packaging.version.InvalidVersion as exc:
        raise click.UsageError(
            f'--ops-source: cannot parse {arg!r} as a version, URL, '
            'owner:branch shorthand, or path'
        ) from exc
    return {'version': arg}


def _split_url_branch(arg: str) -> tuple[str, str | None]:
    m = _URL_WITH_BRANCH_RE.match(arg)
    if m:
        return m.group(1), m.group(2)
    return arg, None


def _resolve_path(raw: str) -> str:
    """Expand ``~`` and resolve to an absolute path."""
    return str(pathlib.Path(raw).expanduser().resolve())


def _build_patcher(
    *,
    no_patch: bool,
    ops_source: str,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    auto_python: bool,
):
    if no_patch:
        return patchers.NullPatcher()
    parsed = _parse_ops_source(ops_source)
    ops = patchers.OpsSource(
        url=parsed.get('url') or 'https://github.com/canonical/operator',
        branch=parsed.get('branch'),
        version=parsed.get('version'),
        path=parsed.get('path'),
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
        auto_python=auto_python,
    )
    return patchers.PatcherStack([patchers.OpsSourcePatcher(ops)])


def _build_runner(
    *,
    choice: runners.RunnerChoice,
    tox_executable: str,
    make_executable: str,
    timeout: int,
):
    if choice is runners.RunnerChoice.TOX:
        return tox.ToxRunner(executable=tox_executable, timeout=timeout)
    if choice is runners.RunnerChoice.MAKE:
        return make_runner.MakeRunner(executable=make_executable, timeout=timeout)
    return runners.auto(
        tox_executable=tox_executable,
        make_executable=make_executable,
        timeout=timeout,
    )


def _select_repos(
    cache: pathlib.Path,
    *,
    config: config_loader.Config,
    repo_re: str,
    limit: int,
    framework: str | None,
) -> tuple[list[pathlib.Path], list[tuple[pathlib.Path, str]]]:
    """Return (repos to run, list of (repo, skip-reason) pairs)."""
    chain: list[filt.Filter] = [
        filt.not_legacy,
        filt.regex_filter(repo_re),
        filt.ignore_filter(config.ignore, base=cache),
        filt.has_runnable_target,
    ]
    if framework:

        def framework_filter(repo: pathlib.Path) -> filt.SkipReason:
            return (
                None if frameworks.uses_framework(repo, framework) else f'does not use {framework}'
            )

        chain.append(framework_filter)

    repos: list[pathlib.Path] = []
    skipped: list[tuple[pathlib.Path, str]] = []
    raw = enum_mod.iter_charm_repos(cache)
    if limit > 0:
        raw = itertools.islice(raw, limit)
    for repo in raw:
        for predicate in chain:
            reason = predicate(repo)
            if reason:
                skipped.append((repo, reason))
                break
        else:
            repos.append(repo)
    return repos, skipped


@click.command()
@click.version_option(hyrum.__version__)
@click.option(
    '--cache-folder',
    envvar='HYRUM_CHARMS',
    default=lambda: pathlib.Path('~/.cache/hyrum/charms').expanduser(),
    show_default='~/.cache/hyrum/charms',
    type=click.Path(exists=True, file_okay=False, path_type=pathlib.Path),
    help='Folder containing pre-cloned charm repositories. [env: HYRUM_CHARMS]',
)
@click.option(
    '--config',
    'config_path',
    type=click.Path(dir_okay=False, path_type=pathlib.Path),
    default=pathlib.Path('hyrum.toml'),
    show_default=True,
    help='TOML config file (only the [ignore] table is read today).',
)
@click.argument('target')
@click.option('--repo', default='.*', show_default=True, help='Regex on the repo name.')
@click.option(
    '--limit',
    default=0,
    type=click.IntRange(0),
    help='Stop after this many charms (0 = all).',
)
@click.option(
    '--framework',
    type=click.Choice(list(frameworks.supported_frameworks()), case_sensitive=False),
    default=None,
    help='Only run for charms using this testing framework.',
)
@click.option(
    '--workers',
    default=1,
    type=click.IntRange(1),
    show_default=True,
    help='Number of charms to process concurrently.',
)
@click.option(
    '--runner',
    'runner_choice',
    type=click.Choice([c.value for c in runners.RunnerChoice]),
    default=runners.RunnerChoice.AUTO.value,
    show_default=True,
    help='auto = tox if tox.ini, else make; falls back if the target is missing.',
)
@click.option('--tox-executable', default='tox', show_default=True, help='Tox command.')
@click.option('--make-executable', default='make', show_default=True, help='Make command.')
@click.option(
    '--timeout',
    default=1800,
    type=click.IntRange(1),
    show_default=True,
    help='Per-charm timeout in seconds.',
)
@click.option(
    '--no-patch/--patch',
    default=False,
    help='Skip the dependency-swap; run against whatever the charm already pins.',
)
@click.option(
    '--ops-source',
    default='https://github.com/canonical/operator',
    show_default=True,
    help=(
        'Where to pull ops from. Accepts: a PyPI version (``2.17.0``); a '
        'git URL with optional ``@branch`` (``https://…/operator@fix/X`` or '
        '``git+https://…/operator@fix/X``); the GitHub shorthand '
        '``owner:branch`` (expands to ``https://github.com/<owner>/operator`` '
        'at that branch); or a local path (``/abs/operator``, ``~/operator``, '
        '``file:///abs/operator``).'
    ),
)
@click.option(
    '--poetry-executable',
    default='poetry',
    show_default=True,
    help='Poetry command, used to regenerate the lockfile after patching.',
)
@click.option(
    '--uv-executable',
    default='uv',
    show_default=True,
    help='uv command, used to regenerate the lockfile after patching.',
)
@click.option(
    '--lock-timeout',
    default=600,
    type=click.IntRange(1),
    show_default=True,
    help='Timeout for poetry/uv lock during patching. Independent of --timeout.',
)
@click.option(
    '--auto-python/--no-auto-python',
    default=True,
    show_default=True,
    help=(
        "Run poetry lock under an interpreter that satisfies the charm's "
        'requires-python (via uv run --python X.Y). Requires uv on PATH.'
    ),
)
@click.option(
    '--quiet',
    is_flag=True,
    default=False,
    help='No output except errors. Exit code still reflects pass/fail.',
)
@click.option(
    '--verbose',
    is_flag=True,
    default=False,
    help='Descriptive detail: include the per-charm offender list in the report.',
)
@click.option(
    '--verbosity',
    type=click.Choice(['debug', 'trace'], case_sensitive=False),
    default=None,
    help=(
        'Developer-level detail. Use debug for execution detail; trace reserved for '
        'future code-level detail (currently aliased to debug).'
    ),
)
@click.option(
    '--log-dir',
    type=click.Path(file_okay=False, path_type=pathlib.Path),
    default=None,
    help=(
        "Write each charm's runner stdout/stderr to a per-charm file under "
        'this directory. Useful for triaging failures without rerunning. '
        'File names use the repo path with ``/`` flattened to ``__``.'
    ),
)
@click.option(
    '--no-headers',
    is_flag=True,
    default=False,
    help='Suppress header row in the summary table.',
)
@click.option(
    '--no-fail',
    is_flag=True,
    default=False,
    help='Always exit 0, even if some charms failed (default: exit non-zero on any failure).',
)
@click.option(
    '--host-env-defaults/--no-host-env-defaults',
    default=True,
    show_default=True,
    help=(
        'Inject sensible default env vars (e.g. PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1) '
        'plus matching TOX_OVERRIDE pass_env entries so common host build issues '
        'do not get mis-attributed to the charm.'
    ),
)
def main(
    cache_folder: pathlib.Path,
    config_path: pathlib.Path,
    target: str,
    runner_choice: str,
    repo: str,
    limit: int,
    framework: str | None,
    workers: int,
    tox_executable: str,
    make_executable: str,
    timeout: int,
    no_patch: bool,
    ops_source: str,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    auto_python: bool,
    log_dir: pathlib.Path | None,
    quiet: bool,
    verbose: bool,
    verbosity: str | None,
    no_headers: bool,
    no_fail: bool,
    host_env_defaults: bool,
) -> None:
    """Run TARGET (a tox environment or make target, e.g. unit, lint) across many charm repos."""
    if sum([quiet, verbose, verbosity is not None]) > 1:
        raise click.UsageError('--quiet, --verbose, and --verbosity are mutually exclusive.')
    _configure_logging(_resolve_log_level(quiet=quiet, verbose=verbose, verbosity=verbosity))
    if host_env_defaults:
        _apply_host_env_defaults(target)

    cfg = config_loader.load(config_path)
    repos, skipped = _select_repos(
        cache_folder,
        config=cfg,
        repo_re=repo,
        limit=limit,
        framework=framework,
    )
    logger.info('Selected %d charm(s); skipping %d up-front.', len(repos), len(skipped))

    patcher = _build_patcher(
        no_patch=no_patch,
        ops_source=ops_source,
        poetry_executable=poetry_executable,
        uv_executable=uv_executable,
        lock_timeout=lock_timeout,
        auto_python=auto_python,
    )
    runner = _build_runner(
        choice=runners.RunnerChoice(runner_choice),
        tox_executable=tox_executable,
        make_executable=make_executable,
        timeout=timeout,
    )

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)

    results: list[pool.Outcome] = asyncio.run(
        pool.run_pool(
            repos,
            patcher=patcher,
            runner=runner,
            target=target,
            workers=workers,
            log_dir=log_dir,
            log_base=cache_folder,
        )
    )
    pool.add_skipped(results, skipped)
    results.sort(key=lambda o: str(o.repo))

    if not quiet:
        report.render(
            results,
            base=cache_folder,
            target=target,
            verbose=verbose,
            no_headers=no_headers,
        )
    elif not pool.passed(results):
        failed = sum(1 for o in results if o.status in ('failed', 'timeout', 'patcher_error'))
        click.echo(f'hyrum: {failed} charm(s) did not pass.', err=True)

    if not no_fail and not pool.passed(results):
        sys.exit(1)
