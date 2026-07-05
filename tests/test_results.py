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


def test_load_missing_file_names_the_path(tmp_path: pathlib.Path):
    path = tmp_path / 'nope.json'
    with pytest.raises(ValueError, match=r'nope\.json'):
        results_mod.load(path)


def test_load_invalid_json_names_the_path(tmp_path: pathlib.Path):
    path = tmp_path / 'corrupt.json'
    path.write_text('{"version": 2, "outcomes": [')
    with pytest.raises(ValueError, match=r'corrupt\.json.*invalid JSON'):
        results_mod.load(path)


def test_load_rejects_non_object_top_level(tmp_path: pathlib.Path):
    path = tmp_path / 'list.json'
    path.write_text('[]')
    with pytest.raises(ValueError, match=r'list\.json.*top level'):
        results_mod.load(path)


def test_load_rejects_missing_outcomes_list(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2}')
    with pytest.raises(ValueError, match='no outcomes list'):
        results_mod.load(path)


def test_load_rejects_outcome_missing_status(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": [{"repo": "/cache/x"}]}')
    with pytest.raises(ValueError, match="missing 'status' in outcome 0"):
        results_mod.load(path)


def test_load_rejects_non_object_outcome(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": ["oops"]}')
    with pytest.raises(ValueError, match='outcome 0 is not an object'):
        results_mod.load(path)


def test_load_rejects_unknown_status(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": [{"repo": "/cache/x", "status": "exploded"}]}')
    with pytest.raises(ValueError, match="unknown status 'exploded' in outcome 0"):
        results_mod.load(path)


def test_load_rejects_bad_field_value(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text(
        '{"version": 2, "outcomes": '
        '[{"repo": "/cache/x", "status": "passed", "duration_s": "fast"}]}'
    )
    with pytest.raises(ValueError, match='bad value in outcome 0'):
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
