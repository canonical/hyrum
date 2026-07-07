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
from collections.abc import Generator, Sequence

from hyrum._patchers import base
from hyrum._patchers._common import restore, snapshot
from hyrum._patchers.generic import DepSource, GenericDepPatcher

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class VendoredLibSwap:
    """Identify a vendored charm library and how to replace it.

    ``host_charm`` is the charm that publishes the library — it matches
    the directory name under ``lib/charms/`` (with underscores, e.g.
    ``operator_libs_linux``). ``version`` is the integer version (``0``
    for ``v0``). ``lib_name`` is the Python module name without ``.py``.

    ``source`` is the PyPI replacement, expressed with the same
    :class:`DepSource` shape :class:`GenericDepPatcher` accepts.

    By default the imports are rewritten to ``charmlibs.<lib_name>`` —
    the canonical layout of the ``charmlibs-*`` PyPI packages. Set
    ``new_module`` to override when the PyPI package exposes the library
    under a different dotted path.
    """

    host_charm: str
    version: int
    lib_name: str
    source: DepSource
    new_module: str | None = None

    @property
    def old_module(self) -> str:
        """Dotted module path the charm originally imported."""
        return f'charms.{self.host_charm}.v{self.version}.{self.lib_name}'

    @property
    def effective_new_module(self) -> str:
        """Dotted module path imports are rewritten to."""
        return self.new_module or f'charmlibs.{self.lib_name}'

    @property
    def vendored_relpath(self) -> pathlib.PurePosixPath:
        """Path of the vendored file inside the charm repo."""
        return pathlib.PurePosixPath(
            'lib', 'charms', self.host_charm, f'v{self.version}', f'{self.lib_name}.py'
        )

    @property
    def charm_libs_name(self) -> str:
        """``charm-libs`` ``lib:`` value for this library.

        ``charmcraft.yaml`` writes the charm with hyphens, even when the
        Python package uses underscores.
        """
        return f'{self.host_charm.replace("_", "-")}.{self.lib_name}'


class VendoredLibPatcher:
    """Swap a vendored ``lib/charms/...`` file for a PyPI package."""

    def __init__(self, swap: VendoredLibSwap):
        self.swap = swap

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Apply the swap to ``repo``; restore every touched file on exit."""
        vendored = repo / self.swap.vendored_relpath
        if not vendored.exists():
            raise base.PatcherSkip(
                base.PatcherSkipReason.VENDORED_LIB_ABSENT,
                f'vendored library {self.swap.vendored_relpath} not found',
            )

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

            with GenericDepPatcher(self.swap.source, on_absent='inject').apply(repo):
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


_CHARM_LIBS_HEADER_RE = re.compile(r'^charm-libs\s*:\s*(?P<rest>.*?)\s*(?:#.*)?$')
_CHARM_LIBS_DASH_RE = re.compile(r'^(?P<indent>\s+)-\s')
_CHARM_LIBS_KV_RE = re.compile(
    r'^\s*(?:-\s*)?(?P<key>[A-Za-z0-9_-]+)\s*:\s*(?P<value>.*?)\s*(?:#.*)?$'
)


def _strip_charm_libs_entry(content: str, charm_libs_name: str) -> str:
    """Remove the ``charm-libs`` block entry whose ``lib:`` matches ``charm_libs_name``.

    Scoped to the top-level ``charm-libs:`` section so unrelated
    ``- lib:`` lines elsewhere in ``charmcraft.yaml`` can't collide.
    Falls back to returning ``content`` unchanged if the block uses YAML
    flow style (``charm-libs: [ ... ]`` / ``{ ... }``) — we don't try to
    parse those without a YAML library.
    """
    lines = content.splitlines(keepends=True)
    header_idx = _find_charm_libs_header(lines)
    if header_idx is None:
        return content

    end_idx = _find_block_end(lines, header_idx + 1)
    block = lines[header_idx + 1 : end_idx]

    entries, prelude = _split_block_entries(block)
    if entries is None:
        return content

    kept = [entry for entry in entries if _entry_lib_name(entry) != charm_libs_name]
    if len(kept) == len(entries):
        return content

    new_block = ''.join(prelude) + ''.join(line for entry in kept for line in entry)
    return ''.join(lines[: header_idx + 1]) + new_block + ''.join(lines[end_idx:])


def _find_charm_libs_header(lines: Sequence[str]) -> int | None:
    """Return the index of the top-level ``charm-libs:`` line, or ``None``."""
    for i, raw in enumerate(lines):
        stripped = raw.rstrip('\n')
        if not stripped or stripped[:1].isspace() or stripped.startswith('#'):
            continue
        match = _CHARM_LIBS_HEADER_RE.match(stripped)
        if match is None:
            continue
        rest = match.group('rest')
        if rest.startswith(('[', '{')):
            logger.warning('flow-style charm-libs block, not stripping: %r', stripped)
            return None
        return i
    return None


def _find_block_end(lines: Sequence[str], start: int) -> int:
    """Return the first index >= ``start`` where the ``charm-libs`` block ends."""
    for j in range(start, len(lines)):
        stripped = lines[j].rstrip('\n')
        if not stripped.strip():
            continue
        if stripped.lstrip().startswith('#'):
            continue
        if not stripped[:1].isspace():
            return j
    return len(lines)


def _split_block_entries(
    block: Sequence[str],
) -> tuple[list[list[str]] | None, list[str]]:
    """Group ``block`` into sequence entries keyed by the leading ``-`` indent.

    Returns ``(entries, prelude)`` where ``prelude`` is any content
    (comments, blanks) before the first ``-``. Returns ``(None, [])`` if
    the block has no ``-`` entries at all.
    """
    first_indent: str | None = None
    for raw in block:
        match = _CHARM_LIBS_DASH_RE.match(raw.rstrip('\n'))
        if match is not None:
            first_indent = match.group('indent')
            break
    if first_indent is None:
        return None, []

    entries: list[list[str]] = []
    prelude: list[str] = []
    current: list[str] | None = None
    for raw in block:
        match = _CHARM_LIBS_DASH_RE.match(raw.rstrip('\n'))
        if match is not None and match.group('indent') == first_indent:
            if current is not None:
                entries.append(current)
            current = [raw]
        elif current is None:
            prelude.append(raw)
        else:
            current.append(raw)
    if current is not None:
        entries.append(current)
    return entries, prelude


def _entry_lib_name(entry: Sequence[str]) -> str | None:
    """Return the ``lib:`` value of a sequence ``entry``, or ``None`` if absent."""
    for raw in entry:
        stripped = raw.rstrip('\n')
        if not stripped.strip() or stripped.lstrip().startswith('#'):
            continue
        match = _CHARM_LIBS_KV_RE.match(stripped)
        if match is not None and match.group('key') == 'lib':
            return match.group('value').strip().strip('"').strip("'")
    return None
