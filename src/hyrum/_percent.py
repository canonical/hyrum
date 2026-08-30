"""Percentage formatting shared by the run report and the run-to-run diff.

A single helper so both keep the same floor and ceiling: a non-zero count
never renders as ``0%``, and a count short of the total never renders as
``100%``, because a table cell that contradicts the count beside it looks
like a bug in the tally rather than a rounding artefact.
"""

from __future__ import annotations


def format_pct(fraction: float, *, decimals: int = 0) -> str:
    """Format *fraction* (0.0-1.0) as a percentage with *decimals* decimal places.

    A non-zero fraction that would round down to zero renders as the smallest
    representable value prefixed with ``<`` — ``<1%`` at whole-number
    precision, ``<0.1%`` at one decimal place. A fraction below one that would
    round up to a hundred renders as the largest representable value prefixed
    with ``>`` — ``>99%``, or ``>99.9%`` at one decimal place.
    """
    pct = fraction * 100
    rendered = f'{pct:.{decimals}f}'
    # Compare the rendered text rather than the value: what matters is whether
    # the string the user sees is a zero, not how close the float is to one.
    if pct > 0 and rendered == f'{0:.{decimals}f}':
        return f'<{10**-decimals:.{decimals}f}%'
    if pct < 100 and rendered == f'{100:.{decimals}f}':
        return f'>{100 - 10**-decimals:.{decimals}f}%'
    return f'{rendered}%'
