"""Patcher that points a charm's arbitrary dependency at a chosen source.

The companion to :class:`OpsSourcePatcher` / ``CharmlibPatcher`` for any
package that doesn't need special-case handling (no companion packages,
no python-version uplift). Three source kinds:

- **PyPI version specifier** — ``==1.2.3``, ``>=1.2,<2``, ``~=1.2.3``.
- **Git URL** — ``git+https://...`` with optional branch and subdirectory.
- **Local path** — an absolute path expressed as ``file://<path>``.

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

from hyrum._patchers import base
from hyrum._patchers._common import (
    collect_pyproject_pkg_extras,
    detect_pyproject_flavour,
    patch_git_dep,
    patch_path_dep,
    patch_version_dep,
    restore,
    run_lock,
    snapshot,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class DepSource:
    """Where to pull a dependency from when patching a charm.

    Pick a source kind by setting exactly one of ``version``, ``url``, or
    ``path``. ``branch`` and ``subdir`` apply only to the git kind.
    """

    pkg_name: str
    version: str | None = None
    url: str | None = None
    branch: str | None = None
    subdir: str | None = None
    path: str | None = None
    poetry_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('poetry',))
    uv_executable: Sequence[str] = dataclasses.field(default_factory=lambda: ('uv',))
    lock_timeout: int = 600

    def __post_init__(self) -> None:
        set_fields = [f for f in ('version', 'url', 'path') if getattr(self, f) is not None]
        if len(set_fields) != 1:
            raise ValueError(
                f'DepSource: set exactly one of `version`, `url`, `path`; got {set_fields}'
            )
        if self.version is not None and (self.branch is not None or self.subdir is not None):
            raise ValueError('DepSource: `branch`/`subdir` only apply when `url` is set')
        if self.path is not None and (self.branch is not None or self.subdir is not None):
            raise ValueError('DepSource: `branch`/`subdir` only apply when `url` is set')

    @property
    def kind(self) -> str:
        """Which source kind is in use: ``'pypi'``, ``'git'``, or ``'path'``."""
        if self.version is not None:
            return 'pypi'
        if self.url is not None:
            return 'git'
        return 'path'


class GenericDepPatcher:
    """Point a charm at a chosen source for a single dependency."""

    def __init__(self, source: DepSource):
        self.source = source

    @contextlib.contextmanager
    def apply(self, repo: pathlib.Path) -> Generator[None, None, None]:
        """Patch ``repo``'s declaration of ``self.source.pkg_name``; restore on exit."""
        pyproject = repo / 'pyproject.toml'
        if not pyproject.exists():
            raise base.PatcherError(f'{repo} has no pyproject.toml')

        yield from self._apply_pyproject(repo, pyproject)

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
            extras = collect_pyproject_pkg_extras(parsed, self.source.pkg_name)
            flavour = detect_pyproject_flavour(parsed, uv_lock.exists())
            original_text = snapshots[pyproject] or ''

            if flavour not in ('uv', 'poetry', 'pep621'):
                raise base.PatcherError(
                    f'{pyproject} has no recognisable [project] or [tool.poetry] deps'
                )

            new_text = self._rewrite(original_text, extras, flavour)
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

    def _rewrite(self, original: str, extras: set[str], flavour: str) -> str:
        src = self.source
        if src.kind == 'pypi':
            assert src.version is not None
            return patch_version_dep(original, src.pkg_name, src.version, extras, flavour)
        if src.kind == 'git':
            assert src.url is not None
            return patch_git_dep(
                original, src.pkg_name, src.url, src.branch, src.subdir, extras, flavour
            )
        assert src.path is not None
        return patch_path_dep(original, src.pkg_name, src.path, extras, flavour)
