"""hyrum CLI."""

from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import json
import logging
import os
import pathlib
import re
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] — subprocess is core to the git ls-remote preflight
import sys
import time
from collections.abc import Sequence

import packaging.requirements

from hyrum import _compare, _enumerate, _results, _version
from hyrum import _config as config_loader
from hyrum import _filters as filt
from hyrum import _frameworks as frameworks
from hyrum import _get_charms as get_charms
from hyrum import _patchers as patchers
from hyrum import _pool as pool
from hyrum import _report as report
from hyrum import _runners as runners
from hyrum._runners import make_runner, tox

logger = logging.getLogger('hyrum')


# rstrip guards against HOME=/ (e.g. root on a minimal container), where the
# raw expansion would make _HOME_PREFIX '//' and rewrite every '/' to '~/'.
_HOME_PREFIX = os.path.expanduser('~').rstrip('/') + '/'
_HOME_RE = re.compile(r'(^|[^\w./-])' + re.escape(_HOME_PREFIX))


class _HyrumFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        return _HOME_RE.sub(r'\1~/', super().format(record))


def _configure_logging(level: int) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        _HyrumFormatter(fmt='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%SZ')
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
_PEP503_NAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$')


_DEP_SUBDIR_RE = re.compile(r'#subdirectory=([^\s#]+)$')


_VENDORED_LHS_RE = re.compile(r'^charms\.([A-Za-z0-9_]+)\.v(\d+)\.([A-Za-z0-9_]+)$')


def _split_url_branch(arg: str) -> tuple[str, str | None]:
    m = _URL_WITH_BRANCH_RE.match(arg)
    if m:
        return m.group(1), m.group(2)
    return arg, None


def _resolve_path(raw: str) -> str:
    """Expand ``~`` and resolve to an absolute path."""
    return str(pathlib.Path(raw).expanduser().resolve())


@dataclasses.dataclass(frozen=True)
class PatchSpec:
    """A parsed ``--patch`` value.

    Non-vendored patches carry ``pkg_name`` plus one of {``version``,
    ``path``, or (``url`` [+ ``branch`` [+ ``subdir``])}. Vendored-library
    swaps additionally set the four ``vendored_*`` fields; ``pkg_name`` is
    then the dotted LHS (``charms.<author>.v<n>.<lib>``) and
    ``vendored_pkg`` is the replacement package name.
    """

    pkg_name: str
    version: str | None = None
    url: str | None = None
    branch: str | None = None
    subdir: str | None = None
    path: str | None = None
    vendored_author: str | None = None
    vendored_version: str | None = None
    vendored_lib: str | None = None
    vendored_pkg: str | None = None

    def __str__(self) -> str:
        if self.version:
            return f'{self.pkg_name}{self.version}'
        if self.path:
            return f'{self.pkg_name} @ {self.path}'
        source = self.url or ''
        if self.branch:
            source += f'@{self.branch}'
        if self.subdir:
            source += f'#subdirectory={self.subdir}'
        return f'{self.pkg_name} @ {source}'


def _parse_patch_source(rhs: str, *, pkg_name: str) -> dict[str, str | None]:
    """Parse the source half of ``name @ <source>``.

    Returns a dict containing some of ``url``, ``branch``, ``subdir``, ``path``.
    """
    if not rhs:
        raise argparse.ArgumentTypeError(f'--patch: empty source for {pkg_name!r}')
    if rhs.startswith('git+'):
        bare = rhs.removeprefix('git+')
        subdir: str | None = None
        m = _DEP_SUBDIR_RE.search(bare)
        if m:
            subdir = m.group(1)
            bare = bare[: m.start()]
        url, branch = _split_url_branch(bare)
        out: dict[str, str | None] = {'url': url, 'branch': branch}
        if subdir is not None:
            out['subdir'] = subdir
        return out
    if rhs.startswith('file://'):
        return {'path': _resolve_path(rhs.removeprefix('file://'))}
    if '://' in rhs:
        url, branch = _split_url_branch(rhs)
        return {'url': url, 'branch': branch}
    if rhs.startswith(('/', './', '../', '~')):
        return {'path': _resolve_path(rhs)}
    m = _GITHUB_SHORTHAND_RE.match(rhs)
    if m and '/' not in m.group(1):
        owner, branch = m.group(1), m.group(2)
        if pkg_name == 'ops':
            return {'url': f'https://github.com/{owner}/operator', 'branch': branch}
        if pkg_name.startswith('charmlibs-'):
            return {'url': f'https://github.com/{owner}/charmlibs', 'branch': branch}
        raise argparse.ArgumentTypeError(
            f"--patch: owner:branch shorthand is only supported for 'ops' and "
            f'charmlibs-* (got package {pkg_name!r}); pass an explicit git+URL'
        )
    raise argparse.ArgumentTypeError(f'--patch: cannot parse source {rhs!r} for {pkg_name!r}')


def _parse_patch(arg: str) -> PatchSpec:
    """Parse a ``--patch`` value.

    Forms:

    - ``<name><specifier>`` — PyPI version pin (e.g. ``ops==2.17.0``,
      ``requests>=1.2,<2``).
    - ``<name> @ git+<url>[@<branch>][#subdirectory=<sub>]`` — git source.
    - ``<name> @ <url>[@<branch>]`` — bare git URL.
    - ``<name> @ file://<path>`` or a bare path (``/abs``, ``~/x``, ``./rel``).
    - ``ops @ <owner>:<branch>`` — GitHub shorthand for ops, expands to
      ``https://github.com/<owner>/operator``.
    - ``charmlibs-<name> @ <owner>:<branch>`` — GitHub shorthand for a
      charmlib, expands to ``https://github.com/<owner>/charmlibs``. The
      subdirectory is taken from the package name verbatim, so type the
      separators (``-`` vs ``_``) the way the directory exists on disk
      (e.g. ``charmlibs-nginx_k8s``, ``charmlibs-interfaces-k8s-service``).
    - ``charms.<author>.v<n>.<lib> -> <spec>`` — vendored-library swap.
      The LHS is the dotted import path of the vendored library
      (the directory ``lib/charms/<author>/v<n>/<lib>.py``). The RHS is
      any of the forms above for the replacement PyPI package, e.g.
      ``charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0`` or
      ``charms.operator_libs_linux.v0.apt -> charmlibs-apt @ git+https://github.com/canonical/charmlibs@main#subdirectory=apt``.

    Extras on the input are not honoured; the patcher preserves whatever
    extras the charm itself declares.
    """
    text = arg.strip()
    if not text:
        raise argparse.ArgumentTypeError('--patch: empty value')

    lhs, sep, rhs = text.partition(' -> ')
    if sep:
        lhs = lhs.strip()
        m = _VENDORED_LHS_RE.match(lhs)
        if not m:
            raise argparse.ArgumentTypeError(
                f'--patch: left of "->" must be a vendored dotted form '
                f'``charms.<author>.v<n>.<lib>``, got {lhs!r}'
            )
        rhs_spec = rhs.strip()
        if not rhs_spec:
            raise argparse.ArgumentTypeError(
                f'--patch: empty replacement spec after "->" in {arg!r}'
            )
        new_spec = _parse_patch(rhs_spec)
        return dataclasses.replace(
            new_spec,
            pkg_name=lhs,
            vendored_author=m.group(1),
            vendored_version=m.group(2),
            vendored_lib=m.group(3),
            vendored_pkg=new_spec.pkg_name,
        )

    name, sep, rhs = text.partition(' @ ')
    if sep:
        pkg_name = name.strip()
        if not pkg_name:
            raise argparse.ArgumentTypeError(f'--patch: empty package name in {arg!r}')
        if not _PEP503_NAME_RE.match(pkg_name):
            raise argparse.ArgumentTypeError(f'--patch: invalid package name {pkg_name!r}')
        return PatchSpec(pkg_name=pkg_name, **_parse_patch_source(rhs.strip(), pkg_name=pkg_name))

    try:
        req = packaging.requirements.Requirement(text)
    except packaging.requirements.InvalidRequirement as exc:
        raise argparse.ArgumentTypeError(f'--patch: cannot parse {arg!r}: {exc}') from exc
    if not str(req.specifier):
        raise argparse.ArgumentTypeError(
            f'--patch: {arg!r} must include a version specifier (==X.Y.Z), '
            f'a ``@`` source (git+URL, file:// path, owner:branch shorthand), '
            f'or a bare path'
        )
    return PatchSpec(pkg_name=req.name, version=str(req.specifier))


_DEFAULT_OPS_PATCH = PatchSpec(
    pkg_name='ops',
    url='https://github.com/canonical/operator',
    branch='main',
)


def _build_ops_patcher(
    spec: PatchSpec,
    *,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    auto_python: bool,
) -> patchers.OpsSourcePatcher:
    ops = patchers.OpsSource(
        url=spec.url or 'https://github.com/canonical/operator',
        branch=spec.branch,
        version=spec.version,
        path=spec.path,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
        auto_python=auto_python,
    )
    return patchers.OpsSourcePatcher(ops)


def _build_dep_patcher(
    spec: PatchSpec,
    *,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
) -> patchers.GenericDepPatcher:
    source = patchers.DepSource(
        pkg_name=spec.pkg_name,
        version=spec.version,
        url=spec.url,
        branch=spec.branch,
        subdir=spec.subdir,
        path=spec.path,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
    )
    return patchers.GenericDepPatcher(source)


def _build_charmlib_patcher(
    spec: PatchSpec,
    *,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
) -> patchers.CharmlibPatcher:
    if spec.path is not None:
        raise argparse.ArgumentTypeError(
            f'--patch: charmlibs deps must be patched from a git source, '
            f'not a local path: {spec.pkg_name!r}'
        )
    if spec.version is not None:
        raise argparse.ArgumentTypeError(
            f'--patch: charmlibs deps must be patched from a git source, '
            f'not a version pin: {spec.pkg_name!r}'
        )
    source = patchers.CharmlibSource(
        pkg_name=spec.pkg_name,
        url=spec.url or 'https://github.com/canonical/charmlibs',
        branch=spec.branch,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
    )
    return patchers.CharmlibPatcher(source)


def _build_vendored_patcher(
    spec: PatchSpec,
    *,
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
) -> patchers.VendoredLibPatcher:
    assert spec.vendored_pkg is not None
    assert spec.vendored_author is not None
    assert spec.vendored_version is not None
    assert spec.vendored_lib is not None
    source = patchers.DepSource(
        pkg_name=spec.vendored_pkg,
        version=spec.version,
        url=spec.url,
        branch=spec.branch,
        subdir=spec.subdir,
        path=spec.path,
        poetry_executable=tuple(poetry_executable.split()),
        uv_executable=tuple(uv_executable.split()),
        lock_timeout=lock_timeout,
    )
    swap = patchers.VendoredLibSwap(
        host_charm=spec.vendored_author,
        version=int(spec.vendored_version),
        lib_name=spec.vendored_lib,
        source=source,
    )
    return patchers.VendoredLibPatcher(swap)


def _build_patcher(
    *,
    patches: Sequence[PatchSpec],
    poetry_executable: str,
    uv_executable: str,
    lock_timeout: int,
    auto_python: bool,
) -> patchers.Patcher:
    if not patches:
        return patchers.NullPatcher()
    stack: list[patchers.Patcher] = []
    for spec in patches:
        pkg_name = spec.pkg_name
        if spec.vendored_author is not None:
            stack.append(
                _build_vendored_patcher(
                    spec,
                    poetry_executable=poetry_executable,
                    uv_executable=uv_executable,
                    lock_timeout=lock_timeout,
                )
            )
        elif pkg_name == 'ops':
            stack.append(
                _build_ops_patcher(
                    spec,
                    poetry_executable=poetry_executable,
                    uv_executable=uv_executable,
                    lock_timeout=lock_timeout,
                    auto_python=auto_python,
                )
            )
        elif pkg_name.startswith('charmlibs-'):
            stack.append(
                _build_charmlib_patcher(
                    spec,
                    poetry_executable=poetry_executable,
                    uv_executable=uv_executable,
                    lock_timeout=lock_timeout,
                )
            )
        else:
            stack.append(
                _build_dep_patcher(
                    spec,
                    poetry_executable=poetry_executable,
                    uv_executable=uv_executable,
                    lock_timeout=lock_timeout,
                )
            )
    if len(stack) == 1:
        return stack[0]
    return patchers.PatcherStack(stack)


def _describe_patches(patches: Sequence[PatchSpec]) -> str:
    """One-line human-readable summary of the run's dependency swap, for run metadata."""
    if not patches:
        return 'none'
    return '; '.join(str(spec) for spec in patches)


def _build_runner(
    *,
    choice: runners.RunnerChoice,
    tox_executable: str,
    make_executable: str,
    timeout: int,
    prefer: Sequence[str] = ('tox', 'make'),
):
    if choice is runners.RunnerChoice.TOX:
        return tox.ToxRunner(executable=tox_executable, timeout=timeout)
    if choice is runners.RunnerChoice.MAKE:
        return make_runner.MakeRunner(executable=make_executable, timeout=timeout)
    return runners.auto(
        tox_executable=tox_executable,
        make_executable=make_executable,
        timeout=timeout,
        prefer=prefer,
    )


# Backends each ``--runner`` choice may end up invoking, in preference order.
_RUNNER_BACKENDS: dict[runners.RunnerChoice, tuple[str, ...]] = {
    runners.RunnerChoice.TOX: ('tox',),
    runners.RunnerChoice.MAKE: ('make',),
    runners.RunnerChoice.AUTO: ('tox', 'make'),
}


def _missing_program(command: str) -> str | None:
    """Return ``command``'s program name if it is not on PATH, else ``None``."""
    argv = shlex.split(command)
    if not argv:
        return command
    return None if shutil.which(argv[0]) else argv[0]


def _available_backends(
    choice: runners.RunnerChoice,
    *,
    tox_executable: str,
    make_executable: str,
) -> tuple[str, ...]:
    """Return the runner backends whose executable is actually installed.

    A backend that isn't installed would otherwise fail identically in every
    charm, producing one ``runner_error`` per charm for a single host problem.
    Under ``--runner auto`` the missing backend is dropped with a warning (a
    fleet with no make-driven charms shouldn't need make); if nothing is left,
    that's fatal and we say so once, before any charm runs.
    """
    commands = {'tox': tox_executable, 'make': make_executable}
    available: list[str] = []
    missing: list[str] = []
    for name in _RUNNER_BACKENDS[choice]:
        missing_program = _missing_program(commands[name])
        if missing_program is None:
            available.append(name)
        else:
            missing.append(missing_program)
            logger.warning('%s is not installed; %s charms cannot be run', missing_program, name)
    if not available:
        sys.exit(f'hyrum: error: no runner available: {", ".join(missing)} not found on PATH.')
    return tuple(available)


# A ref that ``git ls-remote`` cannot see but git can still check out: a full
# commit SHA. Anything shorter is ambiguous, and uv's shallow fetch cannot
# resolve an abbreviated hash, so we ask for the full one.
_FULL_SHA_RE = re.compile(r'^[0-9a-f]{40}$')
_ABBREVIATED_SHA_RE = re.compile(r'^[0-9a-f]{4,39}$')

# ``git ls-remote --exit-code`` exits 2 when no ref matched; other non-zero
# exits mean the remote itself could not be queried.
_LS_REMOTE_NO_MATCH = 2


def _unresolvable_ref(url: str, ref: str, *, timeout: int = 30) -> str | None:
    """Return why ``ref`` cannot be found in ``url``, or ``None`` if it can.

    Network and authentication problems are not the user's ref being wrong, so
    they warn and pass; only a remote that answered and had no such ref fails.
    """
    argv = ['git', 'ls-remote', '--exit-code', url, ref]
    try:
        result = subprocess.run(argv, check=False, capture_output=True, timeout=timeout)  # ruff: ignore[subprocess-without-shell-equals-true]
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning('could not check %s in %s: %s', ref, url, exc)
        return None
    if result.returncode == 0:
        return None
    if result.returncode != _LS_REMOTE_NO_MATCH:
        logger.warning(
            'could not check %s in %s: %s',
            ref,
            url,
            result.stderr.decode(errors='replace').strip(),
        )
        return None
    if _FULL_SHA_RE.match(ref):
        return None
    if _ABBREVIATED_SHA_RE.match(ref):
        return (
            f'{ref!r} is not a branch or tag in {url}; if it is a commit, give the '
            f'full 40-character SHA (an abbreviated one cannot be fetched)'
        )
    return f'{ref!r} does not resolve to a branch or tag in {url}'


def _preflight_patch_refs(patches: Sequence[PatchSpec]) -> None:
    """Fail fast if a ``--patch`` ref does not exist in its remote.

    An unresolvable ref patches cleanly and only breaks later, when the runner
    installs the dependency — which records every charm as ``failed``,
    indistinguishable from a genuine test failure. One ``git ls-remote`` per
    distinct (url, ref) costs well under a second and names the typo instead.
    """
    checked: set[tuple[str, str]] = set()
    for spec in patches:
        url, ref = spec.url, spec.branch
        if url is None or ref is None or (url, ref) in checked:
            continue
        checked.add((url, ref))
        problem = _unresolvable_ref(url, ref)
        if problem is not None:
            sys.exit(f'hyrum: error: --patch: {problem}')


def _select_repos(
    cache: pathlib.Path,
    *,
    config: config_loader.Config,
    repo_re: str,
    limit: int,
    framework: str | None,
) -> tuple[list[pathlib.Path], list[tuple[pathlib.Path, str]]]:
    """Return (repos to run, list of (repo, skip-reason) pairs).

    ``limit`` caps the number of charms *selected to run*, not the number
    considered: enumeration continues past charms the filter chain skips.
    The collection is alphabetical and opens on a run of legacy charms, so a
    cap applied before filtering makes small values select nothing at all.
    Charms passed over on the way to the cap still land in ``skipped``, so
    the summary stays honest about what was looked at.
    """
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
    for repo in _enumerate.iter_charm_repos(cache):
        for predicate in chain:
            reason = predicate(repo)
            if reason:
                skipped.append((repo, reason))
                break
        else:
            repos.append(repo)
            if limit > 0 and len(repos) >= limit:
                break
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


def _default_auto_save_dir() -> pathlib.Path:
    return pathlib.Path('~/.cache/hyrum/results').expanduser()


def _log_written(path: pathlib.Path, count: int) -> None:
    """Note the file a save plan just produced."""
    noun = 'outcome' if count == 1 else 'outcomes'
    logger.info('Wrote %d %s to %s', count, noun, path)


@dataclasses.dataclass(frozen=True)
class _NoSavePlan:
    """Do not persist results."""

    def validate(self) -> bool:
        return True

    def save(
        self,
        outcomes: list[pool.Outcome],
        *,
        base: pathlib.Path,
        target: str,
        patcher: str,
    ) -> None:
        pass


@dataclasses.dataclass(frozen=True)
class _PathSavePlan:
    """Write the outcomes to one exact file."""

    path: pathlib.Path

    def validate(self) -> bool:
        parent = self.path.parent
        if not parent.is_dir():
            print(f'hyrum: error: save directory {parent} does not exist.', file=sys.stderr)
            return False
        if not os.access(parent, os.W_OK):
            print(f'hyrum: error: save directory {parent} is not writable.', file=sys.stderr)
            return False
        if self.path.is_dir():
            print(f'hyrum: error: save path {self.path} is a directory.', file=sys.stderr)
            return False
        return True

    def save(
        self,
        outcomes: list[pool.Outcome],
        *,
        base: pathlib.Path,
        target: str,
        patcher: str,
    ) -> None:
        _results.save(outcomes, self.path, base=base, target=target, patcher=patcher)
        _log_written(self.path, len(outcomes))


@dataclasses.dataclass(frozen=True)
class _DirectorySavePlan:
    """Base for the plans that write into a directory."""

    directory: pathlib.Path

    def validate(self) -> bool:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f'hyrum: error: cannot create save directory {self.directory}: {exc}',
                file=sys.stderr,
            )
            return False
        if not os.access(self.directory, os.W_OK):
            print(
                f'hyrum: error: save directory {self.directory} is not writable.',
                file=sys.stderr,
            )
            return False
        return True


@dataclasses.dataclass(frozen=True)
class _TimestampedSavePlan(_DirectorySavePlan):
    """Write a ``hyrum-<UTC>-<target>.json`` file into the directory."""

    def save(
        self,
        outcomes: list[pool.Outcome],
        *,
        base: pathlib.Path,
        target: str,
        patcher: str,
    ) -> None:
        path = self.directory / _results.timestamped_name(target)
        _results.save(outcomes, path, base=base, target=target, patcher=patcher)
        _log_written(path, len(outcomes))


@dataclasses.dataclass(frozen=True)
class _RollingSavePlan(_DirectorySavePlan):
    """Write the rolling ``<target>.auto.json`` pair into the directory."""

    def save(
        self,
        outcomes: list[pool.Outcome],
        *,
        base: pathlib.Path,
        target: str,
        patcher: str,
    ) -> None:
        path = _results.save_auto(
            outcomes, self.directory, target=target, base=base, patcher=patcher
        )
        _log_written(path, len(outcomes))


_SavePlan = _NoSavePlan | _PathSavePlan | _TimestampedSavePlan | _RollingSavePlan


def _resolve_save_plan(
    *,
    no_save: bool,
    save: pathlib.Path | None,
    auto_save: pathlib.Path | None,
    save_config: config_loader.SaveConfig | None,
) -> _SavePlan:
    """Fold the CLI flags and config default into a single :class:`_SavePlan`.

    Precedence: explicit CLI flag > config file > built-in default (auto-save
    to ``~/.cache/hyrum/results/``).
    """
    if no_save:
        return _NoSavePlan()
    if save is not None:
        if save.is_dir():
            return _TimestampedSavePlan(save)
        return _PathSavePlan(save)
    if auto_save is not None:
        return _RollingSavePlan(auto_save)
    # No CLI save flag: consult the config file, else fall back to auto-save.
    if save_config is not None:
        return _plan_from_config(save_config)
    return _RollingSavePlan(_default_auto_save_dir())


def _plan_from_config(save_config: config_loader.SaveConfig) -> _SavePlan:
    """Turn a validated ``save`` config setting into a plan."""
    if save_config.mode == 'off':
        return _NoSavePlan()
    if save_config.mode == 'auto':
        return _RollingSavePlan(save_config.path or _default_auto_save_dir())
    # The remaining modes all name a location; `_config` guarantees the path.
    assert save_config.path is not None
    if save_config.mode == 'timestamped':
        return _TimestampedSavePlan(save_config.path)
    if save_config.mode == 'file':
        return _PathSavePlan(save_config.path)
    # 'path': a location with no layout named, so pick by what's on disk.
    if save_config.path.is_dir():
        return _TimestampedSavePlan(save_config.path)
    return _PathSavePlan(save_config.path)


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
        help=(
            'TOML config file (the [ignore] table and the save setting are '
            'read today). [default: hyrum.toml]'
        ),
    )
    parser.add_argument('--repo', default='.*', help='Regex on the repo name. [default: .*]')
    parser.add_argument(
        '--limit',
        type=_non_negative_int,
        default=0,
        help='Stop after selecting this many charms to run (0 = all).',
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
        '--patch',
        dest='patches',
        action='append',
        type=_parse_patch,
        default=[],
        help=(
            'Swap a dependency. PEP 508 form, such as ``ops==2.17.0``, '
            '``ops @ canonical:fix/X`` (``owner:branch`` shorthand for ops or '
            'charmlibs-*), ``requests==2.31.0``, ``requests>=1.2,<2``, '
            '``requests @ git+https://github.com/psf/requests@main``, '
            '``mylib @ file:///abs/path``, or '
            '``charmlibs-nginx_k8s @ canonical:main`` to point a charmlib at '
            'a branch of canonical/charmlibs (type the package name with the '
            'same separators as the on-disk directory), or '
            '``charms.<author>.v<n>.<lib> -> <spec>`` to swap a vendored '
            'lib/charms/<author>/v<n>/<lib>.py file for a PyPI package '
            "(``<spec>`` accepts the same forms as above; for canonical's "
            'monorepo include ``#subdirectory=<lib>``). May be given multiple times. '
            'If not given (and ``--no-patch`` is not set), defaults to '
            '``ops @ canonical:main``. Mutually exclusive with ``--no-patch``.'
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
        '--preflight',
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            'Before running any charm, check that each --patch git ref exists in '
            'its remote and that the runner executables are installed, so a typo '
            'or a missing tool fails once rather than once per charm. Needs '
            'network access for the ref check. [default: enabled]'
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
            "Write each charm's runner output (stdout and stderr merged, in the "
            'order they were written) to a per-charm file under this directory. '
            'Useful for triaging failures without rerunning. '
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
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        '--save',
        dest='save_path',
        type=pathlib.Path,
        default=None,
        help=(
            'After the run, write the outcomes as JSON. If PATH is an existing '
            'directory, write a timestamped `hyrum-<UTC>-<target>.json` inside '
            'it; otherwise treat PATH as the exact output file. The file can '
            'later be fed to `hyrum compare`.'
        ),
    )
    save_group.add_argument(
        '--auto-save',
        dest='auto_save_dir',
        type=pathlib.Path,
        nargs='?',
        # `const` is not run through `type`, so a bare `--auto-save` becomes
        # True — unreachable for anything the user can type as a path.
        const=True,
        default=None,
        help=(
            'Write a rolling pair `<target>.auto.json` / `<target>.auto.prev.json` '
            'into DIR (default: ~/.cache/hyrum/results). Keyed on target so '
            'different runs do not clobber each other. This is the default '
            'when no --save/--auto-save/--no-save is given.'
        ),
    )
    save_group.add_argument(
        '--no-save',
        dest='no_save',
        action='store_true',
        help='Do not persist results after the run.',
    )
    parser.set_defaults(func=_run_check)
    return parser


def _add_compare_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        'compare',
        help='Diff two saved hyrum runs.',
        description=(
            'Diff two saved hyrum runs (status level): show new failures, resolved, new errors.'
        ),
    )
    parser.add_argument('baseline', type=pathlib.Path, help='Path to the baseline results JSON.')
    parser.add_argument('current', type=pathlib.Path, help='Path to the current results JSON.')
    parser.add_argument(
        '--fail-on-regression',
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            'Exit 1 on any regression: a charm that passed in the baseline now '
            'fails, or hits a new timeout or patcher error. Charms present in '
            'only one of the runs never count as regressions; if the two runs '
            'share no charms at all the gate cannot be evaluated and hyrum '
            'exits 2. [default: disabled]'
        ),
    )
    parser.add_argument(
        '--format',
        dest='output_format',
        choices=['text', 'markdown', 'json'],
        default='text',
        help=(
            'text: the colourised status-level summary. markdown: a table with one row '
            'per non-passing charm and a per-run failure summary. json: the same diff '
            "as a machine-readable object, with both runs' metadata. [default: text]"
        ),
    )
    parser.set_defaults(func=_run_compare)
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
    parser.add_argument(
        '--workers',
        type=int,
        default=get_charms.DEFAULT_WORKERS,
        help=(f'Maximum concurrent git subprocesses. [default: {get_charms.DEFAULT_WORKERS}]'),
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=get_charms.DEFAULT_TIMEOUT,
        help=(
            'Seconds before a single git clone or pull is abandoned; 0 waits forever. '
            f'[default: {get_charms.DEFAULT_TIMEOUT:g}]'
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
    _add_compare_subparser(subparsers)
    _add_get_charms_subparser(subparsers)
    return parser


def _run_check(args: argparse.Namespace) -> int:
    charms_dir: pathlib.Path = args.charms_dir or _default_charms_dir()
    if not charms_dir.is_dir():
        sys.exit(f'hyrum: error: --charms-dir: {charms_dir} is not a directory.')

    cfg = config_loader.load(args.config_path)
    auto_save_dir = args.auto_save_dir
    if auto_save_dir is True:
        auto_save_dir = _default_auto_save_dir()
    # Now either a path (flag given) or None (not given).
    save_plan = _resolve_save_plan(
        no_save=args.no_save,
        save=args.save_path,
        auto_save=auto_save_dir,
        save_config=cfg.save,
    )
    # Reject an unusable save target now, not after a multi-hour run.
    if not save_plan.validate():
        return 2

    _configure_logging(_resolve_log_level(quiet=args.quiet, verbosity=args.verbosity))
    if args.host_env_defaults:
        _apply_host_env_defaults(args.target)

    repos, skipped = _select_repos(
        charms_dir,
        config=cfg,
        repo_re=args.repo,
        limit=args.limit,
        framework=args.framework,
    )
    logger.info('Selected %d charm(s); skipping %d up-front.', len(repos), len(skipped))

    if args.no_patch and args.patches:
        raise SystemExit('--no-patch is mutually exclusive with --patch')
    seen_pkgs: set[str] = set()
    for spec in args.patches:
        if spec.pkg_name in seen_pkgs:
            raise SystemExit(f'--patch specified more than once for {spec.pkg_name!r}')
        seen_pkgs.add(spec.pkg_name)
    if args.no_patch:
        patch_specs: list[PatchSpec] = []
    elif args.patches:
        patch_specs = list(args.patches)
    else:
        patch_specs = [_DEFAULT_OPS_PATCH]
    if args.preflight and patch_specs:
        _preflight_patch_refs(patch_specs)
    patcher = _build_patcher(
        patches=patch_specs,
        poetry_executable=args.poetry_executable,
        uv_executable=args.uv_executable,
        lock_timeout=args.lock_timeout,
        auto_python=args.auto_python,
    )
    patcher_desc = _describe_patches(patch_specs)
    choice = runners.RunnerChoice(args.runner_choice)
    prefer = ('tox', 'make')
    if args.preflight:
        prefer = _available_backends(
            choice,
            tox_executable=args.tox_executable,
            make_executable=args.make_executable,
        )
    runner = _build_runner(
        choice=choice,
        tox_executable=args.tox_executable,
        make_executable=args.make_executable,
        timeout=args.timeout,
        prefer=prefer,
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

    try:
        save_plan.save(
            results,
            base=charms_dir,
            target=args.target,
            patcher=patcher_desc,
        )
    except OSError as exc:
        # Still render the report — the run itself succeeded, and the
        # printed output is all the user has left if the save was lost.
        logger.error('Cannot write results: %s', exc)
        save_failed = True
    else:
        save_failed = False

    if not args.quiet:
        report.render(
            results,
            base=charms_dir,
            target=args.target,
            verbose=args.verbose,
            no_headers=args.no_headers,
        )
    elif not pool.passed(results):
        failed = sum(
            1
            for o in results
            if o.status in ('failed', 'timeout', 'runner_error', 'patcher_error')
        )
        print(f'hyrum: {failed} charm(s) did not pass.', file=sys.stderr)

    if save_failed:
        return 1
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
    asyncio.run(get_charms.process_rows(rows, dest, workers=args.workers, timeout=args.timeout))
    return 0


def _describe_run(label: str, path: pathlib.Path, meta: _results.RunMeta) -> str:
    prefix = f'{label}: {path}'
    summary = meta.summary()
    return f'{prefix} — {summary}' if summary else prefix


def _run_compare(args: argparse.Namespace) -> int:
    try:
        baseline = _results.load(args.baseline)
        current = _results.load(args.current)
    except ValueError as exc:
        print(f'hyrum: error: {exc}', file=sys.stderr)
        # 2 = bad input, matching argparse, and distinct from 1 = the
        # --fail-on-regression gate tripping on a comparison that did run.
        return 2

    if (
        baseline.meta.target
        and current.meta.target
        and baseline.meta.target != current.meta.target
    ):
        print(
            f'hyrum: warning: comparing different targets: baseline ran '
            f'{baseline.meta.target!r}, current ran {current.meta.target!r}',
            file=sys.stderr,
        )

    result = _compare.diff(baseline.outcomes, current.outcomes)
    if result.disjoint:
        print(
            'hyrum: warning: the two runs have no charms in common — were they '
            'saved from different charm collections, or by a hyrum version that '
            'stored absolute paths?',
            file=sys.stderr,
        )

    if args.output_format == 'json':
        payload = {
            # Bump when the shape below changes incompatibly, so scripts
            # consuming this can tell which contract they are looking at.
            'version': _compare.JSON_FORMAT_VERSION,
            'baseline': {
                'path': str(args.baseline),
                'meta': dataclasses.asdict(baseline.meta),
            },
            'current': {
                'path': str(args.current),
                'meta': dataclasses.asdict(current.meta),
            },
            'diff': result.as_dict(),
        }
        print(json.dumps(payload, indent=2))
    elif args.output_format == 'markdown':
        target = current.meta.target or baseline.meta.target
        title = f'hyrum run comparison ({target})' if target else 'hyrum run comparison'
        _compare.render_markdown(baseline.outcomes, current.outcomes, result, title=title)
    else:
        print(_describe_run('Baseline', args.baseline, baseline.meta))
        print(_describe_run('Current', args.current, current.meta))
        print()
        _compare.render(result)

    if args.fail_on_regression:
        if result.disjoint:
            # The gate cannot be evaluated over runs with no charms in common;
            # exiting 0 would green-light a meaningless comparison.
            return 2
        if result.new_failures or result.new_errors:
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Bulk-run a check across many charm repositories with a dependency swapped out."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))
