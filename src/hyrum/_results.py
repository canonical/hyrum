"""Serialise and deserialise hyrum run results to/from JSON."""

from __future__ import annotations

import dataclasses
import json
import pathlib

from hyrum import _pool as pool

SCHEMA_VERSION = 2
_SUPPORTED_VERSIONS = frozenset({1, 2})


def save(outcomes: list[pool.Outcome], path: pathlib.Path) -> None:
    """Serialise *outcomes* to a JSON file at *path* with a schema version header."""
    records = []
    for outcome in outcomes:
        record = dataclasses.asdict(outcome)
        record['repo'] = str(outcome.repo)
        records.append(record)
    path.write_text(json.dumps({'version': SCHEMA_VERSION, 'outcomes': records}, indent=2))


def _load_outcome(record: object, *, path: pathlib.Path, index: int) -> pool.Outcome:
    """Build one Outcome from a raw JSON record, rejecting malformed shapes."""
    if not isinstance(record, dict):
        raise ValueError(f'{path}: not a hyrum results file (outcome {index} is not an object)')
    for required in ('repo', 'status'):
        if required not in record:
            raise ValueError(
                f'{path}: not a hyrum results file (missing {required!r} in outcome {index})'
            )
    status = str(record['status'])
    if status not in pool.OUTCOME_STATUSES:
        raise ValueError(
            f'{path}: unknown status {status!r} in outcome {index} '
            f'(file written by a newer hyrum, or hand-edited?)'
        )
    try:
        return pool.Outcome(
            repo=pathlib.Path(str(record['repo'])),
            status=status,
            runner=str(record.get('runner', '')),
            target=str(record.get('target', '')),
            duration_s=float(record.get('duration_s', 0.0)),
            returncode=int(record['returncode']) if record.get('returncode') is not None else None,
            skip_reason=str(record.get('skip_reason', '')),
            error=str(record.get('error', '')),
            summary=str(record.get('summary', '')),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'{path}: not a hyrum results file (bad value in outcome {index}: {exc})'
        ) from exc


def load(path: pathlib.Path) -> list[pool.Outcome]:
    """Load outcomes from *path*.

    Older v1 files load fine — the ``summary`` field added in v2 is left empty.

    This is the validation boundary for user-supplied results files: any
    unreadable, non-JSON, or wrong-shape input raises :class:`ValueError`
    with a message that names the offending file.
    """
    try:
        text = path.read_text()
    except OSError as exc:
        raise ValueError(f'{path}: {exc.strerror or exc}') from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f'{path}: not a hyrum results file (invalid JSON: {exc}; was the save interrupted?)'
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(f'{path}: not a hyrum results file (top level is not an object)')
    version = raw.get('version')
    if version not in _SUPPORTED_VERSIONS:
        raise ValueError(
            f'{path}: schema version mismatch: file has {version!r}, '
            f'expected one of {sorted(_SUPPORTED_VERSIONS)}'
        )
    outcomes = raw.get('outcomes')
    if not isinstance(outcomes, list):
        raise ValueError(f'{path}: not a hyrum results file (no outcomes list)')
    return [_load_outcome(record, path=path, index=index) for index, record in enumerate(outcomes)]
