"""Sales tax: computing tax on a sale, and what's owed to each agency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import (LedgerEntry, TaxAgency, TaxRate, Transaction, TransactionTaxLine)
from pps_tools.books.money import allocate, round_cents
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.dates import add_months, quarter_bounds


@dataclass
class TaxPart:
    rate: TaxRate
    taxable_cents: int
    amount_cents: int


def compute(rate: Optional[TaxRate], taxable_cents: int, override_cents: Optional[int] = None) -> list[TaxPart]:
    """Tax on ``taxable_cents`` at ``rate`` (combined rates split by component).

    With ``override_cents`` the total is fixed by hand and spread across the
    components in proportion to their rates.
    """
    if rate is None:
        return []
    leaves = [r for r in rate.leaf_rates()]
    if not leaves:
        return []
    if override_cents is not None:
        weights = [r.rate for r in leaves]
        if sum(weights, Decimal(0)) == 0:
            weights = [Decimal(1)] * len(leaves)
        parts = allocate(override_cents, weights)
        return [TaxPart(r, taxable_cents, p) for r, p in zip(leaves, parts)]
    return [TaxPart(r, taxable_cents, round_cents(Decimal(taxable_cents) * r.rate / Decimal(10000)))
            for r in leaves]


def agency_balance(s: Session, agency_id: int, as_of: Optional[date] = None) -> int:
    """What's owed to the agency (credit balance of Sales Tax Payable for it)."""
    stp = system_account_id(s, "sales_tax_payable")
    q = select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
        LedgerEntry.account_id == stp, LedgerEntry.tax_agency_id == agency_id)
    if as_of:
        q = q.where(LedgerEntry.date <= as_of)
    return -int(s.scalar(q) or 0)


def filing_periods(agency: TaxAgency, today: date, count: int = 6) -> list[tuple[date, date]]:
    """The agency's most recent filing periods, newest first."""
    out = []
    if agency.filing_frequency == "monthly":
        start = today.replace(day=1)
        for _ in range(count):
            end = add_months(start, 1).replace(day=1)
            out.append((start, end - timedelta(days=1)))
            start = add_months(start, -1)
    elif agency.filing_frequency == "annually":
        for i in range(count):
            y = today.year - i
            out.append((date(y, 1, 1), date(y, 12, 31)))
    else:
        start, end = quarter_bounds(today)
        for _ in range(count):
            out.append((start, end))
            start, end = quarter_bounds(start - timedelta(days=1))
    return out


@dataclass
class LiabilityRow:
    rate_id: int
    rate_name: str
    rate_pct: Decimal
    agency_id: Optional[int]
    agency_name: str
    taxable_cents: int
    tax_cents: int


def liability_by_rate(s: Session, start: Optional[date], end: Optional[date],
                      agency_id: Optional[int] = None) -> list[LiabilityRow]:
    """Taxable sales and tax collected per component rate (accrual basis)."""
    q = (select(TransactionTaxLine.tax_rate_id, TransactionTaxLine.agency_id, Transaction.type,
                func.sum(TransactionTaxLine.taxable_cents), func.sum(TransactionTaxLine.amount_cents))
         .join(Transaction, Transaction.id == TransactionTaxLine.txn_id)
         .where(Transaction.voided.is_(False),
                Transaction.type.in_(("invoice", "sales_receipt", "credit_memo", "refund_receipt")))
         .group_by(TransactionTaxLine.tax_rate_id, TransactionTaxLine.agency_id, Transaction.type))
    if start:
        q = q.where(Transaction.date >= start)
    if end:
        q = q.where(Transaction.date <= end)
    if agency_id:
        q = q.where(TransactionTaxLine.agency_id == agency_id)
    acc: dict[tuple, list[int]] = {}
    for rate_id, ag_id, ttype, taxable, tax in s.execute(q):
        sign = -1 if ttype in ("credit_memo", "refund_receipt") else 1
        key = (rate_id, ag_id)
        row = acc.setdefault(key, [0, 0])
        row[0] += sign * int(taxable or 0)
        row[1] += sign * int(tax or 0)
    rows = []
    for (rate_id, ag_id), (taxable, tax) in acc.items():
        rate = s.get(TaxRate, rate_id)
        agency = s.get(TaxAgency, ag_id) if ag_id else None
        rows.append(LiabilityRow(rate_id, rate.name if rate else "?", rate.rate if rate else Decimal(0),
                                 ag_id, agency.name if agency else "(no agency)", taxable, tax))
    rows.sort(key=lambda r: (r.agency_name, r.rate_name))
    return rows


def payments_to_agency(s: Session, agency_id: int, start: Optional[date], end: Optional[date]) -> int:
    q = select(func.coalesce(func.sum(Transaction.total_cents), 0)).where(
        Transaction.type == "sales_tax_payment", Transaction.tax_agency_id == agency_id,
        Transaction.voided.is_(False))
    if start:
        q = q.where(Transaction.date >= start)
    if end:
        q = q.where(Transaction.date <= end)
    return int(s.scalar(q) or 0)


def adjustments_for_agency(s: Session, agency_id: int, start: Optional[date], end: Optional[date]) -> int:
    q = select(func.coalesce(func.sum(Transaction.total_cents), 0)).where(
        and_(Transaction.type == "sales_tax_adjustment", Transaction.tax_agency_id == agency_id,
             Transaction.voided.is_(False)))
    if start:
        q = q.where(Transaction.date >= start)
    if end:
        q = q.where(Transaction.date <= end)
    return int(s.scalar(q) or 0)
