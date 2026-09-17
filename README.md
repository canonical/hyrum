# hyrum

> Named after [Hyrum's Law](https://www.hyrumslaw.com/): once you have enough users, every observable behaviour of your code is depended on by somebody. This tool exists to find out who that "somebody" is — by running a proposed dependency change against a fleet of consumer repositories before you ship it.

Bulk-run a check (typically lint or unit tests) across many charm repositories, optionally swapping out one of their dependencies first.

> [!WARNING]
> Hyrum executes third-party code on your machine. Unit tests — and, in principle, even lint hooks — run with your user's privileges: anything you can do, a test can do. Charm test suites may not mock every side effect, so a test may write or delete files anywhere your user can reach, install packages, modify `crontab`, download arbitrary content, or reach out to the network.
>
> **Always run hyrum in an isolated VM** (for example, [Multipass](https://canonical.com/multipass) or an LXD virtual machine): create a throwaway instance, install hyrum inside it, and dispose of the instance when you are done. Do not run checks on your workstation, laptop, or any host holding data you care about.

## Install

```text
uv tool install --prerelease=allow hyrum
```

## Quick start

```text
# Run tox -e unit with ops swapped to a development branch:
hyrum check unit --patch 'ops @ canonical:fix/my-change' --workers 8

# Run without any dependency swap:
hyrum check unit --no-patch
```

## Documentation

Full documentation — including a tutorial, how-to guides, CLI reference, and background explanation — is in the [`docs/`](docs/) directory.
