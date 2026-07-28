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

Hyrum exposes three subcommands:

- `hyrum check TARGET [OPTIONS]` — run `TARGET` (a tox environment name or make target, for example `unit`, `lint`) across many charm repos.
- `hyrum compare BASELINE CURRENT [OPTIONS]` — diff two saved runs.
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
: Path to the TOML configuration file. The `[ignore]` table and the `save` setting are read.
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
: - `ops @ <owner>:<branch>` — GitHub shorthand for `ops`; expands to `https://github.com/<owner>/operator` at that branch.
: - `charmlibs-<name> @ <owner>:<branch>` — GitHub shorthand for a charm library; expands to `https://github.com/<owner>/charmlibs` at that branch, with the subdirectory taken from the package name verbatim. Type the separators the way the directory exists in the monorepo (for example, `charmlibs-nginx_k8s`, `charmlibs-interfaces-k8s-service`). Charmlibs packages must be patched from a git source: a version pin or a local path is rejected.
: - `charms.<author>.v<n>.<lib> -> <spec>` — swap a vendored charm library for a package. The left side is the dotted import path of the vendored `lib/charms/<author>/v<n>/<lib>.py` file; `<spec>` is any of the forms above for the replacement package, for example `charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0`.
: The `owner:branch` shorthand is only accepted for `ops` and `charmlibs-*` packages. Any other package needs an explicit `git+<url>` or bare `https://…` URL.
: When the patched package is `ops`, hyrum also rewrites the `ops[testing]` and `ops[tracing]` companion packages from matching subdirectories of the operator monorepo.
: Extras written into `SPEC` are not honoured: the patcher preserves whatever extras the charm itself declares.
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

### Saving results

The three save options are mutually exclusive. When none of them is given, hyrum reads the `save` setting from `hyrum.toml`; if that is absent too, it falls back to `--auto-save` with the default directory. An unusable save target is rejected before the run starts, rather than after it.

`--save PATH`
: Write the run's outcomes as JSON. If `PATH` is an existing directory, hyrum writes a timestamped `hyrum-<UTC>-<target>.json` file inside it; otherwise `PATH` is the exact output file.
: Default: (not set)

`--auto-save [DIR]`
: Write a rolling pair of files into `DIR`: `<target>.auto.json` for this run, with the previous run's file rotated to `<target>.auto.prev.json`. Keyed on the target, so runs of different targets do not clobber each other.
: Default: `~/.cache/hyrum/results` (also the default when no save option is given at all)

`--no-save`
: Do not persist results.
: Default: off

## `hyrum compare`

```text
hyrum compare [OPTIONS] BASELINE CURRENT
```

Diff two saved results files at the status level: which charms newly fail, which are resolved, and which newly error. `BASELINE` and `CURRENT` are paths to JSON files written by `hyrum check` (see [Output reference](output)).

Charms are matched by their path relative to the charms directory, so two runs from different hosts or checkouts still compare charm-for-charm. A charm present in only one of the runs is reported as absent rather than as a change. If the two files record different targets, hyrum prints a warning to stderr and compares them anyway.

### Options

`--fail-on-regression / --no-fail-on-regression`
: Exit non-zero if there are any new failures or new errors relative to the baseline.
: Default: `--no-fail-on-regression`

`--format {text,markdown}`
: `text`: the colourised status-level summary, preceded by a line of metadata for each run.
: `markdown`: a document with a pass-rate paragraph, a list per change category, and a table with one row per non-passing charm, including each run's failure summary. Suitable for pasting into an issue or pull request.
: Default: `text`

## `hyrum get-charms`

```text
hyrum get-charms [OPTIONS]
```

Clone every repository listed in a CSV file into the charms directory, or `git pull` it if the directory already exists. Each row in the CSV is one repository; repositories that host multiple charms in subdirectories are cloned once.

Each repository is cloned to `<dest>/<owner>/<name>`, where `<owner>` and `<name>` are the last two components of the repository URL. A row that names a branch is cloned to `<dest>/<owner>/<name>-<branch>`, so the same repository can be present at more than one branch.

### Options

`--source PATH`
: Path to the charm-list CSV. Only the `Repository` column (required) and `Branch (if not the default)` column (optional) are read; any other column, such as those in the bundled `charm-list/charms.csv`, is ignored.
: Default: `charms.csv` or `charm-list/charms.csv` in the current directory.

`--dest PATH`
: Directory to clone into.
: Default: `~/.cache/hyrum/charms`
: Environment variable: `HYRUM_CHARMS`

`--workers N`
: Maximum number of concurrent `git` subprocesses. The cap keeps a large charm list from exhausting the process file-descriptor limit.
: Default: `16`

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
| `0`  | All non-skipped charms passed (or `--no-fail` was set, or `hyrum get-charms` succeeded, or `hyrum compare` found no regressions) |
| `1`  | At least one charm resulted in `failed`, `timeout`, or `patcher_error`; or the results file could not be written; or `hyrum compare` could not read a results file, or found a regression under `--fail-on-regression` |
| `2`  | The save target given to `hyrum check` is unusable (a missing or unwritable directory, or a path that is a directory when a file is expected). Checked before the run starts. |

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

# Point a charm library at a branch of canonical/charmlibs:
hyrum check unit --patch 'charmlibs-nginx_k8s @ canonical:main'

# Replace a vendored charm library with its PyPI package:
hyrum check unit --patch 'charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0'

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

# Save a baseline, then diff a patched run against it:
hyrum check unit --no-patch --save baseline.json
hyrum check unit --patch 'ops @ canonical:fix/my-change' --save current.json
hyrum compare baseline.json current.json

# Gate on regressions, and produce a table to paste into a pull request:
hyrum compare baseline.json current.json --fail-on-regression
hyrum compare baseline.json current.json --format markdown > report.md
```
