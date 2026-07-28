"""Load ``hyrum.toml``.

Only the ``[ignore]`` table and the ``save`` setting are interpreted here
today; other tables are preserved as-is so callers can read tool-specific
extensions without a schema change in this module.

``save`` takes either a bare string::

    save = "auto"        # or "off", or a path

or a table, which is the only form that can pin down both the layout and
the location::

    [save]
    mode = "auto"        # auto | off | file | timestamped
    path = "~/runs"      # optional for auto, required for file/timestamped
"""

from __future__ import annotations

import dataclasses
import pathlib
import tomllib
from typing import Any

SAVE_MODES = ('auto', 'off', 'file', 'timestamped')


@dataclasses.dataclass(frozen=True)
class SaveConfig:
    """Normalised ``save`` setting: what to do, and optionally where.

    ``mode`` is one of :data:`SAVE_MODES`, or ``'path'`` for the bare-string
    form that names a location without saying which layout to use — the
    caller picks ``file`` or ``timestamped`` by looking at the path.
    """

    mode: str
    path: pathlib.Path | None = None


@dataclasses.dataclass(frozen=True)
class Config:
    """Parsed ``hyrum.toml``: ignore table + the raw mapping for callers."""

    ignore: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    save: SaveConfig | None = None
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)


def load(path: pathlib.Path) -> Config:
    """Load the config from ``path``; return an empty Config if it doesn't exist."""
    if not path.exists():
        return Config()
    data: dict[str, Any] = tomllib.loads(path.read_text())
    ignore: Any = data.get('ignore', {})
    if not isinstance(ignore, dict):
        raise ValueError(f'[ignore] in {path} must be a table')
    cleaned: dict[str, list[str]] = {}
    items: Any
    for category, items in ignore.items():
        if not isinstance(items, list):
            raise ValueError(f'[ignore].{category} in {path} must be a list')
        cleaned[str(category)] = [str(item) for item in items]
    save = _parse_save(data['save'], path) if 'save' in data else None
    return Config(ignore=cleaned, save=save, raw=data)


def _parse_save(raw: Any, path: pathlib.Path) -> SaveConfig:
    """Normalise the ``save`` setting, which is either a string or a table."""
    if isinstance(raw, str):
        setting = raw.strip()
        if setting.lower() in ('auto', 'off'):
            return SaveConfig(mode=setting.lower())
        return SaveConfig(mode='path', path=pathlib.Path(setting).expanduser())
    if not isinstance(raw, dict):
        raise ValueError(f'save in {path} must be a string ("auto", "off", or a path) or a table')
    table: dict[str, Any] = raw
    unknown = set(table) - {'mode', 'path'}
    if unknown:
        keys = ', '.join(sorted(unknown))
        raise ValueError(f'[save] in {path} has unknown keys: {keys}')
    raw_path: Any = table.get('path')
    if raw_path is not None and not isinstance(raw_path, str):
        raise ValueError(f'[save].path in {path} must be a string')
    save_path = pathlib.Path(raw_path).expanduser() if raw_path is not None else None
    raw_mode: Any = table.get('mode')
    if raw_mode is None:
        if save_path is None:
            raise ValueError(f'[save] in {path} must set mode, path, or both')
        # A location with no layout named: let the caller pick, as for the
        # bare-string form.
        return SaveConfig(mode='path', path=save_path)
    if not isinstance(raw_mode, str):
        raise ValueError(f'[save].mode in {path} must be a string')
    mode = raw_mode.strip().lower()
    if mode not in SAVE_MODES:
        modes = ', '.join(SAVE_MODES)
        raise ValueError(f'[save].mode in {path} must be one of: {modes}')
    if mode == 'off' and save_path is not None:
        raise ValueError(f'[save].path in {path} is meaningless with mode = "off"')
    if mode in ('file', 'timestamped') and save_path is None:
        raise ValueError(f'[save].path in {path} is required with mode = "{mode}"')
    return SaveConfig(mode=mode, path=save_path)
