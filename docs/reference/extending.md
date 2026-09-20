---
myst:
  html_meta:
    description: The Patcher and Runner protocols that hyrum's patching and running layers are built on, for adapting or extending hyrum.
---

# Extending hyrum

This page is for people who want to adapt or extend hyrum, rather than use it. It
describes the two protocols that the patching and running layers are built on. For
why the two are separated, see [Architecture and design](../explanation/design).

## The Patcher protocol

The `Patcher` protocol is narrow:

```python
class Patcher(Protocol):
    def apply(self, repo: Path) -> AbstractContextManager[None]: ...
```

Any object with an `apply` method that returns a context manager satisfies the protocol. That narrowness is what let the patcher set grow without touching the pool or runner layers: the ops-source patcher was joined by a generic single-dependency patcher, a charmlibs patcher that repoints a `charmlibs-*` dependency at a branch of the monorepo, and a vendored-library patcher that deletes a `lib/charms/<author>/v<n>/<lib>.py` file, adds the equivalent package, and rewrites the charm's imports.

`PatcherStack` composes multiple patchers and unwinds them in reverse order on exit, behaving like nested context managers.

`NullPatcher` does nothing. It is used when `--no-patch` is set.

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

## Room for more patchers

The narrowness of the `Patcher` protocol is deliberate. [Pebble](https://github.com/canonical/pebble), the service manager embedded in every Kubernetes charm container, has its own set of consumers and its own evolution challenges, and a pebble-library patcher can be added later without changing the runner or pool layers.
