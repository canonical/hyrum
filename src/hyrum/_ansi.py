"""Shared ANSI SGR palette and colour-enable detection.

Colour is emitted only when the target stream is a tty and the
``NO_COLOR`` environment variable is unset.
"""

from __future__ import annotations

import os
from typing import TextIO

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
MAGENTA = '\033[35m'
BRIGHT_RED = '\033[91m'


def use_colour(stream: TextIO) -> bool:
    """Return ``True`` if ANSI colour should be emitted to *stream*."""
    if os.environ.get('NO_COLOR'):
        return False
    return hasattr(stream, 'isatty') and stream.isatty()
