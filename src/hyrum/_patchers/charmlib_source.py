"""Patcher that points a charm's charmlib dependency at a git source.

Rewrites the charm's pip / Poetry / uv dependency declarations so that
a ``charmlibs-*`` package is pulled from a branch of the
``canonical/charmlibs`` monorepo instead of from PyPI.

The canonical/charmlibs monorepo layout has two namespaces:

* **General libs** — top-level directories (mostly underscore-named).
* **Interface libs** — under ``interfaces/<name>/`` (a mix of
  underscored and hyphenated dirs).  Most interface directories are
  schema-only and have no ``pyproject.toml``; in that case the patcher
  raises ``PatcherError`` when ``charmlibs_path`` is set.

The subdirectory is taken from the ``--patch`` package name verbatim
(separators preserved), so the user picks the on-disk form: e.g.
``charmlibs-nginx_k8s``, ``charmlibs-interfaces-tls_certificates``, or
``charmlibs-interfaces-k8s-service``.  The PyPI name used to match the
charm's dependency is independently canonicalised to hyphens, so the
match still works regardless of which separators the user typed.

The patch is applied in a context manager and reversed on exit so the
cache folder stays clean across runs.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import pathlib
import re
import shlex
import tomllib
from collections.abc import Generator, Sequence

from hyrum._patchers import base
from hyrum._patchers._common import (
    collect_pyproject_pkg_extras,
    detect_pyproject_flavour,
    patch_git_dep,
    restore,
    run_lock,
    snapshot,
)

logger = logging.getLogger(__name__)

_CHARMLIBS_URL = 'https://github.com/canonical/charmlibs'


def _lib_names(user_name: str) -> tuple[str, str]:
    """Return ``(pypi_name, subdir)`` for a charmlib name.

    The PyPI name is canonicalised (lowercase, hyphen-separated) per
    PEP 503 so it matches whatever form the charm uses in its
    ``pyproject.toml``.  The subdirectory is taken from the input
    verbatim — separators are preserved — so the user controls the
    on-disk form.  Accepts either the short form (``nginx_k8s``) or
    the full package name (``charmlibs-nginx_k8s``).

    Examples::

        'nginx_k8s'                         -> ('charmlibs-nginx-k8s', 'nginx_k8s')
        'charmlibs-nginx_k8s'               -> ('charmlibs-nginx-k8s', 'nginx_k8s')
        'interfaces-tls_certificates'       -> ('charmlibs-interfaces-tls-certificates',
                                                'interfaces/tls_certificates')
        'charmlibs-interfaces-k8s-service'  -> ('charmlibs-interfaces-k8s-service',
                                                'interfaces/k8s-service')
    """
    rest = re.sub(r'^charmlibs[-_.]+', '', user_name, flags=re.IGNORECASE)
    pypi_name = 'charmlibs-' + re.sub(r'[-_.]+', '-', rest).lower()
    iface_match = re.match(r'^interfaces[-_.]+(.+)$', rest, flags=re.IGNORECASE)
    if iface_match:
        return pypi_name, f'interfaces/{iface_match.group(1)}'
    return pypi_name, rest


@dataclasses.dataclass(frozen=True)
class CharmlibSource:
    """Where to pull a charmlib from when patching a charm.

    ``pkg_name`` is either the short form (``nginx_k8s``) or the full
    package name (``charmlibs-nginx_k8s``).  The subdirectory inside
    the charmlibs monorepo is taken from ``pkg_name`` verbatim, so the
    separators the user types are what end up on disk.
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
            poetry_lock: snapshot(poetry_lock),
            uv_lock: snapshot(uv_lock),
        }

        try:
            parsed = tomllib.loads(snapshots[pyproject] or '')
        except tomllib.TOMLDecodeError as exc:
            raise base.PatcherError(f'could not parse {pyproject}: {exc}') from exc

        try:
            extras = collect_pyproject_pkg_extras(parsed, self.source.pypi_name)
            flavour = detect_pyproject_flavour(parsed, uv_lock.exists())
            original_text = snapshots[pyproject] or ''

            if flavour not in ('uv', 'poetry', 'pep621'):
                raise base.PatcherError(
                    f'{pyproject} has no recognisable [project] or [tool.poetry] deps'
                )

            new_text = patch_git_dep(
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
                run_lock(
                    repo,
                    (*shlex.split(' '.join(self.source.poetry_executable)), 'lock'),
                    self.source.lock_timeout,
                    on_failure_remove=poetry_lock,
                )
            elif flavour == 'uv' and uv_lock.exists():
                run_lock(
                    repo,
                    (*self.source.uv_executable, 'lock'),
                    self.source.lock_timeout,
                )

            yield
        finally:
            for path, original in snapshots.items():
                restore(path, original)
