# How-to guides

```{toctree}
:hidden:

install
run-charm-list
filter-a-run
patch-ops-branch
patch-other-dependency
interpret-results
compare-runs
suppress-results
```

Procedures for exercising hyrum against a charms directory: installing the tool and its host prerequisites, running the full fleet and narrowing it to the charms you care about, patching a dependency to a development branch or alternative source, and triaging the results table to decide what action to take.

## Running hyrum
<!--
Themes: installation, charm selection, fleet execution, dependency patching
Justification: shared concern — preparing and launching a run against the charms directory, from one charm to the full fleet with optional dependency patches
User journey context: initial setup, run configuration, execution
-->

**[Install hyrum](install)**
: Install hyrum from PyPI with uv, plus the host build packages needed for a clean fleet signal.

**[Run against the charm list](run-charm-list)**
: Use `hyrum get-charms` to populate the charms directory, then run across many charms.

**[Filter a run](filter-a-run)**
: Use `--repo`, `--framework`, or `--limit` to narrow a run to one charm or a subset of the fleet.

**[Patch ops to a development branch](patch-ops-branch)**
: Use `--patch` to test a pre-release `ops` against your charm fleet.

**[Patch a non-ops dependency](patch-other-dependency)**
: Use `--patch` to point any other package at a PyPI pin, a git source, or a local checkout.

## Reading and curating results
<!--
Themes: outcome statuses, summary table interpretation, run-to-run comparison, exclusion lists, baseline curation
Justification: shared concern — turning a run's output into a decision, including diffing against a baseline and suppressing known offenders so future runs surface only new breakage
User journey context: post-run triage, baseline maintenance
Strategic notes: interpret-results explains status semantics; compare-runs turns two runs into a delta; suppress-results acts on that interpretation by codifying expected failures in hyrum.toml. Sequence matters — interpret first, then compare, then curate.
-->

**[Interpret results](interpret-results)**
: Understand each outcome status and decide what action, if any, to take.

**[Compare two runs](compare-runs)**
: Save a baseline and use `hyrum compare` to see which charms your change broke.

**[Suppress known results](suppress-results)**
: Use `hyrum.toml` to exclude repositories from a run.
