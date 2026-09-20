---
myst:
  html_meta:
    description: The dependency declarations, patch subjects, testing frameworks, and runner backends that hyrum supports.
---

# Supported charms

Whether hyrum can run a charm depends on three things: how the charm declares its dependencies, what it can be asked to patch, and whether the repository has a target hyrum can run.

## Dependency declarations

| Format | Detected by |
|---|---|
| pip | `requirements.txt` |
| Poetry | `[tool.poetry]` in `pyproject.toml` |
| uv | `[tool.uv]` in `pyproject.toml` |
| PEP 621 extras | `[project.optional-dependencies]` in `pyproject.toml` |
| PEP 735 groups | `[dependency-groups]` in `pyproject.toml` |

The `ops[testing]` and `ops[tracing]` extras are handled, including the companion packages they pull from subdirectories of the operator monorepo.

## What can be patched

| Subject | Patcher | Form |
|---|---|---|
| `ops` | ops-source | Branch, tag, commit, PyPI version, or local path |
| Any other package | generic | `--patch <PEP 508 requirement>` |
| `charmlibs-*` | charmlibs | Branch of the [charmlibs](https://github.com/canonical/charmlibs) monorepo |
| Vendored `lib/charms/<author>/v<n>/<lib>.py` | vendored-library | Replaced by the published package, with the charm's imports rewritten |

Most charms use neither a given charm library nor its vendored ancestor, so charm-library runs report the bulk of the fleet as `skipped` rather than as an error.

## Detectable frameworks

| `--framework` | Detected by |
|---|---|
| `scenario` | An `ops[testing]` or `ops-scenario` dependency, falling back to AST analysis of test files |
| `jubilant` | A `jubilant` dependency |

Jubilant is detectable, but hyrum does not run integration tests, so only charms with a unit or lint target are useful subjects.

## Runner backends

| Backend | Detected by | Invocation |
|---|---|---|
| tox | `tox.ini` | `tox -e <target>` |
| make | `Makefile` | `make <target>` |

When both are present, hyrum prefers tox. When the requested target is missing, it falls back to the other backend. GNU make's missing-target behaviour is ambiguous (non-zero exit or a warning), so hyrum probes with `make -nq` before running.
