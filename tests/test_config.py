from __future__ import annotations

import pathlib

import pytest

from hyrum import _config as config


def test_missing_returns_empty(tmp_path: pathlib.Path):
    cfg = config.load(tmp_path / 'missing.toml')
    assert cfg.ignore == {}


def test_loads_ignore_categories(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[ignore]\nexpensive = ["argo-operators"]\nmanual = ["opensearch-operator"]\n')
    cfg = config.load(p)
    assert cfg.ignore['expensive'] == ['argo-operators']
    assert cfg.ignore['manual'] == ['opensearch-operator']


def test_bad_ignore_shape_raises(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[ignore]\nexpensive = "argo"\n')
    with pytest.raises(ValueError):
        config.load(p)


def test_save_default_is_none(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('')
    assert config.load(p).save is None


@pytest.mark.parametrize('value', ['auto', 'off'])
def test_save_string_keywords(tmp_path: pathlib.Path, value: str):
    p = tmp_path / 'hyrum.toml'
    p.write_text(f'save = "{value}"\n')
    assert config.load(p).save == config.SaveConfig(mode=value)


def test_save_string_path_defers_layout(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('save = "~/results"\n')
    assert config.load(p).save == config.SaveConfig(
        mode='path', path=pathlib.Path('~/results').expanduser()
    )


def test_save_non_string_rejected(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('save = 3\n')
    with pytest.raises(ValueError, match='save in'):
        config.load(p)


def test_save_table_mode_and_path(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[save]\nmode = "auto"\npath = "~/runs"\n')
    assert config.load(p).save == config.SaveConfig(
        mode='auto', path=pathlib.Path('~/runs').expanduser()
    )


def test_save_table_auto_without_path(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[save]\nmode = "auto"\n')
    assert config.load(p).save == config.SaveConfig(mode='auto')


def test_save_table_path_only_defers_layout(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[save]\npath = "/runs"\n')
    assert config.load(p).save == config.SaveConfig(mode='path', path=pathlib.Path('/runs'))


@pytest.mark.parametrize(
    ('body', 'match'),
    [
        ('[save]\nmode = "sideways"\n', 'must be one of'),
        ('[save]\nmode = "file"\n', 'required with mode'),
        ('[save]\nmode = "timestamped"\n', 'required with mode'),
        ('[save]\nmode = "off"\npath = "/runs"\n', 'meaningless'),
        ('[save]\nmode = 3\n', 'must be a string'),
        ('[save]\npath = 3\n', 'must be a string'),
        ('[save]\nmmode = "auto"\n', 'unknown keys'),
        ('[save]\n', 'must set mode, path, or both'),
    ],
)
def test_save_table_errors(tmp_path: pathlib.Path, body: str, match: str):
    p = tmp_path / 'hyrum.toml'
    p.write_text(body)
    with pytest.raises(ValueError, match=match):
        config.load(p)
