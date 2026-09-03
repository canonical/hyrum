from __future__ import annotations

import pathlib

import pytest

from hyrum import _clean as clean


def _charm(base: pathlib.Path, name: str) -> pathlib.Path:
    repo = base / name
    (repo / '.git').mkdir(parents=True)
    (repo / '.git' / 'config').write_text('[core]\n')
    (repo / 'src').mkdir()
    (repo / 'src' / 'charm.py').write_text('# charm\n')
    (repo / 'charmcraft.yaml').write_text('type: charm\n')
    return repo


def _artefacts(base: pathlib.Path) -> set[str]:
    return {str(a.path.relative_to(base)) for a in clean.find_artefacts(base)}


def test_finds_the_usual_build_artefacts(tmp_path: pathlib.Path):
    repo = _charm(tmp_path, 'a-charm')
    for name in ('.tox', '.venv', '.pytest_cache', '.ruff_cache', '.mypy_cache', 'htmlcov'):
        (repo / name).mkdir()
    (repo / 'src' / '__pycache__').mkdir()
    (repo / 'hyrum.egg-info').mkdir()
    (repo / '.coverage').write_text('')
    assert _artefacts(tmp_path) == {
        'a-charm/.tox',
        'a-charm/.venv',
        'a-charm/.pytest_cache',
        'a-charm/.ruff_cache',
        'a-charm/.mypy_cache',
        'a-charm/htmlcov',
        'a-charm/hyrum.egg-info',
        'a-charm/src/__pycache__',
        'a-charm/.coverage',
    }


def test_leaves_the_checkout_alone(tmp_path: pathlib.Path):
    repo = _charm(tmp_path, 'a-charm')
    # A charm is free to have a __pycache__ inside .git, and .git is not ours
    # to walk into at all.
    (repo / '.git' / '__pycache__').mkdir()
    assert _artefacts(tmp_path) == set()
    for artefact in clean.find_artefacts(tmp_path):
        clean.remove(artefact)
    assert (repo / '.git' / 'config').exists()
    assert (repo / 'src' / 'charm.py').exists()
    assert (repo / 'charmcraft.yaml').exists()


def test_does_not_descend_into_an_artefact(tmp_path: pathlib.Path):
    repo = _charm(tmp_path, 'a-charm')
    nested = repo / '.tox' / 'unit' / 'lib' / '__pycache__'
    nested.mkdir(parents=True)
    # The whole .tox goes as one removal, so its innards are not listed
    # separately.
    assert _artefacts(tmp_path) == {'a-charm/.tox'}


def test_a_symlinked_artefact_is_left_where_it_is(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    repo = _charm(cache, 'a-charm')
    outside = tmp_path / 'elsewhere' / '.tox'
    outside.mkdir(parents=True)
    (outside / 'big').write_bytes(b'x' * 100)
    (repo / '.tox').symlink_to(outside)
    # Removing the link reclaims nothing, and following it would take the
    # walk out of the cache.
    assert _artefacts(cache) == set()


def test_sizes_the_tree_it_would_remove(tmp_path: pathlib.Path):
    repo = _charm(tmp_path, 'a-charm')
    (repo / '.tox' / 'unit').mkdir(parents=True)
    (repo / '.tox' / 'unit' / 'a').write_bytes(b'x' * 500)
    (repo / '.tox' / 'unit' / 'b').write_bytes(b'x' * 524)
    (artefact,) = list(clean.find_artefacts(tmp_path))
    assert artefact.size == 1024
    assert clean.format_size(artefact.size) == '1.0 KiB'


def test_removes_what_it_finds(tmp_path: pathlib.Path):
    repo = _charm(tmp_path, 'a-charm')
    (repo / '.tox').mkdir()
    (repo / '.coverage').write_text('')
    for artefact in clean.find_artefacts(tmp_path):
        assert clean.remove(artefact)
    assert not (repo / '.tox').exists()
    assert not (repo / '.coverage').exists()
    assert (repo / 'src' / 'charm.py').exists()


def test_a_missing_cache_is_an_error(tmp_path: pathlib.Path):
    with pytest.raises(FileNotFoundError):
        list(clean.find_artefacts(tmp_path / 'nope'))
    a_file = tmp_path / 'file'
    a_file.write_text('')
    with pytest.raises(NotADirectoryError):
        list(clean.find_artefacts(a_file))


@pytest.mark.parametrize(
    ('size', 'expected'),
    [
        (0, '0 B'),
        (999, '999 B'),
        (1024, '1.0 KiB'),
        (1024 * 1024 * 3 // 2, '1.5 MiB'),
        (1024**3 * 12, '12.0 GiB'),
        (1024**4, '1024.0 GiB'),
    ],
)
def test_format_size(size: int, expected: str):
    assert clean.format_size(size) == expected
