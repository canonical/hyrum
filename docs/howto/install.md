---
myst:
  html_meta:
    description: Install hyrum from PyPI with uv, build a development checkout, and provision the host packages needed to run the charm fleet cleanly.
---

# How to install hyrum

## Install from PyPI

Install hyrum with [uv](https://docs.astral.sh/uv/):

```text
uv tool install hyrum
```

After installation, `hyrum --version` should print the installed version.

## Install from source

Clone the repository and install in editable mode with the development dependency groups:

```text
git clone https://github.com/canonical/hyrum
cd hyrum
uv sync --all-groups
```

The `uv sync` command creates a virtual environment and installs all dependencies. Run hyrum via `uv run hyrum` or activate the virtual environment first.

## System requirements

- Python 3.11 or later
- `tox` or `make` on your PATH (whichever your charms use)
- `git` on your PATH, for `hyrum get-charms` and any manual cloning

When `--patch` points at a git URL or local checkout, you also need:

- `poetry` on your PATH if any charms in your charms directory use Poetry
- `uv` on your PATH if any charms use uv

See [How to swap ops to a development branch](swap-ops-branch) for details.

## Host prerequisites for fleet runs

A non-trivial fraction of charms pull C/Rust extensions that `pip` or `uv` will build from source if no wheel is available for the host's Python. On a fresh Ubuntu host, missing build tools surface as `failed` outcomes with messages like *"command 'x86_64-linux-gnu-gcc' failed: No such file"* or *"fatal error: Python.h / ffi.h: No such file"*. That is noise rather than a charm regression.

To get a clean signal against the curated charm list, install:

```bash
sudo apt-get install -y \
    build-essential \
    pkg-config \
    libffi-dev \
    libpq-dev \
    libmariadb-dev \
    python3-dev   # or python3.<minor>-dev matching the Python uv selects

# Poetry is invoked by ~5% of charms' tox envs:
uv tool install poetry
```

A handful of charms shell out to other tools (for example `yq`, `go`, `skopeo`, a JDK, libjpeg) from their tox env or Makefile. They are not installed up-front since they only affect a few charms; they surface as `failed` with a `command not found` line in the per-charm log. Install the missing tool to unmask the underlying charm result.

### Python-version-specific build issues

Some charms pull C/Rust extensions whose latest releases pre-date the host's Python version. PyO3 < 0.23 cannot build against Python 3.14 unless you opt in with the stable-ABI escape hatch. Hyrum sets that escape hatch automatically when `--host-env-defaults` is enabled (the default); it injects:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
TOX_OVERRIDE='testenv:<target>.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

Disable it with `--no-host-env-defaults` if it interferes with your run.

If you also want `-Werror` semantics, append `PYTHONWARNINGS=error` to `TOX_OVERRIDE` via `pass_env+=`, not `set_env+=`:

```bash
export PYTHONWARNINGS=error
export TOX_OVERRIDE='testenv:unit.pass_env+=PYTHONWARNINGS;testenv:unit.pass_env+=PYO3_USE_ABI3_FORWARD_COMPATIBILITY'
```

The intuitive `set_env+=PYTHONWARNINGS=error` silently drops anything the charm's own `[testenv]` set via `set_env` (most commonly `PYTHONPATH`), so tests that import the charm module fail at collection with `ModuleNotFoundError`. `pass_env+=` does not touch `set_env`, so the charm's `PYTHONPATH` stays intact.

Empirically, on Ubuntu Resolute with system Python 3.14 and 145 runnable charms in the curated list as of 2026-05: a host with none of these prerequisites passes ~40%; adding `build-essential` plus `python3.14-dev` lifts that to ~60%; the full apt list gets to ~64%; the PyO3 forward-compat flag adds ~3% more, topping out around **67%**. The residual ~33% is genuine charm-side breakage (test failures, dependencies pinned to versions that do not build on the host Python) and is not something hyrum itself can move.
