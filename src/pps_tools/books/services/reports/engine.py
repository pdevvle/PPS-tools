"""Report framework: parameters, result rows, and ledger aggregation.

A report function takes a Session and :class:`Params` and returns a
:class:`Report` — columns plus rows with indentation, row kinds (section,
data, subtotal, total) and drill-down links. The web layer renders that
as HTML; the exporters turn it into CSV or PDF.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, fields, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import (Account, Company, Customer, Employee, Item, LedgerEntry, Location,
                                    TrackingClass, Vendor)
from pps_tools.books.services import cash_basis
from pps_tools.books.services import dates as D
from pps_tools.books.services.accounts import ordered_accounts


@dataclass
class Params:
    preset: str = "this_year_to_date"
    start: Optional[date] = None
    end: Optional[date] = None
    basis: str = "accrual"
    columns: str = "total"  # total|month|quarter|year|week|customer|vendor|class|location|item
    compare: str = "none"  # none|prev_period|prev_year
    pct: str = "none"  # none|income|column|row|expense
    customer_id: Optional[int] = None
    vendor_id: Optional[int] = None
    employee_id: Optional[int] = None
    account_id: Optional[int] = None
    class_id: Optional[int] = None
    location_id: Optional[int] = None
    item_id: Optional[int] = None
    txn_type: Optional[str] = None
    group_by: str = ""
    include_zero: bool = False
    aging_interval: int = 30
    aging_periods: int = 4
    past_due_only: bool = False
    budget_id: Optional[int] = None
    cleared: str = "all"
    show_subaccounts: bool = True
    search: str = ""

    INT_FIELDS = ("customer_id", "vendor_id", "employee_id", "account_id", "class_id", "location_id",
                  "item_id", "budget_id", "aging_interval", "aging_periods")
    BOOL_FIELDS = ("include_zero", "past_due_only", "show_subaccounts")

    @classmethod
    def from_args(cls, args: dict, defaults: Optional[dict] = None) -> "Params":
        p = cls(**(defaults or {}))
        for f in fields(cls):
            if f.name not in args:
                continue
            raw = args.get(f.name)
            if f.name in ("start", "end"):
                try:
                    setattr(p, f.name, D.parse_date(raw) if raw else None)
                except ValueError:
                    setattr(p, f.name, None)
            elif f.name in cls.INT_FIELDS:
                try:
                    setattr(p, f.name, int(raw) if raw not in (None, "", "None") else None)
                except ValueError:
                    setattr(p, f.name, None)
            elif f.name in cls.BOOL_FIELDS:
                setattr(p, f.name, str(raw).lower() in ("1", "true", "on", "yes"))
            else:
                setattr(p, f.name, raw if raw not in (None, "") else getattr(p, f.name))
        if "start" in args or "end" in args:
            if args.get("start") or args.get("end"):
                if p.preset != "all" and "preset" not in args:
                    p.preset = "custom"
        if p.aging_interval in (None, 0):
            p.aging_interval = 30
        if p.aging_periods in (None, 0):
            p.aging_periods = 4
        return p

    def resolve(self, today: date, fy_start_month: int) -> "Params":
        """Fill start/end from the preset (custom keeps what was typed)."""
        if self.preset and self.preset != "custom":
            start, end = D.period_range(self.preset, today, fy_start_month)
            self.start, self.end = start, end
        return self

    def query(self, **overrides) -> str:
        """URL query for these params (defaults left out), with ``overrides``."""
        defaults = Params()
        data = {}
        for f in fields(self):
            v = overrides[f.name] if f.name in overrides else getattr(self, f.name)
            if v in (None, "") or v == getattr(defaults, f.name):
                continue
            if isinstance(v, bool):
                v = "1" if v else "0"
            data[f.name] = v.isoformat() if isinstance(v, date) else v
        return urlencode(data)

    def copy(self, **changes) -> "Params":
        return replace(self, **changes)


@dataclass
class Col:
    key: str
    label: str
    kind: str = "money"  # money|text|date|qty|pct|int|rate
    align: str = ""

    def __post_init__(self):
        if not self.align:
            self.align = "right" if self.kind in ("money", "qty", "pct", "int", "rate") else "left"


@dataclass
class Row:
    cells: dict[str, Any]
    level: int = 0
    kind: str = "data"  # section|data|subtotal|total|grand|blank|note
    link: Optional[str] = None
    links: dict[str, str] = field(default_factory=dict)  # per-cell drilldowns

    def get(self, key: str, default: Any = None) -> Any:
        return self.cells.get(key, default)


@dataclass
class Report:
    key: str
    title: str
    subtitle: str = ""
    columns: list[Col] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    basis: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    params: Optional[Params] = None
    company: str = ""
    chart: Optional[dict] = None

    def add(self, cells: dict, level: int = 0, kind: str = "data", link: Optional[str] = None,
            links: Optional[dict] = None) -> Row:
        row = Row(cells, level, kind, link, links or {})
        self.rows.append(row)
        return row

    def blank(self) -> None:
        self.rows.append(Row({}, kind="blank"))

    def money_keys(self) -> list[str]:
        return [c.key for c in self.columns if c.kind == "money"]


# -- helpers ------------------------------------------------------------------------


def company_info(s: Session) -> Company:
    return s.get(Company, 1)


def long_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"  # no %-d: it isn't portable to Windows


def period_label(p: Params) -> str:
    if p.start and p.end:
        if p.start == p.end:
            return long_date(p.end)
        if p.start.day == 1 and p.end == D.month_end(p.end) and p.start.year == p.end.year:
            if p.start.month == p.end.month:
                return f"{p.start:%B %Y}"
            return f"{p.start:%B}–{p.end:%B %Y}"
        return f"{long_date(p.start)} – {long_date(p.end)}"
    if p.end:
        return f"Through {long_date(p.end)}"
    if p.start:
        return f"Since {long_date(p.start)}"
    return "All dates"


def as_of_label(d: Optional[date]) -> str:
    return f"As of {long_date(d)}" if d else "As of today"


def txn_link(txn_id: int) -> str:
    return f"/txn/{txn_id}"


def report_link(key: str, params: Params, **overrides) -> str:
    return f"/reports/{key}?{params.query(**overrides)}"


def entity_name_maps(s: Session) -> dict[str, dict[int, str]]:
    return {
        "customer": dict(s.execute(select(Customer.id, Customer.display_name)).all()),
        "vendor": dict(s.execute(select(Vendor.id, Vendor.display_name)).all()),
        "employee": dict(s.execute(select(Employee.id, Employee.display_name)).all()),
        "class": {c.id: c.full_name for c in s.scalars(select(TrackingClass))},
        "location": {c.id: c.full_name for c in s.scalars(select(Location))},
        "item": dict(s.execute(select(Item.id, Item.name)).all()),
    }


def customer_scope(s: Session, customer_id: Optional[int]) -> Optional[list[int]]:
    """A customer plus its sub-customers and projects."""
    if not customer_id:
        return None
    out, frontier = [customer_id], [customer_id]
    while frontier:
        kids = s.scalars(select(Customer.id).where(Customer.parent_id.in_(frontier))).all()
        out.extend(kids)
        frontier = list(kids)
    return out


# -- aggregation --------------------------------------------------------------------

DIM_COLUMNS = {
    "customer": "customer_id",
    "vendor": "vendor_id",
    "class": "class_id",
    "location": "location_id",
    "item": "item_id",
    "employee": "employee_id",
}


@dataclass
class Aggregator:
    """Sums ledger entries by account (and optionally a dimension), on either basis."""

    s: Session
    basis: str = "accrual"
    customer_ids: Optional[list[int]] = None
    vendor_id: Optional[int] = None
    class_id: Optional[int] = None
    location_id: Optional[int] = None
    item_id: Optional[int] = None
    employee_id: Optional[int] = None
    _cash_cache: Optional[list] = None

    @classmethod
    def for_params(cls, s: Session, p: Params) -> "Aggregator":
        return cls(s, p.basis, customer_scope(s, p.customer_id), p.vendor_id, p.class_id, p.location_id,
                   p.item_id, p.employee_id)

    def _filters_sql(self, q):
        if self.customer_ids is not None:
            q = q.where(LedgerEntry.customer_id.in_(self.customer_ids))
        if self.vendor_id:
            q = q.where(LedgerEntry.vendor_id == self.vendor_id)
        if self.class_id:
            q = q.where(LedgerEntry.class_id == self.class_id)
        if self.location_id:
            q = q.where(LedgerEntry.location_id == self.location_id)
        if self.item_id:
            q = q.where(LedgerEntry.item_id == self.item_id)
        if self.employee_id:
            q = q.where(LedgerEntry.employee_id == self.employee_id)
        return q

    def _passes(self, e) -> bool:
        if self.customer_ids is not None and e.customer_id not in self.customer_ids:
            return False
        if self.vendor_id and e.vendor_id != self.vendor_id:
            return False
        if self.class_id and e.class_id != self.class_id:
            return False
        if self.location_id and e.location_id != self.location_id:
            return False
        if self.item_id and e.item_id != self.item_id:
            return False
        if self.employee_id and e.employee_id != self.employee_id:
            return False
        return True

    def _cash(self) -> list:
        if self._cash_cache is None:
            self._cash_cache = [e for e in cash_basis.entries(self.s) if self._passes(e)]
        return self._cash_cache

    def totals(self, start: Optional[date], end: Optional[date], dim: Optional[str] = None
               ) -> dict[tuple[int, Any], int]:
        """{(account_id, dim_value): debit-positive sum} for entries in [start, end]."""
        out: dict[tuple[int, Any], int] = defaultdict(int)
        col = DIM_COLUMNS.get(dim) if dim else None
        if self.basis == "cash":
            for e in self._cash():
                if (start is None or e.date >= start) and (end is None or e.date <= end):
                    out[(e.account_id, getattr(e, col) if col else None)] += e.amount_cents
            return dict(out)
        cols = [LedgerEntry.account_id]
        if col:
            cols.append(getattr(LedgerEntry, col))
        q = select(*cols, func.sum(LedgerEntry.amount_cents)).group_by(*cols)
        if start is not None:
            q = q.where(LedgerEntry.date >= start)
        if end is not None:
            q = q.where(LedgerEntry.date <= end)
        q = self._filters_sql(q)
        for row in self.s.execute(q):
            if col:
                out[(row[0], row[1])] += int(row[2] or 0)
            else:
                out[(row[0], None)] += int(row[1] or 0)
        return dict(out)

    def by_account(self, start: Optional[date], end: Optional[date]) -> dict[int, int]:
        return {aid: v for (aid, _), v in self.totals(start, end).items()}


@dataclass
class ColumnSpec:
    key: str
    label: str
    start: Optional[date]
    end: Optional[date]
    dim_value: Any = None
    is_total: bool = False
    kind: str = "period"  # period|dim|compare|pct|total


def period_columns(p: Params, fy_start_month: int) -> list[ColumnSpec]:
    """Columns for the P&L-style reports."""
    start, end = p.start, p.end
    if p.columns in ("month", "quarter", "year", "week") and start and end:
        if p.columns == "month":
            periods = D.month_periods(start, end)
        elif p.columns == "quarter":
            periods = D.quarter_periods(start, end, fy_start_month)
        elif p.columns == "week":
            periods = D.week_periods(start, end)
        else:
            periods = D.year_periods(start, end, fy_start_month)
        cols = [ColumnSpec(f"c{i}", label, a, b) for i, (a, b, label) in enumerate(periods)]
        cols.append(ColumnSpec("total", "Total", start, end, is_total=True, kind="total"))
        return cols
    return [ColumnSpec("total", "Total", start, end, is_total=True, kind="total")]


def compare_range(p: Params) -> tuple[Optional[date], Optional[date], str]:
    if not p.start or not p.end:
        return None, None, ""
    if p.compare == "prev_year":
        try:
            return p.start.replace(year=p.start.year - 1), p.end.replace(year=p.end.year - 1), "Previous year"
        except ValueError:
            return (p.start - timedelta(days=365), p.end - timedelta(days=365), "Previous year")
    if p.compare == "prev_period":
        length = (p.end - p.start).days + 1
        if p.start.day == 1 and p.end == D.month_end(p.end):
            months = (p.end.year - p.start.year) * 12 + p.end.month - p.start.month + 1
            prev_start = D.add_months(p.start, -months)
            return prev_start, D.add_months(prev_start, months) - timedelta(days=1), "Previous period"
        return p.start - timedelta(days=length), p.start - timedelta(days=1), "Previous period"
    return None, None, ""


def account_tree(s: Session, types: Iterable[str], active_or_used: set[int]) -> list[Account]:
    """Accounts of the given types in chart order, hiding unused inactive ones."""
    return [a for a in ordered_accounts(s, types=types) if a.active or a.id in active_or_used]


def rollup(accounts: list[Account], values: dict[int, int]) -> dict[int, int]:
    """Each account's own value plus all of its sub-accounts'."""
    by_id = {a.id: a for a in accounts}
    totals = defaultdict(int)
    for aid, v in values.items():
        node = by_id.get(aid)
        guard = 0
        while node is not None and guard < 20:
            totals[node.id] += v
            node = by_id.get(node.parent_id) if node.parent_id else None
            guard += 1
    return dict(totals)


def visible_depth(a: Account, by_id: dict[int, Account]) -> int:
    d, node = 0, by_id.get(a.parent_id) if a.parent_id else None
    while node is not None and d < 20:
        d += 1
        node = by_id.get(node.parent_id) if node.parent_id else None
    return d


ReportFn = Callable[[Session, Params], Report]


@dataclass
class ReportDef:
    key: str
    title: str
    category: str
    fn: ReportFn
    description: str = ""
    kind: str = "period"  # period|as_of|list
    options: tuple[str, ...] = ()  # which controls to show: columns, compare, pct, basis, customer, ...
    default_preset: str = "this_year_to_date"


REGISTRY: dict[str, ReportDef] = {}

CATEGORIES = [
    ("favorites", "Favorites"),
    ("business", "Business overview"),
    ("receivables", "Who owes you"),
    ("sales", "Sales and customers"),
    ("payables", "What you owe"),
    ("expenses", "Expenses and vendors"),
    ("tax", "Sales tax"),
    ("employees", "Employees and time"),
    ("inventory", "Inventory"),
    ("projects", "Projects"),
    ("banking", "Banking and payments"),
    ("accountant", "For my accountant"),
    ("budgets", "Budgets"),
]


def register(key: str, title: str, category: str, description: str = "", kind: str = "period",
             options: tuple[str, ...] = (), default_preset: str = "this_year_to_date"):
    def deco(fn: ReportFn) -> ReportFn:
        REGISTRY[key] = ReportDef(key, title, category, fn, description, kind, options, default_preset)
        return fn

    return deco


def run(s: Session, key: str, p: Params, today: Optional[date] = None) -> Report:
    rdef = REGISTRY[key]
    company = company_info(s)
    today = today or date.today()
    if rdef.kind == "as_of" and p.preset not in ("custom",) and not p.end:
        p.resolve(today, company.fiscal_year_start_month)
    elif rdef.kind != "list":
        p.resolve(today, company.fiscal_year_start_month)
    report = rdef.fn(s, p)
    report.company = company.name
    report.params = p
    return report


def pct(n: int, d: int) -> Optional[Decimal]:
    if not d:
        return None
    return (Decimal(n) * 100 / Decimal(d)).quantize(Decimal("0.01"))
