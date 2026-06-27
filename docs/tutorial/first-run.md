---
myst:
  html_meta:
    description: A ten-minute tutorial that walks you through installing hyrum, populating a small charm cache, running a check, and reading the report.
---

# First run: test a charm with hyrum

In this tutorial you will install hyrum, populate a small charms directory, run a check, and read the resulting report. The whole thing takes about ten minutes.

## What you need

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) installed and on your PATH
- `tox` or `make` installed and on your PATH
- `git` installed and on your PATH
- An internet connection (to clone a charm)

## Install hyrum

Install hyrum with [uv](https://docs.astral.sh/uv/):

```text
uv tool install hyrum
```

Verify the install:

```text
hyrum --version
```

## Populate a charms directory

Hyrum runs against a directory of already-cloned repositories. Create the default charms directory and clone one charm by hand to experiment with:

```text
mkdir -p ~/.cache/hyrum/charms
cd ~/.cache/hyrum/charms
git clone https://github.com/canonical/charm-apt-mirror
```

Your charms directory now contains one charm:

```text
~/.cache/hyrum/charms/
└── charm-apt-mirror/
    ├── tox.ini
    ├── ...
```

For a fleet-scale run, use `hyrum get-charms` to clone every entry in the bundled charm list instead. That is covered in [How to run against the charm list](../howto/run-charm-list).

## Run the check

Run the `unit` tox environment across every charm in the charms directory, without swapping any dependencies:

```text
hyrum check unit --no-patch
```

Hyrum discovers the charm, detects its runner (tox, because `tox.ini` is present), runs `tox -e unit`, and prints a summary table when it finishes.

You should see output similar to this:

```text
hyrum: unit
STATUS         COUNT     %
passed             1  100%
failed             0    0%
no_target          0    0%
timeout            0    0%
patcher_error      0    0%
skipped            0    0%
1 of 1 runs passed (100%); 0 skipped or errored.
```

## Try with multiple workers

Clone a second charm and run with two parallel workers:

```text
cd ~/.cache/hyrum/charms
git clone https://github.com/canonical/hardware-observer-operator
cd -
hyrum check unit --no-patch --workers 2
```

With `--workers 2`, hyrum runs both charms concurrently. The summary will now show two results.

## Limit the run to one charm

Use `--repo` to filter by name (a regex matched against the directory name) or `--limit` to stop after a given number:

```text
# Only the charm whose directory name contains "apt":
hyrum check unit --no-patch --repo apt

# Stop after the first charm, whichever it is:
hyrum check unit --no-patch --limit 1
```

## Save per-charm logs

Use `--log-dir` to write each charm's runner output to a file for offline triage:

```text
hyrum check unit --no-patch --log-dir ~/hyrum-logs
```

After the run you will find files like `~/hyrum-logs/charm-apt-mirror.log` containing the metadata, stdout, and stderr for that charm's run.

## Next steps

- [How to run hyrum against the full charm list](../howto/run-charm-list)
- [How to swap ops to a development branch](../howto/swap-ops-branch)
- [How to interpret the results](../howto/interpret-results)
- [CLI reference](../reference/cli)
