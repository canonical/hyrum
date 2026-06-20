"""Serialise and deserialise hyrum run results to/from JSON."""

from __future__ import annotations

import dataclasses
import json
import pathlib

from hyrum import _pool as pool

SCHEMA_VERSION = 1


def save(outcomes: list[pool.Outcome], path: pathlib.Path) -> None:
    """Serialise *outcomes* to a JSON file at *path* with a schema version header."""
    records = []
    for outcome in outcomes:
        record = dataclasses.asdict(outcome)
        record['repo'] = str(outcome.repo)
        records.append(record)
    path.write_text(json.dumps({'version': SCHEMA_VERSION, 'outcomes': records}, indent=2))


def load(path: pathlib.Path) -> list[pool.Outcome]:
    """Load outcomes from *path*; raises ``ValueError`` on schema version mismatch."""
    raw = json.loads(path.read_text())
    version = raw.get('version')
    if version != SCHEMA_VERSION:
        raise ValueError(
            f'schema version mismatch: file has {version!r}, expected {SCHEMA_VERSION}'
        )
    return [
        pool.Outcome(
            repo=pathlib.Path(str(record['repo'])),
            status=str(record['status']),
            runner=str(record.get('runner', '')),
            target=str(record.get('target', '')),
            duration_s=float(record.get('duration_s', 0.0)),
            returncode=int(record['returncode']) if record.get('returncode') is not None else None,
            skip_reason=str(record.get('skip_reason', '')),
            error=str(record.get('error', '')),
        )
        for record in raw['outcomes']
    ]
