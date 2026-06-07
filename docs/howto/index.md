# How-to guides

```{toctree}
:maxdepth: 1

install
run-single-charm
run-charm-list
swap-ops-branch
interpret-results
suppress-results
```

Task-focused guides for common hyrum workflows.

**[Install hyrum](install)**
: Install hyrum from PyPI using pip or uv.

**[Run against a single charm](run-single-charm)**
: Use `--repo` or `--limit` to target one repository for a quick check.

**[Run against the charm list](run-charm-list)**
: Point hyrum at a large cache folder and run across many charms.

**[Swap ops to a development branch](swap-ops-branch)**
: Use `--ops-source-branch` to test a pre-release `ops` against your charm fleet.

**[Interpret results](interpret-results)**
: Understand each outcome status and decide what action, if any, to take.

**[Suppress known results](suppress-results)**
: Use `hyrum.toml` to exclude repositories from a run.
