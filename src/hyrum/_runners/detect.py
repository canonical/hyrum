"""Pick the right runner for a given charm."""

from __future__ import annotations

import enum
import pathlib
from collections.abc import Sequence

from hyrum._runners import base, make_runner, tox


class RunnerChoice(enum.StrEnum):
    """User-facing ``--runner`` choices."""

    AUTO = 'auto'
    TOX = 'tox'
    MAKE = 'make'


def by_name(name: str) -> type[base.Runner]:
    """Return the Runner class registered under ``name``."""
    mapping: dict[str, type[base.Runner]] = {
        'tox': tox.ToxRunner,
        'make': make_runner.MakeRunner,
    }
    try:
        return mapping[name]
    except KeyError as exc:
        raise ValueError(f'unknown runner {name!r}') from exc


class AutoRunner:
    """Picks a runner per repo and falls back if the target is not present.

    Order: prefer tox where ``tox.ini`` exists, otherwise make. If the
    primary runner reports ``no_target`` — or could not be launched at
    all — the secondary is tried, so that a charm with both files but the
    target only on the other side still runs.
    """

    name = 'auto'

    def __init__(self, runners: Sequence[base.Runner]):
        self._runners = list(runners)

    @classmethod
    def detect(cls, repo: pathlib.Path) -> bool:
        """Return True if any underlying runner could run in ``repo``."""
        return tox.ToxRunner.detect(repo) or make_runner.MakeRunner.detect(repo)

    async def run(self, repo: pathlib.Path, target: str) -> base.RunResult:
        """Run ``target`` with the first applicable runner; fall back on no_target."""
        applicable = [r for r in self._runners if type(r).detect(repo)]
        if not applicable:
            return base.RunResult(
                repo=repo,
                runner=self.name,
                target=target,
                status=base.RunStatus.NO_TARGET,
                returncode=None,
                duration_s=0.0,
            )
        last_result: base.RunResult | None = None
        launch_failed: base.RunResult | None = None
        for runner in applicable:
            last_result = await runner.run(repo, target)
            if last_result.status is base.RunStatus.RUNNER_ERROR:
                launch_failed = launch_failed or last_result
            elif last_result.status is not base.RunStatus.NO_TARGET:
                return last_result
        # Nothing actually ran: every runner reported ``no_target`` or failed to
        # launch, so ``last_result`` is whichever of those the final runner gave.
        # Report the first launch failure ahead of it: "make is not installed" is
        # more actionable than "no such target".
        assert last_result is not None
        return launch_failed or last_result


def auto(
    *,
    tox_executable: str | Sequence[str] = 'tox',
    make_executable: str | Sequence[str] = 'make',
    timeout: int = 1800,
    prefer: Sequence[str] = ('tox', 'make'),
) -> AutoRunner:
    """Build an AutoRunner that tries runners in ``prefer`` order."""
    available: dict[str, base.Runner] = {
        'tox': tox.ToxRunner(executable=tox_executable, timeout=timeout),
        'make': make_runner.MakeRunner(executable=make_executable, timeout=timeout),
    }
    ordered = [available[name] for name in prefer if name in available]
    return AutoRunner(ordered)
