"""hyrum CLI."""

from __future__ import annotations

import argparse
import asyncio
import csv
import itertools
import logging
import os
import pathlib
import re
import sys
import time
from collections.abc import Sequence

import packaging.requirements
import packaging.version

from hyrum import _config as config_loader
from hyrum import _enumerate as enum_mod
from hyrum import _filters as filt
from hyrum import _frameworks as frameworks
from hyrum import _get_charms as get_charms
from hyrum import _patchers as patchers
from hyrum import _pool as pool
from hyrum import _report as report
from hyrum import _runners as runners
from hyrum import _version
from hyrum._runners import make_runner, tox

logger = logging.getLogger('hyrum')


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime


def _configure_logging(level: int) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        _UTCFormatter(fmt='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%SZ')
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def _resolve_log_level(*, quiet: bool, verbosity: str | None) -> int:
    if quiet:
        return logging.WARNING
    if verbosity in ('debug', 'trace'):
        return logging.DEBUG
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


_DEP_SUBDIR_RE = re.compile(r'#subdirectory=([^\s#]+)$')


def _parse_dep_source(arg: str) -> dict[str, str | None]:
    """Parse a ``--dep-source`` value into kwargs for :class:`patchers.DepSource`.

    The value is a PEP 508 requirement string. Three forms are recognised:

    - ``<name><specifier>`` — PyPI version pin, such as ``requests==2.31.0``,
      ``requests>=1.2,<2``.
    - ``<name> @ git+<url>[@<branch>][#subdirectory=<sub>]`` — git source.
    - ``<name> @ file://<path>`` — local path.

    Extras on the input (``requests[security]==2.31.0``) are not honoured;
    the patcher preserves whatever extras the charm itself declares.
    """
    text = arg.strip()
    if not text:
        raise argparse.ArgumentTypeError('--dep-source: empty value')

    try:
        req = packaging.requirements.Requirement(text)
    except packaging.requirements.InvalidRequirement as exc:
        raise argparse.ArgumentTypeError(f'--dep-source: cannot parse {arg!r}: {exc}') from exc

    out: dict[str, str | None] = {'pkg_name': req.name}

    if req.url:
        url = req.url
        if url.startswith('file://'):
            out['path'] = _resolve_path(url.removeprefix('file://'))
        elif url.startswith('git+'):
            bare = url.removeprefix('git+')
            m = _DEP_SUBDIR_RE.search(bare)
            if m:
                out['subdir'] = m.group(1)
                bare = bare[: m.start()]
            git_url, branch = _split_url_branch(bare)
            out['url'] = git_url
            out['branch'] = branch
        else:
            raise argparse.ArgumentTypeError(
                f'--dep-source: unsupported URL scheme in {arg!r} (expected git+... or file://)'
            )
        return out

    if str(req.specifier):
        out['version'] = str(req.specifier)
        return out

    raise argparse.ArgumentTypeError(
        f'--dep-source: {arg!r} must include a version specifier (==X.Y.Z), '
        f'a git+URL, or a file:// path'
    )


def _build_dep_patcher(
    parsed: dict[str, str | None],
    *,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
) -> patchers.GenericDepPatcher:
    name = parsed['pkg_name']
    assert name is not None
    source = patchers.DepSource(
        pkg_name=name,
        version=parsed.get('version'),
        url=parsed.get('url'),
        branch=parsed.get('branch'),
        subdir=parsed.get('subdir'),
        path=parsed.get('path'),
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
    )
    return patchers.GenericDepPatcher(source)


def _build_patcher(
    *,
    no_patch: bool,
    ops_source: dict[str, str | None],
    dep_sources: Sequence[dict[str, str | None]],
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
    stack: list[patchers.Patcher] = [patchers.OpsSourcePatcher(ops)]
    stack.extend(
        _build_dep_patcher(
            spec,
            poetry_executable=poetry_executable,
            uv_executable=uv_executable,
            lock_timeout=lock_timeout,
        )
        for spec in dep_sources
    )
    return patchers.PatcherStack(stack)


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
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{value!r} is not a positive integer') from None
    if number < 1:
        raise argparse.ArgumentTypeError(f'{value!r} is not a positive integer')
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{value!r} is not a non-negative integer') from None
    if number < 0:
        raise argparse.ArgumentTypeError(f'{value!r} is not a non-negative integer')
    return number


def _default_charms_dir() -> pathlib.Path:
    env = os.environ.get('HYRUM_CHARMS')
    if env:
        return pathlib.Path(env)
    return pathlib.Path('~/.cache/hyrum/charms').expanduser()


def _add_check_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        'check',
        help='Run TARGET across many charm repos.',
        description=(
            'Run TARGET (a tox environment or make target, e.g. unit, lint) '
            'across many charm repos.'
        ),
    )
    parser.add_argument(
        'target',
        metavar='TARGET',
        help='Tox environment or make target to run (e.g. unit, lint).',
    )
    parser.add_argument(
        '--charms-dir',
        type=pathlib.Path,
        default=None,
        help=(
            'Directory containing pre-cloned charm repositories. '
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
    parser.add_argument('--repo', default='.*', help='Regex on the repo name. [default: .*]')
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
        '--no-patch',
        action='store_true',
        help='Skip the dependency-swap; run against whatever the charm already pins.',
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
        '--dep-source',
        dest='dep_sources',
        action='append',
        type=_parse_dep_source,
        default=[],
        help=(
            'Swap an arbitrary dependency. PEP 508 form, e.g. '
            '``requests==2.31.0``, ``requests>=1.2,<2``, '
            '``requests @ git+https://github.com/psf/requests@main``, or '
            '``mylib @ file:///abs/path``. May be given multiple times.'
        ),
    )
    parser.add_argument(
        '--poetry-executable',
        default='poetry',
        help='Poetry command, used to regenerate the lockfile after patching. [default: poetry]',
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
            'requires-python (via uv run --python X.Y). Requires uv on PATH. [default: enabled]'
        ),
    )
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        '--quiet',
        action='store_true',
        help='No output except errors. Exit code still reflects pass/fail.',
    )
    verbosity_group.add_argument(
        '--verbose',
        action='store_true',
        help='Descriptive detail: include the per-charm offender list in the report.',
    )
    verbosity_group.add_argument(
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
            'do not get mis-attributed to the charm. [default: enabled]'
        ),
    )
    parser.set_defaults(func=_run_check)
    return parser


def _add_get_charms_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        'get-charms',
        help='Populate the charms directory by cloning or pulling every charm in the CSV.',
        description=(
            'Populate the charms directory by cloning or pulling every charm listed in the CSV.'
        ),
    )
    parser.add_argument(
        '--source',
        type=pathlib.Path,
        default=None,
        help='Path to the charm list. [default: charms.csv or charm-list/charms.csv]',
    )
    parser.add_argument(
        '--dest',
        type=pathlib.Path,
        default=None,
        help=(
            'Charms directory to download into. '
            '[env: HYRUM_CHARMS] [default: ~/.cache/hyrum/charms]'
        ),
    )
    parser.add_argument('--quiet', action='store_true', help='Suppress non-error output.')
    parser.set_defaults(func=_run_get_charms)
    return parser


def _build_arg_parser() -> argparse.ArgumentParser:
    description = 'Bulk-run a check across many charm repositories with a dependency swapped out.'
    parser = argparse.ArgumentParser(prog='hyrum', description=description)
    parser.add_argument('--version', action='version', version=f'hyrum {_version.__version__}')
    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND', required=True)
    _add_check_subparser(subparsers)
    _add_get_charms_subparser(subparsers)
    return parser


def _run_check(args: argparse.Namespace) -> int:
    charms_dir: pathlib.Path = args.charms_dir or _default_charms_dir()
    if not charms_dir.is_dir():
        sys.exit(f'hyrum: error: --charms-dir: {charms_dir} is not a directory.')

    _configure_logging(_resolve_log_level(quiet=args.quiet, verbosity=args.verbosity))
    if args.host_env_defaults:
        _apply_host_env_defaults(args.target)

    cfg = config_loader.load(args.config_path)
    repos, skipped = _select_repos(
        charms_dir,
        config=cfg,
        repo_re=args.repo,
        limit=args.limit,
        framework=args.framework,
    )
    logger.info('Selected %d charm(s); skipping %d up-front.', len(repos), len(skipped))

    patcher = _build_patcher(
        no_patch=args.no_patch,
        ops_source=args.ops_source,
        dep_sources=args.dep_sources,
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
            log_base=charms_dir,
        )
    )
    pool.add_skipped(results, skipped)
    results.sort(key=lambda o: str(o.repo))

    if not args.quiet:
        report.render(
            results,
            base=charms_dir,
            target=args.target,
            verbose=args.verbose,
            no_headers=args.no_headers,
        )
    elif not pool.passed(results):
        failed = sum(1 for o in results if o.status in ('failed', 'timeout', 'patcher_error'))
        print(f'hyrum: {failed} charm(s) did not pass.', file=sys.stderr)

    if not args.no_fail and not pool.passed(results):
        return 1
    return 0


def _run_get_charms(args: argparse.Namespace) -> int:
    level = logging.ERROR if args.quiet else logging.INFO
    _configure_logging(level)

    source = args.source
    if source is None:
        source = get_charms.find_default_source()
        if source is None:
            candidates = ', '.join(str(p) for p in get_charms.DEFAULT_SOURCE_CANDIDATES)
            sys.exit(f'hyrum: error: No charm list at default locations: {candidates}')
    if not source.exists():
        sys.exit(f'hyrum: error: Charm list not found: {source}')

    dest = args.dest or _default_charms_dir()
    dest.mkdir(parents=True, exist_ok=True)

    with source.open(newline='', encoding='utf-8') as f:
        rows: list[get_charms.CharmRow] = list(csv.DictReader(f))  # type: ignore[arg-type]
    asyncio.run(get_charms.process_rows(rows, dest))
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Bulk-run a check across many charm repositories with a dependency swapped out."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
