from __future__ import annotations

import multiprocessing
import pathlib
import threading
import time

from hyrum import _locks as locks


def test_lock_files_live_out_of_the_way_of_enumeration(tmp_path: pathlib.Path):
    root = locks.lock_root_for(tmp_path)
    # Charm enumeration skips dotted entries, so the locks are invisible to it.
    assert root.name.startswith('.')
    assert root.parent == tmp_path


def test_monorepo_subcharms_lock_separately(tmp_path: pathlib.Path):
    root = locks.lock_root_for(tmp_path)
    one = locks.lock_path(
        tmp_path / 'kfp-operators' / 'charms' / 'kfp-ui', lock_root=root, base=tmp_path
    )
    two = locks.lock_path(
        tmp_path / 'kfp-operators' / 'charms' / 'kfp-api', lock_root=root, base=tmp_path
    )
    assert one != two
    assert one.name == 'kfp-operators__charms__kfp-ui.lock'


def test_a_repo_outside_the_cache_still_gets_a_lock(tmp_path: pathlib.Path):
    root = locks.lock_root_for(tmp_path)
    path = locks.lock_path(pathlib.Path('/elsewhere/a-charm'), lock_root=root, base=tmp_path)
    assert path == root / 'a-charm.lock'


def test_no_lock_root_means_no_lock_file(tmp_path: pathlib.Path):
    with locks.charm_lock(tmp_path / 'a-charm', lock_root=None, base=tmp_path):
        pass
    assert not locks.lock_root_for(tmp_path).exists()


def _hold(cache: str, started, release) -> None:  # type: ignore[no-untyped-def]
    root = locks.lock_root_for(pathlib.Path(cache))
    with locks.charm_lock(
        pathlib.Path(cache) / 'a-charm', lock_root=root, base=pathlib.Path(cache)
    ):
        started.set()
        release.wait(timeout=10)


def test_a_second_process_waits_for_the_first(tmp_path: pathlib.Path):
    # The bug this guards is cross-process, so a same-process test would not
    # see it: two runs share one cache, and the second must not enter a charm
    # the first is part-way through patching.
    ctx = multiprocessing.get_context('spawn')
    started = ctx.Event()
    release = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(tmp_path), started, release))
    holder.start()
    try:
        assert started.wait(timeout=30)
        root = locks.lock_root_for(tmp_path)
        threading.Timer(0.2, release.set).start()
        before = time.monotonic()
        with locks.charm_lock(tmp_path / 'a-charm', lock_root=root, base=tmp_path):
            waited = time.monotonic() - before
        # The block was reached only once the holder let go, rather than
        # alongside it.
        assert waited >= 0.2
    finally:
        release.set()
        holder.join(timeout=10)


def test_different_charms_do_not_block_each_other(tmp_path: pathlib.Path):
    ctx = multiprocessing.get_context('spawn')
    started = ctx.Event()
    release = ctx.Event()
    holder = ctx.Process(target=_hold, args=(str(tmp_path), started, release))
    holder.start()
    try:
        assert started.wait(timeout=30)
        root = locks.lock_root_for(tmp_path)
        before = time.monotonic()
        with locks.charm_lock(tmp_path / 'b-charm', lock_root=root, base=tmp_path):
            pass
        # Serialising the whole cache instead of one charm at a time would
        # make two runs take as long as one after the other.
        assert time.monotonic() - before < 5
    finally:
        release.set()
        holder.join(timeout=10)
