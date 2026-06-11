"""Patcher that points a charm's charmlib dependency at a git source.

Rewrites the charm's pip / Poetry / uv dependency declarations so that
a ``charmlibs-*`` package is pulled from a branch of the
``canonical/charmlibs`` monorepo instead of from PyPI.

The canonical/charmlibs monorepo layout has two namespaces:

* **General libs** — top-level directories, underscore-named.  PyPI
  package ``charmlibs-<name>``  maps to subdirectory ``<name_with_underscores>/``.
* **Interface libs** — under ``interfaces/<name>/``.  PyPI package
  ``charmlibs-interfaces-<name>`` maps to subdirectory
  ``interfaces/<name>/``.  Most interface directories are schema-only
  and have no ``pyproject.toml``; the patcher raises ``PatcherError``
  for those.

The patch is applied in a context manager and reversed on exit so the
cache folder stays clean across runs.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import pathlib
import shlex
import tomllib
from collections.abc import Generator, Sequence

from hyrum.patchers import base
from hyrum.patchers.ops_source import (
    _collect_pyproject_pkg_extras,
    _detect_pyproject_flavour,
    _patch_git_dep,
    _restore,
    _run_lock,
    _snapshot,
)

logger = logging.getLogger(__name__)

_CHARMLIBS_URL = 'https://github.com/canonical/charmlibs'


def _lib_names(user_name: str) -> tuple[str, str]:
    """Return ``(pypi_name, subdir)`` for a short or full charmlib name.

    Accepts either the short form (``nginx-k8s``) or the full PyPI name
    (``charmlibs-nginx-k8s``); both are normalised the same way.

    Examples::

        'nginx-k8s'                         -> ('charmlibs-nginx-k8s', 'nginx_k8s')
        'charmlibs-nginx-k8s'               -> ('charmlibs-nginx-k8s', 'nginx_k8s')
        'interfaces-tls-certificates'       -> ('charmlibs-interfaces-tls-certificates',
                                                'interfaces/tls-certificates')
        'charmlibs-interfaces-tls-certs'    -> ('charmlibs-interfaces-tls-certs',
                                                'interfaces/tls-certs')
    """
    short = user_name.removeprefix('charmlibs-')
    pypi_name = f'charmlibs-{short}'
    if short.startswith('interfaces-'):
        iface_name = short.removeprefix('interfaces-')
        return pypi_name, f'interfaces/{iface_name}'
    return pypi_name, short.replace('-', '_')


@dataclasses.dataclass(frozen=True)
class CharmlibSource:
    """Where to pull a charmlib from when patching a charm.

    ``pkg_name`` is either the short form (``nginx-k8s``) or the full
    PyPI name (``charmlibs-nginx-k8s``); ``_lib_names`` normalises both.
    """

    pkg_name: str
    url: str = _CHARMLIBS_URL
    branch: str | None = None
    poetry_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('poetry',))
    uv_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('uv',))
    lock_timeout: int = 600
    charmlibs_path: pathlib.Path | None = None

    @property
    def pypi_name(self) -> str:
        """Normalised PyPI package name, e.g. ``charmlibs-nginx-k8s``."""
        pypi, _ = _lib_names(self.pkg_name)
        return pypi

    @property
    def subdir(self) -> str:
        """Subdirectory path within the charmlibs monorepo, e.g. ``nginx_k8s``."""
        _, sub = _lib_names(self.pkg_name)
        return sub


class CharmlibPatcher:
    """Point a charm at a development charmlib source for the duration of a run."""

    def __init__(self, source: CharmlibSource):
        self.source = source

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Patch ``repo``'s charmlib dep to ``self.source``; restore on exit."""
        self._validate_interface_lib()

        pyproject = repo / 'pyproject.toml'
        if not pyproject.exists():
            raise base.PatcherError(f'{repo} has no pyproject.toml')

        yield from self._apply_pyproject(repo, pyproject)

    def _validate_interface_lib(self) -> None:
        """Raise PatcherError if this is an interface lib with no pyproject.toml."""
        subdir = self.source.subdir
        if not subdir.startswith('interfaces/'):
            return
        charmlibs_path = self.source.charmlibs_path
        if charmlibs_path is None:
            return
        pyproject = charmlibs_path / subdir / 'pyproject.toml'
        if not pyproject.exists():
            raise base.PatcherError(
                f'{self.source.pypi_name}: {subdir}/ in canonical/charmlibs has no '
                f'pyproject.toml — this interface library is not a published package'
            )

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
            extras = _collect_pyproject_pkg_extras(parsed, self.source.pypi_name)
            flavour = _detect_pyproject_flavour(parsed, uv_lock.exists())
            original_text = snapshots[pyproject] or ''

            if flavour not in ('uv', 'poetry', 'pep621'):
                raise base.PatcherError(
                    f'{pyproject} has no recognisable [project] or [tool.poetry] deps'
                )

            new_text = _patch_git_dep(
                original_text,
                self.source.pypi_name,
                self.source.url,
                self.source.branch,
                self.source.subdir,
                extras,
                flavour,
            )
            pyproject.write_text(new_text)

            if flavour == 'poetry':
                _run_lock(
                    repo,
                    (*shlex.split(' '.join(self.source.poetry_executable)), 'lock'),
                    self.source.lock_timeout,
                    on_failure_remove=poetry_lock,
                )
            elif flavour == 'uv' and uv_lock.exists():
                _run_lock(
                    repo,
                    (*self.source.uv_executable, 'lock'),
                    self.source.lock_timeout,
                )

            yield
        finally:
            for path, original in snapshots.items():
                _restore(path, original)
