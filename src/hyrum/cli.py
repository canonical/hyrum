"""hyrum CLI."""

from __future__ import annotations

import asyncio
import itertools
import logging
import pathlib
import sys

import click
import rich.logging

from hyrum import config as config_loader
from hyrum import enumerate as enum_mod
from hyrum import filters as filt
from hyrum import frameworks, patchers, pool, report, runners
from hyrum.runners import make_runner, tox

logger = logging.getLogger('hyrum')


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(message)s',
        datefmt='[%X]',
        handlers=[rich.logging.RichHandler(show_path=False)],
    )


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
@click.option('--workers', default=1, type=click.IntRange(1), show_default=True)
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
)
@click.option('--ops-source-branch', default=None, help='Branch of --ops-source to use.')
@click.option('--poetry-executable', default='poetry', show_default=True)
@click.option('--uv-executable', default='uv', show_default=True)
@click.option(
    '--lock-timeout',
    default=600,
    type=click.IntRange(1),
    show_default=True,
    help='Timeout for poetry/uv lock during patching. Independent of --timeout.',
)
@click.option(
    '--log-level',
    default='info',
    type=click.Choice(['debug', 'info', 'warning', 'error', 'critical'], case_sensitive=False),
)
@click.option('--verbose/--no-verbose', default=False)
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
    log_level: str,
    verbose: bool,
    no_fail: bool,
) -> None:
    """Run TARGET (a tox environment or make target, e.g. unit, lint) across many charm repos."""
    _configure_logging(log_level)

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

    report.render(results, base=cache_folder, target=target, verbose=verbose)

    if not no_fail and not pool.passed(results):
        sys.exit(1)
