"""hyrum CLI."""

from __future__ import annotations

import asyncio
import datetime
import itertools
import logging
import pathlib
import sys

import click
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


def _build_patcher(
    *,
    no_patch: bool,
    ops_source: str,
    ops_source_branch: str | None,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
):
    if no_patch:
        return patchers.NullPatcher()
    ops = patchers.OpsSource(
        url=ops_source,
        branch=ops_source_branch,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
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
    help='Git URL of the operator repository to swap in.',
)
@click.option('--ops-source-branch', default=None, help='Branch of --ops-source to use.')
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
    ops_source_branch: str | None,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    quiet: bool,
    verbose: bool,
    verbosity: str | None,
    no_headers: bool,
    no_fail: bool,
) -> None:
    """Run TARGET (a tox environment or make target, e.g. unit, lint) across many charm repos."""
    if sum([quiet, verbose, verbosity is not None]) > 1:
        raise click.UsageError('--quiet, --verbose, and --verbosity are mutually exclusive.')
    _configure_logging(_resolve_log_level(quiet=quiet, verbose=verbose, verbosity=verbosity))

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
        ops_source_branch=ops_source_branch,
        poetry_executable=poetry_executable,
        uv_executable=uv_executable,
        lock_timeout=lock_timeout,
    )
    runner = _build_runner(
        choice=runners.RunnerChoice(runner_choice),
        tox_executable=tox_executable,
        make_executable=make_executable,
        timeout=timeout,
    )

    results: list[pool.Outcome] = asyncio.run(
        pool.run_pool(repos, patcher=patcher, runner=runner, target=target, workers=workers)
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
