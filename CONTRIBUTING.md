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

# Develop in a workshop

[Workshop](https://ubuntu.com/workshop) definitions live in `.workshop/`. The `dev` workshop is a container with `uv`, `make`, `tox`, `poetry`, and the C build dependencies that the curated charm list needs, so none of that has to be installed on the host:

```bash
sudo snap install workshop --classic  # If you don't have it already.
workshop launch dev
workshop run dev all
```

The actions mirror the `make` targets: `all`, `format`, `lint`, and `unit`. `unit` passes any extra arguments through to `pytest`, so `workshop run dev unit -k test_pool` does what `make unit ARGS='-k test_pool'` does; `lint` forwards them to `pyright` alone, with `ruff` and `codespell` running over everything first either way. An argument containing whitespace won't survive: the `make` recipes expand `$(ARGS)` unquoted, so `-k 'test_pool and not slow'` reaches `pytest` as four arguments whether you go through the workshop or run `make` yourself.

The `hyrum` action runs the CLI itself. This is the safer way to run `hyrum check`, because the check executes each charm's test suite - arbitrary third-party code - and the workshop runs it in the container, as a separate `hyrum-check` user. Workshop mounts the project directory into the container read-write, so code running as the `workshop` user could write to your hyrum checkout on the host; `hyrum-check` can read the checkout but not modify it, and has no access to the host at all beyond that:

```bash
workshop run dev hyrum get-charms
workshop run dev hyrum check unit --patch 'ops @ canonical:some-branch'
```

Inside the workshop, hyrum's cache is at the usual `~/.cache/hyrum` - but that's the home directory of the container's `hyrum-check` user (`/home/hyrum-check/.cache/hyrum`), not your host's, so the charm checkouts and saved results are separate from anything a host install of hyrum has cached. It's also a mount rather than a plain directory, because `workshop refresh` resets the container's home directories and re-cloning the curated charm list is expensive. By default the mount is storage that workshop manages, and it goes away with `workshop remove dev`. To back it with a directory on the host instead - to share the checkouts with the host or with other workshops, and to keep them when the workshop is removed - run `workshop remount dev/hyrum:cache ~/.cache/hyrum`. A host directory you remount is writable by the checks, so point it somewhere you'd be content for third-party test code to write. Clear the cache from inside the workshop (`workshop exec --uid 0 dev -- rm -rf /home/hyrum-check/.cache/hyrum/charms`) rather than from the host: the checks write as the container's `hyrum-check` user, and a charm's test run can leave directories the host user can't remove.

`hyrum check` sets `PYO3_USE_ABI3_FORWARD_COMPATIBILITY` and the matching `TOX_OVERRIDE` entry itself, so the workshop doesn't need to. See [Host prerequisites for fleet runs](docs/howto/install.md#host-prerequisites-for-fleet-runs) for why they're needed, and `--no-host-env-defaults` to turn them off.

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

# Releases

Two workflows make a release, and you decide twice: once when you review the version-bump PR, and once when you publish the draft release. Nothing reaches PyPI until you publish the draft, so an abandoned attempt costs at most a branch and a draft to delete. Releases only come from `main`.

## 1. Propose the release

Run the ["Propose a release"](https://github.com/canonical/hyrum/actions/workflows/propose-release.yaml) workflow from `main`. A run from any other branch stops with an error. It takes two inputs:

- `version`: leave this empty for an ordinary release. The workflow counts from the last `v*` tag and reads the conventional commits since then: a `feat` or a breaking change makes it a minor release, and anything else makes it a patch release. Fill this in for a major release, which is never inferred, or for a pre-release such as `1.1.0b1`. After a pre-release, you always need to fill it in, since only you know whether the next one is another pre-release or the final release. What you type is used as it stands.
- `dry_run`: do everything except push the branch and open the PR. The proposed version, the changelog entry and the drafted notes go in the run summary.

The workflow writes the [CHANGES.md](CHANGES.md) entry, updates the version in `pyproject.toml`, `src/hyrum/_version.py` and `uv.lock`, drafts the release title and notes, and opens a draft PR from a `release-prep-X.Y.Z` branch. The PR's description lists the next steps, with the PR's number ready for the next workflow.

The PR is a draft so that you can tidy it up before asking anyone else to look: resolve the **Unsure:** notes the model left, cut anything a reader doesn't need, and fix the changelog entry if it needs it. Then mark it ready for review and ask for one.

Review both halves of it:

- The diff: the version and the changelog entry. If a commit message needs adjusting in the changelog, edit `CHANGES.md` in this PR: the draft release copies this version's section from there.
- The release title and notes, which are in the PR description under the "Release title" and "Release notes" headings. Edit them there, and keep the hidden `<!-- release-title:start -->`/`<!-- release-notes:start -->` markers (and their `end` partners): that's where the next workflow reads them from. Write only the summary for the title, since the version is added for you. Everything outside the markers is for reviewers and goes no further.

The PR is opened with the workflow's own token, so GitHub won't start the usual checks on it. Close and reopen the PR to get them to run, then merge it once they pass.

## 2. Create the draft release

Once the PR is merged, run the ["Create the draft release"](https://github.com/canonical/hyrum/actions/workflows/create-draft-release.yaml) workflow with the PR's number. It checks that the PR was merged into `main` and changed the version in `pyproject.toml`, then creates a **draft** release on the merge commit, titled with the version and your summary. The body is the notes from the PR description, then this version's section of `CHANGES.md`, an "All commits" link, and a line thanking any contributors from outside the team. A version with an `a`, `b` or `rc` in it is marked as a pre-release.

Nothing is published and the tag doesn't exist yet. Edit the draft if you need to.

## 3. Publish the draft

Publishing the draft creates the `vX.Y.Z` tag, which starts the `publish` workflow. That publishes to [PyPI](https://pypi.org/p/hyrum) with Trusted Publishing, and attests the build and its SBOM. It stops before building if the tag doesn't match the version in `pyproject.toml`. If that happens, don't move the tag (the tag ruleset won't let you anyway). Delete the release, and release the next patch version instead.

To rehearse a release, run the `publish-test-pypi` workflow manually from the Actions tab: it builds from the current `main` and publishes to [Test PyPI](https://test.pypi.org/p/hyrum). Note that a version can only be uploaded once, so bump the version before re-running it.

## Settings a repository admin has to change

An environment called `release-notes`, holding an `OPENROUTER_API_KEY` secret and an `OPENROUTER_MODEL` variable. Without them, "Propose a release" puts a placeholder where the notes would go and carries on, and you write the notes yourself in the PR description.
