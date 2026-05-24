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

from hyrum import patchers, runners

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
        )

    @classmethod
    def skipped(cls, repo: pathlib.Path, reason: str) -> Outcome:
        """Build a skipped outcome with a human-readable reason."""
        return cls(repo=repo, status='skipped', skip_reason=reason)

    @classmethod
    def patcher_error(cls, repo: pathlib.Path, target: str, message: str) -> Outcome:
        """Build an outcome for a patcher failure (distinct from a run failure)."""
        return cls(repo=repo, status='patcher_error', target=target, error=message)


async def run_one(
    repo: pathlib.Path,
    target: str,
    *,
    patcher: patchers.Patcher,
    runner: runners.Runner,
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
        return Outcome.patcher_error(repo, target, str(exc))
    try:
        result = await runner.run(repo, target)
    finally:
        await asyncio.to_thread(cm.__exit__, None, None, None)
    return Outcome.from_run_result(result)


async def run_pool(
    repos: Iterable[pathlib.Path],
    *,
    patcher: patchers.Patcher,
    runner: runners.Runner,
    target: str,
    workers: int,
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
                outcome = await run_one(repo, target, patcher=patcher, runner=runner)
            except Exception as exc:
                logger.exception('unexpected error in %s', repo)
                outcome = Outcome(
                    repo=repo,
                    status='patcher_error',
                    target=target,
                    error=f'{type(exc).__name__}: {exc}',
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
