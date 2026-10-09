"""Work out which version to release, and write its changelog entry.

Called by the propose-release workflow, from a checkout of `main`. Everything
it needs comes from the environment the workflow sets:

    VERSION_INPUT  An explicit version, or empty to infer one from the commits.
    DRY_RUN        'true' when nothing is going to be pushed.
    CHANGELOG      The uvx `--from` spec for the team's changelog tool.

It writes the changelog entry for the commits since the last tag to
`$RUNNER_TEMP/changes-entry.md`, for the later steps, and sets `previous` (the
last tag, with its `v`) and `version` (without one) as step outputs.
Every refusal is a workflow error annotation and a non-zero exit.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] — runs git, gh and uvx
import sys
import typing


def run(*args: str, stdin: str | None = None) -> str:
    """Run a command and return its stdout, leaving stderr to reach the log."""
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        args, input=stdin, stdout=subprocess.PIPE, text=True, check=True
    ).stdout


def succeeds(*args: str) -> bool:
    """Run a command quietly and say whether it exited zero."""
    return subprocess.run(args, capture_output=True).returncode == 0  # ruff: ignore[subprocess-without-shell-equals-true]


def fail(message: str) -> typing.NoReturn:
    """Report an error annotation on the workflow run, and stop."""
    print(f'::error::{message}')
    sys.exit(1)


def main() -> None:
    """Pick the version, check it can be released, and write its entry."""
    version_input = os.environ['VERSION_INPUT'].removeprefix('v')
    dry_run = os.environ['DRY_RUN'] == 'true'
    changelog = os.environ['CHANGELOG']
    repository = os.environ['GITHUB_REPOSITORY']
    runner_temp = pathlib.Path(os.environ['RUNNER_TEMP'])
    tool = ('uvx', '--from', changelog, 'changelog')

    # The last tag, rather than the version in pyproject.toml, so that the
    # changelog range and the version it is counted from cannot drift apart.
    # Tags have a `v` in front; the changelog tool wants bare versions.
    try:
        previous = run(
            'git', 'describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*.[0-9]*.[0-9]*', 'HEAD'
        ).strip()
    except subprocess.CalledProcessError:
        fail('No release tag in the history of main to count from.')
    print(f'Last tag on main: {previous}')

    log_format = run(*tool, 'git-log-format').strip()
    log = run(
        'git', 'log', '--reverse', '--no-merges', f'--format={log_format}', f'{previous}..HEAD'
    )

    if version_input:
        # An explicit version is used as it stands, with no inference.
        version = version_input
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?', version):
            fail(f"'{version}' is not X.Y.Z or X.Y.Z{{a,b,rc}}N.")
    else:
        # `next-version` refuses to count from a pre-release such as 1.1.0b1,
        # since only a person knows whether the next one is b2 or final.
        try:
            output = run(
                *tool, 'next-version', '--previous', previous.removeprefix('v'), stdin=log
            )
        except subprocess.CalledProcessError:
            fail(
                f'Could not work out the version after {previous}.'
                ' Run this again with an explicit version.'
            )
        fields = dict(line.split('=', 1) for line in output.splitlines())
        version = fields['version']
        print(f'The commits since {previous} are a {fields["size"]} release.')

    if succeeds('git', 'rev-parse', '-q', '--verify', f'refs/tags/v{version}'):
        fail(f'v{version} is already tagged.')

    # Checked here rather than at the push, so that a leftover branch costs
    # nothing: everything after this check writes files and spends a model
    # call. A dry run never pushes, so a leftover branch doesn't block one.
    if not dry_run and succeeds(
        'gh', 'api', f'repos/{repository}/git/ref/heads/release-prep-{version}'
    ):
        fail(
            f'A release-prep-{version} branch already exists. Delete it, or finish the'
            f' pull request that goes with it, before proposing {version} again.'
        )

    entry = run(*tool, 'changes-entry', '--repo', repository, '--tag', version, stdin=log)
    (runner_temp / 'changes-entry.md').write_text(entry)
    print(entry, end='')

    count = run('git', 'rev-list', '--count', f'{previous}..HEAD').strip()
    print(f'Releasing {version}, from the {count} commits since {previous}.')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'previous={previous}\nversion={version}\n')


if __name__ == '__main__':
    main()
