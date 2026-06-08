"""Patcher that points a charm's ``ops`` dependency at a git source.

Rewrites the charm's pip / Poetry / uv dependency declarations so that
``ops`` — and, when the charm uses them, its optional ``testing`` and
``tracing`` companion packages — are pulled from a git URL/branch
instead of from PyPI. The companion packages live in subdirectories of
the operator monorepo (``ops-scenario`` -> ``testing/``,
``ops-tracing`` -> ``tracing/``).

The patch is applied in a context manager and reversed on exit so the
cache folder stays clean across runs.

This module preserves the substantive behaviour of the original
``charm-analysis/tools/hyrum.py::patch_ops`` while splitting it into
smaller helpers. The string-based rewriting of pyproject.toml is
intentional: the stdlib only reads TOML, and a third-party round-trip
writer would alter the file's formatting (changing diffs in unrelated
places and breaking lockfile assumptions).
"""

from __future__ import annotations

import contextlib
import dataclasses
import itertools
import logging
import os
import pathlib
import re
import shlex
import subprocess  # noqa: S404 — subprocess is core to running poetry/uv lock
import tomllib
from collections.abc import Generator, Sequence
from typing import Any

import packaging.requirements

from hyrum.patchers import base

logger = logging.getLogger(__name__)


# Optional extras on the ``ops`` package map to companion packages that
# also live in the operator monorepo. When a charm asks for one of these
# extras, the companion must be sourced from the same git ref.
_COMPANION_PACKAGES: dict[str, tuple[str, str]] = {
    'testing': ('ops-scenario', 'testing'),
    'tracing': ('ops-tracing', 'tracing'),
}


@dataclasses.dataclass(frozen=True)
class OpsSource:
    """Where to pull ``ops`` from when patching a charm.

    Three source kinds, picked by which fields are set:

    - **git** (default): ``url`` plus optional ``branch`` — pulled via
      PEP 508 ``git+<url>[@branch]`` URLs. Companions come from the
      same ref via ``#subdirectory=<sub>``.
    - **path**: ``path`` — local operator checkout, expressed as a
      ``file://`` URL. Companions resolved by ``#subdirectory=<sub>``.
    - **pypi**: ``version`` — pin ops to a PyPI version. Companion
      packages are left untouched, since their versioning is independent
      of ``ops``.
    """

    url: str = 'https://github.com/canonical/operator'
    branch: str | None = None
    version: str | None = None
    path: str | None = None
    poetry_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('poetry',))
    uv_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('uv',))
    lock_timeout: int = 600
    auto_python: bool = True
    """If True, run ``poetry lock`` under an interpreter that satisfies the
    charm's declared Python constraint, via ``uv run --python X.Y``.

    Charms commonly declare a ``requires-python`` higher than hyrum's own
    interpreter, which causes ``poetry lock`` to abort with "Current Python
    version (…) is not allowed by the project". Wrapping with ``uv run`` lets
    uv fetch or select a satisfying interpreter on demand.
    """

    def __post_init__(self) -> None:
        if sum(x is not None for x in (self.version, self.path)) > 1:
            raise ValueError('OpsSource: set at most one of `version` and `path`')

    @property
    def kind(self) -> str:
        """Which source kind is in use: ``'git'``, ``'path'``, or ``'pypi'``."""
        if self.version is not None:
            return 'pypi'
        if self.path is not None:
            return 'path'
        return 'git'

    def _url(self, *, subdir: str | None = None) -> str:
        if self.kind == 'path':
            assert self.path is not None
            url = f'file://{self.path}'
        else:
            url = f'git+{self.url}'
            if self.branch:
                url = f'{url}@{self.branch}'
        if subdir:
            url = f'{url}#subdirectory={subdir}'
        return url

    def pep508_dep(
        self, name: str, *, extras: Sequence[str] = (), subdir: str | None = None
    ) -> str:
        """Full PEP 508 requirement line for ``name``."""
        extras_str = f'[{",".join(sorted(extras))}]' if extras else ''
        if self.kind == 'pypi':
            return f'{name}{extras_str}=={self.version}'
        return f'{name}{extras_str} @ {self._url(subdir=subdir)}'

    def overrides_companions(self) -> bool:
        """Whether companion packages should be swapped in alongside ops.

        Git/path point at an operator checkout whose companions are URL
        workspace deps and must come from the same ref. PyPI ops resolves
        companions from PyPI normally.
        """
        return self.kind != 'pypi'

    def uv_source_inline(self, *, subdir: str | None = None) -> str:
        """Right-hand side for ``pkg = ...`` in ``[tool.uv.sources]``."""
        if self.kind == 'path':
            parts = [f'path = "{self.path}"']
        else:
            parts = [f'git = "{self.url}"']
            if self.branch:
                parts.append(f'branch = "{self.branch}"')
        if subdir:
            parts.append(f'subdirectory = "{subdir}"')
        return '{ ' + ', '.join(parts) + ' }'

    def poetry_dep_inline(self, *, extras: Sequence[str] = (), subdir: str | None = None) -> str:
        """Right-hand side for ``pkg = ...`` in ``[tool.poetry.dependencies]``."""
        if self.kind == 'pypi':
            if not extras:
                return f'"=={self.version}"'
            extras_repr = ', '.join(repr(e) for e in sorted(extras))
            return f'{{ version = "=={self.version}", extras = [{extras_repr}] }}'
        if self.kind == 'path':
            parts = [f'path = "{self.path}"']
        else:
            parts = [f'git = "{self.url}"']
            if self.branch:
                parts.append(f'branch = "{self.branch}"')
        if subdir:
            parts.append(f'subdirectory = "{subdir}"')
        if extras:
            extras_repr = ', '.join(repr(e) for e in sorted(extras))
            parts.append(f'extras = [{extras_repr}]')
        return '{' + ', '.join(parts) + '}'


class OpsSourcePatcher:
    """Point a charm at a development ``ops`` source for the duration of a run."""

    def __init__(self, ops: OpsSource):
        self.ops = ops

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Patch ``repo``'s ops dep to ``self.ops``; restore every touched file on exit."""
        requirements = repo / 'requirements.txt'
        pyproject = repo / 'pyproject.toml'

        if requirements.exists():
            yield from self._apply_requirements(repo, requirements)
        elif pyproject.exists():
            yield from self._apply_pyproject(repo, pyproject)
        else:
            raise base.PatcherError(f'{repo} has neither requirements.txt nor pyproject.toml')

    def _apply_requirements(
        self, repo: pathlib.Path, requirements: pathlib.Path
    ) -> Generator[None, None, None]:
        snapshots: dict[pathlib.Path, str | None] = {requirements: requirements.read_text()}
        # Sibling requirements files often pin ops too; patch them all.
        for sibling in itertools.chain(
            repo.glob('requirements-*.txt'),
            repo.glob('*-requirements.txt'),
            repo.glob('requirements*.in'),
        ):
            if sibling in snapshots:
                continue
            snapshots[sibling] = sibling.read_text()
        try:
            for path in snapshots:
                _patch_requirements_file(path, self.ops)
            yield
        finally:
            for path, original in snapshots.items():
                _restore(path, original)

    def _apply_pyproject(
        self, repo: pathlib.Path, pyproject: pathlib.Path
    ) -> Generator[None, None, None]:
        poetry_lock = repo / 'poetry.lock'
        uv_lock = repo / 'uv.lock'
        snapshots: dict[pathlib.Path, str | None] = {
            pyproject: pyproject.read_text(),
            poetry_lock: _snapshot(poetry_lock),
            uv_lock: _snapshot(uv_lock),
        }

        try:
            parsed = tomllib.loads(snapshots[pyproject] or '')
        except tomllib.TOMLDecodeError as exc:
            raise base.PatcherError(f'could not parse {pyproject}: {exc}') from exc

        try:
            ops_extras = _collect_pyproject_ops_extras(parsed)
            flavour = _detect_pyproject_flavour(parsed, uv_lock.exists())
            original_text = snapshots[pyproject] or ''

            if flavour == 'uv':
                new_text = _patch_pyproject_uv(original_text, self.ops, ops_extras)
            elif flavour == 'poetry':
                new_text = _patch_pyproject_poetry(original_text, self.ops, ops_extras)
            elif flavour == 'pep621':
                new_text = _patch_pyproject_pep621(original_text, self.ops, ops_extras)
            else:
                raise base.PatcherError(
                    f'{pyproject} has no recognisable [project] or [tool.poetry] deps'
                )

            pyproject.write_text(new_text)

            # Re-parse the patched pyproject: ``_patch_pyproject_uv`` bumps
            # ``requires-python`` from 3.8/3.9 to 3.10 (ops's floor), so the
            # original parse would tell us to lock under an interpreter the
            # patched file now rejects.
            py_version: tuple[int, int] | None = None
            if self.ops.auto_python:
                try:
                    py_version = _min_python_from_pyproject(tomllib.loads(new_text))
                except tomllib.TOMLDecodeError:
                    py_version = _min_python_from_pyproject(parsed)

            if flavour == 'poetry':
                base_cmd = (*shlex.split(' '.join(self.ops.poetry_executable)), 'lock')
                _run_lock(
                    repo,
                    _wrap_with_uv_python(base_cmd, py_version, self.ops.uv_executable),
                    self.ops.lock_timeout,
                    on_failure_remove=poetry_lock,
                )
            # Only re-lock when uv.lock is checked in; otherwise the charm
            # regenerates it on demand and our re-lock would be wasted work.
            elif flavour == 'uv' and uv_lock.exists():
                uv_cmd: tuple[str, ...] = (*self.ops.uv_executable, 'lock')
                if py_version is not None:
                    uv_cmd = (*uv_cmd, '--python', f'{py_version[0]}.{py_version[1]}')
                _run_lock(
                    repo,
                    uv_cmd,
                    self.ops.lock_timeout,
                )

            yield
        finally:
            for path, original in snapshots.items():
                _restore(path, original)


def _snapshot(path: pathlib.Path) -> str | None:
    """Read a file's content, or return ``None`` if it does not exist."""
    if not path.exists():
        return None
    return path.read_text()


def _restore(path: pathlib.Path, original: str | None) -> None:
    if original is None:
        if path.exists():
            path.unlink()
    else:
        path.write_text(original)


def _ops_extras_from_pep508_line(line: str) -> set[str]:
    try:
        req = packaging.requirements.Requirement(line)
    except packaging.requirements.InvalidRequirement:
        return set()
    if req.name != 'ops':
        return set()
    return set(req.extras)


def _patch_requirements_file(path: pathlib.Path, ops: OpsSource) -> None:
    """Rewrite a pip-style requirements file in place.

    Removes any existing ``ops`` line, retains any other git-source
    line, and appends ``ops`` (with discovered extras) from ``ops``'s
    git URL. Companion packages for active extras are also appended.
    """
    original_lines = path.read_text().splitlines()
    kept: list[str] = []
    ops_extras: set[str] = set()

    for raw in original_lines:
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('--hash'):
            kept.append(raw)
            continue
        if line.startswith('git+https://github.com/canonical/operator'):
            # Already an ops git source — drop; we'll re-add ours below.
            continue
        if line.startswith('git+https://'):
            kept.append(raw)
            continue
        if line.startswith('-r '):
            # Recursive includes: leave alone; the loop driver patches each
            # requirements*.txt sibling, so transitively-included files
            # are handled when they are themselves enumerated.
            kept.append(raw)
            continue
        try:
            req = packaging.requirements.Requirement(line)
        except packaging.requirements.InvalidRequirement:
            kept.append(raw)
            continue
        if req.name == 'ops':
            ops_extras.update(req.extras)
            continue
        # Drop companion packages only when we'll re-add them from the
        # patched source below; for PyPI mode they resolve normally.
        if ops.overrides_companions() and req.name in {
            pkg for pkg, _ in _COMPANION_PACKAGES.values()
        }:
            continue
        kept.append(raw)

    kept.append(ops.pep508_dep('ops', extras=sorted(ops_extras)))
    if ops.overrides_companions():
        for extra, (pkg, subdir) in _COMPANION_PACKAGES.items():
            if extra in ops_extras:
                kept.append(ops.pep508_dep(pkg, subdir=subdir))

    path.write_text('\n'.join(kept) + '\n')


def _collect_pyproject_ops_extras(data: dict[str, Any]) -> set[str]:
    extras: set[str] = set()

    # tomllib returns nested Any; cast each step to a typed view so we can
    # destructure without lighting up pyright-strict.
    poetry: dict[str, Any] = data.get('tool', {}).get('poetry', {})
    for section in ('dependencies', 'dev-dependencies'):
        deps: Any = poetry.get(section, {})
        if isinstance(deps, dict):
            dep: Any = deps.get('ops')
            if isinstance(dep, dict) and 'extras' in dep:
                extras.update(str(e) for e in dep['extras'])
    for group in poetry.get('group', {}).values():
        group_deps: Any = group.get('dependencies', {})
        if isinstance(group_deps, dict):
            dep = group_deps.get('ops')
            if isinstance(dep, dict) and 'extras' in dep:
                extras.update(str(e) for e in dep['extras'])

    project: dict[str, Any] = data.get('project', {})
    for dep_str in project.get('dependencies', []):
        extras.update(_ops_extras_from_pep508_line(str(dep_str)))
    for opts in project.get('optional-dependencies', {}).values():
        for dep_str in opts:
            extras.update(_ops_extras_from_pep508_line(str(dep_str)))

    return extras


_OPS_LINE_RE = re.compile(r'^ops\s*=')


def _is_top_level_ops_dep_line(stripped: str) -> bool:
    """Heuristic: does this stripped line declare ``ops`` as a dep?"""
    if stripped == 'ops':
        return True
    for prefix in ('ops ', 'ops=', 'ops>', 'ops<', 'ops~', 'ops['):
        if stripped.startswith(prefix):
            return True
    return bool(_OPS_LINE_RE.match(stripped))


def _strip_ops_declarations(original: str) -> str:
    """Remove explicit ``ops`` declarations from pyproject.toml text.

    String-level edit; intentionally conservative (lines that mention
    ``ops`` in unrelated ways — table headers, etc. — are left alone).
    """
    out_lines: list[str] = []
    for raw in original.splitlines(keepends=True):
        stripped = raw.split('#', 1)[0].strip().strip('"').strip("'")
        if _is_top_level_ops_dep_line(stripped):
            continue
        out_lines.append(raw)
    return ''.join(out_lines)


def _strip_companion_declarations(content: str, pkg_name: str) -> str:
    out_lines: list[str] = []
    pep_re = re.compile(rf'^{re.escape(pkg_name)}\s*=')
    for raw in content.splitlines(keepends=True):
        stripped = raw.split('#', 1)[0].strip().strip('"').strip("'")
        if (
            stripped == pkg_name
            or stripped.startswith(f'{pkg_name} ')
            or stripped.startswith(f'{pkg_name}=')
            or pep_re.match(stripped)
        ):
            continue
        out_lines.append(raw)
    return ''.join(out_lines)


def _patch_pyproject_pep621(original: str, ops: OpsSource, ops_extras: set[str]) -> str:
    """Patch a PEP 621 ``[project.dependencies]`` pyproject (non-uv)."""
    stripped = _strip_ops_declarations(original)
    ops_pep508 = ops.pep508_dep('ops', extras=sorted(ops_extras))
    return stripped.replace(
        'dependencies = [',
        f'dependencies = [\n  "{ops_pep508}",',
        1,
    )


def _patch_pyproject_uv(original: str, ops: OpsSource, ops_extras: set[str]) -> str:
    """Patch a uv-managed pyproject.

    uv resolves the dependency graph itself, so the canonical way to
    point ``ops`` at a git source is ``[tool.uv.sources]``. Companion
    packages are always added as direct dependencies plus sources,
    regardless of whether the charm asked for the matching extra: the
    patched ``ops`` HEAD declares its companions as workspace URL deps,
    and uv requires URL deps on transitive packages to be hoisted to
    the top-level pyproject. A charm that pulls ``ops`` transitively
    (e.g. via ``coordinated-workers``) otherwise fails ``uv lock`` with
    "URL dependencies must be expressed as direct requirements".
    """
    if ops.kind == 'pypi':
        # PyPI ops pulls companions from PyPI normally — no source block,
        # no companion hoisting. Just rewrite the ops version pin in
        # [project.dependencies].
        stripped = _strip_ops_declarations(original)
        ops_pep508 = ops.pep508_dep('ops', extras=sorted(ops_extras))
        return stripped.replace(
            'dependencies = [',
            f'dependencies = [\n  "{ops_pep508}",',
            1,
        )

    del ops_extras  # uv hoists all companions unconditionally.
    source_lines: list[str] = [f'ops = {ops.uv_source_inline()}']
    companion_direct: list[str] = []
    for pkg, subdir in _COMPANION_PACKAGES.values():
        source_lines.append(f'{pkg} = {ops.uv_source_inline(subdir=subdir)}')
        companion_direct.append(pkg)

    block = '\n'.join(source_lines)
    if '[tool.uv.sources]' in original:
        out = original.replace(
            '[tool.uv.sources]',
            f'[tool.uv.sources]\n{block}',
            1,
        )
    else:
        out = original.rstrip('\n') + f'\n\n[tool.uv.sources]\n{block}\n'

    if companion_direct:
        dep_entries = ', '.join(f'"{d}"' for d in companion_direct)
        out = out.replace(
            'dependencies = [',
            f'dependencies = [\n  {dep_entries},',
            1,
        )

    # ops HEAD requires Python >=3.10; uv validates against every declared
    # interpreter version, so a lower requires-python causes spurious fails.
    out = re.sub(
        r'requires-python\s*=\s*"[~>]=3\.[89](\.\d+)?"',
        'requires-python = ">=3.10"',
        out,
    )
    return out


def _patch_pyproject_poetry(original: str, ops: OpsSource, ops_extras: set[str]) -> str:
    ops_toml = f'\nops = {ops.poetry_dep_inline(extras=sorted(ops_extras))}\n'

    content = _strip_ops_declarations(original)
    if ops.overrides_companions():
        for extra, (pkg, subdir) in _COMPANION_PACKAGES.items():
            if extra not in ops_extras:
                continue
            content = _strip_companion_declarations(content, pkg)
            ops_toml += f'\n{pkg} = {ops.poetry_dep_inline(subdir=subdir)}\n'

    return content.replace(
        '[tool.poetry.dependencies]',
        f'[tool.poetry.dependencies]{ops_toml}',
        1,
    )


def _detect_pyproject_flavour(parsed: dict[str, Any], uv_lock_present: bool) -> str:
    """Return ``"uv"`` / ``"poetry"`` / ``"pep621"`` / ``"unknown"``."""
    has_pep621_deps = 'dependencies' in parsed.get('project', {})
    if has_pep621_deps and (uv_lock_present or 'uv' in parsed.get('tool', {})):
        return 'uv'
    if 'poetry' in parsed.get('tool', {}):
        return 'poetry'
    if has_pep621_deps:
        return 'pep621'
    return 'unknown'


_PYTHON_BOUND_RE = re.compile(r'(>=|>|==|~=|~|\^)\s*(\d+)\.(\d+)')


def _min_python_from_constraint(constraint: str) -> tuple[int, int] | None:
    """Return the lowest ``(major, minor)`` Python that satisfies ``constraint``.

    Accepts PEP 440 specifiers (``>=3.12,<4.0``) and Poetry shorthand
    (``^3.10``, ``~3.10``). Only lower-bound operators are considered;
    upper bounds (``<``, ``<=``) are ignored because they don't widen the
    set of acceptable interpreters.

    Returns ``None`` if no lower bound is present.
    """
    bounds: list[tuple[int, int]] = []
    for op, major_s, minor_s in _PYTHON_BOUND_RE.findall(constraint):
        major, minor = int(major_s), int(minor_s)
        if op == '>':
            minor += 1
        bounds.append((major, minor))
    if not bounds:
        return None
    return max(bounds)


def _min_python_from_pyproject(parsed: dict[str, Any]) -> tuple[int, int] | None:
    """Extract the project's minimum Python from a parsed pyproject.toml."""
    project: dict[str, Any] = parsed.get('project', {})
    requires_python = project.get('requires-python')
    if isinstance(requires_python, str):
        bound = _min_python_from_constraint(requires_python)
        if bound is not None:
            return bound
    poetry: dict[str, Any] = parsed.get('tool', {}).get('poetry', {})
    python_dep: Any = poetry.get('dependencies', {}).get('python')
    if isinstance(python_dep, str):
        return _min_python_from_constraint(python_dep)
    if isinstance(python_dep, dict):
        version = python_dep.get('version')
        if isinstance(version, str):
            return _min_python_from_constraint(version)
    return None


def _wrap_with_uv_python(
    cmd: Sequence[str],
    py_version: tuple[int, int] | None,
    uv_executable: Sequence[str],
) -> tuple[str, ...]:
    """Prefix ``cmd`` with ``uv run --no-project --python X.Y --`` when ``py_version`` is set.

    ``--no-project`` keeps uv from interpreting the charm's ``pyproject.toml``
    as a uv project: some charms have a ``[project]`` table without a
    ``version`` (legal under Poetry's ``package-mode = false``, rejected by
    uv), which would otherwise abort ``uv run`` before it ever gets to
    invoke poetry.
    """
    if py_version is None:
        return tuple(cmd)
    return (
        *uv_executable,
        'run',
        '--no-project',
        '--python',
        f'{py_version[0]}.{py_version[1]}',
        '--',
        *cmd,
    )


def _run_lock(
    repo: pathlib.Path,
    cmd: Sequence[str],
    timeout: int,
    *,
    on_failure_remove: pathlib.Path | None = None,
) -> None:
    """Best-effort regenerate a lockfile. Logs (never raises) on failure.

    Some charms have unresolvable dev dependencies under the patched
    ``ops`` source; in that case we just delete the lockfile so the
    runner can install without it.
    """
    # Strip ``VIRTUAL_ENV`` so the charm's lock isn't pinned to hyrum's own
    # venv. Poetry in particular reads ``VIRTUAL_ENV`` to decide the project's
    # "current Python" and rejects ``poetry lock`` if it disagrees with the
    # project's requires-python — even when we wrap with ``uv run --python``.
    env = {k: v for k, v in os.environ.items() if k != 'VIRTUAL_ENV'}
    try:
        result = subprocess.run(  # noqa: S603 — cmd built from project config
            list(cmd),
            cwd=repo,
            check=False,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        logger.warning('%s not found, skipping lock for %s', cmd[0], repo)
        return
    except subprocess.TimeoutExpired:
        logger.warning('%s lock timed out after %ds for %s', cmd[0], timeout, repo)
        if on_failure_remove and on_failure_remove.exists():
            on_failure_remove.unlink()
        return
    if result.returncode != 0:
        logger.warning(
            '%s lock failed for %s: %s',
            cmd[0],
            repo,
            result.stderr.decode(errors='replace').strip(),
        )
        if on_failure_remove and on_failure_remove.exists():
            on_failure_remove.unlink()
