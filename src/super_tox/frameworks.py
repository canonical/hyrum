"""Detect which testing framework a charm's test suite uses.

Supports:

  * ``scenario`` — formerly a standalone PyPI package, now exposed as
    ``ops[testing]``; identified by import of ``scenario`` or any of the
    Scenario-specific names from ``ops.testing`` (to distinguish from
    the older ``Harness``-only usage of the same module).
  * ``jubilant`` — the integration-test library; identified by import of
    ``jubilant``.

Dependency declarations are cheaper to scan than parsing every test
file, so we check ``requirements*.txt`` and ``pyproject.toml`` first and
only fall back to AST scanning if nothing matched.
"""

from __future__ import annotations

import ast
import itertools
import logging
import tomllib
from collections.abc import Iterator
from pathlib import Path

import packaging.requirements

logger = logging.getLogger(__name__)

# Module names whose presence in test code indicates use of a framework.
_FRAMEWORK_IMPORTS: dict[str, set[str]] = {
    "scenario": {"scenario"},
    "jubilant": {"jubilant"},
}

# Names exposed via ``ops.testing`` that are unique to Scenario (as
# opposed to the older Harness-only public API of the same module).
_SCENARIO_OPS_TESTING_NAMES: set[str] = {
    "Context",
    "State",
    "Mount",
    "Relation",
    "CloudSpec",
    "Secret",
    "PeerRelation",
    "SubordinateRelation",
}

# Package names in dependency declarations that imply a framework.
# ``ops[testing]`` is handled out-of-band by checking the extras of any
# ``ops`` requirement.
_FRAMEWORK_DEPS: dict[str, set[str]] = {
    "scenario": {"ops-scenario"},
    "jubilant": {"jubilant"},
}


def supported_frameworks() -> tuple[str, ...]:
    return tuple(_FRAMEWORK_IMPORTS)


def _iter_test_files(tests_dir: Path) -> Iterator[Path]:
    if not tests_dir.exists():
        return
    for entry in tests_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            yield from _iter_test_files(entry)
        elif entry.suffix == ".py":
            yield entry


def _has_import(repo: Path, framework: str) -> bool:
    targets = _FRAMEWORK_IMPORTS.get(framework, set())
    for py_file in _iter_test_files(repo / "tests"):
        try:
            tree = ast.parse(py_file.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name in targets for alias in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in targets:
                    return True
                if (
                    framework == "scenario"
                    and node.module == "ops.testing"
                    and any(
                        alias.name in _SCENARIO_OPS_TESTING_NAMES
                        for alias in node.names
                    )
                ):
                    return True
    return False


def _req_matches(req: packaging.requirements.Requirement, framework: str) -> bool:
    if req.name in _FRAMEWORK_DEPS.get(framework, set()):
        return True
    return framework == "scenario" and req.name == "ops" and "testing" in req.extras


def _has_dep_in_requirements(req_path: Path, framework: str) -> bool:
    try:
        text = req_path.read_text()
    except (OSError, UnicodeDecodeError):
        return False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+")):
            continue
        try:
            req = packaging.requirements.Requirement(line)
        except packaging.requirements.InvalidRequirement:
            continue
        if _req_matches(req, framework):
            return True
    return False


def _has_dep_in_pyproject(pyproject_path: Path, framework: str) -> bool:
    try:
        data = tomllib.loads(pyproject_path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False

    dep_strings: list[str] = []
    dep_strings.extend(data.get("project", {}).get("dependencies", []))
    for optional in data.get("project", {}).get("optional-dependencies", {}).values():
        dep_strings.extend(optional)
    poetry = data.get("tool", {}).get("poetry", {})
    dep_strings.extend(poetry.get("dependencies", {}).keys())
    for group in poetry.get("group", {}).values():
        dep_strings.extend(group.get("dependencies", {}).keys())
    for dep in dep_strings:
        try:
            req = packaging.requirements.Requirement(dep)
        except packaging.requirements.InvalidRequirement:
            continue
        if _req_matches(req, framework):
            return True
    return False


def uses_framework(repo: Path, framework: str) -> bool:
    """Return True if ``repo``'s test suite uses ``framework``."""
    if framework not in _FRAMEWORK_IMPORTS:
        raise ValueError(
            f"unknown framework {framework!r}; expected one of {sorted(_FRAMEWORK_IMPORTS)}"
        )
    req_files = set(
        itertools.chain(
            repo.glob("requirements*.txt"),
            repo.glob("*-requirements.txt"),
        )
    )
    if any(_has_dep_in_requirements(rf, framework) for rf in req_files):
        return True
    if _has_dep_in_pyproject(repo / "pyproject.toml", framework):
        return True
    return _has_import(repo, framework)
