"""Transactions, their lines, the links that apply one to another, and
the general-ledger entries every posting transaction generates.

One table holds every kind of transaction (invoice, bill, check, journal
entry...), the way QBO's own data model does. Ledger entries are derived
data: :mod:`pps_tools.books.services.posting` rebuilds them from the
transaction whenever it is saved.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (Boolean, Column, Date, ForeignKey, Index, Integer, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, DecimalString, utcnow

transaction_tags = Table(
    "transaction_tags",
    Base.metadata,
    Column("txn_id", ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_txn_type_date", "type", "date"),
        Index("ix_txn_customer", "customer_id"),
        Index("ix_txn_vendor", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30))
    number: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    expiration_date: Mapped[Optional[date]] = mapped_column(Date)

    # Who the transaction is with. Expenses and checks may be paid to any name.
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    tax_agency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_agencies.id"))

    # Header account: deposit-to (payments, receipts, deposits), paid-from
    # (expenses, checks, bill payments, refunds), transfer-from, or the
    # adjustment account on inventory adjustments.
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    # Transfer-to / credit card being paid down.
    to_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    # A/R or A/P control account for sales and purchase documents.
    ar_ap_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))

    terms_id: Mapped[Optional[int]] = mapped_column(ForeignKey("terms.id"))
    payment_method_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_methods.id"))
    ref_no: Mapped[Optional[str]] = mapped_column(String(60))
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    ship_via: Mapped[Optional[str]] = mapped_column(String(80))
    ship_date: Mapped[Optional[date]] = mapped_column(Date)
    tracking_no: Mapped[Optional[str]] = mapped_column(String(80))
    memo: Mapped[Optional[str]] = mapped_column(Text)  # private note
    message: Mapped[Optional[str]] = mapped_column(Text)  # shown to the customer/vendor
    statement_memo: Mapped[Optional[str]] = mapped_column(String(200))

    email_to: Mapped[Optional[str]] = mapped_column(String(500))
    email_cc: Mapped[Optional[str]] = mapped_column(String(500))
    email_bcc: Mapped[Optional[str]] = mapped_column(String(500))
    sent_at: Mapped[Optional[datetime]] = mapped_column()
    viewed_at: Mapped[Optional[datetime]] = mapped_column()
    print_later: Mapped[bool] = mapped_column(Boolean, default=False)
    printed_at: Mapped[Optional[datetime]] = mapped_column()
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column()

    class_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))

    currency: Mapped[Optional[str]] = mapped_column(String(3))
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(DecimalString)

    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_type: Mapped[Optional[str]] = mapped_column(String(10))  # percent|amount
    discount_value: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_before_tax: Mapped[bool] = mapped_column(Boolean, default=True)
    tax_rate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_rates.id"))
    taxable_subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_override: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_exempt_reason: Mapped[Optional[str]] = mapped_column(String(120))
    shipping_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Open amount for A/R and A/P items: unpaid invoice/bill, unapplied credit.
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)

    # Workflow status for non-posting documents (estimates, purchase orders).
    status: Mapped[Optional[str]] = mapped_column(String(20))
    accepted_by: Mapped[Optional[str]] = mapped_column(String(120))
    accepted_at: Mapped[Optional[datetime]] = mapped_column()

    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    voided_at: Mapped[Optional[datetime]] = mapped_column()
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    recurring_template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recurring_templates.id"))
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True)

    # Stripe identifiers (unique so a webhook delivered twice can't post twice).
    stripe_checkout_session_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    stripe_charge_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    stripe_object_id: Mapped[Optional[str]] = mapped_column(String(80), unique=True)
    stripe_fee_cents: Mapped[Optional[int]] = mapped_column(Integer)
    allow_online_card: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_online_ach: Mapped[bool] = mapped_column(Boolean, default=True)

    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    lines: Mapped[list["TransactionLine"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan", order_by="TransactionLine.position",
        foreign_keys="TransactionLine.txn_id")
    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan", order_by="LedgerEntry.position")
    tax_lines: Mapped[list["TransactionTaxLine"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan")
    links_out: Mapped[list["TransactionLink"]] = relationship(
        foreign_keys="TransactionLink.from_txn_id", back_populates="from_txn",
        cascade="all, delete-orphan")
    links_in: Mapped[list["TransactionLink"]] = relationship(
        foreign_keys="TransactionLink.to_txn_id", back_populates="to_txn",
        cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship(secondary=transaction_tags)  # noqa: F821

    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    employee: Mapped[Optional["Employee"]] = relationship()  # noqa: F821
    tax_agency: Mapped[Optional["TaxAgency"]] = relationship()  # noqa: F821
    account: Mapped[Optional["Account"]] = relationship(foreign_keys=[account_id])  # noqa: F821
    to_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[to_account_id])  # noqa: F821
    ar_ap_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[ar_ap_account_id])  # noqa: F821
    terms: Mapped[Optional["Terms"]] = relationship()  # noqa: F821
    payment_method: Mapped[Optional["PaymentMethod"]] = relationship()  # noqa: F821
    tax_rate: Mapped[Optional["TaxRate"]] = relationship()  # noqa: F821
    tracking_class: Mapped[Optional["TrackingClass"]] = relationship()  # noqa: F821
    location: Mapped[Optional["Location"]] = relationship()  # noqa: F821

    @property
    def info(self):
        from pps_tools.books.txn_types import TXN_TYPES

        return TXN_TYPES[self.type]

    @property
    def entity(self):
        return self.customer or self.vendor or self.employee or self.tax_agency

    @property
    def entity_name(self) -> str:
        e = self.entity
        if e is None:
            return ""
        return getattr(e, "display_name", None) or getattr(e, "name", "")

    @property
    def amount_paid_cents(self) -> int:
        return self.total_cents - self.balance_cents

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction {self.id} {self.type} #{self.number} {self.date} {self.total_cents}>"


class TransactionLine(Base):
    __tablename__ = "transaction_lines"
    __table_args__ = (Index("ix_line_txn", "txn_id"), Index("ix_line_item", "item_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # item | account | description | subtotal | debit/credit lines use "account"
    kind: Mapped[str] = mapped_column(String(12), default="item")
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("items.id"))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    qty: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    rate: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Journal entries: "debit" or "credit". Everything else leaves it empty.
    posting_type: Mapped[Optional[str]] = mapped_column(String(6))
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    service_date: Mapped[Optional[date]] = mapped_column(Date)
    class_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))
    # Customer/project on an expense line (billable or job-costed), or the
    # Name column on journal entry and deposit lines.
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    billable: Mapped[bool] = mapped_column(Boolean, default=False)
    markup_pct: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    # Invoice that billed this expense line / time / delayed charge.
    billed_txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    # Where an invoice/bill line came from: estimate line, PO line, billable
    # expense line, time activity or delayed charge line.
    source_type: Mapped[Optional[str]] = mapped_column(String(20))
    source_id: Mapped[Optional[int]] = mapped_column(Integer)
    # Purchase orders: quantity received on bills so far.
    received_qty: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Deposit lines: payment method and reference number of each check.
    payment_method_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_methods.id"))
    ref_no: Mapped[Optional[str]] = mapped_column(String(60))
    # Inventory adjustments: new quantity counted and its value change.
    new_qty: Mapped[Optional[Decimal]] = mapped_column(DecimalString)

    txn: Mapped[Transaction] = relationship(back_populates="lines", foreign_keys=[txn_id])
    item: Mapped[Optional["Item"]] = relationship()  # noqa: F821
    account: Mapped[Optional["Account"]] = relationship()  # noqa: F821
    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    employee: Mapped[Optional["Employee"]] = relationship()  # noqa: F821
    tracking_class: Mapped[Optional["TrackingClass"]] = relationship()  # noqa: F821
    location: Mapped[Optional["Location"]] = relationship()  # noqa: F821
    billed_txn: Mapped[Optional[Transaction]] = relationship(foreign_keys=[billed_txn_id])

    @property
    def signed_cents(self) -> int:
        """Journal lines: debits positive, credits negative."""
        return -self.amount_cents if self.posting_type == "credit" else self.amount_cents

    @property
    def name_entity(self):
        return self.customer or self.vendor or self.employee


class TransactionLink(Base):
    """One transaction applied to another: a payment against an invoice, a
    deposit sweeping a payment out of Payments to deposit, an estimate
    converted into an invoice."""

    __tablename__ = "transaction_links"
    __table_args__ = (Index("ix_link_from", "from_txn_id"), Index("ix_link_to", "to_txn_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    from_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    to_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    # payment | credit | bill_payment | vendor_credit | deposit | refund |
    # estimate | po | delayed
    link_type: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    # A credit applied from inside a Receive Payment screen remembers that
    # payment, so deleting the payment also releases the credit.
    via_txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    from_txn: Mapped[Transaction] = relationship(foreign_keys=[from_txn_id], back_populates="links_out")
    to_txn: Mapped[Transaction] = relationship(foreign_keys=[to_txn_id], back_populates="links_in")


class TransactionTaxLine(Base):
    """Sales tax on a transaction, split by component rate (state, county, city)."""

    __tablename__ = "transaction_tax_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    tax_rate_id: Mapped[int] = mapped_column(ForeignKey("tax_rates.id"))
    agency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_agencies.id"))
    taxable_cents: Mapped[int] = mapped_column(Integer, default=0)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)

    txn: Mapped[Transaction] = relationship(back_populates="tax_lines")
    tax_rate: Mapped["TaxRate"] = relationship()  # noqa: F821


class LedgerEntry(Base):
    """A general-ledger posting. Debits are positive, credits negative; the
    entries of any one transaction sum to zero."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_le_account_date", "account_id", "date"),
        Index("ix_le_txn", "txn_id"),
        Index("ix_le_customer", "customer_id"),
        Index("ix_le_vendor", "vendor_id"),
        Index("ix_le_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    line_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transaction_lines.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("items.id"))
    class_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))
    tax_rate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_rates.id"))
    tax_agency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_agencies.id"))
    qty: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    memo: Mapped[Optional[str]] = mapped_column(Text)
    # "" not cleared, "C" cleared, "R" reconciled.
    cleared: Mapped[str] = mapped_column(String(1), default="")
    reconciliation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("reconciliations.id", ondelete="SET NULL"))
    # Entries written by the inventory engine (COGS) rather than the document.
    auto: Mapped[Optional[str]] = mapped_column(String(10))

    txn: Mapped[Transaction] = relationship(back_populates="entries")
    account: Mapped["Account"] = relationship()  # noqa: F821
    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    employee: Mapped[Optional["Employee"]] = relationship()  # noqa: F821
    item: Mapped[Optional["Item"]] = relationship()  # noqa: F821

    @property
    def debit_cents(self) -> int:
        return self.amount_cents if self.amount_cents > 0 else 0

    @property
    def credit_cents(self) -> int:
        return -self.amount_cents if self.amount_cents < 0 else 0


class NumberSequence(Base):
    """Next document number per type ('invoice', 'estimate', 'check:12')."""

    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40))
    prefix: Mapped[str] = mapped_column(String(20), default="")
    next_value: Mapped[int] = mapped_column(Integer, default=1001)
