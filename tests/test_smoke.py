"""Smoke test: package imports and CLI registers."""

import hyrum
from hyrum import cli


def _invoke(args: list[str], capsys) -> tuple[int, str, str]:
    code = 0
    try:
        cli.main(args)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return code, out, err


def test_version_string():
    assert isinstance(hyrum.__version__, str)
    assert hyrum.__version__


def test_cli_version_runs(capsys):
    code, out, _ = _invoke(['--version'], capsys)
    assert code == 0
    assert hyrum.__version__ in out


def test_cli_help_runs(capsys):
    code, out, _ = _invoke(['--help'], capsys)
    assert code == 0
    assert '--cache-folder' in out
    assert 'TARGET' in out
    assert '--runner' in out


def test_cli_requires_target(capsys):
    code, _, err = _invoke([], capsys)
    assert code != 0
    assert 'TARGET' in err
