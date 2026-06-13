"""hyrum CLI."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import os
import pathlib
import re
import sys
import time
from collections.abc import Sequence

import packaging.version

import hyrum
from hyrum import config as config_loader
from hyrum import enumerate as enum_mod
from hyrum import filters as filt
from hyrum import frameworks, patchers, pool, report, runners
from hyrum.runners import make_runner, tox

logger = logging.getLogger('hyrum')


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime


def _configure_logging(level: int) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        _UTCFormatter(fmt='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%SZ')
    )
    logging.basicConfig(level=level, handlers=[handler])


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
        raise argparse.ArgumentTypeError('empty value')

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
        raise argparse.ArgumentTypeError(
            f'cannot parse {arg!r} as a version, URL, owner:branch shorthand, or path'
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
    ops_source: dict[str, str | None],
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    auto_python: bool,
):
    if no_patch:
        return patchers.NullPatcher()
    ops = patchers.OpsSource(
        url=ops_source.get('url') or 'https://github.com/canonical/operator',
        branch=ops_source.get('branch'),
        version=ops_source.get('version'),
        path=ops_source.get('path'),
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
        filt.has_python,
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


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f'{value} is not a positive integer')
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f'{value} is not a non-negative integer')
    return number


def _default_cache_folder() -> pathlib.Path:
    env = os.environ.get('HYRUM_CHARMS')
    if env:
        return pathlib.Path(env)
    return pathlib.Path('~/.cache/hyrum/charms').expanduser()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='hyrum',
        description=(
            'Run TARGET (a tox environment or make target, e.g. unit, lint) '
            'across many charm repos.'
        ),
    )
    parser.add_argument('--version', action='version', version=f'hyrum {hyrum.__version__}')
    parser.add_argument(
        'target',
        metavar='TARGET',
        help='Tox environment or make target to run (e.g. unit, lint).',
    )
    parser.add_argument(
        '--cache-folder',
        type=pathlib.Path,
        default=None,
        help=(
            'Folder containing pre-cloned charm repositories. '
            '[env: HYRUM_CHARMS] [default: ~/.cache/hyrum/charms]'
        ),
    )
    parser.add_argument(
        '--config',
        dest='config_path',
        type=pathlib.Path,
        default=pathlib.Path('hyrum.toml'),
        help='TOML config file (only the [ignore] table is read today). [default: hyrum.toml]',
    )
    parser.add_argument(
        '--repo',
        default='.*',
        help='Regex on the repo name. [default: .*]',
    )
    parser.add_argument(
        '--limit',
        type=_non_negative_int,
        default=0,
        help='Stop after this many charms (0 = all).',
    )
    parser.add_argument(
        '--framework',
        type=str.lower,
        choices=list(frameworks.supported_frameworks()),
        default=None,
        help='Only run for charms using this testing framework.',
    )
    parser.add_argument(
        '--workers',
        type=_positive_int,
        default=1,
        help='Number of charms to process concurrently. [default: 1]',
    )
    parser.add_argument(
        '--runner',
        dest='runner_choice',
        choices=[c.value for c in runners.RunnerChoice],
        default=runners.RunnerChoice.AUTO.value,
        help=(
            'auto = tox if tox.ini, else make; falls back if the target is missing. '
            '[default: auto]'
        ),
    )
    parser.add_argument('--tox-executable', default='tox', help='Tox command. [default: tox]')
    parser.add_argument('--make-executable', default='make', help='Make command. [default: make]')
    parser.add_argument(
        '--timeout',
        type=_positive_int,
        default=1800,
        help='Per-charm timeout in seconds. [default: 1800]',
    )
    parser.add_argument(
        '--patch',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Swap the ops dependency before running (--no-patch runs against existing pins).',
    )
    parser.add_argument(
        '--ops-source',
        type=_parse_ops_source,
        default='https://github.com/canonical/operator',
        help=(
            'Where to pull ops from. Accepts: a PyPI version (``2.17.0``); a '
            'git URL with optional ``@branch`` (``https://…/operator@fix/X`` or '
            '``git+https://…/operator@fix/X``); the GitHub shorthand '
            '``owner:branch`` (expands to ``https://github.com/<owner>/operator`` '
            'at that branch); or a local path (``/abs/operator``, ``~/operator``, '
            '``file:///abs/operator``). '
            '[default: https://github.com/canonical/operator]'
        ),
    )
    parser.add_argument(
        '--poetry-executable',
        default='poetry',
        help=('Poetry command, used to regenerate the lockfile after patching. [default: poetry]'),
    )
    parser.add_argument(
        '--uv-executable',
        default='uv',
        help='uv command, used to regenerate the lockfile after patching. [default: uv]',
    )
    parser.add_argument(
        '--lock-timeout',
        type=_positive_int,
        default=600,
        help=(
            'Timeout for poetry/uv lock during patching. Independent of --timeout. [default: 600]'
        ),
    )
    parser.add_argument(
        '--auto-python',
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Run poetry lock under an interpreter that satisfies the charm's "
            'requires-python (via uv run --python X.Y). Requires uv on PATH.'
        ),
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='No output except errors. Exit code still reflects pass/fail.',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Descriptive detail: include the per-charm offender list in the report.',
    )
    parser.add_argument(
        '--verbosity',
        type=str.lower,
        choices=['debug', 'trace'],
        default=None,
        help=(
            'Developer-level detail. Use debug for execution detail; trace reserved for '
            'future code-level detail (currently aliased to debug).'
        ),
    )
    parser.add_argument(
        '--log-dir',
        type=pathlib.Path,
        default=None,
        help=(
            "Write each charm's runner stdout/stderr to a per-charm file under "
            'this directory. Useful for triaging failures without rerunning. '
            'File names use the repo path with ``/`` flattened to ``__``.'
        ),
    )
    parser.add_argument(
        '--no-headers',
        action='store_true',
        help='Suppress header row in the summary table.',
    )
    parser.add_argument(
        '--no-fail',
        action='store_true',
        help=(
            'Always exit 0, even if some charms failed (default: exit non-zero on any failure).'
        ),
    )
    parser.add_argument(
        '--host-env-defaults',
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            'Inject sensible default env vars (e.g. PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1) '
            'plus matching TOX_OVERRIDE pass_env entries so common host build issues '
            'do not get mis-attributed to the charm.'
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run TARGET (a tox environment or make target, e.g. unit, lint) across many charm repos."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    cache_folder: pathlib.Path = args.cache_folder or _default_cache_folder()
    if not cache_folder.is_dir():
        parser.error(f'Invalid value for --cache-folder: {cache_folder} is not a directory.')

    if sum([args.quiet, args.verbose, args.verbosity is not None]) > 1:
        parser.error('--quiet, --verbose, and --verbosity are mutually exclusive.')
    _configure_logging(
        _resolve_log_level(quiet=args.quiet, verbose=args.verbose, verbosity=args.verbosity)
    )
    if args.host_env_defaults:
        _apply_host_env_defaults(args.target)

    cfg = config_loader.load(args.config_path)
    repos, skipped = _select_repos(
        cache_folder,
        config=cfg,
        repo_re=args.repo,
        limit=args.limit,
        framework=args.framework,
    )
    logger.info('Selected %d charm(s); skipping %d up-front.', len(repos), len(skipped))

    patcher = _build_patcher(
        no_patch=not args.patch,
        ops_source=args.ops_source,
        poetry_executable=args.poetry_executable,
        uv_executable=args.uv_executable,
        lock_timeout=args.lock_timeout,
        auto_python=args.auto_python,
    )
    runner = _build_runner(
        choice=runners.RunnerChoice(args.runner_choice),
        tox_executable=args.tox_executable,
        make_executable=args.make_executable,
        timeout=args.timeout,
    )

    if args.log_dir is not None:
        args.log_dir.mkdir(parents=True, exist_ok=True)

    results: list[pool.Outcome] = asyncio.run(
        pool.run_pool(
            repos,
            patcher=patcher,
            runner=runner,
            target=args.target,
            workers=args.workers,
            log_dir=args.log_dir,
            log_base=cache_folder,
        )
    )
    pool.add_skipped(results, skipped)
    results.sort(key=lambda o: str(o.repo))

    if not args.quiet:
        report.render(
            results,
            base=cache_folder,
            target=args.target,
            verbose=args.verbose,
            no_headers=args.no_headers,
        )
    elif not pool.passed(results):
        failed = sum(1 for o in results if o.status in ('failed', 'timeout', 'patcher_error'))
        print(f'hyrum: {failed} charm(s) did not pass.', file=sys.stderr)

    if not args.no_fail and not pool.passed(results):
        sys.exit(1)
