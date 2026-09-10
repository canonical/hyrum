from __future__ import annotations

import logging
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


def test_finds_the_parallel_coverage_files(tmp_path: pathlib.Path):
    """`coverage run --parallel-mode` and pytest-cov under xdist write one per worker."""
    repo = _charm(tmp_path, 'a-charm')
    (repo / '.coverage').write_text('')
    (repo / '.coverage.host.1234.567890').write_text('')
    (repo / '.coverage.host.1235.567891').write_text('')
    (repo / '.hypothesis').mkdir()
    assert _artefacts(tmp_path) == {
        'a-charm/.coverage',
        'a-charm/.coverage.host.1234.567890',
        'a-charm/.coverage.host.1235.567891',
        'a-charm/.hypothesis',
    }


def test_a_directory_of_checkouts_looks_like_a_cache(tmp_path: pathlib.Path):
    _charm(tmp_path, 'a-charm')
    _charm(tmp_path, 'b-charm')
    assert clean.looks_like_a_cache(tmp_path)


def test_an_owner_level_cache_looks_like_a_cache(tmp_path: pathlib.Path):
    """The real layout is <charms-dir>/<owner>/<leaf>, so .git is two levels down."""
    _charm(tmp_path / 'canonical', 'a-charm')
    _charm(tmp_path / 'openstack', 'b-charm')
    assert clean.looks_like_a_cache(tmp_path)


def test_a_source_tree_does_not_look_like_a_cache(tmp_path: pathlib.Path):
    (tmp_path / 'notes').mkdir()
    _charm(tmp_path, 'a-charm')
    assert not clean.looks_like_a_cache(tmp_path)


def test_an_empty_directory_does_not_look_like_a_cache(tmp_path: pathlib.Path):
    assert not clean.looks_like_a_cache(tmp_path)


def _unreadable(target: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``target.iterdir()`` raise, the way an unreadable directory does.

    Monkeypatched rather than chmodded, because a test running as root can
    read a directory whose mode says otherwise.
    """
    real = pathlib.Path.iterdir

    def fake(self: pathlib.Path):
        if self == target:
            raise PermissionError(13, 'Permission denied')
        return real(self)

    monkeypatch.setattr(pathlib.Path, 'iterdir', fake)


def test_an_unreadable_cache_does_not_look_like_a_cache(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _charm(tmp_path, 'a-charm')
    _unreadable(tmp_path, monkeypatch)
    with caplog.at_level(logging.ERROR, logger=clean.logger.name):
        assert not clean.looks_like_a_cache(tmp_path)
    assert any('Could not read' in m for m in caplog.messages)


def test_an_unreadable_owner_does_not_look_like_a_cache(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """The refusal has to say it could not look, not that the contents are not checkouts."""
    owner = tmp_path / 'canonical'
    _charm(owner, 'a-charm')
    _unreadable(owner, monkeypatch)
    with caplog.at_level(logging.ERROR, logger=clean.logger.name):
        assert not clean.looks_like_a_cache(tmp_path)
    assert any('Could not check' in m for m in caplog.messages)
