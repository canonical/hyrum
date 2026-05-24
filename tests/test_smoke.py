"""Smoke test: package imports and CLI registers."""

from click import testing

import hyrum
from hyrum import cli


def test_version_string():
    assert isinstance(hyrum.__version__, str)
    assert hyrum.__version__


def test_cli_help_runs():
    result = testing.CliRunner().invoke(cli.main, ['--help'])
    assert result.exit_code == 0
    assert '--cache-folder' in result.output
    assert '--target' in result.output
    assert '--runner' in result.output


def test_cli_requires_target():
    result = testing.CliRunner().invoke(cli.main, [])
    assert result.exit_code != 0
    assert '--target' in result.output or 'Missing option' in result.output
