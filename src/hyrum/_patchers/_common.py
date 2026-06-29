"""Shared helpers used by more than one patcher.

Anything ops- or charmlib-specific lives next to the patcher it belongs to;
this module only carries logic exercised by multiple patchers.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
import subprocess  # noqa: S404 — subprocess is core to running poetry/uv lock
from collections.abc import Sequence
from typing import Any

import packaging.requirements

logger = logging.getLogger(__name__)


def snapshot(path: pathlib.Path) -> str | None:
    """Read a file's content, or return ``None`` if it does not exist."""
    if not path.exists():
        return None
    return path.read_text()


def restore(path: pathlib.Path, original: str | None) -> None:
    """Restore ``path`` to ``original``; remove the file if it didn't exist before."""
    if original is None:
        if path.exists():
            path.unlink()
    else:
        path.write_text(original)


def _norm(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def collect_pyproject_pkg_extras(data: dict[str, Any], pkg_name: str) -> set[str]:
    """Collect all extras declared on ``pkg_name`` across every dep section."""
    extras: set[str] = set()

    def _extras_from_pep508_line(line: str) -> set[str]:
        try:
            req = packaging.requirements.Requirement(line)
        except packaging.requirements.InvalidRequirement:
            return set()
        if _norm(req.name) != _norm(pkg_name):
            return set()
        return set(req.extras)

    # tomllib returns nested Any; cast each step to a typed view so we can
    # destructure without lighting up pyright-strict.
    poetry: dict[str, Any] = data.get('tool', {}).get('poetry', {})
    for section in ('dependencies', 'dev-dependencies'):
        deps: Any = poetry.get(section, {})
        if isinstance(deps, dict):
            dep: Any = deps.get(pkg_name)
            if isinstance(dep, dict) and 'extras' in dep:
                extras.update(str(e) for e in dep['extras'])
    for group in poetry.get('group', {}).values():
        group_deps: Any = group.get('dependencies', {})
        if isinstance(group_deps, dict):
            dep = group_deps.get(pkg_name)
            if isinstance(dep, dict) and 'extras' in dep:
                extras.update(str(e) for e in dep['extras'])

    project: dict[str, Any] = data.get('project', {})
    for dep_str in project.get('dependencies', []):
        extras.update(_extras_from_pep508_line(str(dep_str)))
    for opts in project.get('optional-dependencies', {}).values():
        for dep_str in opts:
            extras.update(_extras_from_pep508_line(str(dep_str)))

    # PEP 735 [dependency-groups]: same shape as optional-dependencies but at
    # top-level. Used by uv-managed charms that don't put deps under [project].
    dep_groups: Any = data.get('dependency-groups', {})
    if isinstance(dep_groups, dict):
        for group_value in dep_groups.values():
            if isinstance(group_value, list):
                for dep_str in group_value:
                    extras.update(_extras_from_pep508_line(str(dep_str)))

    return extras


def pkg_is_declared(data: dict[str, Any], pkg_name: str) -> bool:
    """Return whether ``pkg_name`` is declared as a dep anywhere in ``data``.

    Mirrors the locations scanned by :func:`collect_pyproject_pkg_extras`:
    Poetry's ``dependencies`` / ``dev-dependencies`` / ``group.*.dependencies``,
    PEP 621 ``[project]`` dependencies and optional-dependencies, and
    PEP 735 ``[dependency-groups]``. Names are matched after PEP 503
    canonicalisation so ``Foo_Bar`` matches ``foo-bar``.
    """
    target = _norm(pkg_name)

    def _matches_pep508(line: str) -> bool:
        try:
            req = packaging.requirements.Requirement(line)
        except packaging.requirements.InvalidRequirement:
            return False
        return _norm(req.name) == target

    poetry: dict[str, Any] = data.get('tool', {}).get('poetry', {})
    for section in ('dependencies', 'dev-dependencies'):
        deps: Any = poetry.get(section, {})
        if isinstance(deps, dict):
            for name in deps:
                if _norm(str(name)) == target:
                    return True
    for group in poetry.get('group', {}).values():
        group_deps: Any = group.get('dependencies', {})
        if isinstance(group_deps, dict):
            for name in group_deps:
                if _norm(str(name)) == target:
                    return True

    project: dict[str, Any] = data.get('project', {})
    for dep_str in project.get('dependencies', []):
        if _matches_pep508(str(dep_str)):
            return True
    for opts in project.get('optional-dependencies', {}).values():
        for dep_str in opts:
            if _matches_pep508(str(dep_str)):
                return True

    dep_groups: Any = data.get('dependency-groups', {})
    if isinstance(dep_groups, dict):
        for group_value in dep_groups.values():
            if isinstance(group_value, list):
                for dep_str in group_value:
                    if _matches_pep508(str(dep_str)):
                        return True

    return False


def strip_dep_declaration(content: str, pkg_name: str) -> str:
    """Remove all declarations of ``pkg_name`` from pyproject.toml text.

    String-level edit; intentionally conservative (lines that mention
    the name in unrelated ways — table headers, etc. — are left alone).
    """
    out_lines: list[str] = []
    dep_re = re.compile(rf'^{re.escape(pkg_name)}(\s*[=><~\[]|\s|$)')
    for raw in content.splitlines(keepends=True):
        stripped = raw.split('#', 1)[0].strip().strip('"').strip("'")
        if dep_re.match(stripped):
            continue
        out_lines.append(raw)
    return ''.join(out_lines)


def detect_pyproject_flavour(parsed: dict[str, Any], uv_lock_present: bool) -> str:
    """Return ``"uv"`` / ``"poetry"`` / ``"pep621"`` / ``"unknown"``.

    A pyproject is treated as ``uv`` if it carries the uv signal (a
    ``[tool.uv]`` table or a ``uv.lock``) alongside deps declared in any
    of the standard PEP 621 / PEP 735 locations:
    ``[project.dependencies]``, ``[project.optional-dependencies]``, or
    ``[dependency-groups]``.
    """
    project = parsed.get('project', {})
    has_project_table = isinstance(project, dict) and bool(project)
    has_pep621_deps = (
        'dependencies' in project
        or 'optional-dependencies' in project
        or 'dependency-groups' in parsed
    )
    if has_pep621_deps and (uv_lock_present or 'uv' in parsed.get('tool', {})):
        return 'uv'
    if 'poetry' in parsed.get('tool', {}):
        return 'poetry'
    if has_pep621_deps or has_project_table:
        return 'pep621'
    return 'unknown'


def _extras_str(extras: Sequence[str]) -> str:
    return f'[{",".join(sorted(extras))}]' if extras else ''


def _pep508_for_git(url: str, branch: str | None, subdir: str | None) -> str:
    out = f'git+{url}@{branch}' if branch else f'git+{url}'
    if subdir:
        out += f'#subdirectory={subdir}'
    return out


def patch_git_dep(
    original: str,
    pkg_name: str,
    url: str,
    branch: str | None,
    subdir: str | None,
    extras: set[str],
    flavour: str,
) -> str:
    """Inject a single git-source dep for ``pkg_name`` into a pyproject.toml string.

    Strips any existing declaration of the package and rewrites for
    ``flavour`` (``"pep621"``, ``"uv"``, or ``"poetry"``).
    """
    extras_str = _extras_str(sorted(extras))
    pep508_url = _pep508_for_git(url, branch, subdir)

    if flavour == 'pep621':
        stripped = strip_dep_declaration(original, pkg_name)
        pkg_pep508 = f'{pkg_name}{extras_str} @ {pep508_url}'
        return _inject_pep621(stripped, pkg_pep508)

    if flavour == 'uv':
        subdir_part = f', subdirectory = "{subdir}"' if subdir else ''
        branch_part = f', branch = "{branch}"' if branch else ''
        source_line = f'{pkg_name} = {{ git = "{url}"{branch_part}{subdir_part} }}'
        return _inject_uv_source(original, source_line)

    if flavour == 'poetry':
        extras_list = (
            f', extras = [{", ".join(repr(e) for e in sorted(extras))}]' if extras else ''
        )
        subdir_part = f', subdirectory = "{subdir}"' if subdir else ''
        branch_part = f', branch = "{branch}"' if branch else ''
        pkg_toml = f'\n{pkg_name} = {{git = "{url}"{branch_part}{subdir_part}{extras_list}}}\n'
        content = strip_dep_declaration(original, pkg_name)
        return _inject_poetry(content, pkg_toml)

    raise ValueError(f'unknown flavour: {flavour}')


def patch_version_dep(
    original: str,
    pkg_name: str,
    specifier: str,
    extras: set[str],
    flavour: str,
) -> str:
    """Inject a single PyPI version specifier for ``pkg_name``.

    ``specifier`` is a PEP 440 specifier without the package name —
    ``"==1.2.3"``, ``">=1.2,<2"``, or ``"~=1.2.3"``. Any pre-existing
    declaration of ``pkg_name`` (including a ``[tool.uv.sources]`` entry)
    is removed so the version specifier actually wins.
    """
    extras_str = _extras_str(sorted(extras))

    if flavour == 'pep621':
        stripped = strip_dep_declaration(original, pkg_name)
        pkg_pep508 = f'{pkg_name}{extras_str}{specifier}'
        return _inject_pep621(stripped, pkg_pep508)

    if flavour == 'uv':
        # Drop any [tool.uv.sources] override so the PyPI version wins.
        stripped = _drop_uv_source(strip_dep_declaration(original, pkg_name), pkg_name)
        pkg_pep508 = f'{pkg_name}{extras_str}{specifier}'
        return _inject_pep621(stripped, pkg_pep508)

    if flavour == 'poetry':
        if extras:
            extras_repr = ', '.join(repr(e) for e in sorted(extras))
            rhs = f'{{ version = "{specifier}", extras = [{extras_repr}] }}'
        else:
            rhs = f'"{specifier}"'
        content = strip_dep_declaration(original, pkg_name)
        return _inject_poetry(content, f'\n{pkg_name} = {rhs}\n')

    raise ValueError(f'unknown flavour: {flavour}')


def patch_path_dep(
    original: str,
    pkg_name: str,
    path: str,
    extras: set[str],
    flavour: str,
) -> str:
    """Inject a single local-path dep for ``pkg_name``.

    ``path`` is an absolute filesystem path. For pep621 it is expressed
    as a ``file://`` PEP 508 URL; for uv/poetry the native ``path = ...``
    table form is used.
    """
    extras_str = _extras_str(sorted(extras))

    if flavour == 'pep621':
        stripped = strip_dep_declaration(original, pkg_name)
        pkg_pep508 = f'{pkg_name}{extras_str} @ file://{path}'
        return _inject_pep621(stripped, pkg_pep508)

    if flavour == 'uv':
        source_line = f'{pkg_name} = {{ path = "{path}" }}'
        return _inject_uv_source(original, source_line)

    if flavour == 'poetry':
        extras_list = (
            f', extras = [{", ".join(repr(e) for e in sorted(extras))}]' if extras else ''
        )
        pkg_toml = f'\n{pkg_name} = {{path = "{path}"{extras_list}}}\n'
        content = strip_dep_declaration(original, pkg_name)
        return _inject_poetry(content, pkg_toml)

    raise ValueError(f'unknown flavour: {flavour}')


def _inject_pep621(content: str, pkg_pep508: str) -> str:
    return content.replace(
        'dependencies = [',
        f'dependencies = [\n  "{pkg_pep508}",',
        1,
    )


def _inject_uv_source(content: str, source_line: str) -> str:
    if '[tool.uv.sources]' in content:
        return content.replace('[tool.uv.sources]', f'[tool.uv.sources]\n{source_line}', 1)
    return content.rstrip('\n') + f'\n\n[tool.uv.sources]\n{source_line}\n'


def _inject_poetry(content: str, pkg_toml: str) -> str:
    return content.replace(
        '[tool.poetry.dependencies]',
        f'[tool.poetry.dependencies]{pkg_toml}',
        1,
    )


def _drop_uv_source(content: str, pkg_name: str) -> str:
    """Remove a ``pkg = { ... }`` entry from ``[tool.uv.sources]``.

    Conservative: only touches the line immediately matching
    ``pkg_name = ...`` while we're inside the ``[tool.uv.sources]`` table.
    """
    out: list[str] = []
    in_sources = False
    section_re = re.compile(r'^\s*\[([^\]]+)\]\s*$')
    pkg_re = re.compile(rf'^\s*{re.escape(pkg_name)}\s*=')
    for raw in content.splitlines(keepends=True):
        header = section_re.match(raw)
        if header:
            in_sources = header.group(1).strip() == 'tool.uv.sources'
            out.append(raw)
            continue
        if in_sources and pkg_re.match(raw):
            continue
        out.append(raw)
    return ''.join(out)


def run_lock(
    repo: pathlib.Path,
    cmd: Sequence[str],
    timeout: int,
    *,
    on_failure_remove: pathlib.Path | None = None,
) -> None:
    """Best-effort regenerate a lockfile. Logs (never raises) on failure.

    Some charms have unresolvable dev dependencies under the patched
    source; in that case we just delete the lockfile so the runner can
    install without it.
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
