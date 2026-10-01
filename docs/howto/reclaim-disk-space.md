---
myst:
  html_meta:
    description: Use hyrum clean to remove the .tox, .venv, and cache directories a fleet run leaves behind, without re-cloning the charms.
---

# How to reclaim disk space

A fleet run leaves build artefacts in every charm it touches: `.tox`, `.venv`, tool caches, `__pycache__`. Across several hundred charms these reach tens of gigabytes, on top of the checkouts themselves. `hyrum clean` removes the artefacts and leaves the git checkouts alone, so the next run does not have to clone everything again.

## See what would go

`--dry-run` reports each artefact and what it holds, without removing anything:

```text
hyrum clean --dry-run
```

```text
2026-07-28T08:47:35Z INFO Would remove canonical/charm-apt-mirror/.tox (412.8 MiB)
2026-07-28T08:47:35Z INFO Would remove canonical/charm-apt-mirror/__pycache__ (1.2 MiB)
Would reclaim 11.3 GiB from 1274 artefacts.
```

## Clean the charms directory

```text
hyrum clean
```

```text
Reclaimed 11.3 GiB from 1274 artefacts.
```

The checkouts stay, so a later `hyrum get-charms` pulls rather than clones, and a later `hyrum check` starts from a clean environment in each charm.

## Clean a different directory

`hyrum clean` reads the same charms directory as the rest of hyrum, so `--charms-dir` and `HYRUM_CHARMS` both apply:

```text
hyrum clean --charms-dir /srv/hyrum-charms
```

Hyrum refuses to clean a directory whose contents are not git checkouts:

```text
hyrum: error: --charms-dir: /srv/scratch does not look like a charms directory
(its contents are not git checkouts). Pass --force to clean it anyway.
```

That guard is there so a mistyped path cannot recursively delete something else. Pass `--force` only once you have checked the path is the one you meant, ideally by running `--dry-run` against it first.

## Suppress the output

`--quiet` silences everything but errors, for a scheduled job:

```text
hyrum clean --quiet
```
