"""Runner backends drive a per-charm check (tox / make / future others).

Each runner is a small adapter around a subprocess invocation.  The
:func:`auto` helper picks one per charm based on which configuration
files are present, with an explicit ``--runner`` flag overriding the
choice.
"""

from super_tox.runners.base import Runner, RunResult, RunStatus
from super_tox.runners.detect import RunnerChoice, auto, by_name
from super_tox.runners.make_runner import MakeRunner
from super_tox.runners.tox import ToxRunner

__all__ = [
    "MakeRunner",
    "RunResult",
    "RunStatus",
    "Runner",
    "RunnerChoice",
    "ToxRunner",
    "auto",
    "by_name",
]
