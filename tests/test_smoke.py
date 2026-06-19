"""Smoke test: package imports and CLI registers."""

from __future__ import annotations

import pytest

import hyrum
from hyrum import _cli


def test_version_string():
    assert isinstance(hyrum.__version__, str)
    assert hyrum.__version__


def test_cli_version_runs(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        _cli.main(['--version'])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert hyrum.__version__ in (captured.out + captured.err)


def test_cli_help_runs(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        _cli.main(['--help'])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert 'check' in out
    assert 'get-charms' in out


def test_cli_check_help_runs(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        _cli.main(['check', '--help'])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert '--charms-dir' in out
    assert 'TARGET' in out
    assert '--runner' in out


def test_cli_requires_subcommand(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        _cli.main([])
    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert 'command is required' in err or 'usage' in err.lower()
