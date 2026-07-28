---
myst:
  html_meta:
    description: Save hyrum run results to JSON and diff a patched run against a baseline with hyrum compare.
---

# How to compare two runs

A single run's failure count is rarely the number you want: many charms fail for reasons that predate the change under test. The useful signal is the *delta* between a baseline run and a patched one. Hyrum saves each run's outcomes to a JSON file, and `hyrum compare` diffs two of those files.

## Compare the last two runs

By default, every `hyrum check` run writes a rolling pair of files into `~/.cache/hyrum/results`, named after the target. No flags are needed to get this:

```text
# Baseline: how the charms behave on their own pinned dependencies.
hyrum check unit --no-patch

# Patched: how they behave with the proposed ops change.
hyrum check unit --patch 'ops @ canonical:fix/my-change'

# Diff the previous run against the current one.
hyrum compare ~/.cache/hyrum/results/unit.auto.prev.json \
              ~/.cache/hyrum/results/unit.auto.json
```

Because the rolling files are keyed on the target, a `lint` run does not overwrite the `unit` pair.

## Keep a named baseline

The rolling pair only remembers one run back. To keep a baseline that survives further runs, name the file:

```text
hyrum check unit --no-patch --save ~/hyrum-runs/baseline.json

# ... any number of other runs later ...
hyrum check unit --patch 'ops @ canonical:fix/my-change' --save ~/hyrum-runs/patched.json
hyrum compare ~/hyrum-runs/baseline.json ~/hyrum-runs/patched.json
```

Pass an existing directory instead of a file to have hyrum name the file after the run's timestamp and target:

```text
hyrum check unit --save ~/hyrum-runs/
# writes ~/hyrum-runs/hyrum-20260728T084735Z-unit.json
```

To make that the default for every run, set it in `hyrum.toml`:

```toml
[save]
mode = "timestamped"
path = "~/hyrum-runs"
```

## Read the comparison

```text
Baseline: baseline.json — saved 2026-07-28T08:47:45Z, target unit, patch none
Current: patched.json — saved 2026-07-28T09:31:02Z, target unit, patch ops @ canonical:fix/my-change

Pass rate: 64% (was 67%) delta -3% (4 new failures, 1 resolved)

NEW FAILURES

  canonical/charm-apt-mirror
  ...
```

The charms under `NEW FAILURES` are the ones to investigate: they passed on their pinned dependencies and fail with the patch applied. `NEW ERRORS` lists charms that newly ended as `patcher_error` or `timeout`, which usually points at an infrastructure problem rather than a regression. Charms that fail in both runs do not appear at all.

Charms are matched by their path relative to the charms directory, so a baseline saved on one machine can be compared against a run from another.

## Gate a script or CI job on regressions

`hyrum compare --fail-on-regression` exits non-zero when there are new failures or new errors:

```text
hyrum check unit --patch 'ops @ canonical:main' --save current.json --no-fail
hyrum compare baseline.json current.json --fail-on-regression
```

Passing `--no-fail` to the check step keeps the run's own pre-existing failures from failing the job: the comparison is what decides the outcome.

## Produce a report to share

`--format markdown` renders the diff as a document with a pass-rate summary, a list per category, and a table of every non-passing charm with a one-line reason for each run:

```text
hyrum compare baseline.json current.json --format markdown > report.md
```

Paste the result into an issue or a pull request on the dependency you are testing.

## Turn saving off

If you do not want results on disk at all:

```text
hyrum check unit --no-save
```

Or set `save = "off"` in `hyrum.toml`.
