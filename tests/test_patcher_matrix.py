"""The permutations the patchers and the runner auto-detection have to handle.

Coverage of these two areas grew a test at a time, alongside the fixes, which
left it shaped by the bugs that happened to be found rather than by what the
code claims to support. Both defects the last full-collection run turned up
(pyproject-flavour misdetection, and a lockfile left behind after a failed
``uv lock``) were here, and both got past the tests that existed.

So this module enumerates the permutations rather than sampling them:

* **Where a dependency can be declared** - Poetry's ``dependencies``,
  ``dev-dependencies`` and ``group.<name>.dependencies``; PEP 621
  ``[project] dependencies`` and ``optional-dependencies``; PEP 735
  ``[dependency-groups]``. Every one of them, for both the "is it there"
  question and the "what extras does it carry" question, plus the
  canonicalisation rule that makes ``Foo_Bar`` and ``foo-bar`` the same name.
* **The shapes that are not valid** - each of those sites holding something
  other than the table or array it is supposed to, which must skip the charm
  as malformed rather than raise something the pool reports as a crash.
* **Which flavour a pyproject is** - the uv / poetry / pep621 / unknown
  decision, over the combinations of signals that decide it.
* **Which runner a layout gets** - tox.ini, Makefile, either capitalisation,
  both, neither, and the preference order between them.

Cases already covered elsewhere are not repeated here: the rewrite bodies
themselves live in ``test_patchers.py``, the vendored-lib patcher in
``test_vendored_lib_patcher.py``, and the runner invocation mechanics in
``test_runners.py``.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess  # ruff: ignore[suspicious-subprocess-import] — TimeoutExpired is what run_lock catches
from typing import Any

import pytest

from hyrum._patchers import _common as common
from hyrum._patchers import base
from hyrum._runners import detect, make_runner, tox

# Every place a charm can declare a dependency, with `ops` declared carrying
# the `testing` extra where the site can express one.
DECLARATION_SITES: dict[str, dict[str, Any]] = {
    'poetry-dependencies': {
        'tool': {'poetry': {'dependencies': {'ops': {'version': '^2', 'extras': ['testing']}}}}
    },
    'poetry-dev-dependencies': {
        'tool': {'poetry': {'dev-dependencies': {'ops': {'version': '^2', 'extras': ['testing']}}}}
    },
    'poetry-group': {
        'tool': {
            'poetry': {
                'group': {
                    'unit': {'dependencies': {'ops': {'version': '^2', 'extras': ['testing']}}}
                }
            }
        }
    },
    'pep621-dependencies': {'project': {'dependencies': ['ops[testing]>=2']}},
    'pep621-optional-dependencies': {
        'project': {'optional-dependencies': {'dev': ['ops[testing]>=2']}}
    },
    'pep735-dependency-groups': {'dependency-groups': {'unit': ['ops[testing]>=2']}},
}

# The same sites holding the wrong kind of value.
MALFORMED_SITES: dict[str, dict[str, Any]] = {
    'poetry-dependencies': {'tool': {'poetry': {'dependencies': ['ops']}}},
    'poetry-dev-dependencies': {'tool': {'poetry': {'dev-dependencies': ['ops']}}},
    'poetry-group': {'tool': {'poetry': {'group': {'unit': {'dependencies': ['ops']}}}}},
    'dependency-groups-not-a-table': {'dependency-groups': ['ops']},
    'dependency-group-not-an-array': {'dependency-groups': {'unit': {'ops': '*'}}},
}


@pytest.mark.parametrize('site', sorted(DECLARATION_SITES))
def test_a_dependency_is_found_wherever_it_is_declared(site: str):
    assert common.pkg_is_declared(DECLARATION_SITES[site], 'ops')


@pytest.mark.parametrize('site', sorted(DECLARATION_SITES))
def test_extras_are_collected_wherever_they_are_declared(site: str):
    assert common.collect_pyproject_pkg_extras(DECLARATION_SITES[site], 'ops') == {'testing'}


@pytest.mark.parametrize('site', sorted(DECLARATION_SITES))
def test_another_package_is_not_found_at_any_site(site: str):
    assert not common.pkg_is_declared(DECLARATION_SITES[site], 'requests')
    assert common.collect_pyproject_pkg_extras(DECLARATION_SITES[site], 'requests') == set()


@pytest.mark.parametrize(
    ('declared', 'looked_for'),
    [
        ('charmlibs_pathops', 'charmlibs-pathops'),
        ('charmlibs-pathops', 'charmlibs_pathops'),
        ('Charmlibs.PathOps', 'charmlibs-pathops'),
    ],
)
def test_names_match_after_canonicalisation(declared: str, looked_for: str):
    # PEP 503 says these are one package, and charms spell it both ways.
    poetry = {'tool': {'poetry': {'dependencies': {declared: '^1'}}}}
    pep621 = {'project': {'dependencies': [f'{declared}>=1']}}
    assert common.pkg_is_declared(poetry, looked_for)
    assert common.pkg_is_declared(pep621, looked_for)


@pytest.mark.parametrize('site', sorted(MALFORMED_SITES))
def test_a_malformed_site_skips_the_charm(site: str):
    data = MALFORMED_SITES[site]
    with pytest.raises(base.PatcherSkip) as declared:
        common.pkg_is_declared(data, 'ops')
    assert declared.value.reason is base.PatcherSkipReason.MALFORMED_PYPROJECT
    with pytest.raises(base.PatcherSkip) as extras:
        common.collect_pyproject_pkg_extras(data, 'ops')
    assert extras.value.reason is base.PatcherSkipReason.MALFORMED_PYPROJECT


def test_an_unparseable_requirement_is_not_a_match():
    # A charm is free to put something in that is not PEP 508 at all; it just
    # is not the package we are looking for.
    data = {'project': {'dependencies': ['this is not a requirement']}}
    assert not common.pkg_is_declared(data, 'ops')
    assert common.collect_pyproject_pkg_extras(data, 'ops') == set()


@pytest.mark.parametrize(
    ('name', 'parsed', 'uv_lock', 'expected'),
    [
        (
            'uv table and pep621 deps',
            {'project': {'dependencies': []}, 'tool': {'uv': {}}},
            False,
            'uv',
        ),
        ('uv lock and pep621 deps', {'project': {'dependencies': []}}, True, 'uv'),
        (
            'uv table and dependency groups',
            {'dependency-groups': {}, 'tool': {'uv': {}}},
            False,
            'uv',
        ),
        (
            'uv table and optional deps only',
            {'project': {'optional-dependencies': {}}, 'tool': {'uv': {}}},
            False,
            'uv',
        ),
        # The signal on its own is not enough: uv with no PEP 621 or PEP 735
        # deps to rewrite is a pep621 charm as far as patching goes.
        ('uv table but no deps', {'project': {'name': 'x'}, 'tool': {'uv': {}}}, False, 'pep621'),
        ('poetry', {'tool': {'poetry': {'dependencies': {}}}}, False, 'poetry'),
        # Poetry plus a uv.lock is the one real ambiguity, and uv wins only
        # when the deps are declared where uv would read them.
        (
            'poetry with a uv lock',
            {'tool': {'poetry': {'dependencies': {}}}},
            True,
            'poetry',
        ),
        ('pep621 deps alone', {'project': {'dependencies': []}}, False, 'pep621'),
        ('dependency groups alone', {'dependency-groups': {}}, False, 'pep621'),
        ('a project table with no deps', {'project': {'name': 'x'}}, False, 'pep621'),
        ('nothing recognisable', {'build-system': {}}, False, 'unknown'),
        ('empty', {}, False, 'unknown'),
    ],
)
def test_pyproject_flavour_detection(
    name: str, parsed: dict[str, Any], uv_lock: bool, expected: str
):
    assert common.detect_pyproject_flavour(parsed, uv_lock) == expected, name


ORIGINALS: dict[str, str] = {
    'pep621': '[project]\nname = "demo"\ndependencies = ["ops>=2"]\n',
    'uv': '[project]\nname = "demo"\ndependencies = ["ops>=2"]\n\n[tool.uv]\n',
    'poetry': '[tool.poetry]\nname = "demo"\n\n[tool.poetry.dependencies]\nops = "^2"\n',
}


@pytest.mark.parametrize('flavour', sorted(ORIGINALS))
def test_every_flavour_can_be_patched(flavour: str):
    original = ORIGINALS[flavour]
    git = common.patch_git_dep(
        original, 'ops', 'https://example.com/operator', 'main', None, set(), flavour
    )
    version = common.patch_version_dep(original, 'ops', '==2.17.0', set(), flavour)
    assert 'https://example.com/operator' in git
    assert '2.17.0' in version


def test_the_poetry_rewrite_needs_a_poetry_table():
    # Worth pinning because it is silent: the poetry injection is a string
    # replace on the section header, so a file without one comes back
    # unchanged rather than raising. Detection is what keeps the flavour and
    # the file in step, and this is what the code does if they ever aren't.
    original = ORIGINALS['pep621']
    assert (
        common.patch_git_dep(
            original, 'ops', 'https://example.com/operator', 'main', None, set(), 'poetry'
        )
        == original
    )


@pytest.mark.parametrize('patch', [common.patch_git_dep, common.patch_version_dep])
def test_an_unknown_flavour_is_a_programming_error(patch: Any):
    # 'unknown' comes back from detection for a pyproject with nothing to
    # rewrite, and a caller that passes it on has skipped the check.
    with pytest.raises(ValueError, match='unknown flavour'):
        if patch is common.patch_git_dep:
            patch('', 'ops', 'https://example.com/operator', None, None, set(), 'unknown')
        else:
            patch('', 'ops', '==1.0', set(), 'unknown')


LAYOUTS: dict[str, tuple[str, ...]] = {
    'tox only': ('tox.ini',),
    'Makefile only': ('Makefile',),
    'lowercase makefile only': ('makefile',),
    'both': ('tox.ini', 'Makefile'),
    'neither': (),
}


@pytest.mark.parametrize(
    ('layout', 'tox_detects', 'make_detects'),
    [
        ('tox only', True, False),
        ('Makefile only', False, True),
        ('lowercase makefile only', False, True),
        ('both', True, True),
        ('neither', False, False),
    ],
)
def test_runner_detection_by_layout(
    tmp_path: pathlib.Path, layout: str, tox_detects: bool, make_detects: bool
):
    for name in LAYOUTS[layout]:
        (tmp_path / name).write_text('')
    assert tox.ToxRunner.detect(tmp_path) is tox_detects
    assert make_runner.MakeRunner.detect(tmp_path) is make_detects
    # auto is exactly "one of the others could run here".
    assert detect.AutoRunner.detect(tmp_path) is (tox_detects or make_detects)


@pytest.mark.parametrize('flavour', sorted(ORIGINALS))
def test_every_flavour_can_take_a_local_path(flavour: str):
    patched = common.patch_path_dep(
        ORIGINALS[flavour], 'ops', pathlib.Path('/src/operator'), set(), flavour
    )
    assert '/src/operator' in patched


def test_a_local_path_also_rejects_an_unknown_flavour():
    with pytest.raises(ValueError, match='unknown flavour'):
        common.patch_path_dep('', 'ops', pathlib.Path('/src/operator'), set(), 'unknown')


class _Recorder:
    """Stands in for subprocess.run, recording the call and replaying a result."""

    def __init__(self, result: Any):
        self.result = result
        self.env: dict[str, str] = {}
        self.calls = 0

    def __call__(self, cmd: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.env = kwargs.get('env') or {}
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclasses.dataclass(frozen=True)
class _Completed:
    returncode: int
    stderr: bytes = b''


@pytest.mark.parametrize(
    ('result', 'lock_survives'),
    [
        (_Completed(0), True),
        # A lock that cannot be regenerated under the patched source must not
        # be left behind: the run would then install the charm's original
        # pins and report on the wrong dependency. This is one of the two
        # defects the last full-collection run turned up.
        (_Completed(1, b'no solution found'), False),
        (subprocess.TimeoutExpired(cmd='uv', timeout=1), False),
        # A missing tool is a host problem rather than a charm one, so the
        # charm's own lockfile is left as it was.
        (FileNotFoundError(2, 'No such file or directory', 'uv'), True),
    ],
)
def test_a_failed_lock_does_not_leave_a_stale_lockfile(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, result: Any, lock_survives: bool
):
    lockfile = tmp_path / 'uv.lock'
    lockfile.write_text('version = 1\n')
    recorder = _Recorder(result)
    monkeypatch.setattr(common.subprocess, 'run', recorder)
    common.run_lock(tmp_path, ['uv', 'lock'], 60, on_failure_remove=lockfile)
    assert lockfile.exists() is lock_survives


def test_lock_runs_without_hyrums_own_virtualenv(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # Poetry reads VIRTUAL_ENV to decide the project's current Python and
    # refuses the lock when it disagrees with requires-python.
    monkeypatch.setenv('VIRTUAL_ENV', '/somewhere/hyrum/.venv')
    recorder = _Recorder(_Completed(0))
    monkeypatch.setattr(common.subprocess, 'run', recorder)
    common.run_lock(tmp_path, ['poetry', 'lock'], 60)
    assert 'VIRTUAL_ENV' not in recorder.env
