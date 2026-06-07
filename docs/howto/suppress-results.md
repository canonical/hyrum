# How to suppress known results

If some charm repositories are always expected to fail, or are too slow to be useful, exclude them from hyrum runs with a `hyrum.toml` configuration file.

## Create hyrum.toml

In the directory where you run hyrum, create a file named `hyrum.toml` (or point to one with `--config`):

```toml
[ignore]
expensive     = ["argo-operators", "mysql-router-k8s"]
pre-existing  = ["opensearch-operator"]
manual        = ["my-internal-charm"]
```

Each key under `[ignore]` is a free-form category name. The values are lists of charm paths, relative to the cache folder. The category name appears in the run output as the skip reason, so choose names that explain *why* the charm is excluded.

## Category naming conventions

Good category names make the output self-documenting:

- `expensive` — charms whose tests take too long for routine runs
- `pre-existing` — charms with known failures that predate the change under test
- `manual` — charms that require manual steps before running
- `broken-upstream` — charms that are broken in their own main branch

## Point to a different config file

Use `--config` to use a config file with a non-default path or name:

```text
hyrum unit --no-patch --config ~/configs/hyrum-baseline.toml
```

## Verify which charms are being skipped

Run with `--verbose` to see the full list of skipped charms and their reasons:

```text
hyrum unit --no-patch --verbose
```

Skipped charms appear at the bottom of the verbose output with the category name from your `hyrum.toml` as the reason, for example: `charm-apt-mirror — ignored (expensive)`.

## Paths in monorepos

For charms that live inside a monorepo (for example, `kfp-operators/charms/kfp-ui`), use the path relative to the cache folder:

```toml
[ignore]
slow = ["kfp-operators/charms/kfp-ui"]
```

You can also match by the charm's directory name alone (the last path component):

```toml
[ignore]
slow = ["kfp-ui"]
```

## No per-category limit

You can have as many categories as you like, and each category can list as many paths as needed:

```toml
[ignore]
expensive     = ["mysql-router-k8s", "postgresql-k8s", "mongodb-k8s"]
broken        = ["legacy-charm"]
manual        = ["my-charm-a", "my-charm-b"]
```
