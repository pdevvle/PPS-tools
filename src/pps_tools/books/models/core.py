"""Company settings, users, audit trail, attachments, email outbox, Stripe
event log, saved reports and API tokens."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, utcnow


class Company(Base):
    """The one company this database keeps books for (row id 1)."""

    __tablename__ = "company"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    ein: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(320))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    website: Mapped[Optional[str]] = mapped_column(String(300))
    address_line1: Mapped[Optional[str]] = mapped_column(String(200))
    address_line2: Mapped[Optional[str]] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20))
    country: Mapped[Optional[str]] = mapped_column(String(60), default="US")
    industry: Mapped[Optional[str]] = mapped_column(String(120))
    # sole_prop | partnership | s_corp | c_corp | llc | nonprofit
    entity_type: Mapped[str] = mapped_column(String(20), default="llc")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)
    accounting_method: Mapped[str] = mapped_column(String(10), default="accrual")
    home_currency: Mapped[str] = mapped_column(String(3), default="USD")
    multicurrency: Mapped[bool] = mapped_column(Boolean, default=False)
    closing_date: Mapped[Optional[date]] = mapped_column(Date)
    closing_password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    logo_attachment_id: Mapped[Optional[int]] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    # Everything else: sales form defaults, numbering, reminders, Stripe
    # options, invoice template... read through services.prefs.
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    def address_lines(self) -> list[str]:
        lines = [p for p in (self.address_line1, self.address_line2) if p]
        locality = " ".join(p for p in [", ".join(p for p in (self.city, self.state) if p),
                                         self.postal_code] if p)
        if locality:
            lines.append(locality)
        return lines


ROLES = {
    "admin": "Company admin",
    "accountant": "Accountant",
    "standard": "Standard (all access)",
    "sales": "Standard (customers & sales)",
    "purchases": "Standard (vendors & purchases)",
    "reports": "Reports only",
    "time": "Time tracking only",
    "viewer": "View only",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="standard")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_object", "object_type", "object_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    user_name: Mapped[Optional[str]] = mapped_column(String(120))
    # create | update | delete | void | login | logout | settings | close_books | ...
    action: Mapped[str] = mapped_column(String(20))
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[Optional[int]] = mapped_column(Integer)
    txn_type: Mapped[Optional[str]] = mapped_column(String(30))
    txn_date: Mapped[Optional[date]] = mapped_column(Date)
    amount_cents: Mapped[Optional[int]] = mapped_column(Integer)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(500), default="")
    before: Mapped[Optional[dict]] = mapped_column(JSON)
    after: Mapped[Optional[dict]] = mapped_column(JSON)
    ip: Mapped[Optional[str]] = mapped_column(String(64))


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    note: Mapped[Optional[str]] = mapped_column(Text)
    # Receipt capture: inbox | reviewed | used
    receipt_status: Mapped[Optional[str]] = mapped_column(String(10))
    extracted: Mapped[Optional[dict]] = mapped_column(JSON)
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    links: Mapped[list["AttachmentLink"]] = relationship(back_populates="attachment",
                                                        cascade="all, delete-orphan")


class AttachmentLink(Base):
    __tablename__ = "attachment_links"
    __table_args__ = (Index("ix_attach_object", "object_type", "object_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"))
    object_type: Mapped[str] = mapped_column(String(30))  # transaction | customer | vendor | item ...
    object_id: Mapped[int] = mapped_column(Integer)
    include_in_email: Mapped[bool] = mapped_column(Boolean, default=False)

    attachment: Mapped[Attachment] = relationship(back_populates="links")


class EmailMessage(Base):
    """Outbox. Without SMTP configured, messages stay here as 'logged'."""

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    to_addr: Mapped[str] = mapped_column(String(1000))
    cc_addr: Mapped[Optional[str]] = mapped_column(String(1000))
    bcc_addr: Mapped[Optional[str]] = mapped_column(String(1000))
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[Optional[str]] = mapped_column(Text)
    attachment_names: Mapped[list] = mapped_column(JSON, default=list)
    object_type: Mapped[Optional[str]] = mapped_column(String(30))
    object_id: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued|sent|failed|logged
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column()


class StripeEvent(Base):
    """Every webhook event we've seen, so a redelivery is a no-op."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(80))
    livemode: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="received")  # processed|ignored|error
    error: Mapped[Optional[str]] = mapped_column(Text)
    txn_id: Mapped[Optional[int]] = mapped_column(Integer)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)


class SavedReport(Base):
    __tablename__ = "saved_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    report_key: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    shared: Mapped[bool] = mapped_column(Boolean, default=True)
    # Email the report on a schedule: none | daily | weekly | monthly
    email_schedule: Mapped[str] = mapped_column(String(10), default="none")
    email_to: Mapped[Optional[str]] = mapped_column(String(500))
    last_emailed_at: Mapped[Optional[datetime]] = mapped_column()
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    last_used_at: Mapped[Optional[datetime]] = mapped_column()
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship()


class CustomFieldDef(Base):
    """Custom fields on sales and purchase forms (QBO 'Custom fields')."""

    __tablename__ = "custom_field_defs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # Comma-separated transaction types it appears on: "invoice,estimate".
    applies_to: Mapped[str] = mapped_column(String(200), default="invoice,estimate,sales_receipt")
    print_on_form: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_field_defs.id", ondelete="CASCADE"))
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(Text, default="")

    field: Mapped[CustomFieldDef] = relationship()
