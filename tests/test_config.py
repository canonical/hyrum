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


@pytest.mark.parametrize('value', ['"auto"', '"off"', '"~/results"'])
def test_save_string_values(tmp_path: pathlib.Path, value: str):
    p = tmp_path / 'hyrum.toml'
    p.write_text(f'save = {value}\n')
    assert config.load(p).save == value.strip('"')


def test_save_non_string_rejected(tmp_path: pathlib.Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('save = 3\n')
    with pytest.raises(ValueError, match='save in'):
        config.load(p)
