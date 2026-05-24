"""Smoke test: package imports and CLI registers."""

from click.testing import CliRunner

from super_tox import __version__
from super_tox.cli import main


def test_version_string():
    assert isinstance(__version__, str)
    assert __version__


def test_cli_help_runs():
    result = CliRunner().invoke(main, ['--help'])
    assert result.exit_code == 0
    assert '--cache-folder' in result.output
    assert '--target' in result.output
    assert '--runner' in result.output


def test_cli_requires_target():
    result = CliRunner().invoke(main, [])
    assert result.exit_code != 0
    assert '--target' in result.output or 'Missing option' in result.output
