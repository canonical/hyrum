---
myst:
  html_meta:
    description: Complete reference for the hyrum command-line interface, including every subcommand, option, argument, and exit code.
---

# CLI reference

## Synopsis

```text
hyrum [--version] COMMAND ...
```

Hyrum exposes two subcommands:

- `hyrum check TARGET [OPTIONS]` — run `TARGET` (a tox environment name or make target, for example `unit`, `lint`) across many charm repos.
- `hyrum get-charms [OPTIONS]` — clone or update every charm listed in a CSV into the charms directory.

## `hyrum check`

```text
hyrum check [OPTIONS] TARGET
```

`TARGET` is the tox environment name or make target to run in each charm (for example, `unit`, `lint`, `fmt`).

### Charm selection

`--charms-dir PATH`
: Directory containing pre-cloned charm repositories.
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

`--no-patch`
: Skip the dependency-swap step entirely. Run charms against whatever dependencies they already pin. Mutually exclusive with `--patch`.
: Default: off (the default `--patch` of `ops @ canonical:main` applies)

`--patch SPEC`
: Swap a dependency. `SPEC` is a PEP 508 requirement. May be given multiple times (once per package). If `--patch` is not given (and `--no-patch` is not set), hyrum applies the default `ops @ canonical:main`. Accepted forms:
: - `<name>==<version>` (or any PEP 440 specifier) — pin to a PyPI version, for example `ops==2.17.0`, `requests>=1.2,<2`.
: - `<name> @ git+<url>[@<ref>][#subdirectory=<sub>]` — explicit PEP 508 git source. `<ref>` is any git ref (branch, tag, commit SHA).
: - `<name> @ <url>[@<ref>]` — bare `https://…` URL with optional `@ref`.
: - `<name> @ file://<path>`, or a bare path (`/abs`, `./rel`, `~/checkout`) — a local checkout.
: - `ops @ <owner>:<branch>` — GitHub shorthand for `ops` only; expands to `https://github.com/<owner>/operator` at that branch.
: When the patched package is `ops`, hyrum also rewrites the `ops[testing]` and `ops[tracing]` companion packages from matching subdirectories of the operator monorepo.
: Default: `ops @ canonical:main`

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

### Host environment

`--host-env-defaults / --no-host-env-defaults`
: Inject sensible default environment variables (currently `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`) plus matching `TOX_OVERRIDE` `pass_env+=` entries, so common host build issues are not mis-attributed to the charm. Existing values are preserved. See [Host prerequisites](../howto/install) for the rationale.
: Default: `--host-env-defaults`

### Logging and output

`--log-dir PATH`
: Directory to write per-charm log files. Each file contains the runner's stdout, stderr, and run metadata. File names use the charm's path relative to the charms directory with `/` replaced by `__`.
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

## `hyrum get-charms`

```text
hyrum get-charms [OPTIONS]
```

Clone every repository listed in a CSV file into the charms directory, or `git pull` it if the directory already exists. Each row in the CSV is one repository; repositories that host multiple charms in subdirectories are cloned once.

### Options

`--source PATH`
: Path to the charm-list CSV. The expected columns are `Team,Charm Name,Repository,Branch,Source` (additional columns are ignored).
: Default: `charms.csv` or `charm-list/charms.csv` in the current directory.

`--dest PATH`
: Directory to clone into.
: Default: `~/.cache/hyrum/charms`
: Environment variable: `HYRUM_CHARMS`

`--quiet`
: Suppress non-error output.

## Top-level options

`--version`
: Print the installed hyrum version and exit.

`--help`
: Print the help text and exit. Available on each subcommand as well.

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | All non-skipped charms passed (or `--no-fail` was set, or `hyrum get-charms` succeeded) |
| `1`  | At least one charm resulted in `failed`, `timeout`, or `patcher_error` |

## Environment variables

`HYRUM_CHARMS`
: Default charms directory used by both `hyrum check --charms-dir` and `hyrum get-charms --dest`. Overridden by the explicit flag.

`NO_COLOR`
: When set (to any value), suppresses ANSI colour in the summary table even on a tty.

`TOX_OVERRIDE`
: Read and appended to by `--host-env-defaults` so that tox `pass_env` entries propagate into the testenv. See [Host prerequisites](../howto/install).

## Examples

```text
# Populate the default charms directory from the bundled CSV:
hyrum get-charms

# Run tox -e unit with ops swapped to a dev branch, 8 workers:
hyrum check unit --patch 'ops @ canonical:fix/my-change' --workers 8

# Pin ops to a specific PyPI release across the fleet:
hyrum check unit --patch 'ops==2.17.0'

# Swap a non-ops dependency from a git fork:
hyrum check unit --patch 'requests @ git+https://github.com/psf/requests@main'

# Patch ops *and* another dependency in the same run:
hyrum check unit \
    --patch 'ops @ canonical:fix/my-change' \
    --patch 'requests==2.31.0'

# Run without patching:
hyrum check unit --no-patch

# Run only charms that use the Scenario framework:
hyrum check unit --no-patch --framework scenario

# Run only charms matching a name pattern:
hyrum check unit --no-patch --repo '^mysql'

# Save logs for offline triage:
hyrum check unit --no-patch --log-dir ~/hyrum-logs

# Always exit 0 (useful in scripts):
hyrum check unit --no-patch --no-fail

# Show failed charms inline:
hyrum check unit --no-patch --verbose
```
