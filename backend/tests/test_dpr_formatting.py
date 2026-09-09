from fractions import Fraction

import pytest

from app.dpr.formatting import (
    bps_percent,
    fraction_ratio,
    indian_currency,
)


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0"),
        (1, "₹0.01"),
        (100, "₹1"),
        (12_345_600, "₹1,23,456"),
        (12_345_678, "₹1,23,456.78"),
        (1_234_567_890, "₹1,23,45,678.90"),
        (-12_345_678, "-₹1,23,456.78"),
        (None, "Not established"),
    ],
)
def test_indian_currency(paise, expected):
    assert indian_currency(paise) == expected


@pytest.mark.parametrize("value", [True, False, 100.0, "100", Fraction(100)])
def test_currency_rejects_non_integer_money(value):
    with pytest.raises(TypeError):
        indian_currency(value)


def test_rate_and_ratio_formatting():
    assert bps_percent(1100) == "11.00%"
    assert fraction_ratio(Fraction(5, 4)) == "1.25"
    assert fraction_ratio(None) == "N/A — no debt service"