---
myst:
  html_meta:
    description: Why hyrum separates patching from running, how the async worker pool is structured, and how outcomes are classified.
---

# Architecture and design

## The patcher–runner model

Hyrum separates the work of *modifying a charm's dependencies* (patching) from the work of *running a check* (running):

- Patchers are synchronous context managers. They touch the filesystem, may shell out to `poetry lock` or `uv lock`, and must restore every file on exit, whether or not the run succeeded.
- Runners are async. They spawn a subprocess (`tox` or `make`) and wait for it to exit, returning a structured `RunResult`.

Because patching involves slow, blocking subprocesses (lockfile regeneration can take minutes), the pool runs each patcher's `apply` in a thread (`asyncio.to_thread`) so that concurrent workers overlap their lock subprocesses rather than waiting in sequence.

## The async worker pool

The pool is a simple queue-based design:

1. All charm paths are loaded into an `asyncio.Queue`.
2. `N` concurrent consumer coroutines (controlled by `--workers`) each pull from the queue, patch, run, and report.
3. Results are collected in a list and sorted by repo path before display.

The pool deliberately does not use `asyncio.Semaphore` or structured concurrency beyond `asyncio.gather` on the consumer tasks. The queue approach means each worker is idle for at most one charm at a time and work is distributed evenly as workers complete.

## The Patcher protocol

The `Patcher` protocol is narrow:

```python
class Patcher(Protocol):
    def apply(self, repo: Path) -> AbstractContextManager[None]: ...
```

Any object with an `apply` method that returns a context manager satisfies the protocol. This makes it straightforward to add new patchers (for example, a charm-library patcher that swaps a vendored `lib/charms/X/v1/X.py` file from a git source) without changing the pool or runner layers.

`PatcherStack` composes multiple patchers and unwinds them in reverse order on exit, behaving like nested context managers.

`NullPatcher` does nothing. It is used when `--no-patch` is set or when no ops-source branch is specified.

## The Runner protocol

```python
class Runner(Protocol):
    name: str

    @classmethod
    def detect(cls, repo: Path) -> bool: ...

    async def run(self, repo: Path, target: str) -> RunResult: ...
```

`detect` returns `True` if the runner believes it can run in the given repo (for example, `ToxRunner.detect` checks for `tox.ini`). `runners.auto()` calls each runner's `detect` to select the right one per charm.

`RunResult` is a frozen dataclass carrying the repo path, runner name, target name, status, return code, duration, and captured stdout/stderr. The stdout and stderr are preserved in memory for the duration of the run so they can be written to `--log-dir` immediately after.

## Outcome statuses and attribution

`pool.Outcome` normalises across three paths through the pool:

- A pre-pool skip (filtered out before patching): `status='skipped'`.
- A patcher failure: `status='patcher_error'` with the error message in `outcome.error`.
- A runner result (pass, fail, no-target, timeout): status from `RunStatus`.

The distinction between `patcher_error` and `failed` is important: a patcher failure means hyrum could not apply the dependency swap, which is an infrastructure problem. A `failed` outcome means the charm's own tests reported failure. Mixing these two would make the "N charms broke" count misleading.

## Charm discovery and filtering

Charm discovery handles three layouts:

- **Flat**: one charm per top-level directory (has `charmcraft.yaml` or `metadata.yaml`).
- **Bundle**: a `bundle.yaml` directory; charms are in `charms/` subdirectories.
- **Monorepo**: a directory containing charm subdirectories, heuristically detected.

Filters are applied as a chain. Each filter either returns `None` (passes) or a skip reason string. The chain short-circuits on the first reason:

1. `not_legacy`: skip reactive/hooks-based charms.
2. `regex_filter`: skip charms not matching `--repo`.
3. `ignore_filter`: skip charms listed in `hyrum.toml [ignore]`.
4. `has_runnable_target`: skip charms with neither `tox.ini` nor `Makefile`.
5. Framework filter (if `--framework` is set).

## Signal vs noise

Hyrum produces a table of outcomes, not a verdict. Two factors prevent treating any single run's numbers as ground truth:

- **Pre-existing failures.** Many charm repositories have failing tests that predate any change under test. A baseline run (`--no-patch`) establishes how many charms fail without any modification, providing a comparison point.
- **Flaky tests.** Some tests are non-deterministic. A charm that fails once may pass on a re-run.

The intended workflow is to run hyrum twice (once without patching, once with) and compare the delta. Charms that move from `passed` to `failed` in the patched run are the likely regressions introduced by the change.
