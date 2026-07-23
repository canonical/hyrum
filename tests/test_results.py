from __future__ import annotations

import datetime
import os
import pathlib

import pytest

from hyrum import _pool as pool
from hyrum import _results as results


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
    results.save(original, path)
    loaded = results.load(path)
    assert loaded.outcomes == original


def test_save_stores_charms_dir_relative_identity(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    base = pathlib.Path('/home/alice/.cache/hyrum/charms')
    outcomes = [pool.Outcome(repo=base / 'canonical' / 'foo', status='passed')]
    results.save(outcomes, path, base=base)
    loaded = results.load(path)
    assert loaded.outcomes[0].repo == pathlib.Path('canonical/foo')


def test_save_identity_survives_differently_spelled_base(tmp_path: pathlib.Path):
    # `--charms-dir ./cache` vs an absolute path must produce the same identity.
    cache = tmp_path / 'cache'
    (cache / 'canonical' / 'foo').mkdir(parents=True)
    outcomes = [pool.Outcome(repo=cache / 'canonical' / 'foo', status='passed')]
    path = tmp_path / 'out.json'
    results.save(outcomes, path, base=pathlib.Path(os.path.relpath(cache)))
    loaded = results.load(path)
    assert loaded.outcomes[0].repo == pathlib.Path('canonical/foo')


def test_save_is_atomic_no_temp_file_left(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results.save(_outcomes(), path)
    assert path.exists()
    assert list(tmp_path.glob('*.tmp')) == []


def test_save_write_failure_removes_temp_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A crashed write leaves no half-written tmp file behind."""
    path = tmp_path / 'out.json'

    def boom(self: pathlib.Path, data: str, *args: object, **kwargs: object) -> int:
        raise OSError('disk full')

    monkeypatch.setattr(pathlib.Path, 'write_text', boom)
    with pytest.raises(OSError, match='disk full'):
        results.save(_outcomes(), path)
    assert list(tmp_path.iterdir()) == []


def test_save_replace_failure_preserves_temp_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """If the atomic rename fails, keep the fully-written tmp file for recovery."""
    path = tmp_path / 'out.json'

    def boom(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        raise OSError('cross-device')

    monkeypatch.setattr(pathlib.Path, 'replace', boom)
    with pytest.raises(OSError, match='cross-device'):
        results.save(_outcomes(), path)
    assert list(tmp_path.iterdir()) == [path.with_name(path.name + '.tmp')]


def test_save_records_run_meta(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results.save(
        [],
        path,
        base=pathlib.Path('/cache'),
        target='unit',
        patcher='ops @ https://github.com/canonical/operator@main',
    )
    meta = results.load(path).meta
    assert meta.target == 'unit'
    assert meta.patcher == 'ops @ https://github.com/canonical/operator@main'
    assert meta.charms_dir == '/cache'
    assert meta.hyrum_version
    assert meta.created_at.endswith('Z')


def test_load_meta_tolerates_unknown_keys(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 3, "meta": {"target": "lint", "shiny": "new"}, "outcomes": []}')
    assert results.load(path).meta.target == 'lint'


def test_load_rejects_wrong_schema_version(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 999, "outcomes": []}')
    with pytest.raises(ValueError, match='schema version'):
        results.load(path)


def test_load_missing_file_names_the_path(tmp_path: pathlib.Path):
    path = tmp_path / 'nope.json'
    with pytest.raises(ValueError, match=r'nope\.json'):
        results.load(path)


def test_load_invalid_json_names_the_path(tmp_path: pathlib.Path):
    path = tmp_path / 'corrupt.json'
    path.write_text('{"version": 2, "outcomes": [')
    with pytest.raises(ValueError, match=r'corrupt\.json.*invalid JSON'):
        results.load(path)


def test_load_rejects_non_object_top_level(tmp_path: pathlib.Path):
    path = tmp_path / 'list.json'
    path.write_text('[]')
    with pytest.raises(ValueError, match=r'list\.json.*top level'):
        results.load(path)


def test_load_rejects_missing_outcomes_list(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2}')
    with pytest.raises(ValueError, match='no outcomes list'):
        results.load(path)


def test_load_rejects_outcome_missing_status(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": [{"repo": "/cache/x"}]}')
    with pytest.raises(ValueError, match="missing 'status' in outcome 0"):
        results.load(path)


def test_load_rejects_non_object_outcome(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": ["oops"]}')
    with pytest.raises(ValueError, match='outcome 0 is not an object'):
        results.load(path)


def test_load_rejects_unknown_status(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"version": 2, "outcomes": [{"repo": "/cache/x", "status": "exploded"}]}')
    with pytest.raises(ValueError, match="unknown status 'exploded' in outcome 0"):
        results.load(path)


def test_load_rejects_bad_field_value(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text(
        '{"version": 2, "outcomes": '
        '[{"repo": "/cache/x", "status": "passed", "duration_s": "fast"}]}'
    )
    with pytest.raises(ValueError, match='bad value in outcome 0'):
        results.load(path)


def test_load_missing_version_rejected(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    path.write_text('{"outcomes": []}')
    with pytest.raises(ValueError, match='schema version'):
        results.load(path)


def test_save_includes_schema_version(tmp_path: pathlib.Path):
    path = tmp_path / 'out.json'
    results.save([], path)
    import json

    raw = json.loads(path.read_text())
    assert raw['version'] == results.SCHEMA_VERSION
    assert raw['outcomes'] == []


def test_timestamped_name_shape():
    when = datetime.datetime(2026, 7, 24, 14, 30, 12, tzinfo=datetime.UTC)
    assert results.timestamped_name('unit', now=when) == 'hyrum-20260724T143012Z-unit.json'


def test_timestamped_name_sanitises_target():
    when = datetime.datetime(2026, 7, 24, 14, 30, 12, tzinfo=datetime.UTC)
    # `/` and other unsafe characters get folded to `-`; nothing escapes the dir.
    got = results.timestamped_name('lint/quick', now=when)
    assert got == 'hyrum-20260724T143012Z-lint-quick.json'
    assert '/' not in got


def test_timestamped_name_empty_target():
    when = datetime.datetime(2026, 7, 24, 14, 30, 12, tzinfo=datetime.UTC)
    assert results.timestamped_name('', now=when) == 'hyrum-20260724T143012Z-run.json'


def test_save_auto_writes_current(tmp_path: pathlib.Path):
    written = results.save_auto(_outcomes(), tmp_path, target='unit')
    assert written == tmp_path / 'unit.auto.json'
    assert written.exists()
    # No previous yet; only the current file.
    assert not (tmp_path / 'unit.auto.prev.json').exists()


def test_save_auto_rotates_prior_to_prev(tmp_path: pathlib.Path):
    first = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='passed')]
    second = [pool.Outcome(repo=pathlib.Path('/cache/alpha'), status='failed')]
    results.save_auto(first, tmp_path, target='unit')
    results.save_auto(second, tmp_path, target='unit')
    current = results.load(tmp_path / 'unit.auto.json')
    previous = results.load(tmp_path / 'unit.auto.prev.json')
    assert current.outcomes[0].status == 'failed'
    assert previous.outcomes[0].status == 'passed'


def test_save_auto_keyed_by_target_does_not_clobber(tmp_path: pathlib.Path):
    # Two consecutive `unit` runs must not touch the `lint` baseline.
    results.save_auto(_outcomes(), tmp_path, target='lint')
    results.save_auto(_outcomes(), tmp_path, target='unit')
    results.save_auto(_outcomes(), tmp_path, target='unit')
    assert (tmp_path / 'lint.auto.json').exists()
    assert not (tmp_path / 'lint.auto.prev.json').exists()
    assert (tmp_path / 'unit.auto.json').exists()
    assert (tmp_path / 'unit.auto.prev.json').exists()


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
    results.save(original, path)
    assert results.load(path).outcomes == original
