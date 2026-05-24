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

- Cloning or curating the charm collection. `hyrum` assumes a folder
  of already-cloned charm repos is provided.
- Running integration tests.
- Acting as a general-purpose CI orchestrator.

## Usage

```bash
# Install (editable, with the lint/static/unit dependency groups for
# ruff, pyright, pytest, …):
uv sync --all-groups

# Run `tox -e unit` across every charm in ~/charms, with ops swapped
# to the `fix/X` branch of canonical/operator:
hyrum \
    --cache-folder ~/charms \
    --target unit \
    --workers 8 \
    --ops-source-branch fix/X

# Force the make runner (default is auto-detect: tox.ini -> tox,
# Makefile -> make, fall back to the other if the target is missing):
hyrum --cache-folder ~/charms --target unit --runner make

# Skip the dependency swap; just check how the charms behave as-pinned:
hyrum --cache-folder ~/charms --target unit --no-patch

# Only run for charms that use the Scenario testing framework:
hyrum --cache-folder ~/charms --target unit --filter scenario

# Exit non-zero if any charm fails, times out, or hits a patcher error:
hyrum --cache-folder ~/charms --target unit --fail-on-regression
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

`hyrum.toml` (path overridable via `-c`) supports an `[ignore]`
table that maps a category to a list of repo paths to skip. Categories
are free-form; their name shows up in the run output as the skip
reason. Example:

```toml
[ignore]
expensive = ["argo-operators", "mysql-router-k8s"]
manual    = ["opensearch-operator"]
```

See `PLAN.md` in the parent work-queue tree for the broader
productisation plan.

## License

Apache 2.0. See `LICENSE.txt`.
