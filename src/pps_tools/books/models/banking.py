"""Bank feeds, bank rules and reconciliations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, DecimalString, utcnow


class BankImportBatch(Base):
    __tablename__ = "bank_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    source: Mapped[str] = mapped_column(String(20))  # csv|ofx|qfx|stripe|stripe_fc
    filename: Mapped[Optional[str]] = mapped_column(String(255))
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    # Statement ending balance reported by the file, if any (OFX LEDGERBAL).
    statement_balance_cents: Mapped[Optional[int]] = mapped_column(Integer)
    statement_balance_date: Mapped[Optional[date]] = mapped_column(Date)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class BankFeedItem(Base):
    """A transaction downloaded or imported from the bank, waiting in For Review."""

    __tablename__ = "bank_feed_items"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_feed_external"),
        Index("ix_feed_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bank_import_batches.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(20), default="csv")
    external_id: Mapped[str] = mapped_column(String(120))
    date: Mapped[date] = mapped_column(Date)
    # Positive = money into the account (deposit / card refund), negative = money out.
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500), default="")
    payee: Mapped[Optional[str]] = mapped_column(String(200))
    memo: Mapped[Optional[str]] = mapped_column(String(500))
    check_number: Mapped[Optional[str]] = mapped_column(String(20))
    bank_category: Mapped[Optional[str]] = mapped_column(String(120))
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # review | added | matched | excluded
    status: Mapped[str] = mapped_column(String(10), default="review")
    txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    # What the For Review screen proposes.
    suggested_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    suggested_vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    suggested_customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    suggested_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bank_rules.id", ondelete="SET NULL"))
    suggested_match_txn_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"))
    suggestion_source: Mapped[Optional[str]] = mapped_column(String(10))  # rule|history|ai|match
    suggestion_confidence: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    suggestion_reason: Mapped[Optional[str]] = mapped_column(Text)
    raw: Mapped[Optional[dict]] = mapped_column(JSON)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column()
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    account: Mapped["Account"] = relationship(foreign_keys=[account_id])  # noqa: F821
    txn: Mapped[Optional["Transaction"]] = relationship(foreign_keys=[txn_id])  # noqa: F821
    suggested_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[suggested_account_id])  # noqa: F821
    suggested_vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    suggested_customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    suggested_rule: Mapped[Optional["BankRule"]] = relationship()
    suggested_match: Mapped[Optional["Transaction"]] = relationship(  # noqa: F821
        foreign_keys=[suggested_match_txn_id])

    @property
    def money_in(self) -> bool:
        return self.amount_cents > 0


class BankRule(Base):
    """'When the description contains AMAZON, categorize as Office Supplies.'"""

    __tablename__ = "bank_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # in | out | both
    direction: Mapped[str] = mapped_column(String(4), default="out")
    # Bank/credit card account ids the rule watches; empty = all.
    account_ids: Mapped[list] = mapped_column(JSON, default=list)
    match_all: Mapped[bool] = mapped_column(Boolean, default=True)
    # [{"field": "description|payee|amount|memo", "op": "contains|not_contains|equals|
    #   starts_with|ends_with|regex|gt|lt|between", "value": "...", "value2": "..."}]
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    # expense | deposit | transfer | exclude
    action: Mapped[str] = mapped_column(String(10), default="expense")
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    # Optional split: [{"account_id": 1, "percent": "60", "class_id": null}, ...]
    splits: Mapped[list] = mapped_column(JSON, default=list)
    class_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))
    memo: Mapped[Optional[str]] = mapped_column(String(200))
    tag_ids: Mapped[list] = mapped_column(JSON, default=list)
    auto_add: Mapped[bool] = mapped_column(Boolean, default=False)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    account: Mapped[Optional["Account"]] = relationship()  # noqa: F821


class Reconciliation(Base):
    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    statement_date: Mapped[date] = mapped_column(Date)
    beginning_balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    ending_balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    service_charge_cents: Mapped[int] = mapped_column(Integer, default=0)
    interest_earned_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="in_progress")  # in_progress|completed
    cleared_balance_cents: Mapped[Optional[int]] = mapped_column(Integer)
    adjustment_txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    completed_at: Mapped[Optional[datetime]] = mapped_column()
    completed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    account: Mapped["Account"] = relationship()  # noqa: F821
