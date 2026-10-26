"""Money and quantity helpers.

Every amount in the ledger is an integer number of cents. Rates and
quantities are Decimals, because a print shop prices sheets at $0.0350
and sells 2,500 of them: the line amount is rounded to the cent once,
when quantity meets rate, and never again.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Optional, Sequence, Union

Number = Union[int, float, str, Decimal, None]

CENT = Decimal("0.01")
ZERO = Decimal(0)
HUNDRED = Decimal(100)


class MoneyError(ValueError):
    """Raised when user input can't be read as an amount."""


def to_decimal(value: Number, default: Optional[Decimal] = ZERO) -> Optional[Decimal]:
    """Read a user- or file-supplied number: '1,234.50', '$12', '(5.00)', '-3'."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise MoneyError(f"not a number: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    text = str(value).strip()
    if not text:
        return default
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    if text.endswith("-"):  # some bank exports write 12.00-
        negative = not negative
        text = text[:-1].strip()
    if text.startswith("-"):
        negative = not negative
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()
    for sym in ("$", "€", "£", "¥", "USD", "CAD", "EUR", "GBP"):
        text = text.replace(sym, "")
    text = text.replace(",", "").replace(" ", "")
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    try:
        d = Decimal(text)
    except InvalidOperation as exc:
        raise MoneyError(f"not a number: {value!r}") from exc
    if not d.is_finite():
        raise MoneyError(f"not a number: {value!r}")
    return -d if negative else d


def cents(value: Number, default: int = 0) -> int:
    """Parse an amount in dollars ('12.34', Decimal('12.34'), 12.34) to cents."""
    d = to_decimal(value, None)
    if d is None:
        return default
    return round_cents(d)


def round_cents(dollars: Decimal) -> int:
    """Dollars (Decimal) to integer cents, rounding half away from zero."""
    return int((dollars * HUNDRED).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def dollars(amount_cents: Optional[int]) -> Decimal:
    if amount_cents is None:
        return ZERO
    return (Decimal(int(amount_cents)) / HUNDRED).quantize(CENT)


def line_amount(qty: Number, rate: Number) -> int:
    """Quantity x rate, rounded to the cent."""
    q = to_decimal(qty) or ZERO
    r = to_decimal(rate) or ZERO
    return round_cents(q * r)


def percent_of(amount_cents: int, pct: Number) -> int:
    p = to_decimal(pct) or ZERO
    return round_cents(Decimal(amount_cents) * p / HUNDRED / HUNDRED)


def allocate(total: int, weights: Sequence[Union[int, Decimal]]) -> list[int]:
    """Split ``total`` cents across ``weights`` so the parts sum exactly.

    Largest-remainder method; parts keep the sign of ``total``. Used for
    discounts spread over lines, combined tax rates split by component,
    and cash-basis recognition of partially paid invoices.
    """
    n = len(weights)
    if n == 0:
        return []
    ws = [Decimal(w) for w in weights]
    wsum = sum(ws, ZERO)
    if wsum == 0:
        out = [0] * n
        out[0] = total
        return out
    if any(w < 0 for w in ws):
        # Mixed signs (an invoice with a discount line): round each share and
        # put the residual cent(s) on the heaviest weight.
        parts = [round_cents(Decimal(total) * w / wsum / HUNDRED) for w in ws]
        heaviest = max(range(n), key=lambda k: abs(ws[k]))
        parts[heaviest] += total - sum(parts)
        return parts
    sign = -1 if total < 0 else 1
    magnitude = abs(total)
    raw = [Decimal(magnitude) * w / wsum for w in ws]
    floors = [int(r.to_integral_value(rounding=ROUND_FLOOR)) for r in raw]
    remainder = magnitude - sum(floors)
    order = sorted(range(n), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[: max(remainder, 0)]:
        floors[i] += 1
    return [sign * f for f in floors]


def fmt(amount_cents: Optional[int], symbol: str = "$", blank_zero: bool = False,
        parens: bool = False) -> str:
    """1234567 -> '$12,345.67'; negative -> '-$12.34' (or '($12.34)')."""
    if amount_cents is None:
        return ""
    amount_cents = int(amount_cents)
    if blank_zero and amount_cents == 0:
        return ""
    neg = amount_cents < 0
    whole, frac = divmod(abs(amount_cents), 100)
    body = f"{symbol}{whole:,}.{frac:02d}"
    if not neg:
        return body
    return f"({body})" if parens else f"-{body}"


def fmt_plain(amount_cents: Optional[int]) -> str:
    """Cents to an editable '1234.50' (no symbol, no separators)."""
    if amount_cents is None:
        return ""
    return f"{dollars(amount_cents):f}"


def fmt_qty(value: Number) -> str:
    """Decimal quantity without trailing zeros: Decimal('2.500') -> '2.5'."""
    d = to_decimal(value, None)
    if d is None:
        return ""
    if d == d.to_integral_value():
        return f"{int(d):,}"
    text = format(d.normalize(), "f")
    whole, _, frac = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    return f"{sign}{int(whole):,}.{frac}"


def fmt_rate(value: Number) -> str:
    """Unit price for display: at least 2 decimals, up to 5 when they matter."""
    d = to_decimal(value, None)
    if d is None:
        return ""
    q = d.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP).normalize()
    exp = -q.as_tuple().exponent if q.as_tuple().exponent < 0 else 0
    places = max(2, min(5, exp))
    return f"{d:,.{places}f}"


def amount_in_words(amount_cents: int) -> str:
    """For printed checks: 1234.56 -> 'One thousand two hundred thirty-four and 56/100'."""
    whole, frac = divmod(abs(int(amount_cents)), 100)
    words = _int_words(whole) if whole else "Zero"
    words = words[0].upper() + words[1:]
    return f"{words} and {frac:02d}/100"


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _int_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (f"-{_ONES[o]}" if o else "")
    if n < 1000:
        h, rest = divmod(n, 100)
        return f"{_ONES[h]} hundred" + (f" {_int_words(rest)}" if rest else "")
    for size, name in ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= size:
            big, rest = divmod(n, size)
            return f"{_int_words(big)} {name}" + (f" {_int_words(rest)}" if rest else "")
    return str(n)


def sum_cents(values: Iterable[Optional[int]]) -> int:
    return sum(int(v or 0) for v in values)
