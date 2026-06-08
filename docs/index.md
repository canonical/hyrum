# Hyrum

```{toctree}
:hidden:
:maxdepth: 2

tutorial/index
howto/index
reference/index
explanation/index
```

Hyrum bulk-runs a check (typically lint or unit tests) across many charm repositories, optionally swapping out one of their dependencies first.

The primary use case is pointing every charm's `ops` dependency at a development branch of the [operator](https://github.com/canonical/operator) repository to find out which charms break before shipping the change. Named after [Hyrum's Law](https://www.hyrumslaw.com/): once you have enough users, every observable behaviour of your code is depended on by somebody.

## Install

```text
uv tool install hyrum
```

## Quick start

```text
# Run tox -e unit across every charm in ~/.cache/hyrum/charms,
# with ops swapped to a development branch:
hyrum unit --ops-source-branch fix/my-change --workers 8

# Run without any dependency swap (test charms as they are pinned):
hyrum unit --no-patch
```

## In this documentation

::::{grid} 1 1 2 2

:::{grid-item-card} [Tutorial](tutorial/index)
A hands-on walkthrough: set up a cache folder, run hyrum, and read the report.
:::

:::{grid-item-card} [How-to guides](howto/index)
Task-focused guides: install, filter runs, swap a dependency, and triage results.
:::

:::{grid-item-card} [Reference](reference/index)
CLI options, `hyrum.toml` configuration, and output-status reference.
:::

:::{grid-item-card} [Explanation](explanation/index)
Background on Hyrum's Law, design decisions, and the relationship to charm tooling.
:::

::::

This documentation uses the [Diátaxis](https://diataxis.fr/) documentation structure.

## Project and community

Hyrum is an open source project ([Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0)) maintained by the [Canonical Charm Tech](https://github.com/canonical/charm-tech) team.

- [Report a bug](https://github.com/canonical/hyrum/issues)
- [Contribute](https://github.com/canonical/hyrum/blob/main/CONTRIBUTING.md)
- [Charm Development on Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Discourse forum](https://discourse.charmhub.io/)
- [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)
