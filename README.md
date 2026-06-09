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

## Host prerequisites

A non-trivial fraction of charms in the curated list pull C/Rust
extensions that `pip` / `uv` will build from source if no wheel is
available for the host's Python. On a fresh Ubuntu host, missing build
tools surface as `failed` outcomes with messages like *"command
'x86_64-linux-gnu-gcc' failed: No such file"* or *"fatal error: Python.h
/ ffi.h: No such file"*, which is noise rather than a charm regression.

To get a clean signal against the curated charm list, install:

```bash
sudo apt-get install -y \
    build-essential \
    pkg-config \
    libffi-dev \
    libpq-dev \
    libmariadb-dev \
    python3-dev   # or python3.<minor>-dev matching the Python uv selects

# Poetry is invoked by ~5 % of charms' tox envs; install it if you want
# those to run instead of failing with "No such file or directory:
# 'poetry'".
uv tool install poetry
```

Some charms also pull C/Rust extensions whose latest releases pre-date
the host's Python version. PyO3 < 0.23 can't build against Python 3.14
unless you opt in with the stable-ABI escape hatch (`unit` in
`testenv:unit.…` is the tox env name `hyrum` invokes via `tox -e unit`,
i.e. the charm's unit-test environment):

```bash
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
export TOX_OVERRIDE='testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

If you also want `-Werror` semantics (warnings promoted to errors),
inject `PYTHONWARNINGS=error` via `pass_env`, not `set_env`:

```bash
export PYTHONWARNINGS=error
export TOX_OVERRIDE='testenv:unit.pass_env+=PYTHONWARNINGS;testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

The intuitive form `set_env+=PYTHONWARNINGS=error` looks correct but
silently drops anything the charm's `[testenv]` set via `set_env` (most
commonly `PYTHONPATH`), so tests that do `from charm import …` fail at
collection with `ModuleNotFoundError` — a misleading "regression" that
isn't a warning at all. `pass_env+=` doesn't touch `set_env`, so the
charm's PYTHONPATH stays intact and the warning still propagates.

Empirically (Ubuntu Resolute, system Python 3.14, 145 runnable charms in
the curated list as of 2026-05): a host with none of these installed
passes ~40 %; adding `build-essential` + `python3.14-dev` lifts that to
~60 %; the full apt list above gets to ~64 %; the PyO3 forward-compat
flag adds ~3 % more, topping out around **67 %**. The residual ~33 % is
genuine charm-side breakage (test failures, dependencies pinned to
versions that don't build on the host Python) and is not something
`hyrum` itself can move.

## Usage

```bash
# Install (editable, with the lint/static/unit dependency groups for
# ruff, pyright, pytest, …):
uv sync --all-groups

# Populate the local cache with every charm in charm-list/charms.csv
# (shallow clones, pulls for repos that already exist):
hyrum get-charms

# Run `tox -e unit` across every charm in the default cache
# (~/.cache/hyrum/charms), with ops swapped to the `fix/X` branch of
# canonical/operator. Override the cache folder with --cache-folder or
# the HYRUM_CHARMS environment variable.
hyrum check unit --workers 8 --ops-source fix/X

# --ops-source also accepts: a PyPI version (`2.17.0`), a `git+<url>[@branch]`
# reference, a plain `https://…/operator[@branch]` URL, the `owner:branch`
# GitHub shorthand, or a local checkout (`/path/to/operator`,
# `~/operator`, `file:///path/to/operator`).

# Force the make runner (default is auto-detect: tox.ini -> tox,
# Makefile -> make, fall back to the other if the target is missing):
hyrum check unit --runner make

# Skip the dependency swap; just check how the charms behave as-pinned:
hyrum check unit --no-patch

# Only run for charms that use the Scenario testing framework:
hyrum check unit --framework scenario

# Always exit 0, even if some charms fail (default is exit non-zero on
# any failure):
hyrum check unit --no-fail

# Dump each charm's stdout, stderr, and run metadata to a per-charm
# file under the given directory for offline triage:
hyrum check unit --log-dir ~/hyrum-runs/logs
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
