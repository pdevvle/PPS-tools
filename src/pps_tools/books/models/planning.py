"""Recurring templates, budgets, time tracking, mileage and statements."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, DecimalString, utcnow


class RecurringTemplate(Base):
    __tablename__ = "recurring_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    txn_type: Mapped[str] = mapped_column(String(30))
    # scheduled: created automatically; reminder: listed for you to create;
    # unscheduled: a saved template you use on demand.
    mode: Mapped[str] = mapped_column(String(12), default="scheduled")
    interval: Mapped[str] = mapped_column(String(10), default="monthly")  # daily|weekly|monthly|yearly
    every: Mapped[int] = mapped_column(Integer, default=1)
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer)  # 0=Mon
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer)  # 1..28, 0 = last day
    month_of_year: Mapped[Optional[int]] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    max_occurrences: Mapped[Optional[int]] = mapped_column(Integer)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    next_date: Mapped[Optional[date]] = mapped_column(Date)
    days_in_advance: Mapped[int] = mapped_column(Integer, default=0)
    auto_send: Mapped[bool] = mapped_column(Boolean, default=False)
    autopay: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column()
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)  # year the fiscal year starts in
    # none | customer | class | location
    subdivide_by: Mapped[str] = mapped_column(String(10), default="none")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    lines: Mapped[list["BudgetLine"]] = relationship(back_populates="budget", cascade="all, delete-orphan")


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    __table_args__ = (Index("ix_budget_line", "budget_id", "account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    subdivision_id: Mapped[Optional[int]] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)  # 1..12, months from fiscal-year start
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)

    budget: Mapped[Budget] = relationship(back_populates="lines")


class TimeActivity(Base):
    __tablename__ = "time_activities"
    __table_args__ = (Index("ix_time_customer", "customer_id"), Index("ix_time_date", "date"))

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("items.id"))
    class_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[Optional[time]] = mapped_column(Time)
    end_time: Mapped[Optional[time]] = mapped_column(Time)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    billable: Mapped[bool] = mapped_column(Boolean, default=False)
    hourly_rate: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    billed_txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    employee: Mapped[Optional["Employee"]] = relationship()  # noqa: F821
    vendor: Mapped[Optional["Vendor"]] = relationship()  # noqa: F821
    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821
    item: Mapped[Optional["Item"]] = relationship()  # noqa: F821

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.minutes) / Decimal(60)).quantize(Decimal("0.01"))

    @property
    def worker_name(self) -> str:
        w = self.employee or self.vendor
        return w.display_name if w else ""

    @property
    def status(self) -> str:
        if not self.billable:
            return "Not billable"
        return "Billed" if self.billed_txn_id else "Billable"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    year: Mapped[Optional[int]] = mapped_column(Integer)
    make: Mapped[Optional[str]] = mapped_column(String(60))
    model: Mapped[Optional[str]] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MileageTrip(Base):
    __tablename__ = "mileage_trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id"))
    start_location: Mapped[Optional[str]] = mapped_column(String(200))
    end_location: Mapped[Optional[str]] = mapped_column(String(200))
    miles: Mapped[Decimal] = mapped_column(DecimalString)
    purpose: Mapped[str] = mapped_column(String(20), default="business")  # business|personal
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    vehicle: Mapped[Optional[Vehicle]] = relationship()
    customer: Mapped[Optional["Customer"]] = relationship()  # noqa: F821


class Statement(Base):
    """A customer statement that was generated, emailed or printed."""

    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    statement_date: Mapped[date] = mapped_column(Date)
    # balance_forward | open_item | transaction
    kind: Mapped[str] = mapped_column(String(16), default="balance_forward")
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    customer: Mapped["Customer"] = relationship()  # noqa: F821
