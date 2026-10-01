---
myst:
  html_meta:
    description: How Hyrum's Law applies to the ops library and why hyrum exists to surface charms that depend on observable behaviour before it changes.
---

# Hyrum's Law and this tool

## Hyrum's Law

[Hyrum's Law](https://www.hyrumslaw.com/), stated by Hyrum Wright, reads:

> With a sufficient number of users of an API, it does not matter what you promise in the contract: all observable behaviours of your system will be depended on by somebody.

Once a library has enough consumers, *any* observable behaviour will be relied on by some consumer, including behaviours the library author thought of as implementation details, bugs, or accidents of timing. When the library changes that behaviour, some consumer breaks, even if the change was well within the documented contract.

## Why this matters for ops

The `ops` library (from `canonical/operator`) is the foundation for all Juju charms written in Python. It has a large and diverse set of consumers, each with its own test suite. When the ops team changes a behaviour (a method signature, an exception type, a hook-dispatch order, an internal class that leaked into the public namespace), they cannot reliably predict which charms will break by reading the source code alone. Consumer code evolves independently and may depend on behaviour that was never part of the public API.

Charm libraries make the same problem worse. Traditionally a charm library is *vendored*: charmcraft fetches a single-file copy into `lib/charms/<author>/v<n>/<lib>.py`, so every consumer holds its own copy, at whatever version it last fetched, which is precisely the situation in which a behaviour change is hard to assess.

## What hyrum does

Hyrum automates the process of finding breakages before shipping a change. Given:

1. A directory of pre-cloned charm repositories (populate it manually or with `hyrum get-charms`).
2. A proposed change to `ops` (expressed as a git branch, tag, commit, PyPI version, or local checkout).

It rewrites each charm's dependency declarations to point `ops` at the proposed branch, regenerates lockfiles, runs a check (typically `tox -e unit`) across every charm concurrently, and reports which charms passed and which failed.

The result is a compatibility matrix: *this proposed change breaks N charms, here is the list*. The ops maintainers can then decide whether to revise the change, reach out to charm authors, or accept the breakage as unavoidable.

## What hyrum does not do

- It does not decide what to *do* about failures. That is a human judgment call.
- It does not curate the charm collection. `hyrum get-charms` will populate the charms directory from a CSV, but deciding *which* charms appear in that CSV is a separate concern.
- It does not run integration tests, only lint and unit tests, which run without a live Juju model.
- It does not guarantee that passing tests mean the charm works correctly under the new `ops`. Tests only cover what they cover.

## Why a single run is not enough

Some charms have pre-existing test failures that have nothing to do with the change under test, so a bare "N charms failed" number is often misleading. The useful signal is the *delta* between a baseline run and a patched one — see [How to compare two runs](../howto/compare-runs).
