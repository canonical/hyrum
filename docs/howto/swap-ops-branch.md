# How to swap ops to a development branch

The ops-source patcher rewrites each charm's dependency declarations so that `ops` is pulled from a git source instead of PyPI. This lets you run the charm fleet against a pre-release `ops` to find breakages before shipping.

## Basic usage

Point hyrum at a branch of the `canonical/operator` repository:

```text
hyrum unit --ops-source-branch fix/my-change --workers 8
```

Hyrum will:

1. Rewrite each charm's `requirements.txt` or `pyproject.toml` to use `ops` from the git source.
2. Regenerate the lockfile (`poetry.lock` or `uv.lock`) if one is checked in.
3. Run the target (`tox -e unit` or `make unit`).
4. Restore every touched file to its original state when finished.

## Use a fork

To use a branch on a fork rather than the upstream repository:

```text
hyrum unit \
    --ops-source https://github.com/your-fork/operator \
    --ops-source-branch my-experimental-branch
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
hyrum unit --ops-source-branch fix/my-change --lock-timeout 300
```

### Use a custom poetry or uv executable

If `poetry` or `uv` is not on your PATH, or if you need a specific version:

```text
hyrum unit --ops-source-branch fix/my-change \
    --poetry-executable "uvx poetry" \
    --uv-executable "uvx uv"
```

## Python version handling

Some charms declare a `requires-python` that is higher than the Python you are running hyrum under. When `--auto-python` is enabled (the default), hyrum wraps `poetry lock` with `uv run --python X.Y` so that Poetry runs under the charm's minimum Python version.

Disable this behaviour if it causes problems:

```text
hyrum unit --ops-source-branch fix/my-change --no-auto-python
```

## Run without patching

To verify that your charm fleet is passing before applying the patch — useful as a baseline:

```text
hyrum unit --no-patch --workers 8
```

This skips the dependency rewrite entirely and runs against whatever each charm already pins.
