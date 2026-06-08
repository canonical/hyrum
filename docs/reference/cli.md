---
myst:
  html_meta:
    description: Complete reference for the hyrum command-line interface, including every option, argument, and exit code.
---

# CLI reference

## Synopsis

```text
hyrum [OPTIONS] TARGET
```

`TARGET` is the tox environment name or make target to run in each charm (for example, `unit`, `lint`, `fmt`).

## Options

### Charm selection

`--cache-folder PATH`
: Folder containing pre-cloned charm repositories.
: Default: `~/.cache/hyrum/charms`
: Environment variable: `HYRUM_CHARMS`

`--config PATH`
: Path to the TOML configuration file.
: Default: `hyrum.toml` (in the current directory; silently ignored if absent)

`--repo REGEX`
: Case-insensitive regular expression matched against each charm's directory name. Only matching charms are processed.
: Default: `.*` (all charms)

`--limit N`
: Stop after processing the first *N* charms discovered (0 = no limit).
: Default: `0`

`--framework {scenario,jubilant}`
: Only process charms that use the specified testing framework. Framework detection checks dependency declarations first, then falls back to AST scanning of test files.
: Default: (no filter; all frameworks)

### Runner

`--runner {auto,tox,make}`
: Which runner backend to use.
: `auto`: prefer tox if `tox.ini` is present, otherwise prefer make; fall back to the other backend if the requested target is absent.
: `tox`: always use tox.
: `make`: always use make.
: Default: `auto`

`--workers N`
: Number of charm repositories to process concurrently (minimum: 1).
: Default: `1`

`--tox-executable CMD`
: Tox command to use.
: Default: `tox`

`--make-executable CMD`
: Make command to use.
: Default: `make`

`--timeout SECONDS`
: Per-charm timeout in seconds. Charms that exceed this are marked `timeout`.
: Default: `1800`

### Dependency patching

`--no-patch / --patch`
: Skip the dependency-swap step entirely. Run charms against whatever dependencies they already pin.
: Default: `--patch` (when patching, charms are run against the default branch of `--ops-source` unless another ref is supplied)

`--ops-source SPEC`
: Where to pull `ops` from. Accepts several forms:
: - PyPI version (`2.17.0`, or any PEP 440 version). Companion packages (`ops-scenario`, `ops-tracing`) resolve from PyPI normally.
: - `git+<url>[@ref]` — explicit git URL (the form `pip` and `uv` print). `ref` is any git ref: branch, tag, or commit SHA.
: - `<url>[@ref]` — bare `https://…` git URL with optional `@ref`.
: - `owner:branch` — GitHub shorthand, expands to `https://github.com/<owner>/operator` at that branch.
: - `file://<path>` or a bare path (`/abs/operator`, `./operator`, `~/operator`) — a local operator checkout.
: Default: `https://github.com/canonical/operator` (the default branch)

`--poetry-executable CMD`
: Poetry command used to regenerate `poetry.lock` after patching.
: Accepts a shell-quoted string (`"uvx poetry"`) or a single executable name.
: Default: `poetry`

`--uv-executable CMD`
: `uv` command used to regenerate `uv.lock` after patching.
: Default: `uv`

`--lock-timeout SECONDS`
: Timeout for `poetry lock` or `uv lock` during patching. Independent of `--timeout` (the per-charm runner timeout).
: Default: `600`

`--auto-python / --no-auto-python`
: When enabled, hyrum wraps `poetry lock` with `uv run --python X.Y` so that the lock command runs under an interpreter that satisfies the charm's declared `requires-python`. Requires `uv` on PATH.
: Default: `--auto-python`

### Logging and output

`--log-dir PATH`
: Directory to write per-charm log files. Each file contains the runner's stdout, stderr, and run metadata. File names use the charm's path relative to the cache folder with `/` replaced by `__`.
: Default: (not set; logs are not written)

`--quiet`
: Suppress all output except errors. The exit code still reflects pass/fail. Mutually exclusive with `--verbose` and `--verbosity`.
: Default: off

`--verbose`
: Include the per-charm offender list in the report (failed, timed-out, and errored charms with their error messages, plus all skipped charms with their reasons). Mutually exclusive with `--quiet` and `--verbosity`.
: Default: off

`--verbosity {debug,trace}`
: Developer-level log verbosity.
: `debug`: detailed execution logging.
: `trace`: currently aliased to `debug`; reserved for future per-line code tracing.
: Mutually exclusive with `--quiet` and `--verbose`.
: Default: (not set; INFO level)

`--no-headers`
: Suppress the header row in the summary table.
: Default: off

`--no-fail`
: Always exit with code 0, even if some charms failed. The summary is still printed.
: Default: off (exit non-zero on any failure)

### Meta

`--version`
: Print the installed hyrum version and exit.

`--help`
: Print the help text and exit.

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | All non-skipped charms passed (or `--no-fail` was set) |
| `1`  | At least one charm resulted in `failed`, `timeout`, or `patcher_error` |

## Environment variables

`HYRUM_CHARMS`
: Default value for `--cache-folder`. Overridden by the `--cache-folder` flag.

## Examples

```text
# Run tox -e unit with ops swapped to a dev branch, 8 workers:
hyrum unit --ops-source canonical:fix/my-change --workers 8

# Run without patching:
hyrum unit --no-patch

# Run only charms that use the Scenario framework:
hyrum unit --no-patch --framework scenario

# Run only charms matching a name pattern:
hyrum unit --no-patch --repo '^mysql'

# Save logs for offline triage:
hyrum unit --no-patch --log-dir ~/hyrum-logs

# Always exit 0 (useful in scripts):
hyrum unit --no-patch --no-fail

# Show failed charms inline:
hyrum unit --no-patch --verbose
```
