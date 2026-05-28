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
    libjpeg-dev \
    zlib1g-dev \
    default-jdk \
    skopeo \
    python3-dev   # or python3.<minor>-dev matching the Python uv selects

# Poetry is invoked by ~5 % of charms' tox envs; install it if you want
# those to run instead of failing with "No such file or directory:
# 'poetry'".
uv tool install poetry
```

Beyond the obvious compilers, the less-obvious entries each unblock a
specific cluster of charms:

- `libjpeg-dev` + `zlib1g-dev` — let Pillow build from source (pulled in
  transitively by `matplotlib` via `prometheus-api-client`); without
  them the COS charms fail with *"The headers or library files could
  not be found for jpeg"*.
- `default-jdk` — the Kafka charms shell out to `keytool`; missing it
  surfaces as `CalledProcessError: Command 'keytool' returned non-zero
  exit status 127`.
- `skopeo` — `kyuubi-k8s` inspects container image metadata via
  `skopeo` and errors with `FileNotFoundError: Could not find 'skopeo'`.

A handful of charms also need their charm libraries vendored before
their tests import cleanly (`ModuleNotFoundError: No module named
'charms'`); run `charmcraft fetch-libs` in the charm dir to populate
`lib/charms/…` (`uv tool install charmcraft` if you don't have it).

Some charms also pull C/Rust extensions whose latest releases pre-date
the host's Python version. PyO3 < 0.23 can't build against Python 3.14
unless you opt in with the stable-ABI escape hatch:

```bash
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
TOX_OVERRIDE='testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

If you also want `-Werror` semantics (warnings promoted to errors),
inject `PYTHONWARNINGS=error` via `pass_env`, not `set_env`:

```bash
export PYTHONWARNINGS=error
TOX_OVERRIDE='testenv:unit.pass_env+=PYTHONWARNINGS
testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

The intuitive form `set_env+=PYTHONWARNINGS=error` looks correct but
silently drops anything the charm's `[testenv]` set via `set_env` (most
commonly `PYTHONPATH`), so tests that do `from charm import …` fail at
collection with `ModuleNotFoundError` — a misleading "regression" that
isn't a warning at all. `pass_env+=` doesn't touch `set_env`, so the
charm's PYTHONPATH stays intact and the warning still propagates.

### The Python version is the biggest lever

The apt list and PyO3 flag matter, but the single largest factor in the
pass rate is the **interpreter version**. The curated charms' pinned
dependency stacks have largely caught up to Python 3.12, but not yet to
3.13/3.14, where stdlib removals (`cgi`, `ast.Str`,
`_PyInterpreterState_Get`) and un-rebuilt C/Rust wheels (PyO3 < 0.23,
`netifaces`, `psycopg2`) start to bite. Same fleet, same `--no-patch`,
only the interpreter changed (Ubuntu Resolute, 134 runnable `unit`
envs, 2026-05):

| Python | passed / ran | pass rate |
|--------|-------------:|----------:|
| 3.14   | 86 / 134     | 64 %  |
| 3.10   | 89 / 134     | 66 % † |
| 3.12   | 118 / 134    | 88 %  |

† 3.10 looks no better than 3.14 only because forcing a single old
interpreter breaks the ~30 kubeflow/istio charms that declare
`requires-python >= 3.12`; it is not a fair comparison. 3.12 is the
sweet spot — new enough for those charms, old enough to dodge the
3.13/3.14 stdlib and wheel breakage — so **run the fleet on Python
3.12** for the cleanest signal.

The headline takeaway: most of what a 3.14-only run reports as
"charm-side breakage" is just *not-yet-3.14-ready dependencies*, not
broken charms. On 3.12 the genuine residual is small (~12 %): a couple
of charms need the extra host tooling listed above (`default-jdk`,
`skopeo`, `charmcraft fetch-libs`), two OOM the host under worker
concurrency (`mysql-router/kubernetes` runs `pytest -n 120`,
`namespace-node-affinity`), and ~9 have real test bugs independent of
the interpreter — stale Harness `set_can_connect` assumptions,
over-mocked snap helpers, reliance on a removed `ops` internal. With
`default-jdk` + `skopeo` installed (recovering the two Kafka charms)
3.12 lands around **90 %**.

### Known-broken charms on Python 3.12

These are the charms that still fail a `--no-patch` `unit` run on 3.12
with the full apt list above, grouped by cause (audited 2026-05-28).
`hyrum` does not ship a default ignore list — most of the 3.14 noise
evaporates simply by running on 3.12 — but if you want a quiet tally you
can drop these into a local `hyrum.toml` `[ignore]` table under whatever
category names you like.

- **Genuine test bugs** (independent of interpreter and ops version):
  `exim-operator` (pebble layer assertion), `grafana-agent-operator` and
  `parca-agent-operator` (over-mocked snap helpers), `redis-operator`
  and `tls-truststore-operator` (stale Harness `set_can_connect`
  assumption), `snappass-test` (uses a removed `ops` internal),
  `timescaledb-charm` (`mock` spec change), `tls-certificates-requirer-operator`
  (test-isolation `Patch is already started`).
- **Resource-intensive** (OOM under worker concurrency, pass when run
  alone): `mysql-router-operators/kubernetes` (`pytest -n 120`),
  `namespace-node-affinity-operator`.
- **Build** (a transitive sdist fails the modern setuptools build):
  `ks-charmed`.
- **Tox config drift** (env points pytest at an empty `tests/unit`):
  `opensearch-operator`.

Three more are *recoverable* and deliberately left off the list:
`kafka-k8s-operator` and `kafka-operator` pass once `default-jdk` is
installed (above), and `self-signed-certificates-operator` passes after
`charmcraft fetch-libs`.

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
