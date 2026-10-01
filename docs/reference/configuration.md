---
myst:
  html_meta:
    description: Reference for the hyrum.toml configuration file format, including the ignore section and all supported keys.
---

# Configuration reference

Hyrum reads an optional TOML file, defaulting to `hyrum.toml` in the current working directory. Use `--config PATH` to specify a different location.

If the file is absent, hyrum runs with no configured exclusions and saves results as if `save = "auto"` were set.

## File format

```text
save = "<mode-or-path>"

[save]
mode = "<mode>"
path = "<path>"

[ignore]
<category> = ["<charm-path>", ...]
```

## `save`

The `save` setting controls where `hyrum check` writes the run's outcomes. It takes either a bare string or a table.

**Type:** `str | dict[str, str]`

The bare-string form takes one of:

- `"auto"`: write the rolling `<target>.auto.json` and `<target>.auto.prev.json` pair into `~/.cache/hyrum/results`.
- `"off"`: do not persist results.
- Any other string: a path. If it names an existing directory, hyrum writes a timestamped file into it; otherwise it is the exact output file.

```toml
save = "~/hyrum-runs"
```

The table form is the only one that pins down both the layout and the location:

```toml
[save]
mode = "timestamped"
path = "~/hyrum-runs"
```

`mode`
: One of `auto`, `off`, `file`, or `timestamped`. Omit it to get the same "pick by what is on disk" behaviour as the bare-string path form.

`path`
: Optional for `auto` (defaults to `~/.cache/hyrum/results`), required for `file` and `timestamped`, and rejected for `off`. `~` is expanded.

The `--save`, `--auto-save`, and `--no-save` command-line options take precedence over this setting. If neither a command-line option nor a `save` setting is present, hyrum saves as if `save = "auto"`.

## `[ignore]`

The `[ignore]` table maps category names to lists of charm paths to exclude.

**Type:** `dict[str, list[str]]`

Each key is a free-form string that names the reason for the exclusion. This string appears in the run output as the skip reason (for example, the `expensive` in `skipped: ignored (expensive)`). Choose names that communicate *why* the charm is excluded.

Each value is a list of charm paths, where each path is one of:

- The path of the charm's directory relative to the charms directory (for example, `kfp-operators/charms/kfp-ui`).
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

# Keep every run's results, named by timestamp, for later comparison:
[save]
mode = "timestamped"
path = "~/hyrum-runs"

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
