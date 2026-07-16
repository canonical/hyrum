"""Serialise and deserialise hyrum run results to/from JSON."""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib

from hyrum import _pool as pool
from hyrum import _version

SCHEMA_VERSION = 3
_SUPPORTED_VERSIONS = frozenset({1, 2, 3})


@dataclasses.dataclass(frozen=True)
class RunMeta:
    """Metadata about the run a results file was saved from.

    All fields are empty strings when unknown (files saved by older hyrum
    versions carry no metadata).
    """

    created_at: str = ''
    hyrum_version: str = ''
    target: str = ''
    patcher: str = ''
    charms_dir: str = ''

    def summary(self) -> str:
        """Human-readable ``saved X, target Y, patch Z`` string, empty if unknown."""
        bits: list[str] = []
        if self.created_at:
            bits.append(f'saved {self.created_at}')
        if self.target:
            bits.append(f'target {self.target}')
        if self.patcher:
            bits.append(f'patch {self.patcher}')
        return ', '.join(bits)


@dataclasses.dataclass(frozen=True)
class RunResults:
    """One loaded results file: the outcomes plus the run's metadata."""

    outcomes: list[pool.Outcome]
    meta: RunMeta


def _identity(repo: pathlib.Path, base: pathlib.Path | None) -> str:
    """Return a host-independent identity for *repo*: its path under *base*.

    The cache layout is ``<charms-dir>/<owner>/<leaf>``, so relative to the
    charms dir the identity is ``owner/leaf`` — stable across hosts,
    checkouts, and however the user spelled ``--charms-dir``. Falls back to
    the raw path when *repo* is not under *base*.
    """
    if base is None:
        return str(repo)
    try:
        return str(repo.relative_to(base))
    except ValueError:
        pass
    try:
        return str(repo.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(repo)


def save(
    outcomes: list[pool.Outcome],
    path: pathlib.Path,
    *,
    base: pathlib.Path | None = None,
    target: str = '',
    patcher: str = '',
) -> None:
    """Serialise *outcomes* to a JSON file at *path* with a schema version header.

    *base* is the charms dir; repo paths are stored relative to it so that
    two runs from different hosts or checkouts compare by charm, not by
    where the cache happened to live.
    """
    records = []
    for outcome in outcomes:
        record = dataclasses.asdict(outcome)
        record['repo'] = _identity(outcome.repo, base)
        records.append(record)
    meta = RunMeta(
        created_at=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
        hyrum_version=_version.__version__,
        target=target,
        patcher=patcher,
        charms_dir=str(base) if base is not None else '',
    )
    document = {
        'version': SCHEMA_VERSION,
        'meta': dataclasses.asdict(meta),
        'outcomes': records,
    }
    # Write-then-rename so a crash mid-write can't leave a truncated JSON
    # file that a later `hyrum compare` chokes on.
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(json.dumps(document, indent=2))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


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


def _load_meta(raw: dict[str, object], *, path: pathlib.Path) -> RunMeta:
    """Build a RunMeta from the raw ``meta`` block, tolerating absent/extra keys."""
    block = raw.get('meta')
    if block is None:
        return RunMeta()
    if not isinstance(block, dict):
        raise ValueError(f'{path}: not a hyrum results file (meta is not an object)')
    known = {f.name for f in dataclasses.fields(RunMeta)}
    return RunMeta(**{str(k): str(v) for k, v in block.items() if k in known})


def load(path: pathlib.Path) -> RunResults:
    """Load a results file from *path*.

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
    return RunResults(
        outcomes=[
            _load_outcome(record, path=path, index=index) for index, record in enumerate(outcomes)
        ],
        meta=_load_meta(raw, path=path),
    )
