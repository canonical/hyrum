# super-tox

> **Note:** `super-tox` is a placeholder name; the project may be renamed before
> its first stable release. The Python package is `super_tox` and the console
> script is `super-tox`. Both are intended to be easy to rename.

Bulk-run a check (typically lint or unit tests) across many charm
repositories, optionally swapping out one of their dependencies first —
for example, pointing every charm's `ops` dependency at a development
branch of the [operator](https://github.com/canonical/operator) repo to
see which charms it breaks.

The primary use case today is **swapping out `ops` (and its optional
`testing` / `tracing` companions)**. The patcher layer is built as an
abstraction so other dependencies (e.g. individual charm libraries) can
be swapped in later without rewriting the runner.

Two runner backends are supported:

- **tox** — runs `tox -e <env>` in each charm.
- **make** — runs `make <target>` in each charm.

The runner is auto-detected per charm (`tox.ini` → tox, `Makefile` →
make), with a CLI flag to force a specific one.

## Status

Early-stage carve-out from `charm-analysis/tools/super-tox.py`. Scope
during the 26.10 cycle is **lint and unit tests only** — integration
tests are explicitly out of scope.

## Non-goals

- Cloning or curating the charm collection. `super-tox` assumes a folder
  of already-cloned charm repos is provided.
- Running integration tests.
- Acting as a general-purpose CI orchestrator.

## Usage

Skeleton — the CLI is being ported module-by-module. See
`PLAN.md` in the parent work-queue tree for the productisation plan.

## License

Apache 2.0. See `LICENSE.txt`.
