---
myst:
  html_meta:
    description: Reference for hyrum's outcome statuses, summary table, verbose offender list, log files, and exit codes.
---

# Output reference

## Outcome statuses

Each charm produces exactly one outcome. The possible statuses are:

| Status          | Meaning |
|-----------------|---------|
| `passed`        | The runner exited 0. |
| `failed`        | The runner exited non-zero. |
| `no_target`     | The requested tox environment or make target does not exist in this charm. Not counted as a failure. |
| `timeout`       | The runner was killed after `--timeout` seconds. |
| `runner_error`  | The runner itself could not be launched — for example, `make` is not installed. This is a host problem, not a charm result. |
| `patcher_error` | The dependency swap could not be applied. This is distinct from a runner failure: it points to an infrastructure problem, not a charm test failure. |
| `skipped`       | Excluded before the run began (by `--repo`, `--framework`, `[ignore]` in `hyrum.toml`, no Python source, a legacy reactive/hooks layout, or no `tox.ini`/`Makefile`), or skipped by a patcher that had nothing to do. |

(patcher-skip-reasons)=
### Patcher skip reasons

A patcher skips a charm, rather than reporting `patcher_error`, when the charm simply does not use the thing being swapped. These skips carry a machine-readable category, which appears as an indented row under `skipped` in the summary table:

| Category | Meaning |
|----------|---------|
| `no_pyproject` | The charm has no `pyproject.toml`, so the patched package cannot be one of its declared dependencies. |
| `dep_not_declared` | The charm has a `pyproject.toml`, but does not declare the patched package. |
| `vendored_lib_absent` | A vendored-library swap was requested, but the charm does not vendor that library. |
| `malformed_pyproject` | The charm's `pyproject.toml` has a dependency section of the wrong shape (for example, `[dependency-groups].dev` is not an array). |

## Summary table

After all charms have been processed, hyrum prints a plain-text tally. Columns are separated by two spaces; ANSI colour is applied to status names when stdout is a tty and `NO_COLOR` is unset or empty.

```text
hyrum: unit
STATUS              COUNT     %
passed                 42   70%
failed                  5    8%
no_target               3    5%
timeout                 1    2%
runner_error            0    0%
patcher_error           2    3%
skipped                 7   12%
  dep_not_declared      4    7%
  no_pyproject          2    3%
42 of 48 runs passed (88%); 12 not run (7 skipped, 3 no_target, 2 patcher_error).
```

The `%` column uses the total number of charms (including skipped) as the denominator. The summary line below the table reports the pass rate over charms that were actually run: `passed`, `failed`, and `timeout`. Everything else is counted as not run, broken down by status in the parenthesis.

Indented rows under `skipped` break the skips down by [patcher skip reason](#patcher-skip-reasons). Skips from the up-front filters (`--repo`, `[ignore]`, and so on) have no category and appear only in the `skipped` total.

Use `--no-headers` to suppress the header row.

## Verbose output

With `--verbose`, hyrum appends an offender list after the summary table, grouping charms by status (`failed`, `runner_error`, `patcher_error`, then `timeout`):

```text
failed:
  charm-apt-mirror
  hardware-observer-operator — could not parse pyproject.toml

runner_error:
  charm-nfs-client — make: [Errno 2] No such file or directory

patcher_error:
  opensearch-operator — poetry lock timed out after 600s

skipped:
  legacy-charm — legacy (reactive/hooks) charm
  my-internal-charm — ignored (manual)
```

## Progress logging

While the run is in progress, hyrum logs to stderr with a UTC timestamp and level, for example:

```text
2026-07-28T08:47:35Z INFO Selected 48 charm(s); skipping 12 up-front.
2026-07-28T08:47:35Z INFO Wrote 60 outcomes to ~/.cache/hyrum/results/unit.auto.json
```

Paths under your home directory are rewritten to `~/…` in log messages, so that output pasted into an issue does not leak the account name. `--quiet` raises the level to `WARNING`; `--verbosity debug` lowers it to `DEBUG`.

## Log files

When `--log-dir PATH` is set, hyrum writes one log file per charm. ANSI escape sequences are stripped from the captured output before it is written, since tox forces colour on its subprocesses. Each file name is constructed from the charm's path relative to the charms directory, with `/` replaced by `__`:

| Charm path (relative to charms directory) | Log file name |
|-------------------------------------------|---------------|
| `charm-apt-mirror`                        | `charm-apt-mirror.log` |
| `kfp-operators/charms/kfp-ui`             | `kfp-operators__charms__kfp-ui.log` |

### Successful run log format

```text
=== meta ===
repo: /home/user/.cache/hyrum/charms/charm-apt-mirror
runner: tox
target: unit
status: passed
returncode: 0
duration_s: 12.34
=== stdout ===
<tox stdout>
=== stderr ===
<tox stderr>
```

### Patcher error log format

```text
=== meta ===
repo: /home/user/.cache/hyrum/charms/opensearch-operator
target: unit
status: patcher_error
=== error ===
poetry lock timed out after 600s for opensearch-operator
```

## Saved results

Unless `--no-save` is given, every `hyrum check` run writes its outcomes to a JSON file, so that a later run can be diffed against it with `hyrum compare`. The default is a rolling pair in `~/.cache/hyrum/results`, named after the target:

| File | Contents |
|------|----------|
| `unit.auto.json` | The most recent `hyrum check unit` run. |
| `unit.auto.prev.json` | The run before that, rotated when the current run was saved. |

`--save PATH` writes one named file instead, or a timestamped `hyrum-<UTC>-<target>.json` when `PATH` is an existing directory. Characters outside `A-Za-z0-9._+-` in the target are folded to `-` for the file name.

The file is written to a temporary name and then renamed, so an interrupted save cannot leave a truncated file behind.

### File format

```json
{
  "version": 3,
  "meta": {
    "created_at": "2026-07-28T08:47:35Z",
    "hyrum_version": "1.0.0a1",
    "target": "unit",
    "patcher": "ops @ https://github.com/canonical/operator@main",
    "charms_dir": "/home/user/.cache/hyrum/charms"
  },
  "outcomes": [
    {
      "repo": "canonical/hardware-observer-operator",
      "status": "failed",
      "runner": "tox",
      "target": "unit",
      "duration_s": 48.9,
      "returncode": 1,
      "skip_reason": "",
      "error": "",
      "summary": "3 failed, 102 passed"
    }
  ]
}
```

`version`
: Schema version of the file. The current version is `3`; `hyrum compare` also reads versions 1 and 2. A file with any other version, or one that is not a hyrum results file at all, is rejected with an error naming the file.

`meta`
: What produced the run. Every field is a string, and is empty when unknown (files written by older hyrum versions carry no metadata at all). `patcher` is a one-line summary of the run's `--patch` values, or `none`.

`repo`
: The charm's path relative to the charms directory, so that runs from different hosts or checkouts compare charm-for-charm.

`summary`
: A one-line summary of why the charm did not pass, extracted heuristically from the runner's output — a pytest tally, an exception class, a missing build tool, a resolver error, or a generic `exit N` when nothing recognisable was found. Empty for charms that passed.

## Comparison output

`hyrum compare BASELINE CURRENT` prints a status-level diff. In the default `text` format:

```text
Baseline: baseline.json — saved 2026-07-28T08:47:45Z, target unit, patch none
Current: current.json — saved 2026-07-28T08:47:45Z, target unit, patch ops @ https://github.com/canonical/operator@main

Pass rate: 67% (was 67%) delta +0% (1 new failure, 1 resolved)

NEW FAILURES

  canonical/charm-apt-mirror

RESOLVED

  canonical/hardware-observer-operator
```

Three categories are reported:

`New failures`
: Charms that passed in the baseline and failed in the current run.

`Resolved`
: Charms that failed in the baseline and passed in the current run.

`New errors`
: Charms that ended as `patcher_error`, `runner_error`, or `timeout` in the current run without having done so in the baseline.

If none of the three has any entries, hyrum prints `No changes between runs.` instead.

With `--format markdown`, the same diff is rendered as a document with a pass-rate paragraph, one list per category, and a table with one row per charm that did not pass in either run:

```markdown
# hyrum run comparison (unit)

Baseline pass rate: **67%** (2/3). Current pass rate: **67%** (2/3). 1 new failure(s), 1 resolved, 0 new error(s).

## New failures

- canonical/charm-apt-mirror

| Charm | Baseline | Current |
| --- | --- | --- |
| canonical/charm-apt-mirror | passed | failed: 1 failed, 40 passed |
| canonical/hardware-observer-operator | failed: 3 failed, 102 passed | passed |
```

A cell reads `_absent_` when the charm is missing from that run, and `same` when the current run's cell would be identical to the baseline's.

## Exit codes

| Code | Condition |
|------|-----------|
| `0`  | All non-skipped charms passed (or `--no-fail` was set). |
| `1`  | At least one charm resulted in `failed`, `timeout`, `runner_error`, or `patcher_error`, or the results file could not be written. |
| `2`  | The save target is unusable. Checked before the run starts, so a long run is not lost at the end. |

`no_target` and `skipped` outcomes do not affect the exit code.

`hyrum compare` exits `1` if a results file cannot be read, or if `--fail-on-regression` is set and there are new failures or new errors; otherwise it exits `0`.

## Quiet mode

With `--quiet`, the summary table is suppressed. If any charm failed, hyrum writes a single line to stderr:

```text
hyrum: 5 charm(s) did not pass.
```
