"""Load ``hyrum.toml``.

Only the ``[ignore]`` table is interpreted here today; other tables are
preserved as-is so callers can read tool-specific extensions without a
schema change in this module.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    """Parsed ``hyrum.toml``: ignore table + the raw mapping for callers."""

    ignore: dict[str, list[str]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def load(path: Path) -> Config:
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
    return Config(ignore=cleaned, raw=data)
