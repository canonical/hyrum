---
myst:
  html_meta:
    description: Use --patch to swap a non-ops dependency across the charm fleet, from a PyPI pin, a git source, or a local checkout.
---

# How to swap a non-ops dependency

`--patch` is not limited to `ops`. Any package the charm declares can be swapped, using the same PEP 508 grammar. Use this to:

- Pin a transitive dependency to a candidate release.
- Point a library at a fork or a development branch.
- Test the fleet against a local checkout of a library you maintain.

## Pin to a PyPI version

```text
hyrum check unit --patch 'requests==2.31.0'
```

Specifiers other than `==` are accepted too:

```text
hyrum check unit --patch 'requests>=1.2,<2'
```

If no patch is given hyrum defaults to swapping `ops` to `canonical:main`. As soon as one `--patch` is given, the default goes away — only the packages you list are patched. To run with both `ops` and another dependency patched, pass `--patch` for each:

```text
hyrum check unit \
    --patch 'ops @ canonical:main' \
    --patch 'requests==2.31.0'
```

`--patch` and `--no-patch` are mutually exclusive. Pass `--patch` once per package; specifying it twice for the same package is an error.

## Swap from a git source

```text
hyrum check unit --patch 'requests @ git+https://github.com/psf/requests@main'
```

A bare `https://…` URL is accepted too:

```text
hyrum check unit --patch 'requests @ https://github.com/psf/requests@main'
```

`#subdirectory=<path>` is honoured for git sources where the package lives in a monorepo subdirectory:

```text
hyrum check unit --patch 'mylib @ git+https://github.com/me/monorepo@main#subdirectory=packages/mylib'
```

The `owner:branch` shorthand (`canonical:fix/X`) is **ops-only**. For any other package, pass an explicit `git+<url>` or bare `https://…` URL.

## Swap from a local checkout

```text
hyrum check unit --patch 'mylib @ ~/code/mylib'
hyrum check unit --patch 'mylib @ /abs/path/mylib'
hyrum check unit --patch 'mylib @ file:///abs/path/mylib'
```

## Combine with an ops swap

`--patch` may be repeated, with one occurrence per package:

```text
hyrum check unit \
    --patch 'ops @ canonical:fix/my-change' \
    --patch 'requests==2.31.0' \
    --patch 'mylib @ ~/code/mylib'
```

Hyrum applies each patcher in turn; lockfiles are regenerated once after all rewrites complete.

## What gets rewritten

The generic dependency patcher behaves like the ops-source patcher except that the `ops[testing]` / `ops[tracing]` companion handling is specific to `ops`. For any other package, hyrum rewrites declarations in:

- `requirements.txt` (pip)
- `pyproject.toml` under `[project.dependencies]`, `[project.optional-dependencies]`, `[dependency-groups]` (PEP 735), `[tool.poetry.dependencies]`, and `[tool.uv.sources]`
- The corresponding lockfile (`poetry.lock` or `uv.lock`) is regenerated when present

Charms whose declarations cannot be parsed are reported as `patcher_error` rather than `failed`, so an infrastructure problem is not mis-attributed to a charm regression. See [How to interpret results](interpret-results).
