"""Single source of truth for ``hyrum.__version__``.

Kept in its own module so :mod:`hyrum._cli` can read it without importing
the rest of ``hyrum``'s public surface.
"""

__version__ = '1.0.0a1'
