"""Choose the Python interpreter a charm's checks run under.

Left alone, tox builds its environments with the interpreter tox itself runs
on, and uv with whatever it finds first, which on a current host is a newer
Python than most charms have ever been tested against. Charms pin
dependencies that don't build or import there (pydantic 1, old PyO3 crates,
``ast.Str``), and those failures get reported as the charm's.

So hyrum picks an interpreter per charm: the preferred version (``--python``)
when the charm's ``requires-python`` allows it, and otherwise the installed
version closest to it that the charm does allow. Only ``pythonX.Y`` executables
on PATH count as installed, because that is how tox finds an interpreter.
"""

from __future__ import annotations

import logging
import pathlib
import re
import shutil
import tomllib
from collections.abc import Iterable, Sequence
from typing import Any

import packaging.specifiers

logger = logging.getLogger(__name__)

Version = tuple[int, int]

DEFAULT = (3, 12)
"""What GitHub's ``ubuntu-latest`` runners have, so what most charms' CI uses."""

_CANDIDATE_MINORS = range(8, 20)

_VERSION_RE = re.compile(r'^3\.(\d+)$')


def parse_version(text: str) -> Version:
    """Parse ``3.Y`` into a version tuple, raising ``ValueError`` otherwise."""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        raise ValueError(f'expected a Python version like 3.12, got {text!r}')
    return 3, int(match.group(1))


def format_version(version: Version) -> str:
    """Return ``version`` as ``X.Y``."""
    return f'{version[0]}.{version[1]}'


def discover() -> tuple[Version, ...]:
    """Return the ``python3.Y`` versions installed on PATH, oldest first."""
    return tuple((3, minor) for minor in _CANDIDATE_MINORS if shutil.which(f'python3.{minor}'))


def _poetry_to_pep440(constraint: str) -> list[str]:
    """Translate a Poetry ``python`` constraint into PEP 440 specifier sets.

    Returns one set per ``||`` alternative. Poetry's caret, tilde, and bare
    versions have no PEP 440 spelling, so they are expanded here.
    """
    alternatives: list[str] = []
    for alternative in constraint.split('||'):
        clauses: list[str] = []
        # ">= 3.8, < 4" -> ">=3.8", "<4": glue each operator to its version
        # first, so that the remaining whitespace only separates clauses.
        glued = re.sub(r'([<>=!~^]+)\s+', r'\1', alternative)
        for clause in re.split(r'[,\s]+', glued.strip()):
            if not clause or clause == '*':
                continue
            if clause.startswith('^'):
                parts = clause[1:].split('.')
                clauses += [f'>={clause[1:]}', f'<{int(parts[0]) + 1}']
            elif clause.startswith('~') and not clause.startswith('~='):
                parts = clause[1:].split('.')
                upper = (
                    f'{parts[0]}.{int(parts[1]) + 1}' if len(parts) > 1 else str(int(parts[0]) + 1)
                )
                clauses += [f'>={clause[1:]}', f'<{upper}']
            elif clause[0].isdigit():
                clauses.append(f'=={clause}')
            else:
                clauses.append(clause)
        alternatives.append(','.join(clauses))
    return alternatives


def requires_python(repo: pathlib.Path) -> list[packaging.specifiers.SpecifierSet] | None:
    """Return the charm's Python constraint, or ``None`` if it doesn't declare one.

    The constraint is a list of alternatives, any of which is enough. It comes
    from ``[project] requires-python``, or failing that from Poetry's
    ``python`` dependency. A constraint that can't be parsed counts as no
    constraint, so the charm still gets the preferred version.
    """
    try:
        parsed = tomllib.loads((repo / 'pyproject.toml').read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    texts: list[str] = []
    project: dict[str, Any] = parsed.get('project', {})
    declared = project.get('requires-python')
    if isinstance(declared, str):
        texts = [declared]
    else:
        poetry: dict[str, Any] = parsed.get('tool', {}).get('poetry', {})
        python_dep: Any = poetry.get('dependencies', {}).get('python')
        if isinstance(python_dep, dict):
            python_dep = python_dep.get('version')
        if isinstance(python_dep, str):
            texts = _poetry_to_pep440(python_dep)
    if not texts or not all(text.strip() for text in texts):
        # Nothing declared, or an alternative that allows anything ("*").
        return None
    try:
        specs = [packaging.specifiers.SpecifierSet(text) for text in texts]
    except packaging.specifiers.InvalidSpecifier:
        logger.debug('ignoring unparsable Python constraint in %s: %s', repo, texts)
        return None
    return specs


def _allows(specs: Sequence[packaging.specifiers.SpecifierSet] | None, version: Version) -> bool:
    if specs is None:
        return True
    # A bound can fall inside a minor series (">=3.10.6", "<3.12.3"), and any
    # interpreter in the series might satisfy it, so try both ends.
    releases = [f'{version[0]}.{version[1]}.0', f'{version[0]}.{version[1]}.99']
    return any(spec.contains(release) for spec in specs for release in releases)


def choose(
    specs: Sequence[packaging.specifiers.SpecifierSet] | None,
    preferred: Version,
    available: Iterable[Version],
) -> Version | None:
    """Return the version to run a charm under, or ``None`` to leave it to the runner.

    ``preferred`` wins when the charm allows it and it is installed. Otherwise
    the closest installed version the charm allows is used, the newer of two
    equally close ones. ``None`` means nothing installed satisfies the charm.
    """
    allowed = [version for version in available if _allows(specs, version)]
    if not allowed:
        return None
    return min(allowed, key=lambda v: (abs(v[1] - preferred[1]), -v[1]))


class Selector:
    """Pick the interpreter for each charm, as ``X.Y``, or ``None`` for no override."""

    def __init__(self, preferred: Version, available: Sequence[Version]):
        self.preferred = preferred
        self.available = tuple(available)

    def __call__(self, repo: pathlib.Path) -> str | None:
        """Return the version to run ``repo``'s checks under."""
        specs = requires_python(repo)
        version = choose(specs, self.preferred, self.available)
        if version is None:
            logger.warning(
                'no installed Python satisfies %s (%s); leaving the choice to the runner',
                repo,
                ' or '.join(str(spec) for spec in specs or []),
            )
            return None
        return format_version(version)
