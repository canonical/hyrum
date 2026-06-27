---
myst:
  html_meta:
    description: Point every charm's ops dependency at a development branch of canonical/operator to find breakages before release.
---

# How to swap ops to a development branch

The ops-source patcher rewrites each charm's dependency declarations so that `ops` is pulled from a git source instead of PyPI. This lets you run the charm fleet against a pre-release `ops` to find breakages before shipping.

For swapping any *other* dependency, see [How to swap a non-ops dependency](swap-other-dependency).

## Basic usage

Point hyrum at a branch of the `canonical/operator` repository using the `owner:branch` shorthand:

```text
hyrum check unit --patch 'ops @ canonical:fix/my-change' --workers 8
```

`--patch` is a PEP 508 requirement. For `ops`, the accepted forms are:

- `ops @ canonical:fix/my-change` — `owner:branch` shorthand (ops-only); expands to `https://github.com/canonical/operator` at that branch.
- `ops @ https://github.com/canonical/operator@fix/my-change` — bare git URL with optional `@ref` (branch, tag, or commit SHA).
- `ops @ git+https://github.com/canonical/operator@fix/my-change` — explicit PEP 508 form (the one `pip` and `uv` print).
- `ops==2.17.0` (or any PEP 440 specifier) — a PyPI version; companion packages still resolve from PyPI.
- `ops @ ~/operator`, `ops @ /abs/operator`, or `ops @ file:///abs/operator` — a local operator checkout.

If `--patch` is omitted (and `--no-patch` is not set), hyrum defaults to `ops @ canonical:main`. Pass `--patch` to override or `--no-patch` to disable patching entirely.

Hyrum will:

1. Rewrite each charm's `requirements.txt` or `pyproject.toml` so `ops` is pulled from the patched source.
2. Regenerate the lockfile (`poetry.lock` or `uv.lock`) if one is checked in.
3. Run the target (`tox -e unit` or `make unit`).
4. Restore every touched file to its original state when finished.

## Use a fork

To use a branch on a fork rather than the upstream repository:

```text
hyrum check unit --patch 'ops @ your-fork:my-experimental-branch'
```

## Companion packages

When a charm uses the `testing` or `tracing` extras of `ops`, the patcher also rewrites the companion packages:

- `ops[testing]` → `ops-scenario` from the `testing/` subdirectory of the monorepo
- `ops[tracing]` → `ops-tracing` from the `tracing/` subdirectory of the monorepo

Both are sourced from the same git ref as `ops` itself. No extra flags are needed; the patcher detects the extras automatically.

## Lockfile regeneration

When patching a charm that uses Poetry or uv (detected by the presence of `poetry.lock` or `uv.lock`), hyrum regenerates the lockfile so the dependency graph is consistent with the new source.

If regeneration fails (for example, because the charm has an unresolvable dependency under the new `ops` source), hyrum logs a warning, deletes the stale lockfile, and continues. The runner may then re-generate it on demand, or fail with an informative error.

### Tune the lock timeout

Lockfile regeneration can take a few minutes for large charms. The default timeout is 600 seconds per charm. Adjust it if needed:

```text
hyrum check unit --patch 'ops @ canonical:fix/my-change' --lock-timeout 300
```

### Use a custom poetry or uv executable

If `poetry` or `uv` is not on your PATH, or if you need a specific version:

```text
hyrum check unit --patch 'ops @ canonical:fix/my-change' \
    --poetry-executable "uvx poetry" \
    --uv-executable "uvx uv"
```

## Python version handling

Some charms declare a `requires-python` that is higher than the Python you are running hyrum under. When `--auto-python` is enabled (the default), hyrum wraps `poetry lock` with `uv run --python X.Y` so that Poetry runs under the charm's minimum Python version.

Disable this behaviour if it causes problems:

```text
hyrum check unit --patch 'ops @ canonical:fix/my-change' --no-auto-python
```

## Run without patching

Run a baseline first, to see which charms pass before the patch is applied:

```text
hyrum check unit --no-patch --workers 8
```

This skips the dependency rewrite entirely and runs against whatever each charm already pins.
