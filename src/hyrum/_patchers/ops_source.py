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
import pathlib
import re
import shlex
import tomllib
from collections.abc import Generator, Sequence
from typing import Any

import packaging.requirements

from hyrum._patchers import base
from hyrum._patchers._common import (
    detect_pyproject_flavour,
    restore,
    run_lock,
    snapshot,
)

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
      same ref via ``#subdirectory=<sub>``. ``branch`` is interpolated
      raw into the git URL, so any ref git understands (tag, commit
      SHA) works in the same field.
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
        if self.version is not None and self.path is not None:
            raise ValueError('OpsSource: set at most one of `version` and `path`')

    @property
    def kind(self) -> str:
        """Which source kind is in use: ``'git'``, ``'path'``, or ``'pypi'``."""
        if self.version is not None:
            return 'pypi'
        if self.path is not None:
            return 'path'
        return 'git'

    def _source_url(self, *, subdir: str | None = None) -> str:
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
        return f'{name}{extras_str} @ {self._source_url(subdir=subdir)}'

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
                restore(path, original)

    def _apply_pyproject(
        self, repo: pathlib.Path, pyproject: pathlib.Path
    ) -> Generator[None, None, None]:
        poetry_lock = repo / 'poetry.lock'
        uv_lock = repo / 'uv.lock'
        snapshots: dict[pathlib.Path, str | None] = {
            pyproject: pyproject.read_text(),
            poetry_lock: snapshot(poetry_lock),
            uv_lock: snapshot(uv_lock),
        }

        try:
            parsed = tomllib.loads(snapshots[pyproject] or '')
        except tomllib.TOMLDecodeError as exc:
            raise base.PatcherSkip(
                base.PatcherSkipReason.MALFORMED_PYPROJECT,
                f'could not parse {pyproject}: {exc}',
            ) from exc

        try:
            ops_extras = _collect_pyproject_ops_extras(parsed)
            flavour = detect_pyproject_flavour(parsed, uv_lock.exists())
            original_text = snapshots[pyproject] or ''

            if flavour == 'uv':
                new_text = _patch_pyproject_uv(original_text, parsed, self.ops, ops_extras)
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
                run_lock(
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
                run_lock(
                    repo,
                    uv_cmd,
                    self.ops.lock_timeout,
                )

            yield
        finally:
            for path, original in snapshots.items():
                restore(path, original)


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

    # PEP 735 [dependency-groups]: same shape as optional-dependencies but at
    # top-level. Used by uv-managed charms that don't put deps under [project].
    dep_groups: Any = data.get('dependency-groups', {})
    if isinstance(dep_groups, dict):
        for group_value in dep_groups.values():
            if isinstance(group_value, list):
                for dep_str in group_value:
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


# Match quoted PEP 508 ops entries inside TOML arrays. The trailing lookahead
# constrains the match to a spot where TOML actually expects an array element
# — closing quote followed by a comma or array-close — so config values that
# just happen to be ``"ops"`` (like ``keywords = ["ops"]``) are skipped unless
# we're already inside a dep section.
_OPS_PEP508_RE = re.compile(
    r"""
    "               # opening quote of the array element
    \s* ops         # the package name (TOML allows leading whitespace in the string)
    (?![\w-])       # not followed by a name char: excludes ops-scenario, ops_helper, ...
    (\[[^\]"]*\])?  # capture the optional extras, e.g. [testing]
    [^"]*           # rest of the spec: version, marker, URL, ...
    "               # closing quote
    (?= \s* [,\]] ) # array-element context: comma or closing bracket follows
    """,
    re.VERBOSE,
)
_OPS_SCENARIO_PEP508_RE = re.compile(
    r"""
    "  \s* ops-scenario (?![\w-])  # the package name, not a longer namesake
    [^"]*  "                       # rest of the spec, then closing quote
    (?= \s* [,\]] )                # array-element context
    """,
    re.VERBOSE,
)
_OPS_TRACING_PEP508_RE = re.compile(
    r"""
    "  \s* ops-tracing (?![\w-])
    [^"]*  "
    (?= \s* [,\]] )
    """,
    re.VERBOSE,
)

_SECTION_HEADER_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')
_DEPS_ARRAY_OPENER_RE = re.compile(r'\s*dependencies\s*=\s*\[')
_NAMED_ARRAY_OPENER_RE = re.compile(r'\s*[A-Za-z_][\w-]*\s*=\s*\[')


def _rewrite_pep508_ops_strings(text: str, ops: OpsSource) -> str:
    """Rewrite quoted PEP 508 ops entries in-place to point at the git source.

    Targets ``"ops..."`` / ``"ops-scenario..."`` / ``"ops-tracing..."``
    strings inside sections that hold dep arrays — ``[project]``
    ``dependencies``, ``[project.optional-dependencies]``, and
    ``[dependency-groups]``. Other quoted ops-mentions
    (e.g. ``keywords = ["ops"]``, ``description = "ops charm"``) are left alone.
    """
    repl_scenario = f'"{ops.pep508_dep("ops-scenario", subdir="testing")}"'
    repl_tracing = f'"{ops.pep508_dep("ops-tracing", subdir="tracing")}"'

    def repl_ops(match: re.Match[str]) -> str:
        raw_extras = match.group(1) or ''
        extras = [e.strip() for e in raw_extras.strip('[]').split(',') if e.strip()]
        return f'"{ops.pep508_dep("ops", extras=extras)}"'

    section = ''
    bracket_depth = 0
    in_dep_array = False
    out_lines: list[str] = []

    for raw in text.splitlines(keepends=True):
        header = _SECTION_HEADER_RE.match(raw)
        if header:
            section = header.group(1).strip()
            bracket_depth = 0
            in_dep_array = False
            out_lines.append(raw)
            continue

        opt_or_group = (
            section == 'project.optional-dependencies'
            or section.startswith('project.optional-dependencies.')
            or section == 'dependency-groups'
            or section.startswith('dependency-groups.')
        )
        is_project = section == 'project'

        # Detect the start of a dep array on this line. Under [project] only
        # ``dependencies = [`` qualifies; under opt-deps / dep-groups any
        # ``name = [`` is a dep array by structure.
        opens_dep_array = False
        if bracket_depth == 0 and (
            (is_project and _DEPS_ARRAY_OPENER_RE.match(raw))
            or (opt_or_group and _NAMED_ARRAY_OPENER_RE.match(raw))
        ):
            opens_dep_array = True

        line_in_dep_array = in_dep_array or opens_dep_array
        if line_in_dep_array:
            raw = _OPS_PEP508_RE.sub(repl_ops, raw)
            raw = _OPS_SCENARIO_PEP508_RE.sub(lambda _m: repl_scenario, raw)
            raw = _OPS_TRACING_PEP508_RE.sub(lambda _m: repl_tracing, raw)

        # Update bracket depth from the (possibly rewritten) line.
        opens = raw.count('[')
        closes = raw.count(']')
        bracket_depth = max(0, bracket_depth + opens - closes)
        if opens_dep_array and bracket_depth > 0:
            in_dep_array = True
        if bracket_depth == 0:
            in_dep_array = False

        out_lines.append(raw)
    return ''.join(out_lines)


def _patch_pyproject_pep621(original: str, ops: OpsSource, ops_extras: set[str]) -> str:
    """Patch a PEP 621 pyproject (non-uv).

    Handles deps in any of the standard PEP 621 / PEP 735 locations:
    ``[project.dependencies]``, ``[project.optional-dependencies]``, and
    ``[dependency-groups]``. Each ``"ops..."`` PEP 508 string in those
    arrays is replaced in-place with the git-source form; the
    surrounding extras (e.g. ``[testing]``) are preserved.
    """
    out = _rewrite_pep508_ops_strings(original, ops)
    # If the rewrite didn't touch anything but ops *should* be present
    # (callers told us the charm uses ops, via discovered extras or by the
    # mere fact we're here), fall back to injecting a top-level dep so the
    # tox run picks ours up. This preserves prior behaviour for charms with
    # ``dependencies = [\n  "ops",\n  ...]`` where the literal string never
    # appeared because the line was something like ``"ops>=2.10",`` — the
    # rewriter handles that natively, so this fallback is mainly for empty
    # / unusual layouts.
    if out == original:
        ops_pep508 = ops.pep508_dep('ops', extras=sorted(ops_extras))
        out = out.replace(
            'dependencies = [',
            f'dependencies = [\n  "{ops_pep508}",',
            1,
        )
    return out


def _ops_bearing_dep_group_names(parsed: dict[str, Any]) -> list[str]:
    """Names of PEP 735 ``[dependency-groups]`` arrays that list ``ops``.

    Only direct declarations count; an entry like ``{include-group = "x"}``
    that transitively pulls ops is not picked up.
    """
    names: list[str] = []
    groups: Any = parsed.get('dependency-groups', {})
    if not isinstance(groups, dict):
        return names
    for name, entries in groups.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            try:
                req = packaging.requirements.Requirement(entry)
            except packaging.requirements.InvalidRequirement:
                continue
            if req.name == 'ops':
                names.append(str(name))
                break
    return names


def _patch_pyproject_uv(
    original: str,
    parsed: dict[str, Any],
    ops: OpsSource,
    ops_extras: set[str],
) -> str:
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

    The companion direct-deps are injected into every dep-list that
    declares ``ops`` — both ``[project.dependencies]`` and any PEP 735
    ``[dependency-groups].<name>`` arrays — so the hoist sits in the
    same resolution scope as ``ops`` itself.

    Direct ``"ops..."`` PEP 508 strings under
    ``[project.optional-dependencies]`` / ``[dependency-groups]`` are
    rewritten to their git-source forms so hard version pins
    (``"ops==2.21.1"``) don't conflict with the dev ops version uv would
    otherwise have to satisfy.
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

    out = _rewrite_pep508_ops_strings(original, ops)

    block = '\n'.join(source_lines)
    if '[tool.uv.sources]' in out:
        out = out.replace(
            '[tool.uv.sources]',
            f'[tool.uv.sources]\n{block}',
            1,
        )
    else:
        out = out.rstrip('\n') + f'\n\n[tool.uv.sources]\n{block}\n'

    dep_entries = ', '.join(f'"{d}"' for d in companion_direct)
    # PEP 621 project deps. Anchored at start-of-line so we don't match
    # the trailing "dependencies = [" inside e.g. build-constraint-dependencies.
    if 'dependencies' in parsed.get('project', {}):
        out = re.sub(
            r"""(?xm)
            ^ dependencies   # array name, must start the line
            \s* = \s* \[     # the array opener
            """,
            f'dependencies = [\n  {dep_entries},',
            out,
            count=1,
        )
    # PEP 735 dep-groups that declare ops directly. Same anchoring.
    for group_name in _ops_bearing_dep_group_names(parsed):
        out = re.sub(
            rf"""(?xm)
            ^ {re.escape(group_name)}   # the named group, must start the line
            \s* = \s* \[                # the array opener
            """,
            f'{group_name} = [\n    {dep_entries},',
            out,
            count=1,
        )

    # ops HEAD requires Python >=3.10; uv validates against every declared
    # interpreter version, so a lower requires-python causes spurious fails.
    out = re.sub(
        r"""(?x)
        requires-python \s* = \s*
        "                          # opening quote of the version specifier
        [~>] = 3 \. [89]           # ~=3.8/3.9 or >=3.8/3.9 — the values we lift
        (?: \. \d+ )?              # optional patch component, e.g. >=3.9.2
        "                          # closing quote
        """,
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
