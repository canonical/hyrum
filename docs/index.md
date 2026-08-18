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

```{warning}
Hyrum executes third-party code on your machine. Unit tests — and, in principle, even lint hooks — run with your user's privileges: anything you can do, a test can do. Charm test suites may not mock every side effect, so a test may write or delete files anywhere your user can reach, install packages, modify `crontab`, download arbitrary content, or reach out to the network.

**Always run hyrum in an isolated VM** (for example, [Multipass](https://canonical.com/multipass) or an LXD virtual machine): create a throwaway instance, install hyrum inside it, and dispose of the instance when you are done. Do not run checks on your workstation, laptop, or any host holding data you care about.
```

## Install

```text
uv tool install --prerelease=allow hyrum
```

## Quick start

```text
# Populate ~/.cache/hyrum/charms from a charm-list CSV:
hyrum get-charms

# Run tox -e unit across every charm, with ops swapped to a development branch:
hyrum check unit --patch 'ops @ canonical:fix/my-change' --workers 8

# Run without any dependency swap (test charms as they are pinned):
hyrum check unit --no-patch

# Diff the last two runs to see what the swap changed:
hyrum compare ~/.cache/hyrum/results/unit.auto.prev.json \
              ~/.cache/hyrum/results/unit.auto.json
```

## In this documentation

::::{grid} 1 1 2 2

:::{grid-item-card} [Tutorial](tutorial/index)
A hands-on walkthrough: populate a charms directory, run hyrum, and read the report.
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

Hyrum is an open source project ([Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0)) maintained by the Canonical Charm Tech team.

- [Report a bug](https://github.com/canonical/hyrum/issues)
- [Contribute](https://github.com/canonical/hyrum/blob/main/CONTRIBUTING.md)
- [Charm Development on Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Discourse forum](https://discourse.charmhub.io/)
- [Code of conduct](https://ubuntu.com/community/docs/ethos/code-of-conduct)
