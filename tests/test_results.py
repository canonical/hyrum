from __future__ import annotations

import os
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
    assert loaded.outcomes == original


def test_save_stores_charms_dir_relative_identity(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    base = pathlib.Path('/home/alice/.cache/hyrum/charms')
    outcomes = [pool.Outcome(repo=base / 'canonical' / 'foo', status='passed')]
    results_mod.save(outcomes, path, base=base)
    loaded = results_mod.load(path)
    assert loaded.outcomes[0].repo == pathlib.Path('canonical/foo')


def test_save_identity_survives_differently_spelled_base(tmp_path: pathlib.Path):
    # `--charms-dir ./cache` vs an absolute path must produce the same identity.
    cache = tmp_path / 'cache'
    (cache / 'canonical' / 'foo').mkdir(parents=True)
    outcomes = [pool.Outcome(repo=cache / 'canonical' / 'foo', status='passed')]
    path = tmp_path / 'out.json'
    results_mod.save(outcomes, path, base=pathlib.Path(os.path.relpath(cache)))
    loaded = results_mod.load(path)
    assert loaded.outcomes[0].repo == pathlib.Path('canonical/foo')


def test_save_is_atomic_no_temp_file_left(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results_mod.save(_outcomes(), path)
    assert path.exists()
    assert list(tmp_path.glob('*.tmp')) == []


def test_save_failure_leaves_no_temp_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'out.json'

    def boom(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        raise OSError('disk full')

    monkeypatch.setattr(pathlib.Path, 'replace', boom)
    with pytest.raises(OSError, match='disk full'):
        results_mod.save(_outcomes(), path)
    assert list(tmp_path.iterdir()) == []


def test_save_records_run_meta(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results_mod.save(
        [],
        path,
        base=pathlib.Path('/cache'),
        target='unit',
        patcher='ops @ https://github.com/canonical/operator@main',
    )
    meta = results_mod.load(path).meta
    assert meta.target == 'unit'
    assert meta.patcher == 'ops @ https://github.com/canonical/operator@main'
    assert meta.charms_dir == '/cache'
    assert meta.hyrum_version
    assert meta.created_at.endswith('Z')


def test_load_v2_file_has_empty_meta(tmp_path: pathlib.Path):
    path = tmp_path / 'v2.json'
    path.write_text('{"version": 2, "outcomes": []}')
    assert results_mod.load(path).meta == results_mod.RunMeta()


def test_load_meta_tolerates_unknown_keys(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 3, "meta": {"target": "lint", "shiny": "new"}, "outcomes": []}')
    assert results_mod.load(path).meta.target == 'lint'


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


def test_load_v1_file_leaves_summary_empty(tmp_path: pathlib.Path):
    path = tmp_path / 'v1.json'
    path.write_text(
        '{"version": 1, "outcomes": [{"repo": "/cache/x", "status": "failed", '
        '"runner": "tox", "target": "unit", "duration_s": 0.1, "returncode": 1, '
        '"skip_reason": "", "error": ""}]}'
    )
    loaded = results_mod.load(path)
    assert len(loaded.outcomes) == 1
    assert loaded.outcomes[0].summary == ''
    assert loaded.outcomes[0].status == 'failed'


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
    assert results_mod.load(path).outcomes == original
