---
myst:
  html_meta:
    description: Install hyrum from PyPI with uv, build a development checkout, run hyrum in the repository's workshop, and provision the host packages needed to run the charm fleet cleanly.
---

# How to install hyrum

```{warning}
Hyrum executes third-party code on your machine. Unit tests — and, in principle, even lint hooks — run with your user's privileges: anything you can do, a test can do. Charm test suites may not mock every side effect, so a test may write or delete files anywhere your user can reach, install packages, modify `crontab`, download arbitrary content, or reach out to the network.

**Always install and run hyrum inside an isolated VM** (for example, [Multipass](https://canonical.com/multipass) or an LXD virtual machine): create a throwaway instance, install hyrum inside it, and dispose of the instance when you are done. Alternatively, [run hyrum in the repository's workshop](#run-hyrum-in-a-workshop), which runs the checks in a container as a user that cannot modify the host. The other instructions below assume you are already inside a VM.
```

## Install from PyPI

Install hyrum with [uv](https://docs.astral.sh/uv/). Only pre-release versions have been published so far, so `--prerelease=allow` is needed:

```text
uv tool install --prerelease=allow hyrum
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

(run-hyrum-in-a-workshop)=
## Run hyrum in a workshop

The hyrum repository defines a `dev` [workshop](https://ubuntu.com/workshop): a container with hyrum installed from the checkout, along with `uv`, `tox`, `make`, `poetry`, and the build packages listed under [Host prerequisites for fleet runs](#host-prerequisites-for-fleet-runs), so none of these needs installing on the host. The workshop's `hyrum` action runs the CLI in the container as a separate `hyrum-check` user. Workshop mounts the hyrum checkout into the container read-write, but `hyrum-check` can only read it, and has no other access to the host.

From a clone of the repository:

```text
sudo snap install workshop --classic
workshop launch dev
workshop run dev hyrum get-charms
workshop run dev hyrum check unit --patch 'ops @ canonical:some-branch'
```

Every `hyrum` command in this documentation works the same way through `workshop run dev hyrum`. Inside the workshop, `~/.cache/hyrum` is the `hyrum-check` user's cache, `/home/hyrum-check/.cache/hyrum`, so the default charms and results directories apply unchanged. When you pass one of those paths explicitly, write it out in full: your host shell expands `~` to your own home directory before the workshop sees it.

```text
workshop run dev hyrum show /home/hyrum-check/.cache/hyrum/results/unit.auto.json
```

The cache is a workshop mount, so it survives `workshop refresh` but is removed by `workshop remove dev`. To keep it, or to read the saved results from the host, back it with a host directory:

```text
workshop remount dev/hyrum:cache ~/.cache/hyrum
```

The checks can write to that directory, so choose one you are content for third-party test code to write to. See [`CONTRIBUTING.md`](https://github.com/canonical/hyrum/blob/main/CONTRIBUTING.md) for the workshop's other actions and how to clear its cache.

## System requirements

- Python 3.11 or later
- `tox` or `make` on your PATH (whichever your charms use)
- `git` on your PATH, for `hyrum get-charms` and any manual cloning

When `--patch` points at a git URL or local checkout, you also need:

- `poetry` on your PATH if any charms in your charms directory use Poetry
- `uv` on your PATH if any charms use uv

See [How to patch ops to a development branch](patch-ops-branch) for details.

(host-prerequisites-for-fleet-runs)=
## Host prerequisites for fleet runs

A non-trivial fraction of charms pull C/Rust extensions that `pip` or `uv` will build from source if no wheel is available for the host's Python. On a fresh Ubuntu host, missing build tools surface as `failed` outcomes with messages like *"command 'x86_64-linux-gnu-gcc' failed: No such file"* or *"fatal error: Python.h / ffi.h: No such file"*. That is noise rather than a charm regression.

The [workshop](#run-hyrum-in-a-workshop) has these installed already. Elsewhere, to get a clean signal against the curated charm list, install:

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

A handful of charms shell out to other tools (for example `yq`, `go`, `skopeo`, a JDK, libjpeg) from their tox env or Makefile. They are not installed up-front since they only affect a few charms; they surface as `failed` with a `command not found` line in the per-charm log. Install the missing tool to unmask the underlying charm result. A missing `tox` or `make` itself is caught up front by `--preflight` (on by default) rather than once per charm.

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
