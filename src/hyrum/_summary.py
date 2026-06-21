"""Heuristic one-line failure summaries extracted from runner output.

The goal is a short, human-readable string per non-passing outcome so the
markdown comparison table is readable without round-tripping to the log files.
Patterns are tuned for the common failure shapes we see across the charm
fleet — pytest result lines, common Python exception classes, missing build
tooling, package-resolver errors — and fall back to a generic ``exit N`` blurb
when nothing recognisable is found.
"""

from __future__ import annotations

import re

# Strip ANSI CSI sequences. pytest, tox and uv emit colourised output by default;
# without this every summary/exception regex misses on terminal-colour logs.
_ANSI_RE = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')


def _strip_ansi(buf: bytes) -> bytes:
    return _ANSI_RE.sub(b'', buf)


# Pytest's final summary line, e.g. "=== 6 failed, 102 passed in 4.21s ==="
# or "=== 12 errors in 0.30s ===" for collection-time failures. The trailer
# tolerates extras like "516 warnings" before the duration, plus the
# parenthesised "(0:03:00)" wall-clock pytest appends on longer runs.
_PYTEST_SUMMARY_RE = re.compile(
    rb'=+\s*(?:(\d+)\s+failed)?[,\s]*(?:(\d+)\s+passed)?[,\s]*(?:(\d+)\s+errors?)?'
    rb'[^\n=]*in\s+[\d.]+\s*s[^\n=]*=+',
)

# Pytest's "no tests collected" / "no tests ran" line.
_NO_TESTS_RE = re.compile(rb'=+\s*no tests ran\s+in\s+[\d.]+\s*s\s*=+', re.I)

# Exception class name shape: optional dotted module prefix
# (``unittest.mock.``, ``scenario.errors.``…), optional CamelCase head, and a
# ``Error`` / ``Exception`` / ``Warning`` suffix. Used in three regexes below.
_EXC_NAME = rb'(?:\w+\.)*(?:[A-Z]\w*?)?(?:Error|Exception|Warning)'

# Lines pytest prints for raised exceptions, e.g. "E   ValueError: bad thing".
_PYTEST_E_LINE_RE = re.compile(rb'^E\s+(' + _EXC_NAME + rb'):\s*(.*)$', re.M)

# A bare exception line outside pytest, e.g. "ModuleNotFoundError: No module named 'ops'".
# Leading whitespace is allowed: pip / setuptools indents tracebacks several spaces.
_BARE_EXC_RE = re.compile(rb'^\s*(' + _EXC_NAME + rb'):\s*(.+)$', re.M)

# pytest's "short test summary info" line, e.g.
# ``FAILED tests/foo.py::test_x - scenario.errors.InconsistentScenarioError: ...``.
# These give us the failing exception class *per test*, which lets the summary
# tally classes ("InconsistentScenarioError x13") rather than report a single
# first-match exception.
_PYTEST_FAILED_LINE_RE = re.compile(rb'^FAILED\s+\S+(?:\s+-\s+(' + _EXC_NAME + rb'))?', re.M)

# Poetry's two-line error format: "  TypeError" on one line, blank, then the message.
_POETRY_ERROR_RE = re.compile(
    rb'^\s+([A-Z][\w.]*(?:Error|Exception))\s*\n\s*\n\s+(\S[^\n]*)',
    re.M,
)

# uv / pip's "no such file or directory: <coverage>" — coverage missing from .tox.
_MISSING_COVERAGE_RE = re.compile(rb"can't open file '\S+coverage':")

# tox refuses to run an external command that isn't in ``allowlist_externals``.
# Emitted as ``<env>: failed with <cmd> is not allowed, use allowlist_externals to allow it``.
_TOX_ALLOWLIST_RE = re.compile(
    rb'failed with (\S+) is not allowed, use allowlist_externals to allow it',
)

# pytest collection-error block intro.
_COLLECTION_ERROR_RE = re.compile(rb'ERROR collecting (\S+)')

# Common host-build pitfalls. Order matters — the first hit wins.
_BUILD_PATTERNS: tuple[tuple[bytes, str], ...] = (
    (b'pg_config executable not found', 'psycopg2 build: pg_config not found'),
    (b'fatal error: Python.h', 'C extension build: Python.h not found'),
    (b'mysql_config: not found', 'mysqlclient build: mysql_config not found'),
    (b'mariadb_config: not found', 'mysqlclient build: mariadb_config not found'),
)

_RESOLVER_PATTERNS: tuple[tuple[re.Pattern[bytes], str], ...] = (
    (
        re.compile(rb'The lockfile at `?uv\.lock`? needs to be updated'),
        'uv: lockfile out of date (--locked refused)',
    ),
    (
        re.compile(rb'No solution found when resolving[^\n]*'),
        'uv resolve: no solution',
    ),
    (
        re.compile(rb'URL dependencies must be expressed as direct requirements'),
        'uv resolve: URL dep must be a direct requirement',
    ),
    (
        re.compile(rb'Failed to resolve dependencies for `([^`]+)`'),
        'uv resolve: failed to resolve dependencies',
    ),
    (
        re.compile(rb'Because [^\n]*depends on[^\n]*'),
        'uv resolve: dependency conflict',
    ),
    (
        re.compile(rb'SolverProblemError[^\n]*'),
        'poetry resolve: solver error',
    ),
    (
        re.compile(rb'PackageNotFoundError[^\n]*'),
        'poetry resolve: package not found',
    ),
)

# pytest's "ERROR: file or directory not found" usage error.
_PYTEST_MISSING_PATH_RE = re.compile(
    rb'ERROR:\s+file or directory not found:\s+(\S+)',
)

# pyproject.toml parse errors. The first form is uv's TOML parser, the second
# is tomllib via tox. Both show up when the OpsSource patcher leaves a stray
# duplicate ``ops = …`` line behind — frequent enough to dedicate a pattern to.
_TOML_DUPLICATE_KEY_RE = re.compile(
    rb'(?:duplicate key|Cannot overwrite a value)',
)

# Stale poetry.lock detected by poetry install.
_POETRY_LOCK_STALE_RE = re.compile(
    rb'pyproject\.toml changed significantly since poetry\.lock',
)

_MAX_LEN = 160


def _truncate(s: str) -> str:
    s = s.strip().replace('\n', ' ').replace('\r', ' ')
    if len(s) > _MAX_LEN:
        return s[: _MAX_LEN - 1] + '…'
    return s


def _pytest_failed_count(stdout: bytes) -> int:
    """Number of failed tests in the last pytest summary line (0 if none)."""
    last: re.Match[bytes] | None = None
    for m in _PYTEST_SUMMARY_RE.finditer(stdout):
        last = m
    if last is None:
        return 0
    failed, _, _ = last.groups()
    return int(failed) if failed else 0


def _pytest_counts(stdout: bytes) -> tuple[str, bool] | None:
    """Return (summary, all_passed) if pytest printed a summary line.

    ``all_passed`` is true when the summary line carries a ``passed`` count
    and no ``failed`` / ``error`` count — i.e. pytest itself succeeded and
    any subsequent failure came from a post-test step (coverage, lint,
    pytest-cov teardown, …).
    """
    last: re.Match[bytes] | None = None
    for m in _PYTEST_SUMMARY_RE.finditer(stdout):
        last = m
    if last is None:
        return None
    failed, passed, errors = last.groups()
    parts: list[str] = []
    if failed:
        parts.append(f'{int(failed)} failed')
    if errors:
        parts.append(f'{int(errors)} error{"s" if int(errors) != 1 else ""}')
    if passed:
        parts.append(f'{int(passed)} passed')
    if not parts:
        return None
    return ', '.join(parts), bool(passed) and not failed and not errors


def _shortname(qualname: str) -> str:
    """``unittest.mock.InvalidSpecError`` -> ``InvalidSpecError``."""
    return qualname.rsplit('.', 1)[-1]


def _failed_test_tally(buf: bytes) -> str | None:
    """Tally exception classes across pytest's ``FAILED test - <exc>`` lines.

    Returns the dominant class with its count (and a count of other classes
    when failures span more than one), e.g. ``InconsistentScenarioError x13``
    or ``InvalidSpecError x3 (+2 other)``. Returns ``None`` if no FAILED
    lines were emitted, or none carried an exception class.
    """
    classes: list[str] = []
    for m in _PYTEST_FAILED_LINE_RE.finditer(buf):
        qual = m.group(1)
        if qual:
            classes.append(_shortname(qual.decode('ascii', 'replace')))
    if not classes:
        return None
    by_class: dict[str, int] = {}
    for c in classes:
        by_class[c] = by_class.get(c, 0) + 1
    ordered = sorted(by_class.items(), key=lambda kv: (-kv[1], kv[0]))
    top_class, top_count = ordered[0]
    if len(ordered) == 1:
        return f'{top_class} x{top_count}'
    other_count = sum(c for _, c in ordered[1:])
    return f'{top_class} x{top_count} (+{other_count} other)'


def _first_exception(buf: bytes) -> str | None:
    """Pick the first interesting exception line from pytest 'E   ...' or bare tracebacks."""
    m = _PYTEST_E_LINE_RE.search(buf)
    if m:
        cls = m.group(1).decode('ascii', 'replace')
        msg = m.group(2).decode('utf-8', 'replace').strip()
        return f'{cls}: {msg}' if msg else cls
    m = _BARE_EXC_RE.search(buf)
    if m:
        cls = m.group(1).decode('ascii', 'replace')
        msg = m.group(2).decode('utf-8', 'replace').strip()
        return f'{cls}: {msg}' if msg else cls
    m = _POETRY_ERROR_RE.search(buf)
    if m:
        cls = m.group(1).decode('ascii', 'replace')
        msg = m.group(2).decode('utf-8', 'replace').strip()
        return f'{cls}: {msg}' if msg else cls
    return None


def _resolver_or_build(buf: bytes) -> str | None:
    for needle, label in _BUILD_PATTERNS:
        if needle in buf:
            return label
    for pat, label in _RESOLVER_PATTERNS:
        if pat.search(buf):
            return label
    return None


def from_run_output(
    stdout: bytes,
    stderr: bytes,
    *,
    status: str,
    returncode: int | None,
) -> str:
    """Return a one-line summary for a finished runner invocation."""
    if status == 'passed':
        return ''
    if status == 'timeout':
        return 'timed out'
    if status == 'no_target':
        return 'target not present'

    stdout = _strip_ansi(stdout)
    stderr = _strip_ansi(stderr)
    combined = stdout + b'\n' + stderr

    counts_result = _pytest_counts(stdout)
    counts = counts_result[0] if counts_result else None
    tests_all_passed = counts_result[1] if counts_result else False
    exc = _first_exception(combined)

    # Tests passed cleanly but the run still failed: the failure is in a
    # post-pytest step (tox's next command, a coverage check, pytest-cov
    # teardown, …). Lead with "tests passed" so the row reads correctly,
    # then attach whatever post-step signal we recognise.
    if tests_all_passed and counts:
        allow = _TOX_ALLOWLIST_RE.search(combined)
        if allow:
            cmd = allow.group(1).decode('utf-8', 'replace')
            return _truncate(f'tests passed ({counts}); tox: {cmd!s} not in allowlist_externals')
        if returncode == 3:
            return _truncate(f'tests passed ({counts}); pytest exit 3 (internal error)')
        return _truncate(f'tests passed ({counts}); post-test step failed (exit {returncode})')

    # For runs with multiple test failures, prefer a tally of the FAILED-line
    # exception classes over a single first-match exception — it's far more
    # informative when failures cluster around one or two root causes.
    tally = _failed_test_tally(combined)
    if counts and tally:
        return _truncate(f'{counts}; {tally}')
    if counts and exc:
        # With multiple failures, the first exception's full message can't
        # represent all of them — collapse to ``ClassName xN`` if we know the
        # count, otherwise just the short class name.
        if _pytest_failed_count(stdout) > 1:
            short = _shortname(exc.split(':', 1)[0])
            return _truncate(f'{counts}; {short} x{_pytest_failed_count(stdout)}')
        return _truncate(f'{counts}; {exc}')
    if counts:
        return _truncate(counts)

    collection = _COLLECTION_ERROR_RE.search(combined)
    if collection and exc:
        path = collection.group(1).decode('utf-8', 'replace')
        return _truncate(f'collection error in {path}: {exc}')

    if _NO_TESTS_RE.search(combined):
        return 'pytest: no tests ran'

    if _MISSING_COVERAGE_RE.search(combined):
        return 'tox: coverage missing from venv'

    if _TOML_DUPLICATE_KEY_RE.search(combined):
        return 'pyproject.toml: duplicate key (likely patcher artefact)'

    if _POETRY_LOCK_STALE_RE.search(combined):
        return 'poetry: lock file out of date'

    missing = _PYTEST_MISSING_PATH_RE.search(combined)
    if missing:
        path = missing.group(1).decode('utf-8', 'replace')
        # Trim the leading cache prefix so the result reads as a test path.
        short = re.sub(r'^.*?/(tests?/[^/]+(?:/[^/]+)*)$', r'\1', path) or path
        return _truncate(f'pytest: path not found: {short}')

    build = _resolver_or_build(combined)
    if build:
        return _truncate(build)

    if exc:
        return _truncate(exc)

    if returncode is not None:
        return f'exit {returncode}'
    return 'failed'
