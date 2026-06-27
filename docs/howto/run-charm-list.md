---
myst:
  html_meta:
    description: Use hyrum get-charms to populate the charms directory from the bundled CSV, then run hyrum across the whole fleet.
---

# How to run against the charm list

The `charm-list/` directory in the hyrum repository contains CSV files listing known charm repositories. Use `hyrum get-charms` to clone or refresh them, then run `hyrum check` across the whole fleet.

## Populate the charms directory

Run `hyrum get-charms` from a checkout of the hyrum repository (so it can find `charm-list/charms.csv`), or pass the CSV explicitly:

```text
# From a hyrum checkout: picks up charm-list/charms.csv automatically.
hyrum get-charms

# From anywhere: point at the CSV explicitly.
hyrum get-charms --source /path/to/charms.csv

# Clone into a non-default directory:
hyrum get-charms --dest /srv/hyrum-charms
```

For each row in the CSV, hyrum clones the repository (shallow) into `<dest>/<repo-name>`, or runs `git pull --ff-only` if the directory is already present. Repositories that host multiple charms in subdirectories are cloned once.

The default destination is `~/.cache/hyrum/charms`, overridable by `HYRUM_CHARMS` or `--dest`. The same default and override apply to `hyrum check --charms-dir`.

## Run across the full fleet

With the charms directory populated, run hyrum without any filters:

```text
hyrum check unit --no-patch --workers 8
```

Increase `--workers` to match your machine's CPU count for faster runs. The default is `1`.

## Filter by testing framework

If you only care about charms that use a particular testing framework, use `--framework`:

```text
# Only charms that use the Scenario testing framework:
hyrum check unit --no-patch --workers 8 --framework scenario
```

Supported values for `--framework`: `scenario`, `jubilant`.

## Filter by name pattern

Use `--repo` to limit the run to a subset of charms by name:

```text
# Only charms whose directory names begin with "mysql":
hyrum check unit --no-patch --workers 4 --repo '^mysql'
```

## Save logs for triage

Pass `--log-dir` to write per-charm output files:

```text
hyrum check unit --no-patch --workers 8 --log-dir ~/hyrum-logs/$(date +%Y%m%d)
```

Each file is named using the charm's path relative to the charms directory, with `/` replaced by `__`. For example, a monorepo charm at `kfp-operators/charms/kfp-ui` produces `kfp-operators__charms__kfp-ui.log`.

## Keep the exit code clean

By default hyrum exits non-zero if any charm fails. In scripted contexts where you want to collect all output regardless:

```text
hyrum check unit --no-patch --no-fail
echo "Exit code: $?"
```

## Suppress known problem charms

If some repositories reliably fail for reasons unrelated to the change you are testing, exclude them with `hyrum.toml`. See [How to suppress known results](suppress-results).
