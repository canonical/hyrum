"""Smoke test: the package imports and the CLI stub runs."""

from click.testing import CliRunner

from super_tox import __version__
from super_tox.cli import main


def test_version_string():
    assert isinstance(__version__, str)
    assert __version__


def test_cli_runs():
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "super-tox" in result.output
