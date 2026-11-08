from decimal import Decimal

import pytest

from app.money import MoneyError, format_minor, mask_account_number, parse_amount_to_minor


@pytest.mark.parametrize("raw,expected", [("1", 100), ("1.5", 150), ("1250.50", 125050), (" 0.01 ", 1), (7, 700),
                                          (Decimal("3.10"), 310)])
def test_parse_valid(raw, expected):
    assert parse_amount_to_minor(raw) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "0.001", "abc", "", "NaN", "inf", 1.5, True])
def test_parse_invalid(raw):
    with pytest.raises(MoneyError):
        parse_amount_to_minor(raw)


def test_format_and_mask():
    assert format_minor(125050) == "1250.50"
    assert format_minor(-5) == "-0.05"
    assert mask_account_number("1007123456789012") == "•••• 9012"
