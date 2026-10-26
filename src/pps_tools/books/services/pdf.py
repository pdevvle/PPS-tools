"""PDFs: invoices and other sales forms, purchase orders, statements, checks."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import (Attachment, Company, CustomFieldDef, CustomFieldValue, Statement, Transaction)
from pps_tools.books.money import amount_in_words, fmt, fmt_qty, fmt_rate
from pps_tools.books.services import prefs
from pps_tools.books.services import transactions as tx

TITLES = {"invoice": "Invoice", "estimate": "Estimate", "sales_receipt": "Sales Receipt", "credit_memo": "Credit Memo",
          "refund_receipt": "Refund Receipt", "payment": "Payment Receipt", "purchase_order": "Purchase Order",
          "delayed_charge": "Delayed Charge", "delayed_credit": "Delayed Credit", "bill_payment": "Payment",
          "customer_refund": "Refund"}


def filename_for(txn: Transaction) -> str:
    title = TITLES.get(txn.type, txn.info.label)
    num = re.sub(r"[^A-Za-z0-9-]+", "", txn.number or str(txn.id))
    return f"{title.replace(' ', '-')}-{num}.pdf"


def _esc(text) -> str:
    return (str(text or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


class _Styles:
    def __init__(self, accent: str, font: str = "Helvetica"):
        self.accent = colors.HexColor(accent) if accent.startswith("#") else colors.HexColor("#1d7f3a")
        bold = "Helvetica-Bold" if font.startswith("Helvetica") else f"{font}-Bold"
        self.font, self.bold = "Helvetica", "Helvetica-Bold"
        self.body = ParagraphStyle("body", fontName=self.font, fontSize=9.5, leading=12.5)
        self.small = ParagraphStyle("small", fontName=self.font, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
        self.company = ParagraphStyle("company", fontName=self.bold, fontSize=13, leading=16)
        self.title = ParagraphStyle("title", fontName=self.bold, fontSize=22, leading=26, textColor=self.accent,
                                    alignment=TA_RIGHT)
        self.label = ParagraphStyle("label", fontName=self.bold, fontSize=8, leading=10, textColor=self.accent)
        self.right = ParagraphStyle("right", parent=self.body, alignment=TA_RIGHT)
        self.cell = ParagraphStyle("cell", fontName=self.font, fontSize=9, leading=11.5)
        self.cellb = ParagraphStyle("cellb", fontName=self.bold, fontSize=9, leading=11.5)


def _logo(s: Session, company: Company, config=None) -> Optional[Image]:
    if not company.logo_attachment_id or not prefs.get(s, "invoice_show_logo"):
        return None
    att = s.get(Attachment, company.logo_attachment_id)
    if att is None:
        return None
    try:
        from pps_tools.books.web.core import config as current_config

        cfg = config or current_config()
        path = (cfg.data_dir / att.storage_path)
        img = Image(str(path))
        ratio = img.imageWidth / float(img.imageHeight or 1)
        h = 0.75 * inch
        w = min(h * ratio, 2.2 * inch)
        img.drawWidth, img.drawHeight = w, w / ratio
        return img
    except Exception:  # unreadable image or no app context: skip the logo
        return None


def _header(s: Session, company: Company, st: _Styles, title: str, meta: list[tuple[str, str]], config=None):
    left = []
    logo = _logo(s, company, config)
    if logo is not None:
        left.append(logo)
        left.append(Spacer(1, 4))
    left.append(Paragraph(_esc(company.legal_name or company.name), st.company))
    addr = "<br/>".join(_esc(x) for x in company.address_lines())
    contact = " · ".join(_esc(x) for x in (company.phone, company.email, company.website) if x)
    left.append(Paragraph(addr + ("<br/>" + contact if contact else ""), st.small))
    right = [Paragraph(title.upper(), st.title), Spacer(1, 4)]
    meta_rows = [[Paragraph(f"<b>{_esc(k)}</b>", st.small), Paragraph(_esc(v), st.body)] for k, v in meta if v]
    if meta_rows:
        mt = Table(meta_rows, colWidths=[1.0 * inch, 1.4 * inch], hAlign="RIGHT")
        mt.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
        right.append(mt)
    t = Table([[left, right]], colWidths=[3.9 * inch, 3.4 * inch])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _address_row(st: _Styles, blocks: list[tuple[str, str]]):
    cells = []
    for label, text in blocks:
        if text:
            cells.append([Paragraph(label.upper(), st.label), Paragraph(_esc(text), st.body)])
    if not cells:
        return Spacer(1, 1)
    width = 7.3 * inch / max(len(cells), 1)
    t = Table([cells], colWidths=[width] * len(cells))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _lines_table(txn: Transaction, st: _Styles, show_service_date: bool, purchase: bool = False):
    show_date = show_service_date and any(ln.service_date for ln in txn.lines)
    head = (["Date"] if show_date else []) + ["Product/Service", "Description", "Qty", "Rate", "Amount"]
    rows = [[Paragraph(f"<b>{h}</b>", st.cellb) if i < len(head) - 3 else Paragraph(f"<b>{h}</b>",
             ParagraphStyle("hr", parent=st.cellb, alignment=TA_RIGHT)) for i, h in enumerate(head)]]
    span_rows = []
    for ln in txn.lines:
        if ln.kind == "description":
            row = ([""] if show_date else []) + [Paragraph(f"<b>{_esc(ln.description)}</b>", st.cell), "", "", "", ""]
            rows.append(row)
            span_rows.append(len(rows) - 1)
            continue
        if ln.kind not in ("item", "account"):
            continue
        name = ln.item.name if ln.item else (ln.account.name if (purchase and ln.account) else "")
        row = ([ln.service_date.strftime("%m/%d/%Y") if ln.service_date else ""] if show_date else []) + [
            Paragraph(_esc(name), st.cellb if name else st.cell), Paragraph(_esc(ln.description or ""), st.cell),
            fmt_qty(ln.qty) if ln.qty is not None else "", fmt_rate(ln.rate) if ln.rate is not None else "",
            fmt(ln.amount_cents)]
        rows.append(row)
    widths = ([0.8 * inch] if show_date else []) + [1.6 * inch, (2.9 if show_date else 3.7) * inch, 0.6 * inch,
                                                    0.8 * inch, 0.9 * inch]
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), 1, st.accent), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("ALIGN", (-3, 0), (-1, -1), "RIGHT"), ("FONT", (0, 1), (-1, -1), st.font, 9),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd"))]
    for r in span_rows:
        start = 1 if show_date else 0
        style.append(("SPAN", (start, r), (-1, r)))
    t.setStyle(TableStyle(style))
    return t


def _totals(txn: Transaction, st: _Styles):
    rows = [("Subtotal", fmt(txn.subtotal_cents))]
    if txn.discount_cents:
        rows.append(("Discount", f"-{fmt(txn.discount_cents)}"))
    if txn.info.has_tax and (txn.tax_cents or txn.tax_rate_id):
        label = f"Tax ({txn.tax_rate.name})" if txn.tax_rate else "Tax"
        rows.append((label, fmt(txn.tax_cents)))
    if txn.shipping_cents:
        rows.append(("Shipping", fmt(txn.shipping_cents)))
    rows.append(("TOTAL", fmt(txn.total_cents)))
    if txn.type == "invoice":
        paid = txn.total_cents - txn.balance_cents
        if paid:
            rows.append(("Payment / credit", f"-{fmt(paid)}"))
        rows.append(("BALANCE DUE", fmt(txn.balance_cents)))
    data = [[Paragraph(_esc(k), st.cellb if k.isupper() else st.cell), v] for k, v in rows]
    t = Table(data, colWidths=[1.8 * inch, 1.2 * inch], hAlign="RIGHT")
    style = [("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONT", (1, 0), (1, -1), st.font, 9.5),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i, (k, _) in enumerate(rows):
        if k == "TOTAL":
            style += [("LINEABOVE", (0, i), (-1, i), 0.75, colors.black), ("FONT", (1, i), (1, i), st.bold, 10)]
        if k == "BALANCE DUE":
            style += [("FONT", (1, i), (1, i), st.bold, 12), ("TEXTCOLOR", (0, i), (-1, i), st.accent),
                      ("LINEABOVE", (0, i), (-1, i), 0.75, st.accent)]
    t.setStyle(TableStyle(style))
    return t


def transaction_story(s: Session, txn: Transaction, base_url: str = "", config=None) -> list:
    company = s.get(Company, 1)
    st = _Styles(prefs.get(s, "invoice_accent_color") or "#1d7f3a")
    title = TITLES.get(txn.type, txn.info.label)
    number_label = {"purchase_order": "P.O. no.", "payment": "Reference"}.get(txn.type, f"{txn.info.label} no.")
    meta = [(number_label, txn.number or txn.ref_no or str(txn.id)), ("Date", txn.date.strftime("%m/%d/%Y"))]
    if txn.type == "invoice":
        meta += [("Due date", txn.due_date.strftime("%m/%d/%Y") if txn.due_date else ""),
                 ("Terms", txn.terms.name if txn.terms else "")]
    if txn.type == "estimate" and txn.expiration_date:
        meta.append(("Expires", txn.expiration_date.strftime("%m/%d/%Y")))
    if txn.type in ("sales_receipt", "payment", "refund_receipt") and txn.payment_method:
        meta.append(("Payment method", txn.payment_method.name))
    if txn.ref_no and txn.type != "payment":
        meta.append(("Reference", txn.ref_no))
    story = [_header(s, company, st, title, meta, config), Spacer(1, 16)]
    if txn.voided:
        story += [Paragraph("<font color='#c4320a' size='16'><b>VOID</b></font>", st.body), Spacer(1, 6)]
    if txn.type == "purchase_order":
        vendor = txn.vendor
        story.append(_address_row(st, [("Vendor", txn.billing_address or (vendor.display_name + "\n" + vendor.billing_address()
                                                                           if vendor else "")),
                                       ("Ship to", txn.shipping_address or "")]))
    else:
        bill_to = txn.billing_address or (txn.customer.display_name if txn.customer else txn.entity_name)
        blocks = [("Bill to" if txn.type in ("invoice", "estimate") else "Customer", bill_to)]
        if txn.shipping_address and txn.type in ("invoice", "estimate", "sales_receipt"):
            blocks.append(("Ship to", txn.shipping_address))
        ship = " · ".join(x for x in ((f"Shipped {txn.ship_date:%m/%d/%Y}" if txn.ship_date else ""),
                                       (f"Via {txn.ship_via}" if txn.ship_via else ""),
                                       (f"Tracking {txn.tracking_no}" if txn.tracking_no else "")) if x)
        if ship:
            blocks.append(("Shipping", ship))
        story.append(_address_row(st, blocks))
    # custom fields that print
    fields = s.execute(select(CustomFieldDef.name, CustomFieldValue.value).join(
        CustomFieldValue, CustomFieldValue.field_id == CustomFieldDef.id).where(
        CustomFieldValue.txn_id == txn.id, CustomFieldDef.print_on_form.is_(True))).all()
    if fields:
        story += [Spacer(1, 6), Paragraph(" &nbsp;·&nbsp; ".join(f"<b>{_esc(n)}:</b> {_esc(v)}" for n, v in fields if v),
                                          st.small)]
    story.append(Spacer(1, 14))
    if txn.type == "payment":
        rows = [["Invoice", "Date", "Original amount", "Payment"]]
        for link in txn.links_out:
            if link.link_type == "payment":
                inv = link.to_txn
                rows.append([f"#{inv.number}", inv.date.strftime("%m/%d/%Y"), fmt(inv.total_cents), fmt(link.amount_cents)])
        t = Table(rows, colWidths=[2 * inch, 1.5 * inch, 1.8 * inch, 1.8 * inch])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1, st.accent), ("FONT", (0, 0), (-1, 0), st.bold, 9),
                               ("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
        story += [t, Spacer(1, 12), Paragraph(f"<b>Amount received: {fmt(txn.total_cents)}</b>", st.right)]
        if txn.balance_cents:
            story.append(Paragraph(f"Unapplied credit: {fmt(txn.balance_cents)}", st.right))
    else:
        story.append(_lines_table(txn, st, bool(prefs.get(s, "show_service_date")), purchase=txn.type == "purchase_order"))
        story += [Spacer(1, 10), _totals(txn, st)]
    if txn.message:
        story += [Spacer(1, 14), Paragraph(_esc(txn.message), st.body)]
    if txn.type == "invoice" and not txn.voided and txn.balance_cents > 0 and base_url and \
            prefs.get(s, "invoice_show_payment_link") and (txn.allow_online_card or txn.allow_online_ach) and \
            prefs.get(s, "stripe_enabled"):
        link = f"{base_url}/p/{tx.ensure_token(txn)}"
        story += [Spacer(1, 14), KeepTogether([
            Paragraph("PAY ONLINE", st.label),
            Paragraph(f"<link href='{_esc(link)}'><u>{_esc(link)}</u></link> — card or bank transfer, secured by Stripe.",
                      st.body)])]
    footer = prefs.get(s, "invoice_footer")
    if footer:
        story += [Spacer(1, 18), Paragraph(_esc(footer), st.small)]
    return story


def _build(story: list, title: str, author: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=title, author=author)

    def page_number(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return buf.getvalue()


def render_transaction(s: Session, txn: Transaction, base_url: str = "", config=None) -> bytes:
    company = s.get(Company, 1)
    return _build(transaction_story(s, txn, base_url, config), f"{TITLES.get(txn.type, txn.info.label)} {txn.number or ''}",
                  company.name)


def render_many(s: Session, txns: Iterable[Transaction], base_url: str = "") -> bytes:
    company = s.get(Company, 1)
    story: list = []
    for i, t in enumerate(txns):
        if i:
            story.append(PageBreak())
        story += transaction_story(s, t, base_url)
    return _build(story, "Documents", company.name)


# -- statements -----------------------------------------------------------------------------------


def statement_story(s: Session, st_row: Statement, base_url: str = "") -> list:
    from pps_tools.books.services import statements as st_service

    company = s.get(Company, 1)
    st = _Styles(prefs.get(s, "invoice_accent_color") or "#1d7f3a")
    data = st_service.build(s, st_row)
    meta = [("Statement date", st_row.statement_date.strftime("%m/%d/%Y")),
            ("Amount due", fmt(data["amount_due"]))]
    if st_row.kind != "open_item" and st_row.start_date:
        meta.append(("Period", f"{st_row.start_date:%m/%d/%Y} – {st_row.end_date:%m/%d/%Y}"))
    c = st_row.customer
    story = [_header(s, company, st, "Statement", meta), Spacer(1, 16),
             _address_row(st, [("To", (c.company_name or c.display_name) + ("\n" + c.billing_address()
                                                                             if c.billing_address() else ""))]),
             Spacer(1, 14)]
    rows = [["Date", "Activity", "Amount", "Open amount" if st_row.kind == "open_item" else "Balance"]]
    if data.get("opening") is not None:
        rows.append([st_row.start_date.strftime("%m/%d/%Y") if st_row.start_date else "", "Balance forward", "",
                     fmt(data["opening"])])
    for ln in data["lines"]:
        rows.append([ln["date"].strftime("%m/%d/%Y"), Paragraph(_esc(ln["description"]), st.cell), fmt(ln["amount"]),
                     fmt(ln["balance"])])
    t = Table(rows, colWidths=[1.0 * inch, 3.9 * inch, 1.2 * inch, 1.2 * inch], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1, st.accent), ("FONT", (0, 0), (-1, 0), st.bold, 9),
                           ("FONT", (0, 1), (-1, -1), st.font, 9), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#dddddd"))]))
    story += [t, Spacer(1, 12)]
    aging = data["aging"]
    at = Table([["Current", "1–30 days past due", "31–60 days", "61–90 days", "Over 90 days", "Amount due"],
                [fmt(aging["current"]), fmt(aging["1_30"]), fmt(aging["31_60"]), fmt(aging["61_90"]),
                 fmt(aging["over_90"]), fmt(data["amount_due"])]], colWidths=[1.2 * inch] * 6)
    at.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), st.bold, 7.5), ("FONT", (0, 1), (-1, 1), st.font, 9),
                            ("FONT", (-1, 1), (-1, 1), st.bold, 10), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc"))]))
    story.append(at)
    msg = prefs.get(s, "default_statement_message")
    if msg:
        story += [Spacer(1, 12), Paragraph(_esc(msg), st.body)]
    if base_url and c.portal_token and prefs.get(s, "stripe_enabled") and data["amount_due"] > 0:
        link = f"{base_url}/portal/{c.portal_token}"
        story += [Spacer(1, 12), Paragraph("PAY ONLINE", st.label),
                  Paragraph(f"<link href='{_esc(link)}'><u>{_esc(link)}</u></link>", st.body)]
    return story


def render_statements(s: Session, statements: Iterable[Statement], base_url: str = "") -> bytes:
    company = s.get(Company, 1)
    story: list = []
    for i, st_row in enumerate(statements):
        if i:
            story.append(PageBreak())
        story += statement_story(s, st_row, base_url)
    return _build(story, "Statements", company.name)


# -- checks -----------------------------------------------------------------------------------------


def render_checks(s: Session, txns: Iterable[Transaction]) -> bytes:
    """Voucher checks (check on top, two stubs below) on standard letter-size check stock.
    Nudge alignment with the check_offset_x / check_offset_y preferences (inches)."""
    company = s.get(Company, 1)
    dx = float(prefs.get(s, "check_offset_x") or 0) * inch
    dy = float(prefs.get(s, "check_offset_y") or 0) * inch
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    c.setTitle("Checks")
    w, h = letter
    for txn in txns:
        payee = txn.entity_name or "Cash"
        entity = txn.entity
        address = entity.billing_address() if entity is not None and hasattr(entity, "billing_address") else ""
        amount = txn.total_cents
        # check (top third)
        c.setFont("Helvetica", 10)
        c.drawString(6.6 * inch + dx, h - 0.65 * inch + dy, txn.date.strftime("%m/%d/%Y"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(1.0 * inch + dx, h - 1.25 * inch + dy, payee)
        c.drawRightString(7.9 * inch + dx, h - 1.25 * inch + dy, f"**{fmt(amount, symbol='')}")
        c.setFont("Helvetica", 10)
        words = amount_in_words(amount)
        c.drawString(0.6 * inch + dx, h - 1.6 * inch + dy, (words + " " + "*" * max(0, 80 - len(words)))[:95])
        y = h - 2.0 * inch + dy
        for line in ([payee] + address.split("\n"))[:5]:
            c.drawString(1.0 * inch + dx, y, line)
            y -= 0.17 * inch
        c.drawString(0.6 * inch + dx, h - 3.0 * inch + dy, f"Memo: {(txn.memo or '')[:60]}")
        # two vouchers
        for top in (h - 3.67 * inch, h - 7.33 * inch):
            c.setFont("Helvetica-Bold", 10)
            c.drawString(0.6 * inch, top - 0.3 * inch, company.name)
            c.drawRightString(7.9 * inch, top - 0.3 * inch, f"Check {txn.number or ''}  ·  {txn.date:%m/%d/%Y}")
            c.setFont("Helvetica", 9.5)
            c.drawString(0.6 * inch, top - 0.55 * inch, f"Paid to: {payee}")
            c.drawRightString(7.9 * inch, top - 0.55 * inch, fmt(amount))
            y = top - 0.9 * inch
            rows = []
            if txn.type == "bill_payment":
                for link in txn.links_out:
                    if link.link_type == "bill_payment":
                        b = link.to_txn
                        rows.append((f"Bill {b.number or ''} dated {b.date:%m/%d/%Y}", fmt(b.total_cents), fmt(link.amount_cents)))
            else:
                for ln in txn.lines:
                    if ln.kind in ("item", "account"):
                        label = ln.item.name if ln.item else (ln.account.name if ln.account else "")
                        rows.append((f"{label} {ln.description or ''}".strip()[:70], "", fmt(ln.amount_cents)))
            for label, orig, paid in rows[:9]:
                c.drawString(0.6 * inch, y, label)
                if orig:
                    c.drawRightString(6.4 * inch, y, orig)
                c.drawRightString(7.9 * inch, y, paid)
                y -= 0.18 * inch
        c.showPage()
    c.save()
    return buf.getvalue()
