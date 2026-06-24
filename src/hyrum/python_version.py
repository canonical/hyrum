"""Helpers for picking a Python interpreter matching a charm's requires-python.

Shared by the ops patcher (poetry-lock auto-Python) and the tox runner
(lint/unit auto-Python). The patcher wraps ``poetry lock``; the runner
wraps the whole tox invocation. Both need the same min-Python extraction
and the same ``uv run --python`` wrapping pattern.
"""

from __future__ import annotations

import logging
import pathlib
import re
import tomllib
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

# PEP 440 / Poetry shorthand Python lower-bound forms. Only lower-bound
# operators are considered because upper bounds (<, <=) don't widen the
# set of acceptable interpreters.
_PYTHON_BOUND_RE = re.compile(r'(>=|>|==|~=|~|\^)\s*(\d+)\.(\d+)')


def min_python_from_constraint(constraint: str) -> tuple[int, int] | None:
    """Return the lowest ``(major, minor)`` Python that satisfies ``constraint``.

    Accepts PEP 440 specifiers (``>=3.12,<4.0``) and Poetry shorthand
    (``^3.10``, ``~3.10``). Returns ``None`` if no lower bound is present.
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


def min_python_from_pyproject(parsed: dict[str, Any]) -> tuple[int, int] | None:
    """Extract the project's minimum Python from a parsed pyproject.toml."""
    project: dict[str, Any] = parsed.get('project', {})
    requires_python = project.get('requires-python')
    if isinstance(requires_python, str):
        bound = min_python_from_constraint(requires_python)
        if bound is not None:
            return bound
    poetry: dict[str, Any] = parsed.get('tool', {}).get('poetry', {})
    python_dep: Any = poetry.get('dependencies', {}).get('python')
    if isinstance(python_dep, str):
        return min_python_from_constraint(python_dep)
    if isinstance(python_dep, dict):
        version = python_dep.get('version')
        if isinstance(version, str):
            return min_python_from_constraint(version)
    return None


def min_python_for_repo(repo: pathlib.Path) -> tuple[int, int] | None:
    """Read ``repo/pyproject.toml`` and extract the minimum Python.

    Returns ``None`` if there is no pyproject, it does not parse, or no
    lower bound is declared.
    """
    pyproject = repo / 'pyproject.toml'
    if not pyproject.exists():
        return None
    try:
        parsed = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.debug('%s: cannot parse pyproject.toml: %s', repo, exc)
        return None
    return min_python_from_pyproject(parsed)


def wrap_with_uv_python(
    cmd: Sequence[str],
    py_version: tuple[int, int] | None,
    uv_executable: Sequence[str],
) -> tuple[str, ...]:
    """Prefix ``cmd`` with ``uv run --no-project --python X.Y --`` when ``py_version`` is set.

    ``--no-project`` keeps uv from interpreting the charm's ``pyproject.toml``
    as a uv project: some charms have a ``[project]`` table without a
    ``version`` (legal under Poetry's ``package-mode = false``, rejected by
    uv), which would otherwise abort ``uv run`` before it ever gets to
    invoke the wrapped command.
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
