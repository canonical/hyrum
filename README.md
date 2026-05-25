# hyrum

> Named after [Hyrum's law](https://www.hyrumslaw.com/): once you have enough
> users, every observable behaviour of your code is depended on by somebody.
> This tool exists to find out who that "somebody" is — by running a proposed
> dependency change against a fleet of consumer repos before you ship it.

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

- Running integration tests.
- Acting as a general-purpose CI orchestrator.

The `hyrum` CLI itself doesn't clone or curate the charm collection — it
expects a folder of already-cloned repos. Helpers for populating that
folder live in `tools/` (see *Populating the cache* below).

## Usage

```bash
# Install (editable, with the lint/static/unit dependency groups for
# ruff, pyright, pytest, …):
uv sync --all-groups

# Populate the local cache with every charm in charm-list/charms.csv
# (shallow clones, pulls for repos that already exist):
python tools/get_charms.py

# Run `tox -e unit` across every charm in the default cache
# (~/.cache/hyrum/charms), with ops swapped to the `fix/X` branch of
# canonical/operator. Override the cache folder with --cache-folder or
# the HYRUM_CHARMS environment variable.
hyrum unit --workers 8 --ops-source-branch fix/X

# Force the make runner (default is auto-detect: tox.ini -> tox,
# Makefile -> make, fall back to the other if the target is missing):
hyrum unit --runner make

# Skip the dependency swap; just check how the charms behave as-pinned:
hyrum unit --no-patch

# Only run for charms that use the Scenario testing framework:
hyrum unit --framework scenario

# Always exit 0, even if some charms fail (default is exit non-zero on
# any failure):
hyrum unit --no-fail

# Dump each charm's stdout, stderr, and run metadata to a per-charm
# file under the given directory for offline triage:
hyrum unit --log-dir ~/hyrum-runs/logs
```

Output statuses:

| status          | meaning                                                                |
|-----------------|------------------------------------------------------------------------|
| `passed`        | the runner exited 0                                                    |
| `failed`        | the runner exited non-zero                                             |
| `no_target`     | tox env / make target not present in this charm (skipped, not failed)  |
| `timeout`       | killed after `--timeout` seconds                                       |
| `patcher_error` | the dependency swap could not be applied (distinct from a tox failure) |
| `skipped`       | filtered out before the run (regex, ignore-list, no runnable target, …)|

## Dependency-swap scope

Today only the `ops` family (with optional `testing` / `tracing`
extras → `ops-scenario` / `ops-tracing`) is handled by the built-in
patcher. The patcher layer is a `Patcher` protocol so a future
charm-library patcher (vendored `lib/charms/…/v<n>/<file>.py` swapped
from a git source) can plug in without changes elsewhere.

## Configuration

`hyrum.toml` (path overridable via `--config`) supports an `[ignore]`
table that maps a category to a list of repo paths to skip. Categories
are free-form; their name shows up in the run output as the skip
reason. Example:

```toml
[ignore]
expensive = ["argo-operators", "mysql-router-k8s"]
manual    = ["opensearch-operator"]
```

## License

Apache 2.0. See `LICENSE.txt`.
