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
        (575 / 576, '>99%'),
        (0.999, '>99%'),
        (0.994, '99%'),
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
        (575 / 576, '99.8%'),
        (0.9999, '>99.9%'),
    ],
)
def test_format_pct_one_decimal(fraction: float, expected: str):
    assert _percent.format_pct(fraction, decimals=1) == expected


@pytest.mark.parametrize(
    ('fraction', 'expected'),
    [
        (0.0, '0.00%'),
        (0.001, '0.10%'),
        (0.0000001, '<0.01%'),
        (0.9999999, '>99.99%'),
        (1.0, '100.00%'),
    ],
)
def test_format_pct_two_decimals(fraction: float, expected: str):
    assert _percent.format_pct(fraction, decimals=2) == expected


@pytest.mark.parametrize('fraction', [-0.0001, -1.0, 1.5])
def test_format_pct_rejects_out_of_range(fraction: float):
    with pytest.raises(ValueError):
        _percent.format_pct(fraction)
