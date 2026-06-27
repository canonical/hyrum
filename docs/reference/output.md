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
| `patcher_error` | The dependency swap could not be applied. This is distinct from a runner failure: it points to an infrastructure problem, not a charm test failure. |
| `skipped`       | Excluded before the run began (by `--repo`, `--framework`, `[ignore]` in `hyrum.toml`, no Python source, a legacy reactive/hooks layout, or no `tox.ini`/`Makefile`). |

## Summary table

After all charms have been processed, hyrum prints a plain-text tally. Columns are separated by two spaces; ANSI colour is applied to status names when stdout is a tty and `NO_COLOR` is unset.

```text
hyrum: unit
STATUS         COUNT     %
passed            42   70%
failed             5    8%
no_target          3    5%
timeout            1    2%
patcher_error      2    3%
skipped            7   12%
42 of 48 runs passed (88%); 12 skipped or errored.
```

The `%` column uses the total number of charms (including skipped) as the denominator. The summary line below the table reports the pass rate over charms that were actually run (excluding `skipped` and `no_target`).

Use `--no-headers` to suppress the header row.

## Verbose output

With `--verbose`, hyrum appends an offender list after the summary table, grouping charms by status:

```text
failed:
  charm-apt-mirror
  hardware-observer-operator — could not parse pyproject.toml

patcher_error:
  opensearch-operator — poetry lock timed out after 600s

skipped:
  legacy-charm — legacy (reactive/hooks) charm
  my-internal-charm — ignored (manual)
```

## Log files

When `--log-dir PATH` is set, hyrum writes one log file per charm. Each file name is constructed from the charm's path relative to the charms directory, with `/` replaced by `__`:

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

## Exit codes

| Code | Condition |
|------|-----------|
| `0`  | All non-skipped charms passed (or `--no-fail` was set). |
| `1`  | At least one charm resulted in `failed`, `timeout`, or `patcher_error`. |

`no_target` and `skipped` outcomes do not affect the exit code.

## Quiet mode

With `--quiet`, the summary table is suppressed. If any charm failed, hyrum writes a single line to stderr:

```text
hyrum: 5 charm(s) did not pass.
```
