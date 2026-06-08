---
myst:
  html_meta:
    description: Build a charm cache from the charm-list CSV files and run hyrum across the whole fleet.
---

# How to run against the charm list

The `charm-list/` directory in the hyrum repository contains CSV files listing known charm repositories. Use these to build and maintain a large cache, then run hyrum across the whole fleet.

## Build the cache

Hyrum does not clone charms for you. Clone each charm in the list into your cache folder. Given the CSV format (`Team,Charm Name,Repository,...`), a simple shell loop works:

```bash
CACHE=~/.cache/hyrum/charms
mkdir -p "$CACHE"

tail -n +2 charm-list/charms.csv | while IFS=, read -r team name repo branch source; do
    dest="$CACHE/$(basename "$repo")"
    if [ -d "$dest" ]; then
        git -C "$dest" pull --ff-only
    else
        git clone "$repo" "$dest"
    fi
done
```

Adjust the loop to handle the optional `Branch` column if you need non-default branches.

## Run across the full fleet

With the cache populated, run hyrum without any filters:

```text
hyrum unit --no-patch --workers 8
```

Increase `--workers` to match your machine's CPU count for faster runs. The default is `1`.

## Filter by testing framework

If you only care about charms that use a particular testing framework, use `--framework`:

```text
# Only charms that use the Scenario testing framework:
hyrum unit --no-patch --workers 8 --framework scenario
```

Supported values for `--framework`: `scenario`, `jubilant`.

## Filter by name pattern

Use `--repo` to limit the run to a subset of charms by name:

```text
# Only charms whose directory names begin with "mysql":
hyrum unit --no-patch --workers 4 --repo '^mysql'
```

## Save logs for triage

Pass `--log-dir` to write per-charm output files:

```text
hyrum unit --no-patch --workers 8 --log-dir ~/hyrum-logs/$(date +%Y%m%d)
```

Each file is named using the charm's path relative to the cache folder, with `/` replaced by `__`. For example, a monorepo charm at `kfp-operators/charms/kfp-ui` produces `kfp-operators__charms__kfp-ui.log`.

## Keep the exit code clean

By default hyrum exits non-zero if any charm fails. In scripted contexts where you want to collect all output regardless:

```text
hyrum unit --no-patch --no-fail
echo "Exit code: $?"
```

## Suppress known problem charms

If some repositories reliably fail for reasons unrelated to the change you are testing, exclude them with `hyrum.toml`. See [How to suppress known results](suppress-results).
