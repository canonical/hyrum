from __future__ import annotations

from hyrum import _summary as summary_mod


def _s(stdout: bytes = b'', stderr: bytes = b'', *, status: str = 'failed', rc: int | None = 1):
    return summary_mod.from_run_output(stdout, stderr, status=status, returncode=rc)


def test_passed_status_returns_empty():
    assert _s(status='passed', rc=0) == ''


def test_timeout_status_returns_timed_out():
    assert _s(status='timeout', rc=None) == 'timed out'


def test_no_target_status_returns_label():
    assert _s(status='no_target', rc=None) == 'target not present'


def test_pytest_single_failure_counts_plus_exception():
    # One failure: full exception message is informative, keep it.
    stdout = (
        b'tests/unit/test_foo.py F\n'
        b'E   ValueError: bad thing happened\n'
        b'=========== 1 failed, 102 passed in 4.21s ============\n'
    )
    out = _s(stdout=stdout)
    assert '1 failed' in out
    assert '102 passed' in out
    assert 'ValueError: bad thing happened' in out


def test_pytest_multi_failure_counts_collapse_to_class():
    # Multiple failures: collapse to ClassName xN since one message cannot
    # represent all of them.
    stdout = (
        b'tests/unit/test_foo.py F\n'
        b'E   ValueError: bad thing happened\n'
        b'=========== 3 failed, 102 passed in 4.21s ============\n'
    )
    out = _s(stdout=stdout)
    assert '3 failed' in out
    assert 'ValueError x3' in out


def test_pytest_summary_with_errors():
    stdout = b'======= 2 errors in 0.30s =======\n'
    out = _s(stdout=stdout)
    assert '2 errors' in out


def test_bare_module_not_found():
    stderr = b"ModuleNotFoundError: No module named 'ops'\n"
    out = _s(stderr=stderr)
    assert "ModuleNotFoundError: No module named 'ops'" in out


def test_psycopg2_build_failure():
    stderr = b'some noise\npg_config executable not found\nmore noise\n'
    out = _s(stderr=stderr)
    assert 'psycopg2' in out


def test_python_h_build_failure():
    stderr = b'fatal error: Python.h: No such file or directory\n'
    out = _s(stderr=stderr)
    assert 'Python.h' in out


def test_uv_resolver_failure():
    stderr = b'  x No solution found when resolving dependencies for `ops[testing]`\n'
    out = _s(stderr=stderr)
    assert 'uv resolve' in out


def test_collection_error_path_included():
    stdout = b"ERROR collecting tests/unit/test_tls_manager.py\nKeyError: 'log_on_error'\n"
    out = _s(stdout=stdout)
    assert 'collection error' in out
    assert 'test_tls_manager.py' in out
    assert 'KeyError' in out


def test_falls_back_to_exit_code():
    out = _s(stdout=b'just some noise\n', stderr=b'more noise\n', rc=42)
    assert out == 'exit 42'


def test_summary_truncates_long_messages():
    stderr = b'ValueError: ' + (b'x' * 500) + b'\n'
    out = _s(stderr=stderr)
    assert len(out) <= 160


def test_ansi_colour_codes_do_not_block_match():
    bars = b'=' * 30
    stdout = (
        b'\x1b[1m' + bars + b' test session starts ' + bars + b'\x1b[0m\n'
        b"\x1b[1m\x1b[31mE   ModuleNotFoundError: No module named 'ops'\x1b[0m\x1b[0m\n"
        b'\x1b[31m' + bars + b' \x1b[31m\x1b[1m1 error\x1b[0m\x1b[31m '
        b'in 0.44s\x1b[0m\x1b[31m ' + bars + b'\x1b[0m\n'
    )
    out = _s(stdout=stdout)
    assert '1 error' in out
    assert 'ModuleNotFoundError' in out


def test_pytest_no_tests_ran():
    stdout = b'============================ no tests ran in 0.01s =============================\n'
    out = _s(stdout=stdout, rc=5)
    assert out == 'pytest: no tests ran'


def test_pytest_missing_path_usage_error():
    stderr = b'ERROR: file or directory not found: /home/x/.cache/hyrum/charms/o/c/tests/unit\n'
    out = _s(stderr=stderr, rc=4)
    assert 'path not found' in out
    assert 'tests/unit' in out


def test_dotted_module_exception_matches():
    stderr = b'    unittest.mock.InvalidSpecError: Cannot spec a Mock object.\n'
    out = _s(stderr=stderr)
    assert 'InvalidSpecError' in out
    assert 'Cannot spec a Mock' in out


def test_failed_line_tally_single_class():
    exc = b'scenario.errors.InconsistentScenarioError'
    stdout = (
        b'== 13 failed, 40 passed in 4.5s ==\n'
        b'FAILED tests/test_charm.py::test_a - ' + exc + b': ...\n'
        b'FAILED tests/test_charm.py::test_b - ' + exc + b': ...\n'
        b'FAILED tests/test_charm.py::test_c - ' + exc + b': ...\n'
    )
    out = _s(stdout=stdout)
    assert '13 failed' in out
    assert 'InconsistentScenarioError' in out
    assert 'x3' in out


def test_failed_line_tally_with_other():
    stdout = (
        b'== 5 failed, 1 passed in 0.5s ==\n'
        b'FAILED tests/test_a.py::test_x - InvalidSpecError: ...\n'
        b'FAILED tests/test_a.py::test_y - InvalidSpecError: ...\n'
        b'FAILED tests/test_a.py::test_z - InvalidSpecError: ...\n'
        b'FAILED tests/test_b.py::test_p - ValueError: ...\n'
        b'FAILED tests/test_b.py::test_q - KeyError: ...\n'
    )
    out = _s(stdout=stdout)
    assert 'InvalidSpecError x3' in out
    assert '+2 other' in out


def test_multi_failure_collapses_first_exception_to_class():
    # FAILED lines lack the ``- ExceptionClass`` tail (some verbosity modes),
    # so the tally returns None and we fall through to first-exception. With
    # 13 failures, the long single-message form misrepresents the run; we want
    # ``ClassName x13`` instead.
    stdout = (
        b'== 13 failed, 40 passed in 4.5s ==\n'
        b'FAILED tests/test_charm.py::test_a\n'
        b'FAILED tests/test_charm.py::test_b\n'
    )
    stderr = (
        b'    scenario.errors.InconsistentScenarioError: Inconsistent scenario. '
        b'The following errors were found: container ...\n'
    )
    out = _s(stdout=stdout, stderr=stderr)
    assert '13 failed' in out
    assert 'InconsistentScenarioError x13' in out
    assert 'Inconsistent scenario.' not in out


def test_single_failure_keeps_message():
    stdout = b'== 1 failed, 3 passed in 1s ==\nFAILED tests/test_x.py::test_x\n'
    stderr = b'    ConnectionError: kaput\n'
    out = _s(stdout=stdout, stderr=stderr)
    assert 'ConnectionError: kaput' in out


def test_failed_line_without_exception_falls_back():
    stdout = (
        b'== 2 failed, 5 passed in 0.5s ==\n'
        b'FAILED tests/test_a.py::test_x\n'
        b'FAILED tests/test_a.py::test_y\n'
    )
    # No exception class on the FAILED lines → tally is None; counts-only summary.
    out = _s(stdout=stdout)
    assert out == '2 failed, 5 passed'


def test_post_test_failure_with_allowlist_externals():
    stdout = (
        b'======================= 53 passed, 77 warnings in 9.75s ========================\n'
        b'unit: commands[1]> coverage report\n'
        b'unit: failed with coverage is not allowed, use allowlist_externals to allow it\n'
    )
    out = _s(stdout=stdout, rc=1)
    assert 'tests passed' in out
    assert '53 passed' in out
    assert 'allowlist_externals' in out
    assert 'coverage' in out


def test_post_test_failure_pytest_exit_3():
    stdout = b'======================== 35 passed, 4 warnings in 2.30s ========================\n'
    out = _s(stdout=stdout, rc=3)
    assert 'tests passed' in out
    assert '35 passed' in out
    assert 'pytest exit 3' in out


def test_post_test_failure_unknown_with_exit_code():
    stdout = b'==== 81 passed in 1.0s ====\n'
    out = _s(stdout=stdout, rc=7)
    assert 'tests passed' in out
    assert '81 passed' in out
    assert 'exit 7' in out


def test_toml_duplicate_key_called_out():
    stderr = (
        b'warning: Failed to parse `pyproject.toml` during settings discovery:\n'
        b'  TOML parse error at line 98, column 1\n'
        b'  98 | ops = { git = "...", branch = "main" }\n'
        b'duplicate key\n'
    )
    out = _s(stderr=stderr)
    assert 'duplicate key' in out
    assert 'patcher artefact' in out


def test_poetry_lock_stale_called_out():
    stderr = (
        b'\n'
        b'pyproject.toml changed significantly since poetry.lock was last generated. '
        b'Run `poetry lock` to fix the lock file.\n'
    )
    out = _s(stderr=stderr)
    assert 'lock file out of date' in out


def test_uv_lockfile_out_of_date():
    stderr = b'The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.\n'
    out = _s(stderr=stderr)
    assert 'lockfile out of date' in out


def test_uv_url_dep_must_be_direct():
    stderr = (
        b'  Failed to resolve dependencies for `ops` (v3.7.1)\n'
        b'  Package `ops-scenario` was included as a URL dependency.\n'
        b'  URL dependencies must be expressed as direct requirements\n'
    )
    out = _s(stderr=stderr)
    assert 'URL dep' in out


def test_last_pytest_summary_wins():
    # tox can print several test envs; we should use the LAST summary line.
    stdout = (
        b'=========== 1 failed, 5 passed in 0.5s ============\n'
        b'=========== 6 failed, 102 passed in 4.21s ============\n'
    )
    out = _s(stdout=stdout)
    assert '6 failed' in out
    assert '102 passed' in out
