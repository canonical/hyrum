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
