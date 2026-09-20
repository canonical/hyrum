---
myst:
  html_meta:
    description: Use --repo, --framework, and --limit to narrow a hyrum run to one charm or a subset of the fleet.
---

# How to filter a run

A run covers every charm in the charms directory unless you narrow it. Use `--repo`, `--framework`, and `--limit` to check a single charm, a group of them, or just the first few — for a quick sanity-check, or to debug one failure without waiting for a full fleet run.

These instructions assume the charms directory is already populated. See [How to run against the charm list](run-charm-list) if it is not.

## Run one named charm

`--repo` accepts a case-insensitive regular expression matched against the directory name of each charm, so anchor the pattern to pin it to exactly one charm:

```text
hyrum check unit --no-patch --repo '^charm-apt-mirror$'
```

## Match a group of charms

Without the anchors, the same flag selects every charm whose name matches:

```text
# Any charm whose directory name contains "apt":
hyrum check unit --no-patch --repo apt

# Any charm whose directory name begins with "mysql":
hyrum check unit --no-patch --repo '^mysql'
```

## Filter by testing framework

If you only care about charms that use a particular testing framework, use `--framework`:

```text
# Only charms that use the Scenario testing framework:
hyrum check unit --no-patch --framework scenario
```

Supported values for `--framework`: `scenario`, `jubilant`.

## Limit by count

`--limit N` stops once *N* charms have been selected to run, taken in the order hyrum discovers them, which is alphabetical:

```text
# Run only the first runnable charm found:
hyrum check unit --no-patch --limit 1
```

Charms that the filters skip — legacy charms, charms with no Python source, charms without the requested target — do not count towards *N*. They still show up in the skipped tally, so the summary stays honest about what was looked at on the way there.

## Combine filters

The filters compose, so you can pin a pattern and cap the count together:

```text
hyrum check unit --no-patch --repo apt --limit 1
```
