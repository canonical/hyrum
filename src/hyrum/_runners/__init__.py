"""Runner backends drive a per-charm check (tox / make / future others).

Each runner is a small adapter around a subprocess invocation.  The
:func:`auto` helper picks one per charm based on which configuration
files are present, with an explicit ``--runner`` flag overriding the
choice.
"""

from hyrum.runners.base import Runner, RunResult, RunStatus
from hyrum.runners.detect import RunnerChoice, auto, by_name
from hyrum.runners.make_runner import MakeRunner
from hyrum.runners.tox import ToxRunner

__all__ = [
    'MakeRunner',
    'RunResult',
    'RunStatus',
    'Runner',
    'RunnerChoice',
    'ToxRunner',
    'auto',
    'by_name',
]
