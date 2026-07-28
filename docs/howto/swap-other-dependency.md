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

The `owner:branch` shorthand (`canonical:fix/X`) is accepted only for `ops` and for `charmlibs-*` packages. For any other package, pass an explicit `git+<url>` or bare `https://…` URL.

## Swap from a local checkout

```text
hyrum check unit --patch 'mylib @ ~/code/mylib'
hyrum check unit --patch 'mylib @ /abs/path/mylib'
hyrum check unit --patch 'mylib @ file:///abs/path/mylib'
```

## Swap a charm library from canonical/charmlibs

Packages named `charmlibs-*` get their own shorthand, pointing the dependency at a branch of the [charmlibs](https://github.com/canonical/charmlibs) monorepo:

```text
hyrum check unit --patch 'charmlibs-nginx_k8s @ canonical:main'
```

The subdirectory inside the monorepo is taken from the package name verbatim, so type the separators the way the directory exists on disk. Interface libraries live under `interfaces/`, and the shorthand follows:

```text
# nginx_k8s/ in the monorepo:
hyrum check unit --patch 'charmlibs-nginx_k8s @ canonical:main'

# interfaces/k8s-service/ in the monorepo:
hyrum check unit --patch 'charmlibs-interfaces-k8s-service @ canonical:main'
```

The name used to match the charm's own dependency declaration is canonicalised separately, so the match works whichever separators you type.

A charmlib must be patched from a git source. A version pin (`charmlibs-apt==1.0.0`) or a local path is rejected; use the generic form above if you need those.

Most charms do not depend on any given charm library. Those charms are reported as `skipped` with the reason `dep_not_declared`, not as failures.

## Replace a vendored charm library

Charms have historically vendored charm libraries as `lib/charms/<author>/v<n>/<lib>.py`, imported as `charms.<author>.v<n>.<lib>`. To find out whether a charm still works when that vendored copy is replaced by the equivalent package, use the `->` form:

```text
hyrum check unit --patch 'charms.operator_libs_linux.v0.apt -> charmlibs-apt==1.0.0'
```

The left side is the dotted import path of the vendored file. The right side is the replacement package, in any of the forms above — including a git source from the charmlibs monorepo:

```text
hyrum check unit \
    --patch 'charms.operator_libs_linux.v0.apt -> charmlibs-apt @ git+https://github.com/canonical/charmlibs@main#subdirectory=apt'
```

For each charm, hyrum:

1. Deletes the vendored `lib/charms/<author>/v<n>/<lib>.py` file.
2. Adds the replacement package to the charm's dependency declarations.
3. Rewrites imports of the old dotted module to the new one (`charmlibs.<lib>`) across `src/` and `tests/`.
4. Removes the matching `charm-libs` entry from `charmcraft.yaml`, so charmcraft does not re-fetch the library.
5. Restores every touched file, including the deleted one, when the run finishes.

Charms that do not vendor that library are reported as `skipped` with the reason `vendored_lib_absent`.

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

Charms whose declarations cannot be parsed are reported as `patcher_error` rather than `failed`, so an infrastructure problem is not mis-attributed to a charm regression. Charms that do not declare the package at all are reported as `skipped`, since there was nothing to swap. See [How to interpret results](interpret-results).
