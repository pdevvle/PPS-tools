"""Names and lists: customers, vendors, employees, products & services,
terms, payment methods, classes, locations, tags and sales tax."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, DecimalString, utcnow


class AddressMixin:
    """Billing address columns shared by customers, vendors and employees."""

    bill_line1: Mapped[Optional[str]] = mapped_column(String(200))
    bill_line2: Mapped[Optional[str]] = mapped_column(String(200))
    bill_city: Mapped[Optional[str]] = mapped_column(String(100))
    bill_state: Mapped[Optional[str]] = mapped_column(String(50))
    bill_postal: Mapped[Optional[str]] = mapped_column(String(20))
    bill_country: Mapped[Optional[str]] = mapped_column(String(60))

    def billing_address(self) -> str:
        return format_address(self.bill_line1, self.bill_line2, self.bill_city,
                              self.bill_state, self.bill_postal, self.bill_country)


def format_address(line1, line2, city, state, postal, country) -> str:
    parts = [p for p in (line1, line2) if p]
    locality = " ".join(p for p in [", ".join(p for p in (city, state) if p), postal] if p)
    if locality:
        parts.append(locality)
    if country and country.upper() not in ("US", "USA", "UNITED STATES"):
        parts.append(country)
    return "\n".join(parts)


class PersonNameMixin:
    title: Mapped[Optional[str]] = mapped_column(String(20))
    first_name: Mapped[Optional[str]] = mapped_column(String(80))
    middle_name: Mapped[Optional[str]] = mapped_column(String(80))
    last_name: Mapped[Optional[str]] = mapped_column(String(80))
    suffix: Mapped[Optional[str]] = mapped_column(String(20))
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(320))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    mobile: Mapped[Optional[str]] = mapped_column(String(40))
    fax: Mapped[Optional[str]] = mapped_column(String(40))
    website: Mapped[Optional[str]] = mapped_column(String(300))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    @property
    def contact_name(self) -> str:
        return " ".join(p for p in (self.title, self.first_name, self.middle_name,
                                    self.last_name, self.suffix) if p)


class Terms(Base):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    # "days": due N days after the invoice date. "day_of_month": due on a set day.
    kind: Mapped[str] = mapped_column(String(20), default="days")
    due_days: Mapped[int] = mapped_column(Integer, default=0)
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer)
    # Day-of-month terms: if issued within this many days of the due day, push a month.
    cutoff_days: Mapped[Optional[int]] = mapped_column(Integer)
    discount_pct: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    discount_days: Mapped[Optional[int]] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="other")  # cash|check|card|ach|other
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrackingClass(Base):
    """QBO 'Class' — a second dimension for P&L by department or line of business."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("classes.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["TrackingClass"]] = relationship(remote_side="TrackingClass.id")

    @property
    def full_name(self) -> str:
        return f"{self.parent.full_name}:{self.name}" if self.parent else self.name


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["Location"]] = relationship(remote_side="Location.id")

    @property
    def full_name(self) -> str:
        return f"{self.parent.full_name}:{self.name}" if self.parent else self.name


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    group_name: Mapped[Optional[str]] = mapped_column(String(80))


class Customer(PersonNameMixin, AddressMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), unique=True)
    cc_email: Mapped[Optional[str]] = mapped_column(String(320))
    bcc_email: Mapped[Optional[str]] = mapped_column(String(320))
    ship_same_as_bill: Mapped[bool] = mapped_column(Boolean, default=True)
    ship_line1: Mapped[Optional[str]] = mapped_column(String(200))
    ship_line2: Mapped[Optional[str]] = mapped_column(String(200))
    ship_city: Mapped[Optional[str]] = mapped_column(String(100))
    ship_state: Mapped[Optional[str]] = mapped_column(String(50))
    ship_postal: Mapped[Optional[str]] = mapped_column(String(20))
    ship_country: Mapped[Optional[str]] = mapped_column(String(60))
    terms_id: Mapped[Optional[int]] = mapped_column(ForeignKey("terms.id"))
    payment_method_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_methods.id"))
    preferred_delivery: Mapped[str] = mapped_column(String(10), default="email")  # email|print|none
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    tax_exemption_reason: Mapped[Optional[str]] = mapped_column(String(120))
    resale_number: Mapped[Optional[str]] = mapped_column(String(60))
    default_tax_rate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_rates.id"))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    bill_with_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Projects are sub-customers flagged as projects, as in QBO.
    is_project: Mapped[bool] = mapped_column(Boolean, default=False)
    project_status: Mapped[Optional[str]] = mapped_column(String(20))
    project_start: Mapped[Optional[date]] = mapped_column(Date)
    project_end: Mapped[Optional[date]] = mapped_column(Date)
    project_description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Stripe
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    stripe_payment_method_id: Mapped[Optional[str]] = mapped_column(String(64))
    card_brand: Mapped[Optional[str]] = mapped_column(String(20))
    card_last4: Mapped[Optional[str]] = mapped_column(String(4))
    autopay: Mapped[bool] = mapped_column(Boolean, default=False)
    # Customer portal link
    portal_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    terms: Mapped[Optional[Terms]] = relationship()
    payment_method: Mapped[Optional[PaymentMethod]] = relationship()
    parent: Mapped[Optional["Customer"]] = relationship(remote_side="Customer.id", back_populates="children")
    children: Mapped[list["Customer"]] = relationship(back_populates="parent")
    default_tax_rate: Mapped[Optional["TaxRate"]] = relationship()

    @property
    def full_name(self) -> str:
        return f"{self.parent.full_name}:{self.display_name}" if self.parent else self.display_name

    def shipping_address(self) -> str:
        if self.ship_same_as_bill:
            return self.billing_address()
        return format_address(self.ship_line1, self.ship_line2, self.ship_city,
                              self.ship_state, self.ship_postal, self.ship_country)


class Vendor(PersonNameMixin, AddressMixin, Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), unique=True)
    cc_email: Mapped[Optional[str]] = mapped_column(String(320))
    terms_id: Mapped[Optional[int]] = mapped_column(ForeignKey("terms.id"))
    account_number: Mapped[Optional[str]] = mapped_column(String(60))
    tax_id: Mapped[Optional[str]] = mapped_column(String(20))
    track_1099: Mapped[bool] = mapped_column(Boolean, default=False)
    w9_on_file: Mapped[bool] = mapped_column(Boolean, default=False)
    default_expense_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    terms: Mapped[Optional[Terms]] = relationship()
    default_expense_account: Mapped[Optional["Account"]] = relationship()  # noqa: F821

    @property
    def full_name(self) -> str:
        return self.display_name

    @property
    def masked_tax_id(self) -> str:
        if not self.tax_id:
            return ""
        digits = "".join(ch for ch in self.tax_id if ch.isdigit())
        return f"•••••{digits[-4:]}" if len(digits) >= 4 else "•••"


class Employee(PersonNameMixin, AddressMixin, Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), unique=True)
    employee_number: Mapped[Optional[str]] = mapped_column(String(40))
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    release_date: Mapped[Optional[date]] = mapped_column(Date)
    billable_rate: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    cost_rate: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    ssn_last4: Mapped[Optional[str]] = mapped_column(String(4))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def full_name(self) -> str:
        return self.display_name


class ItemCategory(Base):
    __tablename__ = "item_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("item_categories.id"))

    parent: Mapped[Optional["ItemCategory"]] = relationship(remote_side="ItemCategory.id")

    @property
    def full_name(self) -> str:
        return f"{self.parent.full_name}:{self.name}" if self.parent else self.name


ITEM_TYPES = {
    "service": "Service",
    "non_inventory": "Non-inventory",
    "inventory": "Inventory",
    "bundle": "Bundle",
}


class Item(Base):
    """A product or service (QBO 'Products and services')."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    sku: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    type: Mapped[str] = mapped_column(String(20), default="service")
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("item_categories.id"))
    unit: Mapped[Optional[str]] = mapped_column(String(20))
    description: Mapped[Optional[str]] = mapped_column(Text)
    sales_price: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    income_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    purchase_description: Mapped[Optional[str]] = mapped_column(Text)
    cost: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    expense_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    preferred_vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"))
    asset_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    # Maintained by the FIFO engine for inventory items.
    qty_on_hand: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    inventory_value_cents: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[Optional[Decimal]] = mapped_column(DecimalString)
    inventory_start_date: Mapped[Optional[date]] = mapped_column(Date)
    show_bundle_components: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    category: Mapped[Optional[ItemCategory]] = relationship()
    income_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[income_account_id])  # noqa: F821
    expense_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[expense_account_id])  # noqa: F821
    asset_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[asset_account_id])  # noqa: F821
    preferred_vendor: Mapped[Optional[Vendor]] = relationship()
    components: Mapped[list["BundleComponent"]] = relationship(
        foreign_keys="BundleComponent.bundle_id", cascade="all, delete-orphan",
        order_by="BundleComponent.position")

    @property
    def type_label(self) -> str:
        return ITEM_TYPES.get(self.type, self.type)

    @property
    def is_inventory(self) -> bool:
        return self.type == "inventory"

    @property
    def low_stock(self) -> bool:
        return (self.is_inventory and self.reorder_point is not None
                and (self.qty_on_hand or 0) <= self.reorder_point)


class BundleComponent(Base):
    __tablename__ = "bundle_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(1))
    position: Mapped[int] = mapped_column(Integer, default=0)

    item: Mapped[Item] = relationship(foreign_keys=[item_id])


class TaxAgency(Base):
    __tablename__ = "tax_agencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    registration_number: Mapped[Optional[str]] = mapped_column(String(60))
    filing_frequency: Mapped[str] = mapped_column(String(20), default="quarterly")  # monthly|quarterly|annually
    reporting_method: Mapped[str] = mapped_column(String(10), default="accrual")  # accrual|cash
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


tax_rate_components = Table(
    "tax_rate_components",
    Base.metadata,
    Column("combined_id", ForeignKey("tax_rates.id", ondelete="CASCADE"), primary_key=True),
    Column("component_id", ForeignKey("tax_rates.id"), primary_key=True),
)


class TaxRate(Base):
    """A single agency rate, or a combined rate made of several components."""

    __tablename__ = "tax_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(200))
    agency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tax_agencies.id"))
    rate: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))  # percent, e.g. 6.5
    is_combined: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    agency: Mapped[Optional[TaxAgency]] = relationship()
    components: Mapped[list["TaxRate"]] = relationship(
        secondary=tax_rate_components,
        primaryjoin=lambda: TaxRate.id == tax_rate_components.c.combined_id,
        secondaryjoin=lambda: TaxRate.id == tax_rate_components.c.component_id,
        order_by=lambda: TaxRate.name,
    )

    @property
    def effective_rate(self) -> Decimal:
        if self.is_combined:
            return sum((c.rate for c in self.components), Decimal(0))
        return self.rate

    def leaf_rates(self) -> list["TaxRate"]:
        return list(self.components) if self.is_combined else [self]
