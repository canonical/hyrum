---
myst:
  html_meta:
    description: Use hyrum get-charms to populate the charms directory from the bundled CSV, then run hyrum across the whole fleet.
---

# How to run against the charm list

The `charm-list/` directory in the hyrum repository contains CSV files listing known charm repositories. Use `hyrum get-charms` to clone or refresh them, then run `hyrum check` across the whole fleet.

```{warning}
A fleet run executes the unit tests of every charm in the list on your machine. Those tests run with your user's privileges and may not mock every side effect — they may write or delete files, install packages, modify `crontab`, download arbitrary content, or reach out to the network. **Always run fleet-scale checks inside an isolated VM** (for example, [Multipass](https://multipass.run/) or an LXD virtual machine).
```

## Populate the charms directory

The charm list is not shipped in the hyrum package. Run `hyrum get-charms` from a checkout of the hyrum repository, where it finds `charm-list/charms.csv` automatically, or fetch that file (or supply your own CSV with a `Repository` column) and point at it:

```text
mkdir -p charm-list
curl -sSfL -o charm-list/charms.csv \
    https://raw.githubusercontent.com/canonical/hyrum/main/charm-list/charms.csv
```

Then:

```text
# Picks up charms.csv or charm-list/charms.csv from the current directory.
hyrum get-charms

# From anywhere: point at the CSV explicitly.
hyrum get-charms --source /path/to/charms.csv

# Clone into a non-default directory:
hyrum get-charms --dest /srv/hyrum-charms

# Clone with fewer concurrent git processes (the default is 16):
hyrum get-charms --workers 4
```

For each row in the CSV, hyrum clones the repository (shallow) into `<dest>/<owner>/<name>`, or pulls it if the directory is already present. A row that names a branch is cloned into `<dest>/<owner>/<name>-<branch>`. Repositories that host multiple charms in subdirectories are cloned once.

Clones run concurrently, capped at `--workers` git processes, so that a list of several hundred repositories cannot exhaust the process file-descriptor limit. Only the `Repository` column is required in the CSV; `Branch (if not the default)` is honoured if present, and every other column is ignored.

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

## Compare against an earlier fleet run

Every run saves its outcomes to `~/.cache/hyrum/results` unless you turn that off, so a fleet run can be diffed against the one before it:

```text
hyrum compare ~/.cache/hyrum/results/unit.auto.prev.json \
              ~/.cache/hyrum/results/unit.auto.json
```

See [How to compare two runs](compare-runs) for keeping a longer-lived baseline.

## Keep the exit code clean

By default hyrum exits non-zero if any charm fails. In scripted contexts where you want to collect all output regardless:

```text
hyrum check unit --no-patch --no-fail
echo "Exit code: $?"
```

## Suppress known problem charms

If some repositories reliably fail for reasons unrelated to the change you are testing, exclude them with `hyrum.toml`. See [How to suppress known results](suppress-results).
