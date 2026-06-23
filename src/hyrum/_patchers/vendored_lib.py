"""Patcher that swaps a vendored charm library for a PyPI package.

Charms historically vendor charm libraries under
``lib/charms/<author>/v<n>/<lib>.py``, imported as
``charms.<author>.v<n>.<lib>``.  An equivalent PyPI distribution is
typically published under ``charmlibs-<lib>`` and imported as
``charmlibs.<lib>``.

The patch:

* deletes the vendored ``lib/charms/<author>/v<n>/<lib>.py`` file;
* adds the PyPI package to the charm's pyproject (via the same
  :class:`DepSource` shape :class:`GenericDepPatcher` uses, so all three
  source kinds — PyPI version, git URL, local path — are supported);
* rewrites imports of the old dotted module to the new one across
  ``src/`` and ``tests/``;
* removes the matching ``charm-libs`` entry from ``charmcraft.yaml`` so
  charmcraft will not try to re-fetch the library.

Every touched file (and the deleted vendored file) is snapshotted and
restored on context exit, so the cache stays clean across runs.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import pathlib
import re
from collections.abc import Generator

from hyrum._patchers import base
from hyrum._patchers._common import restore, snapshot
from hyrum._patchers.generic import DepSource, GenericDepPatcher

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class VendoredLibSwap:
    """Identify a vendored charm library and how to replace it.

    ``author`` matches the directory name under ``lib/charms/`` (it uses
    underscores in the Python package, e.g. ``operator_libs_linux``).
    ``version`` is the integer version (``0`` for ``v0``). ``lib_name``
    is the Python module name without ``.py``.

    ``source`` is the PyPI replacement, expressed with the same
    :class:`DepSource` shape :class:`GenericDepPatcher` accepts.

    By default the imports are rewritten to ``charmlibs.<lib_name>`` —
    the canonical layout of the ``charmlibs-*`` PyPI packages. Set
    ``new_module`` to override when the PyPI package exposes the library
    under a different dotted path.
    """

    author: str
    version: int
    lib_name: str
    source: DepSource
    new_module: str | None = None

    @property
    def old_module(self) -> str:
        """Dotted module path the charm originally imported."""
        return f'charms.{self.author}.v{self.version}.{self.lib_name}'

    @property
    def effective_new_module(self) -> str:
        """Dotted module path imports are rewritten to."""
        return self.new_module or f'charmlibs.{self.lib_name}'

    @property
    def vendored_relpath(self) -> pathlib.PurePosixPath:
        """Path of the vendored file inside the charm repo."""
        return pathlib.PurePosixPath(
            'lib', 'charms', self.author, f'v{self.version}', f'{self.lib_name}.py'
        )

    @property
    def charm_libs_name(self) -> str:
        """``charm-libs`` ``lib:`` value for this library.

        ``charmcraft.yaml`` writes the author with hyphens, even when the
        Python package uses underscores.
        """
        return f'{self.author.replace("_", "-")}.{self.lib_name}'


class VendoredLibPatcher:
    """Swap a vendored ``lib/charms/...`` file for a PyPI package."""

    def __init__(self, swap: VendoredLibSwap):
        self.swap = swap

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Apply the swap to ``repo``; restore every touched file on exit."""
        vendored = repo / self.swap.vendored_relpath
        if not vendored.exists():
            raise base.PatcherError(f'{repo}: vendored library {vendored} not found')

        sources = _collect_python_sources(repo)
        py_snapshots: dict[pathlib.Path, str] = {p: p.read_text() for p in sources}

        charmcraft = repo / 'charmcraft.yaml'
        charmcraft_snapshot = snapshot(charmcraft)

        vendored_snapshot = vendored.read_text()

        try:
            vendored.unlink()
            for path, original in py_snapshots.items():
                rewritten = _rewrite_imports(
                    original, self.swap.old_module, self.swap.effective_new_module
                )
                if rewritten != original:
                    path.write_text(rewritten)

            if charmcraft_snapshot is not None:
                stripped = _strip_charm_libs_entry(charmcraft_snapshot, self.swap.charm_libs_name)
                if stripped != charmcraft_snapshot:
                    charmcraft.write_text(stripped)

            with GenericDepPatcher(self.swap.source).apply(repo):
                yield
        finally:
            for path, original in py_snapshots.items():
                restore(path, original)
            restore(charmcraft, charmcraft_snapshot)
            if not vendored.exists():
                vendored.write_text(vendored_snapshot)


def _collect_python_sources(repo: pathlib.Path) -> list[pathlib.Path]:
    """Return every ``*.py`` under ``src/`` and ``tests/`` (sorted, deterministic)."""
    paths: list[pathlib.Path] = []
    for root in ('src', 'tests'):
        base_dir = repo / root
        if not base_dir.is_dir():
            continue
        paths.extend(p for p in base_dir.rglob('*.py') if p.is_file())
    return sorted(paths)


def _rewrite_imports(text: str, old_module: str, new_module: str) -> str:
    """Rewrite occurrences of ``old_module`` to ``new_module`` in Python source.

    Three forms are handled explicitly:

    1. ``from <old_parent> import <old_leaf>`` — the import lists the
       library as the leaf name (e.g. ``from charms.foo.v0 import apt``).
       Rewritten to ``from <new_parent> import <new_leaf>``. When the leaf
       names differ the original local binding is preserved with ``as``.
    2. ``from <old_module> import …`` and ``import <old_module>…`` — the
       dotted module appears directly. Handled by string substitution of
       the full dotted name, which is unambiguous because the prefix is
       qualified.
    3. Bare attribute references (``charms.foo.v0.apt.X``) — same
       string substitution as (2).
    """
    if old_module == new_module:
        return text

    old_parent, _, old_leaf = old_module.rpartition('.')
    new_parent, _, new_leaf = new_module.rpartition('.')

    pattern = re.compile(
        rf'^(?P<indent>[ \t]*)from {re.escape(old_parent)} import {re.escape(old_leaf)}'
        rf'(?P<rest>\b[^\n]*)',
        flags=re.MULTILINE,
    )

    def _form1(match: re.Match[str]) -> str:
        rest = match.group('rest')
        if ' as ' in rest or old_leaf == new_leaf:
            return f'{match.group("indent")}from {new_parent} import {new_leaf}{rest}'
        return f'{match.group("indent")}from {new_parent} import {new_leaf} as {old_leaf}{rest}'

    text = pattern.sub(_form1, text)
    return text.replace(old_module, new_module)


def _strip_charm_libs_entry(content: str, charm_libs_name: str) -> str:
    """Remove the ``charm-libs`` block entry whose ``lib:`` matches ``charm_libs_name``.

    Conservative line-based edit so we don't pull in a YAML dependency.
    Expects the canonical charmcraft layout, where each entry is a
    two-key block::

        charm-libs:
          - lib: operator-libs-linux.apt
            version: "0"

    Only the matching ``- lib: …`` line and the immediately following
    ``version:`` line at the same indent are removed. Entries with
    additional unknown keys are left untouched and logged.
    """
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    lib_re = re.compile(
        r'^(?P<indent>\s*)-\s*lib\s*:\s*["\']?'
        rf'{re.escape(charm_libs_name)}'
        r'["\']?\s*(#.*)?$'
    )
    while i < len(lines):
        match = lib_re.match(lines[i].rstrip('\n'))
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        indent = match.group('indent')
        # Skip the ``- lib:`` line.
        i += 1
        # Skip continuation lines of the same entry (indented deeper than the
        # ``-`` marker), conservatively limited to ``version:`` and comments.
        deeper = indent + ' '
        while i < len(lines):
            stripped = lines[i].rstrip('\n')
            if not stripped.strip():
                break
            if not stripped.startswith(deeper):
                break
            head = stripped.strip()
            if head.startswith('version:') or head.startswith('#'):
                i += 1
                continue
            logger.warning(
                'unexpected charm-libs entry continuation, leaving in place: %r',
                stripped,
            )
            out.append(lines[i])
            i += 1
    return ''.join(out)
