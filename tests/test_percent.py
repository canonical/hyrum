from __future__ import annotations

import pytest

from hyrum import _percent


@pytest.mark.parametrize(
    ('fraction', 'expected'),
    [
        (0.0, '0%'),
        (1.0, '100%'),
        (0.5, '50%'),
        (0.004, '<1%'),
        (1 / 576, '<1%'),
        (0.006, '1%'),
    ],
)
def test_format_pct_whole_numbers(fraction: float, expected: str):
    assert _percent.format_pct(fraction) == expected


@pytest.mark.parametrize(
    ('fraction', 'expected'),
    [
        (0.0, '0.0%'),
        (1 / 576, '0.2%'),
        (0.0001, '<0.1%'),
    ],
)
def test_format_pct_one_decimal(fraction: float, expected: str):
    assert _percent.format_pct(fraction, decimals=1) == expected
