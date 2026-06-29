"""Patchers mutate a charm repo to swap out a dependency, then restore it.

The base protocol allows different patching strategies to coexist:

  * ``OpsSourcePatcher`` rewrites pip/Poetry/uv dependency declarations
    so ``ops`` (and its optional ``testing`` / ``tracing`` companions)
    are pulled from a git source instead of PyPI.
  * ``GenericDepPatcher`` does the same for an arbitrary single
    dependency, picking one of three source kinds (PyPI version, git
    URL, local path).
  * ``CharmlibPatcher`` repoints a ``charmlibs-*`` dependency at a
    branch of the ``canonical/charmlibs`` monorepo instead of PyPI.
  * ``VendoredLibPatcher`` deletes a vendored ``lib/charms/<author>/v<n>/<lib>.py``
    file, adds the equivalent PyPI distribution as a dependency, and
    rewrites the charm's imports to the new dotted path.

Patchers compose via :class:`PatcherStack`, which applies each in
order and unwinds in reverse on exit.
"""

from hyrum._patchers.base import (
    NullPatcher,
    Patcher,
    PatcherError,
    PatcherSkip,
    PatcherStack,
)
from hyrum._patchers.charmlib_source import CharmlibPatcher, CharmlibSource
from hyrum._patchers.generic import DepSource, GenericDepPatcher
from hyrum._patchers.ops_source import OpsSource, OpsSourcePatcher
from hyrum._patchers.vendored_lib import VendoredLibPatcher, VendoredLibSwap

__all__ = [
    'CharmlibPatcher',
    'CharmlibSource',
    'DepSource',
    'GenericDepPatcher',
    'NullPatcher',
    'OpsSource',
    'OpsSourcePatcher',
    'Patcher',
    'PatcherError',
    'PatcherSkip',
    'PatcherStack',
    'VendoredLibPatcher',
    'VendoredLibSwap',
]
