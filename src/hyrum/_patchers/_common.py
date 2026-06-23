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


def strip_dep_declaration(content: str, pkg_name: str) -> str:
    """Remove all declarations of ``pkg_name`` from pyproject.toml text.

    String-level edit; intentionally conservative (lines that mention
    the name in unrelated ways — table headers, etc. — are left alone).
    """
    out_lines: list[str] = []
    pep_re = re.compile(rf'^{re.escape(pkg_name)}\s*=')
    for raw in content.splitlines(keepends=True):
        stripped = raw.split('#', 1)[0].strip().strip('"').strip("'")
        if (
            stripped == pkg_name
            or stripped.startswith(f'{pkg_name} ')
            or stripped.startswith(f'{pkg_name}=')
            or stripped.startswith(f'{pkg_name}>')
            or stripped.startswith(f'{pkg_name}<')
            or stripped.startswith(f'{pkg_name}~')
            or stripped.startswith(f'{pkg_name}[')
            or pep_re.match(stripped)
        ):
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
