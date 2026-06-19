from __future__ import annotations

import pathlib

import pytest

from hyrum import _patchers as patchers
from hyrum import _pool as pool
from hyrum import _runners as runners


class StubRunner:
    name = 'stub'

    def __init__(
        self,
        status: runners.RunStatus = runners.RunStatus.PASSED,
        returncode: int = 0,
        stdout: bytes = b'',
        stderr: bytes = b'',
    ):
        self.status = status
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.seen: list[pathlib.Path] = []

    async def run(self, repo: pathlib.Path, target: str) -> runners.RunResult:
        self.seen.append(repo)
        return runners.RunResult(
            repo=repo,
            runner=self.name,
            target=target,
            status=self.status,
            returncode=self.returncode,
            duration_s=0.01,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class FailingPatcher:
    def apply(self, repo: pathlib.Path):
        raise patchers.PatcherError(f'could not patch {repo}')

    # Make it usable in `with`.
    def __enter__(self):  # pragma: no cover — unused
        return self

    def __exit__(self, *args):  # pragma: no cover — unused
        return False


async def test_run_one_passed(tmp_path: pathlib.Path):
    runner = StubRunner(runners.RunStatus.PASSED)
    outcome = await pool.run_one(tmp_path, 'unit', patcher=patchers.NullPatcher(), runner=runner)
    assert outcome.status == 'passed'
    assert outcome.runner == 'stub'
    assert outcome.target == 'unit'
    assert runner.seen == [tmp_path]


async def test_run_one_patcher_error_short_circuits(tmp_path: pathlib.Path):
    runner = StubRunner(runners.RunStatus.PASSED)
    outcome = await pool.run_one(tmp_path, 'unit', patcher=FailingPatcher(), runner=runner)
    assert outcome.status == 'patcher_error'
    assert 'could not patch' in outcome.error
    assert runner.seen == []  # runner never invoked


async def test_run_pool_concurrent_workers(tmp_path: pathlib.Path):
    repos = [tmp_path / f'c{i}' for i in range(5)]
    for r in repos:
        r.mkdir()
    runner = StubRunner(runners.RunStatus.PASSED)
    results = await pool.run_pool(
        repos, patcher=patchers.NullPatcher(), runner=runner, target='unit', workers=3
    )
    assert len(results) == 5
    assert all(o.status == 'passed' for o in results)
    assert set(runner.seen) == set(repos)


async def test_run_pool_handles_runner_exception_as_patcher_error(tmp_path: pathlib.Path):
    class Boom:
        name = 'boom'

        async def run(self, repo, target):
            raise RuntimeError('kaboom')

    results = await pool.run_pool(
        [tmp_path], patcher=patchers.NullPatcher(), runner=Boom(), target='unit', workers=1
    )
    assert len(results) == 1
    assert results[0].status == 'patcher_error'
    assert 'kaboom' in results[0].error


async def test_log_dir_dumps_runner_output(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    repo = cache / 'argo-operators' / 'charms' / 'kfp-api'
    repo.mkdir(parents=True)
    log_dir = tmp_path / 'logs'
    runner = StubRunner(
        runners.RunStatus.FAILED, returncode=2, stdout=b'pytest ran\n', stderr=b'oops\n'
    )
    outcome = await pool.run_one(
        repo,
        'unit',
        patcher=patchers.NullPatcher(),
        runner=runner,
        log_dir=log_dir,
        log_base=cache,
    )
    assert outcome.status == 'failed'
    # Flattened path: ``/`` becomes ``__`` so monorepo subcharms don't collide.
    log = log_dir / 'argo-operators__charms__kfp-api.log'
    assert log.exists()
    content = log.read_text()
    assert 'status: failed' in content
    assert 'returncode: 2' in content
    assert 'pytest ran' in content
    assert 'oops' in content


async def test_log_dir_dumps_patcher_error(tmp_path: pathlib.Path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    repo = cache / 'broken-charm'
    repo.mkdir()
    log_dir = tmp_path / 'logs'
    outcome = await pool.run_one(
        repo,
        'unit',
        patcher=FailingPatcher(),
        runner=StubRunner(),
        log_dir=log_dir,
        log_base=cache,
    )
    assert outcome.status == 'patcher_error'
    log = log_dir / 'broken-charm.log'
    assert log.exists()
    content = log.read_text()
    assert 'status: patcher_error' in content
    assert 'could not patch' in content


def test_add_skipped_appends():
    results: list[pool.Outcome] = []
    pool.add_skipped(results, [(pathlib.Path('/x'), 'no Makefile')])
    assert len(results) == 1
    assert results[0].status == 'skipped'
    assert results[0].skip_reason == 'no Makefile'


@pytest.mark.parametrize(
    ('outcomes', 'expected'),
    [
        ([], True),
        ([pool.Outcome(repo=pathlib.Path('/x'), status='passed')], True),
        (
            [
                pool.Outcome(repo=pathlib.Path('/x'), status='passed'),
                pool.Outcome(repo=pathlib.Path('/y'), status='skipped'),
                pool.Outcome(repo=pathlib.Path('/z'), status='no_target'),
            ],
            True,
        ),
        ([pool.Outcome(repo=pathlib.Path('/x'), status='failed')], False),
        ([pool.Outcome(repo=pathlib.Path('/x'), status='timeout')], False),
        ([pool.Outcome(repo=pathlib.Path('/x'), status='patcher_error')], False),
    ],
)
def test_passed(outcomes, expected):
    assert pool.passed(outcomes) is expected
