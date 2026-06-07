# How to interpret results

After a run, hyrum prints a summary table and an optional verbose offender list. This guide explains what each status means and how to act on it.

## The summary table

```text
                    hyrum: unit
 ┌───────────────┬───────┬──────┐
 │ STATUS        │ COUNT │    % │
 ├───────────────┼───────┼──────┤
 │ passed        │    42 │  70% │
 │ failed        │     5 │   8% │
 │ no_target     │     3 │   5% │
 │ timeout       │     1 │   2% │
 │ patcher_error │     2 │   3% │
 │ skipped       │     7 │  12% │
 └───────────────┴───────┴──────┘
 42 of 48 runs passed (88%); 12 skipped or errored.
```

The percentage column uses the total number of charms (including skipped) as the denominator.

## Status meanings

`passed`
: The runner exited with return code 0. The charm's tests (or lint) passed under the current configuration.

`failed`
: The runner exited with a non-zero return code. The charm's tests or lint reported failures. Investigate with `--verbose` or `--log-dir`.

`no_target`
: The requested tox environment or make target does not exist in this charm. This is not a failure — the charm simply does not have this kind of test. Hyrum does not count `no_target` as a failure when computing the exit code.

`timeout`
: The runner was killed after `--timeout` seconds (default: 1800). The charm may have a very slow test suite, or it may be hanging. Investigate the log file if you saved one with `--log-dir`.

`patcher_error`
: The dependency swap could not be applied. For example, the charm's `pyproject.toml` could not be parsed, or `poetry lock` failed in a way hyrum could not recover from. This is an infrastructure problem, not a charm failure. Use `--verbose` to see the error message.

`skipped`
: The charm was excluded before the run began. Common skip reasons:
: - Matched the `[ignore]` table in `hyrum.toml`.
: - Did not match the `--repo` regex.
: - Has neither `tox.ini` nor `Makefile`.
: - Is a reactive or classic hooks-based charm (has a `reactive/` or `hooks/` directory).
: - Did not match the `--framework` filter.

## Get more detail

Use `--verbose` to include the offender list (failed, timed-out, and errored charms) in the printed report:

```text
hyrum unit --no-patch --verbose
```

Use `--log-dir` to save each charm's full runner output:

```text
hyrum unit --no-patch --log-dir ./logs
```

Then inspect individual log files:

```text
cat logs/charm-apt-mirror.log
```

The log file starts with a metadata header (`=== meta ===`) followed by `=== stdout ===` and `=== stderr ===` sections.

## Distinguishing signal from noise

Not every `failed` result is caused by the change you are testing. Common sources of noise include:

- Charms with flaky tests that fail intermittently.
- Charms that have known pre-existing failures.
- Charms whose dependencies conflict with a newer Python version on your machine.

Compare a patched run against a `--no-patch` baseline to distinguish failures introduced by your change from pre-existing failures:

```text
hyrum unit --no-patch --log-dir ./baseline
hyrum unit --ops-source-branch fix/my-change --log-dir ./patched
```

Any charm that appears in the `failed` column for the patched run but not the baseline is a genuine regression introduced by your change.

See [Explanation: How to interpret signal vs noise](../explanation/design) for more background.
