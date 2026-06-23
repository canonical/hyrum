"""Patchers mutate a charm repo to swap out a dependency, then restore it.

The base protocol allows different patching strategies to coexist:

  * ``OpsSourcePatcher`` rewrites pip/Poetry/uv dependency declarations
    so ``ops`` (and its optional ``testing`` / ``tracing`` companions)
    are pulled from a git source instead of PyPI.
  * A future charm-library patcher will overwrite a vendored
    ``lib/charms/<author>/v<n>/<lib>.py`` file with a version from a
    git source — same protocol, different mechanism.

Patchers compose via :class:`PatcherStack`, which applies each in
order and unwinds in reverse on exit.
"""

from hyrum._patchers.base import (
    NullPatcher,
    Patcher,
    PatcherError,
    PatcherStack,
)
from hyrum._patchers.generic import DepSource, GenericDepPatcher
from hyrum._patchers.ops_source import OpsSource, OpsSourcePatcher

__all__ = [
    'DepSource',
    'GenericDepPatcher',
    'NullPatcher',
    'OpsSource',
    'OpsSourcePatcher',
    'Patcher',
    'PatcherError',
    'PatcherStack',
]
