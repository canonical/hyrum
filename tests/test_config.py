from __future__ import annotations

from pathlib import Path

import pytest

from hyrum.config import load


def test_missing_returns_empty(tmp_path: Path):
    cfg = load(tmp_path / 'missing.toml')
    assert cfg.ignore == {}


def test_loads_ignore_categories(tmp_path: Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[ignore]\nexpensive = ["argo-operators"]\nmanual = ["opensearch-operator"]\n')
    cfg = load(p)
    assert cfg.ignore['expensive'] == ['argo-operators']
    assert cfg.ignore['manual'] == ['opensearch-operator']


def test_bad_ignore_shape_raises(tmp_path: Path):
    p = tmp_path / 'hyrum.toml'
    p.write_text('[ignore]\nexpensive = "argo"\n')
    with pytest.raises(ValueError):
        load(p)
