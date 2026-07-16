We welcome contributions to hyrum!

Before working on changes, please consider [opening an issue](https://github.com/canonical/hyrum/issues) explaining your use case. If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

# Pull requests

Changes are proposed as [pull requests on GitHub](https://github.com/canonical/hyrum/pulls).

Pull requests should have a short title that follows the [conventional commit style](https://www.conventionalcommits.org/en/) using one of these types:

- chore
- ci
- docs
- feat
- fix
- perf
- refactor
- revert
- test

Some examples:

- feat: add a `make` runner alongside the existing `tox` one
- fix: restore poetry.lock when patching is aborted by Ctrl-C
- docs: clarify how `--patch` interacts with charm extras

We consider this project too small to use scopes, so we don't use them.

Note that the commit messages to the PR's branch do not need to follow the conventional commit format, as these will be squashed into a single commit to `main` using the PR title as the commit message.

To help us review your changes, please rebase your pull request onto the `main` branch before you request a review. If you need to bring in the latest changes from `main` after the review has started, please use a merge commit.

# Install from source

Clone the repository and sync the development dependency groups:

```bash
git clone https://github.com/canonical/hyrum
cd hyrum
uv sync --all-groups
```

`uv sync` creates a virtual environment in `.venv/` and installs `ruff`, `pyright`, `pytest`, and the other tooling used by `make all`. Run the CLI with `uv run hyrum …`, or activate the environment first with `. .venv/bin/activate`.

# Tests

Changes should include tests. Run them locally with:

```bash
make all
```

`lint` covers `ruff check`, `ruff format --check`, `codespell`, and `pyright` in strict mode; `unit` runs `pytest` with coverage. `make all` also runs `format` first. See `make help` for the full target list.

# Coding style

We follow the Charm Tech team style guides:

- [Documentation and docstring style](https://github.com/canonical/charm-tech/blob/main/STYLE.md)
- [Python style](https://github.com/canonical/charm-tech/blob/main/python/STYLE.md)

Most of this is enforced by CI checks.
