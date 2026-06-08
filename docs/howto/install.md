# How to install hyrum

## Install from PyPI

Install hyrum into a virtual environment with pip:

```text
python3 -m venv .venv
source .venv/bin/activate
pip install hyrum
```

Or with uv:

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
- `git` on your PATH, to clone charms separately (hyrum does not clone for you)

When using the ops-source patcher (`--ops-source-branch`), you also need:

- `poetry` on your PATH if any charms in your cache use Poetry
- `uv` on your PATH if any charms use uv

See [How to swap ops to a development branch](swap-ops-branch) for details.
