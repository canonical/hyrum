# Configuration reference

Hyrum reads an optional TOML file, defaulting to `hyrum.toml` in the current working directory. Use `--config PATH` to specify a different location.

If the file is absent, hyrum runs with no configured exclusions.

## File format

```text
[ignore]
<category> = ["<charm-path>", ...]
```

## `[ignore]`

The `[ignore]` table maps category names to lists of charm paths to exclude.

**Type:** `dict[str, list[str]]`

Each key is a free-form string that names the reason for the exclusion. This string appears in the run output as the skip reason (for example, `skipped — ignored (expensive)`). Choose names that communicate *why* the charm is excluded.

Each value is a list of charm paths, where each path is one of:

- The path of the charm's directory relative to the cache folder (for example, `kfp-operators/charms/kfp-ui`).
- The bare directory name of the charm (the last path component, for example, `kfp-ui`). Hyrum matches by both the full relative path and the bare name.

### Example

```toml
[ignore]
expensive    = ["argo-operators", "mysql-router-k8s", "postgresql-k8s"]
pre-existing = ["opensearch-operator"]
manual       = ["my-internal-charm"]
```

### Notes

- Category names are case-sensitive.
- Categories have no semantic meaning to hyrum beyond the label they produce in output.
- There is no limit on the number of categories or entries per category.
- The table is silently ignored if `[ignore]` is absent or empty.

## Full example

```toml
# hyrum.toml
# Charm exclusions for the ops 4.x pre-release compatibility check.

[ignore]
# Takes > 30 min to run; not worth including in routine checks:
expensive = [
    "argo-operators",
    "mysql-router-k8s",
    "postgresql-k8s",
    "mongodb-k8s",
]

# Known pre-existing failures that are not related to ops:
pre-existing = [
    "opensearch-operator",
]

# Requires manual setup steps before running:
manual = [
    "hardware-observer-operator",
]
```
