"""Load ``super-tox.toml``.

Only the ``[ignore]`` table is interpreted here today; other tables are
preserved as-is so callers can read tool-specific extensions without a
schema change in this module.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    ignore: dict[str, list[str]] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def load(path: Path) -> Config:
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    ignore = data.get("ignore", {})
    if not isinstance(ignore, dict):
        raise ValueError(f"[ignore] in {path} must be a table")
    cleaned: dict[str, list[str]] = {}
    for category, items in ignore.items():
        if not isinstance(items, list):
            raise ValueError(f"[ignore].{category} in {path} must be a list")
        cleaned[category] = [str(item) for item in items]
    return Config(ignore=cleaned, raw=data)
