---
myst:
  html_meta:
    description: Use --repo and --limit to run hyrum against one charm for a quick sanity-check or to debug a failure.
---

# How to run against a single charm

To check one specific charm, for a quick sanity-check or to debug a failure, use `--repo` or `--limit` to avoid waiting for a full fleet run.

## Filter by name

`--repo` accepts a case-insensitive regular expression matched against the directory name of each charm in the cache:

```text
# Match any charm whose directory name contains "apt":
hyrum unit --no-patch --repo apt

# Match a charm with an exact name:
hyrum unit --no-patch --repo '^charm-apt-mirror$'
```

## Limit by count

`--limit N` stops after processing the first *N* charms (in the order hyrum discovers them, which is alphabetical):

```text
# Process only the first charm found:
hyrum unit --no-patch --limit 1
```

## Combine filters

You can combine `--repo` and `--limit`:

```text
hyrum unit --no-patch --repo apt --limit 1
```

## Specify a different cache folder

If the charm you want is not in the default cache (`~/.cache/hyrum/charms`), point hyrum at the directory containing it:

```text
hyrum unit --no-patch --cache-folder /path/to/my/charms --repo my-charm
```

Or set the `HYRUM_CHARMS` environment variable instead of passing the flag every time:

```text
export HYRUM_CHARMS=/path/to/my/charms
hyrum unit --no-patch --repo my-charm
```

## Keep the output for inspection

Add `--log-dir` to save the runner's stdout and stderr to a file:

```text
hyrum unit --no-patch --repo my-charm --log-dir ./logs
```

The log file `logs/my-charm.log` will contain the full output for offline inspection.
