"""Jinja filters and globals."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlencode

from flask import request
from jinja2 import Undefined
from markupsafe import Markup, escape

from pps_tools.books import money


def _blank(value: Any) -> bool:
    """None, "", or a name the template doesn't have: all print as nothing."""
    return value is None or isinstance(value, Undefined) or (isinstance(value, str) and value == "")


def money_filter(cents: Any, blank_zero: bool = False, parens: bool = False) -> str:
    if _blank(cents):
        return ""
    return money.fmt(int(cents), blank_zero=blank_zero, parens=parens)


def money_plain(cents: Any) -> str:
    if _blank(cents):
        return ""
    return money.fmt_plain(int(cents))


def qty_filter(value: Any) -> str:
    return "" if _blank(value) else money.fmt_qty(value)


def rate_filter(value: Any) -> str:
    return "" if _blank(value) else money.fmt_rate(value)


def plain_decimal(value: Any) -> str:
    """Decimal for an <input>: no thousands separators, no trailing zeros."""
    if _blank(value):
        return ""
    d = Decimal(value)
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def date_filter(value: Any, fmt: str = "%m/%d/%Y") -> str:
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime(fmt)
    return str(value)


def date_input(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, date) else str(value)


def pct_filter(value: Any) -> str:
    if _blank(value):
        return ""
    return f"{Decimal(value):,.2f}%"


def nl2br(value: Optional[str]) -> Markup:
    if not value:
        return Markup("")
    return Markup("<br>".join(escape(line) for line in str(value).splitlines()))


def report_cell(value: Any, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return money.fmt(int(value))
    if kind == "qty":
        return money.fmt_qty(value)
    if kind == "rate":
        return money.fmt_rate(value)
    if kind == "pct":
        return pct_filter(value)
    if kind == "date":
        return date_filter(value)
    if kind == "int":
        return f"{int(value):,}"
    return str(value)


def url_with(**changes) -> str:
    """The current URL with some query arguments replaced."""
    args = request.args.to_dict(flat=True)
    for k, v in changes.items():
        if v is None:
            args.pop(k, None)
        else:
            args[k] = v
    query = urlencode(args)
    return f"{request.path}?{query}" if query else request.path


def register(app) -> None:
    app.add_template_filter(money_filter, "money")
    app.add_template_filter(money_plain, "money_plain")
    app.add_template_filter(qty_filter, "qty")
    app.add_template_filter(rate_filter, "rate")
    app.add_template_filter(plain_decimal, "plain_decimal")
    app.add_template_filter(date_filter, "date")
    app.add_template_filter(date_input, "date_input")
    app.add_template_filter(pct_filter, "pct")
    app.add_template_filter(nl2br, "nl2br")
    app.add_template_global(report_cell, "report_cell")
    app.add_template_global(url_with, "url_with")
