"""Smoke test: package imports and CLI registers."""

from click import testing

import hyrum


def test_version_string():
    assert isinstance(hyrum.__version__, str)
    assert hyrum.__version__


def test_cli_version_runs():
    result = testing.CliRunner().invoke(hyrum.main, ['--version'])
    assert result.exit_code == 0
    assert hyrum.__version__ in result.output


def test_cli_help_runs():
    result = testing.CliRunner().invoke(hyrum.main, ['--help'])
    assert result.exit_code == 0
    assert 'check' in result.output
    assert 'get-charms' in result.output


def test_cli_check_help_runs():
    result = testing.CliRunner().invoke(hyrum.main, ['check', '--help'])
    assert result.exit_code == 0
    assert '--charms-dir' in result.output
    assert 'TARGET' in result.output
    assert '--runner' in result.output


def test_cli_requires_subcommand():
    result = testing.CliRunner().invoke(hyrum.main, [])
    assert result.exit_code != 0
    assert 'Missing command' in result.output or 'Usage' in result.output
