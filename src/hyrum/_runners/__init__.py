"""Runner backends drive a per-charm check (tox / make / future others).

Each runner is a small adapter around a subprocess invocation.  The
:func:`auto` helper picks one per charm based on which configuration
files are present, with an explicit ``--runner`` flag overriding the
choice.
"""

from hyrum._runners.base import Runner, RunResult, RunStatus
from hyrum._runners.detect import RunnerChoice, auto, by_name
from hyrum._runners.make_runner import MakeRunner
from hyrum._runners.tox import ToxRunner

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
