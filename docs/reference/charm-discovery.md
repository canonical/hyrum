---
myst:
  html_meta:
    description: The repository layouts hyrum recognises and the order in which its skip filters are applied.
---

# Charm discovery and filtering

Charm discovery handles three layouts:

- **Flat**: one charm per top-level directory (has `charmcraft.yaml` or `metadata.yaml`).
- **Bundle**: a `bundle.yaml` directory; charms are in `charms/` subdirectories.
- **Monorepo**: a directory containing charm subdirectories, heuristically detected.

Filters are applied as a chain. Each filter either returns `None` (passes) or a skip reason string. The chain short-circuits on the first reason:

1. `not_legacy`: skip reactive/hooks-based charms (`hooks/`, or `src/reactive/` with `src/layer.yaml`).
2. `has_python`: skip charms with no Python source.
3. `regex_filter`: skip charms not matching `--repo`.
4. `ignore_filter`: skip charms listed in `hyrum.toml [ignore]`.
5. `has_runnable_target`: skip charms with neither `tox.ini` nor `Makefile`.
6. Framework filter (if `--framework` is set).
