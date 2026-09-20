# How-to guides

```{toctree}
:hidden:

install
run-charm-list
filter-a-run
patch-ops-branch
patch-other-dependency
triage-a-run
compare-runs
suppress-results
reclaim-disk-space
```

Procedures for exercising hyrum against a charms directory: installing the tool and its host prerequisites, running the full fleet and narrowing it to the charms you care about, patching a dependency to a development branch or alternative source, triaging the results table to decide what action to take, and keeping the charms directory from filling the disk.

## Running hyrum
<!--
Themes: installation, charm selection, fleet execution, dependency patching
Justification: shared concern — preparing and launching a run against the charms directory, from the full fleet down to a single charm, with optional dependency patches
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
Themes: outcome statuses, summary table interpretation, re-reading saved runs, run-to-run comparison, exclusion lists, baseline curation, cache maintenance
Justification: shared concern — turning a run's output into a decision, including diffing against a baseline and suppressing known offenders so future runs surface only new breakage
User journey context: post-run triage, baseline maintenance, keeping the charms directory workable
Strategic notes: triage-a-run investigates a single run, with the status semantics themselves in the output reference; compare-runs turns two runs into a delta; suppress-results acts on that interpretation by codifying expected failures in hyrum.toml. Sequence matters — triage first, then compare, then curate.
-->

**[Triage a run](triage-a-run)**
: Investigate a result with `--verbose`, `--log-dir`, and `hyrum show`, and tell a real regression from host noise.

**[Compare two runs](compare-runs)**
: Save a baseline and use `hyrum compare` to see which charms your change broke.

**[Suppress known results](suppress-results)**
: Use `hyrum.toml` to exclude repositories from a run.

**[Reclaim disk space](reclaim-disk-space)**
: Use `hyrum clean` to remove the build artefacts a run leaves behind, keeping the checkouts.
