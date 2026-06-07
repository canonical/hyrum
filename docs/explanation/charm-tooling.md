# Relationship to charm tooling

Hyrum sits at the intersection of several tools in the Juju charm ecosystem. Understanding how they relate helps clarify both what hyrum is for and what it is not.

## The operator library (ops)

[`ops`](https://github.com/canonical/operator) is the Python framework for writing Juju charms. It provides the charm lifecycle, event dispatch, storage, relations, and the testing harness. Hyrum's primary purpose is to test proposed changes to `ops` against a fleet of charms before the changes are released.

The ops-source patcher — the component that rewrites each charm's dependency declarations — handles the three packaging formats in common use among charms: pip `requirements.txt`, Poetry (`pyproject.toml` with `[tool.poetry]`), and uv (`pyproject.toml` with `[tool.uv]`). It also handles the `ops[testing]` and `ops[tracing]` extras, which pull companion packages from subdirectories of the operator monorepo.

## Testing frameworks

### Scenario (ops[testing])

Scenario is a unit-testing framework for Juju charms, now distributed as the `testing` extra of `ops`. It provides `Context`, `State`, and related constructs for writing tests that simulate charm events without a live model.

Hyrum can filter to Scenario-using charms with `--framework scenario`. Framework detection checks dependency declarations (`ops[testing]`, `ops-scenario`) and falls back to AST analysis of test files if no dependency match is found.

### Jubilant

[Jubilant](https://github.com/canonical/jubilant) is an integration-testing library that wraps the Juju CLI. Hyrum can filter to Jubilant-using charms with `--framework jubilant`.

However, hyrum does not run integration tests. Jubilant is listed as a detectable framework for completeness (and for potential future use), but integration tests are explicitly out of scope for hyrum today. Only charms that have a unit or lint target are useful as subjects.

## Runner backends

Charm repositories use two common build systems:

- **tox** (`tox.ini` present): `tox -e <env>` runs the environment. Hyrum auto-detects this and uses it by default.
- **make** (`Makefile` present): `make <target>` runs the target. GNU make's missing-target behaviour is ambiguous (non-zero exit vs. warning), so hyrum probes with `make -nq` before running.

When both `tox.ini` and `Makefile` are present, hyrum prefers tox. When the requested target is missing, it falls back to the other backend.

## Pebble

[Pebble](https://github.com/canonical/pebble) is the service manager embedded in every Kubernetes charm container. It has its own set of charm consumers and its own evolution challenges. Hyrum's patcher abstraction is designed so that a pebble-library patcher could be added later without changing the runner or pool layers.

## Scope boundaries

Hyrum is a *lint and unit* test runner. It explicitly does not:

- Clone or curate the charm collection (that is a separate concern).
- Run integration tests (requires a live Juju controller and model).
- Act as a general-purpose CI orchestrator.
- Manage or publish charm releases.

The tool exists to answer one question: *does this proposed upstream change break any charm's lint or unit tests?*
