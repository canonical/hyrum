---
myst:
  html_meta:
    description: Investigate a hyrum run with --verbose and --log-dir, and tell a real regression from host noise.
---

# How to triage a run

A run ends with a summary table and, optionally, a list of the charms that did not pass. For what each status and column means, see the [output reference](../reference/output). This guide covers what to do once you have read it: getting at the detail behind a result, and working out whether a failure is really yours.

## Get more detail

Use `--verbose` to include the offender list (failed, timed-out, and errored charms) in the printed report:

```text
hyrum check unit --no-patch --verbose
```

Use `--log-dir` to save each charm's full runner output:

```text
hyrum check unit --no-patch --log-dir ./logs
```

Then inspect individual log files:

```text
cat logs/charm-apt-mirror.log
```

The log file starts with a metadata header (`=== meta ===`) followed by `=== stdout ===` and `=== stderr ===` sections.

## Distinguishing signal from noise

Not every `failed` result is caused by the change you are testing. Common sources of noise:

- Flaky tests that fail intermittently.
- Charms with known pre-existing failures.
- Charms whose dependencies conflict with the Python version on your machine. See [Host prerequisites](install) for the build-tool packages that eliminate most of this.

Compare a patched run against a `--no-patch` baseline to distinguish failures introduced by your change from pre-existing failures:

```text
hyrum check unit --no-patch --save baseline.json
hyrum check unit --patch 'ops @ canonical:fix/my-change' --save patched.json
hyrum compare baseline.json patched.json
```

The charms listed under `NEW FAILURES` are the ones your change broke. See [How to compare two runs](compare-runs) for the full workflow, including the rolling files hyrum saves by default.

See [Explanation: How to interpret signal vs noise](../explanation/design) for more background.
