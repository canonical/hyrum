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

Any object with an `apply` method that returns a context manager satisfies the protocol. That narrowness is what let the patcher set grow without touching the pool or runner layers: the ops-source patcher was joined by a generic single-dependency patcher, a charmlibs patcher that repoints a `charmlibs-*` dependency at a branch of the monorepo, and a vendored-library patcher that deletes a `lib/charms/<author>/v<n>/<lib>.py` file, adds the equivalent package, and rewrites the charm's imports.

`PatcherStack` composes multiple patchers and unwinds them in reverse order on exit, behaving like nested context managers.

`NullPatcher` does nothing. It is used when `--no-patch` is set.

### Skips versus errors

Patchers signal two different kinds of "this did not happen": `PatcherError`, meaning the swap should have applied but could not, and `PatcherSkip`, meaning there was nothing to swap. The second is not a failure — a charm that never depended on the library you are testing tells you nothing about your change, and reporting it as an error would inflate the numbers exactly where the fleet is largest. Skips carry a machine-readable reason, so the tally can separate the ordinary cases (`dep_not_declared`, `vendored_lib_absent`) from the one that deserves attention (`malformed_pyproject`).

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

Each non-passing outcome also carries a one-line `summary`, extracted heuristically from the runner's output: a pytest tally, an exception class, a missing build tool, a resolver error. It exists so that a comparison table is readable without opening the log files — the shape of a failure is usually enough to tell a genuine regression from host noise.

## Charm discovery and filtering

Charm discovery handles three layouts:

- **Flat**: one charm per top-level directory (has `charmcraft.yaml` or `metadata.yaml`).
- **Bundle**: a `bundle.yaml` directory; charms are in `charms/` subdirectories.
- **Monorepo**: a directory containing charm subdirectories, heuristically detected.

Filters are applied as a chain. Each filter either returns `None` (passes) or a skip reason string. The chain short-circuits on the first reason:

1. `not_legacy`: skip reactive/hooks-based charms (`hooks/`, or `src/reactive/` with `src/layer.yaml`).
2. `has_python`: skip charms with no Python source.
3. `regex_filter`: skip charms not matching `--repo`.
4. `ignore_filter`: skip charms listed in `hyrum.toml [ignore]`.
5. `has_runnable_target`: skip charms with neither `tox.ini` nor `Makefile`.
6. Framework filter (if `--framework` is set).

## Signal vs noise

Hyrum produces a table of outcomes, not a verdict. Two factors prevent treating any single run's numbers as ground truth:

- **Pre-existing failures.** Many charm repositories have failing tests that predate any change under test. A baseline run (`--no-patch`) establishes how many charms fail without any modification, providing a comparison point.
- **Flaky tests.** Some tests are non-deterministic. A charm that fails once may pass on a re-run.

The intended workflow is to run hyrum twice (once without patching, once with) and compare the delta. Charms that move from `passed` to `failed` in the patched run are the likely regressions introduced by the change.

That comparison is built in rather than left to the reader. Every run serialises its outcomes to JSON, keyed on each charm's path relative to the charms directory so that runs from different hosts still line up, and `hyrum compare` reduces two such files to the three categories that carry information: new failures, resolved, and new errors. Saving is on by default — a rolling pair of files per target — on the grounds that the second run is where the value is, and needing to have known in advance to pass a flag would waste the first one.
