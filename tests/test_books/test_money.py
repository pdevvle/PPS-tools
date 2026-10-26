from decimal import Decimal

import pytest

from pps_tools.books import money


@pytest.mark.parametrize("text,expected", [
    ("12.34", 1234), ("$1,234.56", 123456), ("(5.00)", -500), ("-3", -300), ("12.00-", -1200),
    ("", 0), (None, 0), (Decimal("0.005"), 1), ("$-7.10", -710), (19.99, 1999), ("+4", 400),
])
def test_cents_parses_common_formats(text, expected):
    assert money.cents(text) == expected


def test_cents_rejects_garbage():
    with pytest.raises(money.MoneyError):
        money.cents("twelve")


def test_line_amount_rounds_once():
    # 2,500 sheets at $0.0350 = $87.50 exactly; 3 at $0.333 rounds to $1.00
    assert money.line_amount("2500", "0.0350") == 8750
    assert money.line_amount("3", "0.333") == 100


def test_allocate_sums_exactly():
    parts = money.allocate(1000, [1, 1, 1])
    assert sum(parts) == 1000 and sorted(parts) == [333, 333, 334]
    parts = money.allocate(-101, [50, 50])
    assert sum(parts) == -101
    parts = money.allocate(999, [Decimal("6.5"), Decimal("1.0"), Decimal("2.85")])
    assert sum(parts) == 999
    mixed = money.allocate(1000, [1500, -500])
    assert sum(mixed) == 1000 and mixed == [1500, -500]


def test_fmt_and_words():
    assert money.fmt(123456) == "$1,234.56"
    assert money.fmt(-500) == "-$5.00"
    assert money.fmt(-500, parens=True) == "($5.00)"
    assert money.fmt_qty(Decimal("2.500")) == "2.5"
    assert money.fmt_qty(Decimal("1000")) == "1,000"
    assert money.fmt_rate(Decimal("0.035")) == "0.035"
    assert money.fmt_rate(Decimal("12")) == "12.00"
    assert money.amount_in_words(123456) == "One thousand two hundred thirty-four and 56/100"
    assert money.amount_in_words(5) == "Zero and 05/100"
