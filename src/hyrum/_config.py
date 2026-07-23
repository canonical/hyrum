"""Load ``hyrum.toml``.

Only the ``[ignore]`` table is interpreted here today; other tables are
preserved as-is so callers can read tool-specific extensions without a
schema change in this module.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tomllib
from typing import Any


@dataclasses.dataclass(frozen=True)
class Config:
    """Parsed ``hyrum.toml``: ignore table + the raw mapping for callers."""

    ignore: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    save: str | None = None
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
    save: str | None = None
    if 'save' in data:
        raw_save = data['save']
        if not isinstance(raw_save, str):
            raise ValueError(f'save in {path} must be a string ("auto", "off", or a path)')
        save = raw_save
    return Config(ignore=cleaned, save=save, raw=data)
