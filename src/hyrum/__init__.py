"""hyrum: bulk-run checks across many charm repositories.

Named for Hyrum's law: the tool exists to find out which consumers were
relying on observable behaviour of a dependency before you change it.

``hyrum`` is a CLI tool. The only supported public Python surface is
:data:`__version__` and :func:`main`. Anything under ``hyrum._*`` is an
implementation detail and may change without notice.
"""

from hyrum._cli import main
from hyrum._version import __version__

__all__ = ['__version__', 'main']
