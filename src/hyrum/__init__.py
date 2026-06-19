"""hyrum: bulk-run checks across many charm repositories.

Named for Hyrum's law: the tool exists to find out which consumers were
relying on observable behaviour of a dependency before you change it.

The package's public Python surface is re-exported here. Anything not
re-exported below — including every ``hyrum._*`` submodule — is an
implementation detail and may change without notice.
"""

from hyrum._cli import main
from hyrum._config import Config
from hyrum._config import load as load_config
from hyrum._enumerate import iter_charm_repos
from hyrum._filters import (
    Filter,
    SkipReason,
    has_python,
    has_runnable_target,
    ignore_filter,
    not_legacy,
    regex_filter,
)
from hyrum._frameworks import supported_frameworks, uses_framework
from hyrum._patchers import (
    NullPatcher,
    OpsSource,
    OpsSourcePatcher,
    Patcher,
    PatcherError,
    PatcherStack,
)
from hyrum._pool import (
    OUTCOME_STATUSES,
    Outcome,
    add_skipped,
    run_one,
    run_pool,
)
from hyrum._pool import passed as all_passed
from hyrum._report import render as render_report
from hyrum._runners import (
    MakeRunner,
    Runner,
    RunnerChoice,
    RunResult,
    RunStatus,
    ToxRunner,
)
from hyrum._runners import auto as auto_runner
from hyrum._runners import by_name as runner_by_name
from hyrum._version import __version__

__all__ = [
    'OUTCOME_STATUSES',
    'Config',
    'Filter',
    'MakeRunner',
    'NullPatcher',
    'OpsSource',
    'OpsSourcePatcher',
    'Outcome',
    'Patcher',
    'PatcherError',
    'PatcherStack',
    'RunResult',
    'RunStatus',
    'Runner',
    'RunnerChoice',
    'SkipReason',
    'ToxRunner',
    '__version__',
    'add_skipped',
    'all_passed',
    'auto_runner',
    'has_python',
    'has_runnable_target',
    'ignore_filter',
    'iter_charm_repos',
    'load_config',
    'main',
    'not_legacy',
    'regex_filter',
    'render_report',
    'run_one',
    'run_pool',
    'runner_by_name',
    'supported_frameworks',
    'uses_framework',
]
