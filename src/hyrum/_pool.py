"""Drive many ``run_one`` calls concurrently across charm repos.

One :class:`Outcome` per repo is produced. ``patcher_error`` is a
distinct status from ``failed`` so callers can tell infrastructure-style
problems (e.g. the dependency patcher couldn't parse a pyproject.toml)
apart from genuine tox/make failures. The research doc calls this out
as a precondition for sensible run-to-run comparison later.

Patchers remain synchronous context managers (the ``Patcher`` protocol
is dirt-simple and we want third-party patchers to stay that way), but
their setup and teardown — which can take seconds-to-minutes when
shelling out to ``poetry lock`` / ``uv lock`` — run in worker threads
via :func:`asyncio.to_thread` so concurrent workers actually overlap
their lock subprocesses instead of taking turns on the event loop.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import pathlib
from collections.abc import Iterable
from typing import Final

from hyrum import _patchers as patchers
from hyrum import _runners as runners
from hyrum import _summary as summary_mod

logger = logging.getLogger(__name__)


OUTCOME_STATUSES: Final[tuple[str, ...]] = (
    'passed',
    'failed',
    'no_target',
    'timeout',
    'patcher_error',
    'skipped',
)
"""The full set of statuses an Outcome may carry, in display order."""


@dataclasses.dataclass(frozen=True)
class Outcome:
    """One charm's result, normalised across run / skip / error paths."""

    repo: pathlib.Path
    status: str
    runner: str = ''
    target: str = ''
    duration_s: float = 0.0
    returncode: int | None = None
    skip_reason: str = ''
    error: str = ''
    summary: str = ''

    @classmethod
    def from_run_result(cls, result: runners.RunResult) -> Outcome:
        """Build an Outcome from a successful runner invocation."""
        return cls(
            repo=result.repo,
            status=result.status.value,
            runner=result.runner,
            target=result.target,
            duration_s=result.duration_s,
            returncode=result.returncode,
            summary=summary_mod.from_run_output(
                result.stdout,
                result.stderr,
                status=result.status.value,
                returncode=result.returncode,
            ),
        )

    @classmethod
    def skipped(cls, repo: pathlib.Path, reason: str) -> Outcome:
        """Build a skipped outcome with a human-readable reason."""
        return cls(repo=repo, status='skipped', skip_reason=reason)

    @classmethod
    def patcher_error(cls, repo: pathlib.Path, target: str, message: str) -> Outcome:
        """Build an outcome for a patcher failure (distinct from a run failure)."""
        return cls(
            repo=repo,
            status='patcher_error',
            target=target,
            error=message,
            summary=f'patcher: {message}'[:160],
        )


def _log_path(
    log_dir: pathlib.Path,
    repo: pathlib.Path,
    base: pathlib.Path | None,
) -> pathlib.Path:
    """Return the per-charm log filename inside ``log_dir``.

    Uses the repo's path relative to ``base`` (the cache folder) so monorepo
    subcharms like ``kfp-operators/charms/kfp-ui`` don't collide; ``/`` is
    flattened to ``__`` since log files live in a single flat directory.
    """
    try:
        rel = repo.relative_to(base) if base is not None else repo
    except ValueError:
        rel = pathlib.Path(repo.name)
    return log_dir / (str(rel).replace('/', '__') + '.log')


def _dump_run_log(
    log_dir: pathlib.Path,
    base: pathlib.Path | None,
    result: runners.RunResult,
) -> None:
    """Write a single-file log for one runner invocation."""
    path = _log_path(log_dir, result.repo, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f'=== meta ===\n'
        f'repo: {result.repo}\n'
        f'runner: {result.runner}\n'
        f'target: {result.target}\n'
        f'status: {result.status.value}\n'
        f'returncode: {result.returncode}\n'
        f'duration_s: {result.duration_s:.2f}\n'
    )
    with path.open('wb') as fp:
        fp.write(header.encode())
        fp.write(b'=== stdout ===\n')
        fp.write(result.stdout)
        if not result.stdout.endswith(b'\n'):
            fp.write(b'\n')
        fp.write(b'=== stderr ===\n')
        fp.write(result.stderr)
        if result.stderr and not result.stderr.endswith(b'\n'):
            fp.write(b'\n')


def _dump_patcher_error_log(
    log_dir: pathlib.Path,
    base: pathlib.Path | None,
    repo: pathlib.Path,
    target: str,
    error: str,
) -> None:
    """Write a per-charm log for a patcher_error outcome (no runner output)."""
    path = _log_path(log_dir, repo, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'=== meta ===\n'
        f'repo: {repo}\n'
        f'target: {target}\n'
        f'status: patcher_error\n'
        f'=== error ===\n'
        f'{error}\n'
    )


async def run_one(
    repo: pathlib.Path,
    target: str,
    *,
    patcher: patchers.Patcher,
    runner: runners.Runner,
    log_dir: pathlib.Path | None = None,
    log_base: pathlib.Path | None = None,
) -> Outcome:
    """Apply ``patcher`` to ``repo`` and invoke ``runner`` once.

    The patcher's ``apply`` is a synchronous context manager that may shell
    out to ``poetry lock`` / ``uv lock`` (seconds-to-minutes) on entry,
    which would otherwise block the event loop and serialise every worker.
    Enter and exit in a thread so concurrent workers can overlap their lock
    subprocesses; the runner call is already asyncio-native.
    """
    try:
        cm = patcher.apply(repo)
        await asyncio.to_thread(cm.__enter__)
    except patchers.PatcherError as exc:
        logger.warning('patcher error in %s: %s', repo, exc)
        if log_dir is not None:
            _dump_patcher_error_log(log_dir, log_base, repo, target, str(exc))
        return Outcome.patcher_error(repo, target, str(exc))
    try:
        result = await runner.run(repo, target)
    finally:
        await asyncio.to_thread(cm.__exit__, None, None, None)
    if log_dir is not None:
        _dump_run_log(log_dir, log_base, result)
    return Outcome.from_run_result(result)


async def run_pool(
    repos: Iterable[pathlib.Path],
    *,
    patcher: patchers.Patcher,
    runner: runners.Runner,
    target: str,
    workers: int,
    log_dir: pathlib.Path | None = None,
    log_base: pathlib.Path | None = None,
) -> list[Outcome]:
    """Run ``target`` across ``repos`` concurrently with ``workers`` workers."""
    queue: asyncio.Queue[pathlib.Path] = asyncio.Queue()
    for repo in repos:
        queue.put_nowait(repo)
    results: list[Outcome] = []

    async def consumer() -> None:
        while True:
            try:
                repo = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                outcome = await run_one(
                    repo,
                    target,
                    patcher=patcher,
                    runner=runner,
                    log_dir=log_dir,
                    log_base=log_base,
                )
            except Exception as exc:
                logger.exception('unexpected error in %s', repo)
                outcome = Outcome(
                    repo=repo,
                    status='patcher_error',
                    target=target,
                    error=f'{type(exc).__name__}: {exc}',
                    summary=f'patcher: {type(exc).__name__}: {exc}'[:160],
                )
                if log_dir is not None:
                    _dump_patcher_error_log(
                        log_dir, log_base, repo, target, f'{type(exc).__name__}: {exc}'
                    )
            results.append(outcome)
            queue.task_done()

    tasks = [asyncio.create_task(consumer()) for _ in range(max(1, workers))]
    await asyncio.gather(*tasks)
    return results


def add_skipped(
    results: list[Outcome],
    skipped: Iterable[tuple[pathlib.Path, str]],
) -> None:
    """Fold pre-pool skips (filter rejects) into the result list."""
    for repo, reason in skipped:
        results.append(Outcome.skipped(repo, reason))


def passed(results: Iterable[Outcome]) -> bool:
    """Did every non-skipped charm pass?"""
    benign = {runners.RunStatus.PASSED.value, runners.RunStatus.NO_TARGET.value, 'skipped'}
    return all(outcome.status in benign for outcome in results)
