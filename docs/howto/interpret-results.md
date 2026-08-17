---
myst:
  html_meta:
    description: Read the hyrum summary table and verbose offender list, and decide what to do about each outcome status.
---

# How to interpret results

After a run, hyrum prints a summary table and an optional verbose offender list. This guide explains what each status means and how to act on it.

## The summary table

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

The percentage column uses the total number of charms (including skipped) as the denominator. The summary line below the table reports the pass rate over the charms that actually ran — `passed`, `failed`, and `timeout` — and breaks the rest down by status.

Indented rows under `skipped` show why a patcher skipped a charm, when it was a patcher rather than an up-front filter that did the skipping.

## Status meanings

`passed`
: The runner exited with return code 0. The charm's tests (or lint) passed under the current configuration.

`failed`
: The runner exited with a non-zero return code. The charm's tests or lint reported failures. Investigate with `--verbose` or `--log-dir`.

`no_target`
: The requested tox environment or make target does not exist in this charm. This is not a failure: the charm simply doesn't have this kind of test. Hyrum does not count `no_target` as a failure when computing the exit code.

`timeout`
: The runner was killed after `--timeout` seconds (default: 1800). The charm may have a very slow test suite, or it may be hanging. Investigate the log file if you saved one with `--log-dir`.

`runner_error`
: The runner itself could not be launched — for example, `make` is not installed on the host. This is a host problem, not a charm result, so it is reported separately from `failed`. `--preflight` (on by default) catches a missing runner before the run starts, so this status usually means the executable disappeared mid-run or is not executable.

`patcher_error`
: The dependency swap could not be applied. For example, the charm's `pyproject.toml` could not be parsed, or `poetry lock` failed in a way hyrum could not recover from. This is an infrastructure problem, not a charm failure. Use `--verbose` to see the error message.

`skipped`
: The charm was excluded before the run began. Common skip reasons:
: - Matched the `[ignore]` table in `hyrum.toml`.
: - Did not match the `--repo` regex.
: - Has no Python source (no `src/` or `lib/` Python).
: - Is a reactive or classic hooks-based charm (has `src/reactive/` with `src/layer.yaml`, or a `hooks/` directory).
: - Has neither `tox.ini` nor `Makefile`.
: - Did not match the `--framework` filter.
: A charm is also skipped when the patcher has nothing to do — it does not declare the package you are patching (`dep_not_declared`), has no `pyproject.toml` at all (`no_pyproject`), or does not vendor the library you asked to swap (`vendored_lib_absent`). These are expected, not errors: patching `charmlibs-apt` across the fleet will skip most of it. The exception is `malformed_pyproject`, which means the charm's `pyproject.toml` has a dependency section of the wrong shape.

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
