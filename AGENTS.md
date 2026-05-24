# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

`super-tox` bulk-runs a check (typically lint or unit tests) across many charm
repositories, optionally swapping out one of their dependencies first — for
example, pointing every charm's `ops` dependency at a development branch of
the [operator](https://github.com/canonical/operator) repo to see which charms
it breaks. The runner backend is either `tox` or `make`, auto-detected per
charm.

The project is a placeholder name; both the Python package (`super_tox`) and
the console script (`super-tox`) are intentionally easy to rename.

## Common Commands

```bash
tox -e lint    # ruff check + ruff format --check + codespell
tox -e static  # pyright (strict)
tox -e unit    # pytest with coverage
tox -e format  # apply ruff formatting
```

`uv` is the dependency manager (see `pyproject.toml`'s `[dependency-groups]`).
Pre-commit hooks mirror the CI checks; install them with `pre-commit install`.

## Code and Documentation Style

This project follows the Charm Tech team style guides. Read them if more
clarification is required:

- [Documentation and docstring style](https://github.com/canonical/charm-tech/blob/main/STYLE.md)
- [Python style](https://github.com/canonical/charm-tech/blob/main/python/STYLE.md)

Ensure that `pre-commit` is installed (with the user's permission) so that
style is enforced with every commit. If the user does not permit using
`pre-commit`, *always* ensure `tox -e lint,static,unit` shows no issues
before committing.

Avoid writing prose documentation: that is a task for humans. When reviewing
documentation, pay particular attention to consistency with the style guides
above.

## Architecture

- Entry point: `super_tox.cli:main` (a single Click command).
- `enumerate` / `filters` / `frameworks` / `config` — repo selection. Charm
  collection curation is **out of scope**; the tool expects a pre-populated
  cache folder.
- `patchers/` — `Patcher` protocol, `NullPatcher`, `PatcherStack`,
  `OpsSourcePatcher`. The protocol is deliberately narrow so a future
  charm-library patcher (vendored `lib/charms/…/v<n>/<file>.py` swapped from a
  git source) can slot in without changes elsewhere.
- `runners/` — `ToxRunner`, `MakeRunner`, `auto()` per-charm with fallback.
  GNU make's missing-target ambiguity is handled by probing with
  `make -nq` and falling back to stderr inspection.
- `pool` — async worker pool, `Outcome` dataclass with `patcher_error` as a
  status distinct from `failed` (so infrastructure problems don't get
  mis-attributed to the charm).
- `report` — Rich tally + verbose offender lists.

Scope during the 26.10 cycle is **lint and unit tests only**. Do not add
integration-test support.

## Testing

- Unit tests live in `tests/` and follow the layout of `src/super_tox/`.
- Subprocess-driven runners are tested with a `FakeProc` / `FakeSpawner`
  pair (see `tests/test_runners.py`) that monkeypatches
  `asyncio.create_subprocess_exec` — no real subprocesses are spawned in
  the unit suite.
- The ops-source patcher's lockfile regeneration is monkeypatched out (the
  `_run_lock` helper) so unit tests don't spawn `poetry` / `uv`.
