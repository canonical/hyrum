"""super-tox CLI."""

from __future__ import annotations

import asyncio
import itertools
import logging
import sys
from pathlib import Path

import click
import rich.logging

from super_tox import config as config_loader
from super_tox import enumerate as enum_mod
from super_tox import filters as filt
from super_tox.frameworks import supported_frameworks, uses_framework
from super_tox.patchers import NullPatcher, OpsSource, OpsSourcePatcher, PatcherStack
from super_tox.pool import Outcome, add_skipped, passed, run_pool
from super_tox.report import render
from super_tox.runners import RunnerChoice, auto
from super_tox.runners.make_runner import MakeRunner
from super_tox.runners.tox import ToxRunner

logger = logging.getLogger('super_tox')


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
        return NullPatcher()
    ops = OpsSource(
        url=ops_source,
        branch=ops_source_branch,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
    )
    return PatcherStack([OpsSourcePatcher(ops)])


def _build_runner(
    *,
    choice: RunnerChoice,
    executable: str,
    make_executable: str,
    timeout: int,
):
    if choice is RunnerChoice.TOX:
        return ToxRunner(executable=executable, timeout=timeout)
    if choice is RunnerChoice.MAKE:
        return MakeRunner(executable=make_executable, timeout=timeout)
    return auto(
        tox_executable=executable,
        make_executable=make_executable,
        timeout=timeout,
    )


def _select_repos(
    cache: Path,
    *,
    config: config_loader.Config,
    repo_re: str,
    sample: int,
    framework: str | None,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Return (repos to run, list of (repo, skip-reason) pairs)."""
    chain: list[filt.Filter] = [
        filt.regex_filter(repo_re),
        filt.ignore_filter(config.ignore, base=cache),
        filt.has_runnable_target,
    ]
    if framework:

        def framework_filter(repo: Path) -> filt.SkipReason:
            return None if uses_framework(repo, framework) else f'does not use {framework}'

        chain.append(framework_filter)

    repos: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    raw = enum_mod.iter_charm_repos(cache)
    if sample > 0:
        raw = itertools.islice(raw, sample)
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
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help='Folder containing pre-cloned charm repositories.',
)
@click.option(
    '-c',
    '--config',
    'config_path',
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path('super-tox.toml'),
    show_default=True,
    help='TOML config file (only the [ignore] table is read today).',
)
@click.option(
    '-t',
    '--target',
    required=True,
    help='Tox environment or make target (e.g. unit, lint).',
)
@click.option(
    '--runner',
    'runner_choice',
    type=click.Choice([c.value for c in RunnerChoice]),
    default=RunnerChoice.AUTO.value,
    show_default=True,
    help='auto = tox if tox.ini, else make; falls back if the target is missing.',
)
@click.option('--repo', default='.*', show_default=True, help='Regex on the repo name.')
@click.option(
    '--sample',
    default=0,
    type=click.IntRange(0),
    help='Stop after this many charms (0 = all).',
)
@click.option(
    '--filter',
    'framework',
    type=click.Choice(list(supported_frameworks()), case_sensitive=False),
    default=None,
    help='Only run for charms using this testing framework.',
)
@click.option('--workers', default=1, type=click.IntRange(1), show_default=True)
@click.option('--executable', default='tox', show_default=True, help='Tox command.')
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
    help='Timeout for poetry/uv lock during patching.',
)
@click.option(
    '--log-level',
    default='info',
    type=click.Choice(['debug', 'info', 'warning', 'error', 'critical'], case_sensitive=False),
)
@click.option('--verbose/--no-verbose', default=False)
@click.option(
    '--fail-on-regression/--no-fail-on-regression',
    default=False,
    help='Exit non-zero if any charm failed, timed out, or hit a patcher error.',
)
def main(
    cache_folder: Path,
    config_path: Path,
    target: str,
    runner_choice: str,
    repo: str,
    sample: int,
    framework: str | None,
    workers: int,
    executable: str,
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
    fail_on_regression: bool,
) -> None:
    """Run a check (typically lint or unit tests) across many charm repos."""
    _configure_logging(log_level)

    cfg = config_loader.load(config_path)
    repos, skipped = _select_repos(
        cache_folder,
        config=cfg,
        repo_re=repo,
        sample=sample,
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
        choice=RunnerChoice(runner_choice),
        executable=executable,
        make_executable=make_executable,
        timeout=timeout,
    )

    results: list[Outcome] = asyncio.run(
        run_pool(repos, patcher=patcher, runner=runner, target=target, workers=workers)
    )
    add_skipped(results, skipped)
    results.sort(key=lambda o: str(o.repo))

    render(results, base=cache_folder, target=target, verbose=verbose)

    if fail_on_regression and not passed(results):
        sys.exit(1)
