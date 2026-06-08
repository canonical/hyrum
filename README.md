# hyrum

> Named after [Hyrum's Law](https://www.hyrumslaw.com/): once you have enough users, every observable behaviour of your code is depended on by somebody. This tool exists to find out who that "somebody" is — by running a proposed dependency change against a fleet of consumer repositories before you ship it.

Bulk-run a check (typically lint or unit tests) across many charm repositories, optionally swapping out one of their dependencies first.

## Install

```text
uv tool install hyrum
```

## Quick start

```text
# Run tox -e unit with ops swapped to a development branch:
hyrum unit --ops-source canonical:fix/my-change --workers 8

# Run without any dependency swap:
hyrum unit --no-patch
```

## Documentation

Full documentation — including a tutorial, how-to guides, CLI reference, and background explanation — is in the [`docs/`](docs/) directory.
