from __future__ import annotations

import pathlib

import pytest

from hyrum import _pool as pool
from hyrum import _results as results_mod


def _outcomes() -> list[pool.Outcome]:
    return [
        pool.Outcome(
            repo=pathlib.Path('/cache/alpha'),
            status='passed',
            runner='tox',
            target='unit',
            duration_s=1.5,
            returncode=0,
        ),
        pool.Outcome(
            repo=pathlib.Path('/cache/beta'),
            status='failed',
            runner='tox',
            target='unit',
            duration_s=2.5,
            returncode=1,
        ),
        pool.Outcome(
            repo=pathlib.Path('/cache/gamma'),
            status='skipped',
            skip_reason='no charmcraft.yaml',
        ),
        pool.Outcome(
            repo=pathlib.Path('/cache/delta'),
            status='patcher_error',
            target='unit',
            error='lock failed',
        ),
    ]


def test_round_trip(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    original = _outcomes()
    results_mod.save(original, path)
    loaded = results_mod.load(path)
    assert loaded == original


def test_load_rejects_wrong_schema_version(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 999, "outcomes": []}')
    with pytest.raises(ValueError, match='schema version'):
        results_mod.load(path)


def test_load_missing_version_rejected(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"outcomes": []}')
    with pytest.raises(ValueError, match='schema version'):
        results_mod.load(path)


def test_save_includes_schema_version(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results_mod.save([], path)
    import json

    raw = json.loads(path.read_text())
    assert raw['version'] == results_mod.SCHEMA_VERSION
    assert raw['outcomes'] == []


def test_load_v1_file_leaves_summary_empty(tmp_path: pathlib.Path):
    path = tmp_path / 'v1.json'
    path.write_text(
        '{"version": 1, "outcomes": [{"repo": "/cache/x", "status": "failed", '
        '"runner": "tox", "target": "unit", "duration_s": 0.1, "returncode": 1, '
        '"skip_reason": "", "error": ""}]}'
    )
    loaded = results_mod.load(path)
    assert len(loaded) == 1
    assert loaded[0].summary == ''
    assert loaded[0].status == 'failed'


def test_round_trip_preserves_summary(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    original = [
        pool.Outcome(
            repo=pathlib.Path('/cache/beta'),
            status='failed',
            runner='tox',
            target='unit',
            duration_s=2.5,
            returncode=1,
            summary='3 failed, 10 passed; ValueError: bad',
        ),
    ]
    results_mod.save(original, path)
    assert results_mod.load(path) == original
