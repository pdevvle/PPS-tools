"""Outgoing email: invoices, estimates, receipts, statements, reminders.

Everything goes through the outbox table. With SMTP configured (environment
or Settings → Email) messages are sent right away; without it they're kept
as 'logged' so nothing is lost and you can see exactly what would have gone.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from sqlalchemy.orm import Session

from pps_tools.books.db import utcnow
from pps_tools.books.models import Company, EmailMessage, Statement, Transaction, User
from pps_tools.books.money import fmt
from pps_tools.books.services import prefs
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import ValidationError


@dataclass
class SmtpSettings:
    host: Optional[str]
    port: int
    user: Optional[str]
    password: Optional[str]
    sender: Optional[str]
    tls: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


def smtp_settings(s: Session, config=None) -> SmtpSettings:
    stored = prefs.get(s, "smtp") or {}
    host = getattr(config, "smtp_host", None) or stored.get("host")
    if getattr(config, "smtp_host", None):
        return SmtpSettings(config.smtp_host, config.smtp_port, config.smtp_user, config.smtp_password,
                            config.smtp_from or config.smtp_user, config.smtp_tls)
    return SmtpSettings(host, int(stored.get("port") or 587), stored.get("user"), stored.get("password"),
                        stored.get("sender") or stored.get("user"), bool(stored.get("tls", True)))


def _addresses(text: Optional[str]) -> list[str]:
    return [a.strip() for a in (text or "").replace(";", ",").split(",") if a.strip()]


def send(s: Session, config, to: str, subject: str, body: str, cc: Optional[str] = None, bcc: Optional[str] = None,
         attachments: Optional[list[tuple[str, bytes, str]]] = None, object_type: Optional[str] = None,
         object_id: Optional[int] = None, reply_to: Optional[str] = None, html: Optional[str] = None) -> EmailMessage:
    recipients = _addresses(to)
    if not recipients:
        raise ValidationError("Add at least one email address.")
    for addr in recipients + _addresses(cc) + _addresses(bcc):
        if "@" not in addr or " " in addr:
            raise ValidationError(f"“{addr}” doesn't look like an email address.")
    msg_row = EmailMessage(to_addr=", ".join(recipients), cc_addr=cc or None, bcc_addr=bcc or None, subject=subject,
                           body_text=body, body_html=html, attachment_names=[a[0] for a in attachments or []],
                           object_type=object_type, object_id=object_id)
    s.add(msg_row)
    smtp = smtp_settings(s, config)
    company = s.get(Company, 1)
    if not smtp.configured or getattr(config, "testing", False):
        msg_row.status = "logged"
        s.flush()
        return msg_row
    mime = MimeMessage()
    mime["From"] = formataddr((company.name if company else "", smtp.sender))
    mime["To"] = ", ".join(recipients)
    if cc:
        mime["Cc"] = cc
    mime["Subject"] = subject
    mime["Message-ID"] = make_msgid()
    if reply_to or (company and company.email):
        mime["Reply-To"] = reply_to or company.email
    mime.set_content(body)
    if html:
        mime.add_alternative(html, subtype="html")
    for name, data, mimetype in attachments or []:
        maintype, _, subtype = (mimetype or "application/octet-stream").partition("/")
        mime.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    try:
        if smtp.port == 465:
            server = smtplib.SMTP_SSL(smtp.host, smtp.port, context=ssl.create_default_context(), timeout=30)
        else:
            server = smtplib.SMTP(smtp.host, smtp.port, timeout=30)
            if smtp.tls:
                server.starttls(context=ssl.create_default_context())
        with server:
            if smtp.user and smtp.password:
                server.login(smtp.user, smtp.password)
            server.send_message(mime, to_addrs=recipients + _addresses(cc) + _addresses(bcc))
        msg_row.status = "sent"
        msg_row.sent_at = utcnow()
    except (OSError, smtplib.SMTPException) as exc:
        msg_row.status = "failed"
        msg_row.error = str(exc)[:1000]
        s.flush()
        raise ValidationError(f"The email couldn't be sent: {exc}. It's saved in the outbox.")
    s.flush()
    return msg_row


def fill(template: str, **values) -> str:
    """'{customer}'-style placeholders; unknown ones are left alone."""
    class Missing(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(Missing(values))
    except (ValueError, IndexError):
        return template


def _link(base_url: str, txn: Transaction) -> str:
    return f"{base_url}/p/{tx.ensure_token(txn)}"


def draft_for(s: Session, txn: Transaction, base_url: str, config=None) -> dict:
    company = s.get(Company, 1)
    kind = {"invoice": "invoice", "estimate": "estimate", "sales_receipt": "receipt", "payment": "receipt",
            "credit_memo": "receipt", "refund_receipt": "receipt", "purchase_order": "po"}.get(txn.type, "invoice")
    link = _link(base_url, txn) if txn.info.customer_facing else ""
    ctx = {"customer": (txn.customer.display_name if txn.customer else ""), "vendor": txn.vendor.display_name
           if txn.vendor else "", "company": company.name, "number": txn.number or "",
           "amount": fmt(txn.balance_cents if txn.type == "invoice" else txn.total_cents),
           "due_date": f"{txn.due_date:%B %d, %Y}" if txn.due_date else "", "link": link}
    to = txn.email_to or (txn.customer.email if txn.customer else "") or (txn.vendor.email if txn.vendor else "") or ""
    cc = txn.email_cc or (txn.customer.cc_email if txn.customer else None)
    bcc = txn.email_bcc or (txn.customer.bcc_email if txn.customer else None)
    return {"to": to, "cc": cc, "bcc": bcc,
            "subject": fill(prefs.get(s, f"email_{kind}_subject") or "", **ctx),
            "body": fill(prefs.get(s, f"email_{kind}_body") or "", **ctx), "link": link,
            "smtp": smtp_settings(s, config).configured}


def send_transaction(s: Session, config, txn: Transaction, to: str, base_url: str, user: Optional[User] = None,
                     cc: Optional[str] = None, bcc: Optional[str] = None, subject: str = "", body: str = "",
                     attach_pdf: bool = True) -> EmailMessage:
    draft = draft_for(s, txn, base_url, config)
    attachments = []
    if attach_pdf:
        from pps_tools.books.services import pdf as pdf_service

        attachments.append((pdf_service.filename_for(txn), pdf_service.render_transaction(s, txn, base_url=base_url),
                            "application/pdf"))
    msg = send(s, config, to or draft["to"], subject or draft["subject"], body or draft["body"], cc=cc, bcc=bcc,
               attachments=attachments, object_type="transaction", object_id=txn.id)
    txn.sent_at = utcnow()
    if to and txn.type in ("invoice", "estimate", "sales_receipt", "credit_memo", "purchase_order"):
        txn.email_to = to
    return msg


def send_statement(s: Session, config, st: Statement, base_url: str, user: Optional[User] = None) -> EmailMessage:
    from pps_tools.books.services import pdf as pdf_service

    company = s.get(Company, 1)
    c = st.customer
    if not st.public_token:
        st.public_token = tx.new_token()
    link = f"{base_url}/portal/{c.portal_token}" if c.portal_token else f"{base_url}/s/{st.public_token}"
    ctx = {"customer": c.display_name, "company": company.name, "amount": fmt(st.balance_cents), "link": link}
    data = pdf_service.render_statements(s, [st], base_url=base_url)
    msg = send(s, config, c.email, fill(prefs.get(s, "email_statement_subject"), **ctx),
               fill(prefs.get(s, "email_statement_body"), **ctx), cc=c.cc_email,
               attachments=[(f"statement-{st.statement_date:%Y-%m-%d}.pdf", data, "application/pdf")],
               object_type="statement", object_id=st.id)
    st.sent_at = utcnow()
    return msg


def send_reminder(s: Session, config, invoice: Transaction, base_url: str) -> Optional[EmailMessage]:
    to = invoice.email_to or (invoice.customer.email if invoice.customer else None)
    if not to:
        return None
    company = s.get(Company, 1)
    ctx = {"customer": invoice.customer.display_name, "company": company.name, "number": invoice.number or "",
           "amount": fmt(invoice.balance_cents), "due_date": f"{invoice.due_date:%B %d, %Y}" if invoice.due_date else "",
           "link": _link(base_url, invoice)}
    msg = send(s, config, to, fill(prefs.get(s, "email_reminder_subject"), **ctx),
               fill(prefs.get(s, "email_reminder_body"), **ctx), object_type="transaction", object_id=invoice.id)
    invoice.last_reminder_at = utcnow()
    return msg
