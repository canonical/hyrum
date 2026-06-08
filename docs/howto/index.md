# How-to guides

```{toctree}
:hidden:

install
run-single-charm
run-charm-list
swap-ops-branch
interpret-results
suppress-results
```

Procedures for exercising hyrum against a charm cache: installing the tool, scoping a run from a single charm up to a full fleet, swapping `ops` to a development branch, and triaging the results table to decide what action to take.

## Running hyrum
<!--
Themes: installation, charm selection, fleet execution, dependency patching
Justification: shared concern — preparing and launching a run against the charm cache, from one charm to the full fleet with optional ops swap
User journey context: initial setup, run configuration, execution
-->

**[Install hyrum](install)**
: Install hyrum from PyPI using pip or uv.

**[Run against a single charm](run-single-charm)**
: Use `--repo` or `--limit` to target one repository for a quick check.

**[Run against the charm list](run-charm-list)**
: Point hyrum at a large cache folder and run across many charms.

**[Swap ops to a development branch](swap-ops-branch)**
: Use `--ops-source` to test a pre-release `ops` against your charm fleet.

## Reading and curating results
<!--
Themes: outcome statuses, summary table interpretation, exclusion lists, baseline curation
Justification: shared concern — turning a run's output into a decision, including suppressing known offenders so future runs surface only new breakage
User journey context: post-run triage, baseline maintenance
Strategic notes: interpret-results explains status semantics; suppress-results acts on that interpretation by codifying expected failures in hyrum.toml. Sequence matters — interpret first, then curate.
-->

**[Interpret results](interpret-results)**
: Understand each outcome status and decide what action, if any, to take.

**[Suppress known results](suppress-results)**
: Use `hyrum.toml` to exclude repositories from a run.
