"""Dates: payment terms, fiscal years, report periods and recurrence."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

from pps_tools.books.models import Terms


def add_months(d: date, months: int, day: Optional[int] = None) -> date:
    """Same day ``months`` later, clamped to month end. ``day=0`` means last day."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    target = d.day if day is None else (last if day == 0 else day)
    return date(y, m, min(target, last))


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def due_date(terms: Optional[Terms], txn_date: date) -> date:
    if terms is None:
        return txn_date
    if terms.kind == "day_of_month" and terms.day_of_month:
        day = terms.day_of_month
        candidate = add_months(txn_date.replace(day=1), 0, day)
        if candidate < txn_date or (terms.cutoff_days and (candidate - txn_date).days < terms.cutoff_days):
            candidate = add_months(txn_date.replace(day=1), 1, day)
        return candidate
    return txn_date + timedelta(days=terms.due_days or 0)


def discount_date(terms: Optional[Terms], txn_date: date) -> Optional[date]:
    if terms is None or not terms.discount_days or not terms.discount_pct:
        return None
    return txn_date + timedelta(days=terms.discount_days)


def fiscal_year_start(d: date, start_month: int) -> date:
    year = d.year if d.month >= start_month else d.year - 1
    return date(year, start_month, 1)


def fiscal_year_bounds(d: date, start_month: int) -> tuple[date, date]:
    start = fiscal_year_start(d, start_month)
    end = add_months(start, 12) - timedelta(days=1)
    return start, end


def quarter_bounds(d: date, start_month: int = 1) -> tuple[date, date]:
    fy = fiscal_year_start(d, start_month)
    months_in = (d.year - fy.year) * 12 + d.month - fy.month
    q_start = add_months(fy, (months_in // 3) * 3)
    return q_start, add_months(q_start, 3) - timedelta(days=1)


PERIOD_PRESETS = [
    ("today", "Today"),
    ("this_week", "This week"),
    ("this_week_to_date", "This week to date"),
    ("this_month", "This month"),
    ("this_month_to_date", "This month to date"),
    ("this_quarter", "This quarter"),
    ("this_quarter_to_date", "This quarter to date"),
    ("this_year", "This year"),
    ("this_year_to_date", "This year to date"),
    ("yesterday", "Yesterday"),
    ("last_week", "Last week"),
    ("last_month", "Last month"),
    ("last_quarter", "Last quarter"),
    ("last_year", "Last year"),
    ("last_year_to_date", "Last year to date"),
    ("last_7_days", "Last 7 days"),
    ("last_30_days", "Last 30 days"),
    ("last_90_days", "Last 90 days"),
    ("last_365_days", "Last 365 days"),
    ("next_month", "Next month"),
    ("next_quarter", "Next quarter"),
    ("all", "All dates"),
    ("custom", "Custom"),
]


def period_range(preset: str, today: date, fy_start_month: int = 1) -> tuple[Optional[date], Optional[date]]:
    """Resolve a report date preset. Years and quarters follow the fiscal year."""
    if preset == "today":
        return today, today
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset in ("this_week", "this_week_to_date"):
        start = today - timedelta(days=(today.weekday() + 1) % 7)  # weeks start Sunday
        return start, (today if preset.endswith("to_date") else start + timedelta(days=6))
    if preset == "last_week":
        start = today - timedelta(days=(today.weekday() + 1) % 7 + 7)
        return start, start + timedelta(days=6)
    if preset in ("this_month", "this_month_to_date"):
        start = today.replace(day=1)
        return start, (today if preset.endswith("to_date") else month_end(today))
    if preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if preset == "next_month":
        start = add_months(today.replace(day=1), 1)
        return start, month_end(start)
    if preset in ("this_quarter", "this_quarter_to_date"):
        start, end = quarter_bounds(today, fy_start_month)
        return start, (today if preset.endswith("to_date") else end)
    if preset == "last_quarter":
        start, _ = quarter_bounds(today, fy_start_month)
        return quarter_bounds(start - timedelta(days=1), fy_start_month)
    if preset == "next_quarter":
        _, end = quarter_bounds(today, fy_start_month)
        return quarter_bounds(end + timedelta(days=1), fy_start_month)
    if preset in ("this_year", "this_year_to_date"):
        start, end = fiscal_year_bounds(today, fy_start_month)
        return start, (today if preset.endswith("to_date") else end)
    if preset == "last_year":
        start, _ = fiscal_year_bounds(today, fy_start_month)
        return fiscal_year_bounds(start - timedelta(days=1), fy_start_month)
    if preset == "last_year_to_date":
        start, _ = fiscal_year_bounds(today, fy_start_month)
        ly_start, _ = fiscal_year_bounds(start - timedelta(days=1), fy_start_month)
        try:
            ly_today = today.replace(year=today.year - 1)
        except ValueError:  # Feb 29
            ly_today = today.replace(year=today.year - 1, day=28)
        return ly_start, ly_today
    for days in (7, 30, 90, 365):
        if preset == f"last_{days}_days":
            return today - timedelta(days=days - 1), today
    if preset == "all":
        return None, None
    return None, None


def month_periods(start: date, end: date) -> list[tuple[date, date, str]]:
    out = []
    cur = start.replace(day=1)
    while cur <= end:
        p_start = max(cur, start)
        p_end = min(month_end(cur), end)
        out.append((p_start, p_end, cur.strftime("%b %Y")))
        cur = add_months(cur, 1)
    return out


def quarter_periods(start: date, end: date, fy_start_month: int = 1) -> list[tuple[date, date, str]]:
    out = []
    q_start, q_end = quarter_bounds(start, fy_start_month)
    while q_start <= end:
        label = f"{q_start.strftime('%b')}–{q_end.strftime('%b %Y')}"
        out.append((max(q_start, start), min(q_end, end), label))
        q_start = q_end + timedelta(days=1)
        q_start, q_end = quarter_bounds(q_start, fy_start_month)
    return out


def year_periods(start: date, end: date, fy_start_month: int = 1) -> list[tuple[date, date, str]]:
    out = []
    y_start, y_end = fiscal_year_bounds(start, fy_start_month)
    while y_start <= end:
        label = str(y_start.year) if fy_start_month == 1 else f"FY{y_end.year}"
        out.append((max(y_start, start), min(y_end, end), label))
        y_start, y_end = fiscal_year_bounds(y_end + timedelta(days=1), fy_start_month)
    return out


def week_periods(start: date, end: date) -> list[tuple[date, date, str]]:
    out = []
    cur = start - timedelta(days=(start.weekday() + 1) % 7)
    while cur <= end:
        w_end = cur + timedelta(days=6)
        out.append((max(cur, start), min(w_end, end), f"{max(cur, start):%b %d}–{min(w_end, end):%b %d}"))
        cur = w_end + timedelta(days=1)
    return out


def next_occurrence(current: date, interval: str, every: int = 1, day_of_week: Optional[int] = None,
                    day_of_month: Optional[int] = None, month_of_year: Optional[int] = None) -> date:
    every = max(1, every or 1)
    if interval == "daily":
        return current + timedelta(days=every)
    if interval == "weekly":
        nxt = current + timedelta(days=7 * every)
        if day_of_week is not None:
            nxt = nxt - timedelta(days=(nxt.weekday() - day_of_week) % 7)
        return nxt
    if interval == "yearly":
        target_month = month_of_year or current.month
        base = date(current.year + every, target_month, 1)
        return add_months(base, 0, day_of_month if day_of_month is not None else current.day)
    # monthly
    return add_months(current.replace(day=1), every,
                      day_of_month if day_of_month is not None else current.day)


def parse_date(value, default: Optional[date] = None) -> Optional[date]:
    if value is None or value == "":
        return default
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%Y%m%d",
                "%Y-%m-%dT%H:%M:%S", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {value!r}")
