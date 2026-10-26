"""Sales and customer reports; expense and vendor reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import (ACCOUNT_TYPES, Account, Customer, Item, LedgerEntry, PaymentMethod,
                                    TimeActivity, Transaction, TransactionLine, TransactionLink, Vendor)
from pps_tools.books.money import fmt_qty
from pps_tools.books.services import dates as D
from pps_tools.books.services.reports.engine import (Aggregator, Col, ColumnSpec, Params, Report,
                                                     company_info, customer_scope, entity_name_maps, pct,
                                                     period_columns, period_label, register, report_link,
                                                     txn_link)
from pps_tools.books.txn_types import TXN_TYPES

SALE_DOCS = ("invoice", "sales_receipt", "credit_memo", "refund_receipt")
PURCHASE_DOCS = ("bill", "expense", "check", "cc_credit", "vendor_credit")
NEGATIVE_DOCS = ("credit_memo", "refund_receipt", "cc_credit", "vendor_credit")


def _sign(t: Transaction) -> int:
    return -1 if t.type in NEGATIVE_DOCS else 1


def _income_ids(s: Session) -> list[int]:
    return list(s.scalars(select(Account.id).where(Account.type == "income")))


def _expense_ids(s: Session) -> list[int]:
    return list(s.scalars(select(Account.id).where(Account.type.in_(("cogs", "expense", "other_expense")))))


def _by_party_summary(s: Session, p: Params, key: str, title: str, party: str, account_ids: list[int],
                      sign: int) -> Report:
    company = company_info(s)
    agg = Aggregator.for_params(s, p)
    cols = period_columns(p, company.fiscal_year_start_month)
    names = entity_name_maps(s)[party]
    values: dict[str, dict] = {}
    for c in cols:
        tot = agg.totals(c.start, c.end, party)
        vals: dict = defaultdict(int)
        for (aid, pid), v in tot.items():
            if aid in account_ids:
                vals[pid] += sign * v
        values[c.key] = vals
    r = Report(key, title, period_label(p), basis=p.basis)
    r.columns = [Col("name", "", "text")] + [Col(c.key, c.label) for c in cols]
    if p.pct == "column" or key.startswith("sales_by_customer"):
        r.columns.append(Col("pct", "% of total", "pct"))
    parties = {pid for vals in values.values() for pid, v in vals.items() if v}
    grand = {c.key: sum(values[c.key].values()) for c in cols}
    detail = key.replace("summary", "detail")
    for pid in sorted(parties, key=lambda i: (i is None, (names.get(i) or "").lower())):
        cells = {"name": names.get(pid, "Not specified") if pid else "Not specified"}
        for c in cols:
            cells[c.key] = values[c.key].get(pid, 0)
        cells["pct"] = pct(cells["total"], grand["total"])
        r.add(cells, 1, "data", link=report_link(detail, p, **{f"{party}_id": pid}) if pid else None)
    cells = {"name": "TOTAL", **grand, "pct": Decimal(100) if grand.get("total") else None}
    r.add(cells, 0, "grand")
    return r


@register("sales_by_customer_summary", "Sales by Customer Summary", "sales", "Sales per customer.",
          options=("columns", "basis", "class", "location"))
def sales_by_customer_summary(s: Session, p: Params) -> Report:
    return _by_party_summary(s, p, "sales_by_customer_summary", "Sales by Customer Summary", "customer",
                             _income_ids(s), -1)


@register("income_by_customer_summary", "Income by Customer Summary", "sales",
          "Income, costs and net income per customer.", options=("basis",))
def income_by_customer_summary(s: Session, p: Params) -> Report:
    agg = Aggregator.for_params(s, p)
    tot = agg.totals(p.start, p.end, "customer")
    types = dict(s.execute(select(Account.id, Account.type)).all())
    names = entity_name_maps(s)["customer"]
    rows: dict = defaultdict(lambda: [0, 0])
    for (aid, cid), v in tot.items():
        cls = ACCOUNT_TYPES[types[aid]].classification
        if cid is None:
            continue
        if cls == "income":
            rows[cid][0] += -v
        elif cls == "expense":
            rows[cid][1] += v
    r = Report("income_by_customer_summary", "Income by Customer Summary", period_label(p), basis=p.basis)
    r.columns = [Col("name", "", "text"), Col("income", "Income"), Col("expenses", "Expenses"),
                 Col("net", "Net income")]
    gi = ge = 0
    for cid in sorted(rows, key=lambda i: names.get(i, "").lower()):
        inc, exp = rows[cid]
        if not inc and not exp:
            continue
        r.add({"name": names.get(cid, ""), "income": inc, "expenses": exp, "net": inc - exp}, 1, "data",
              link=report_link("pl_by_customer", p, customer_id=cid))
        gi += inc
        ge += exp
    r.add({"name": "TOTAL", "income": gi, "expenses": ge, "net": gi - ge}, 0, "grand")
    return r


def _sale_lines(s: Session, p: Params, types=SALE_DOCS, party: str = "customer"):
    q = (select(TransactionLine, Transaction).join(Transaction, Transaction.id == TransactionLine.txn_id)
         .where(Transaction.type.in_(types), Transaction.voided.is_(False),
                TransactionLine.kind.in_(("item", "account"))))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if party == "customer" and p.customer_id:
        q = q.where(Transaction.customer_id.in_(customer_scope(s, p.customer_id)))
    if party == "vendor" and p.vendor_id:
        q = q.where(Transaction.vendor_id == p.vendor_id)
    if p.item_id:
        q = q.where(TransactionLine.item_id == p.item_id)
    if p.class_id:
        q = q.where((TransactionLine.class_id == p.class_id) | (Transaction.class_id == p.class_id))
    if p.location_id:
        q = q.where(Transaction.location_id == p.location_id)
    return s.execute(q.order_by(Transaction.date, Transaction.id, TransactionLine.position)).all()


DETAIL_LINE_COLS = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"),
                    Col("num", "Num", "text"), Col("item", "Product/Service", "text"),
                    Col("memo", "Memo/Description", "text"), Col("qty", "Qty", "qty"),
                    Col("rate", "Sales price", "rate"), Col("amount", "Amount"), Col("balance", "Balance")]


@register("sales_by_customer_detail", "Sales by Customer Detail", "sales", "Every sale, grouped by customer.",
          options=("customer", "item", "class", "location"), default_preset="this_month")
def sales_by_customer_detail(s: Session, p: Params) -> Report:
    rows = _sale_lines(s, p)
    names = entity_name_maps(s)
    r = Report("sales_by_customer_detail", "Sales by Customer Detail", period_label(p))
    r.columns = list(DETAIL_LINE_COLS)
    by_party: dict[int, list] = defaultdict(list)
    for line, t in rows:
        by_party[t.customer_id].append((line, t))
    grand = 0
    for cid in sorted(by_party, key=lambda i: names["customer"].get(i, "").lower()):
        r.add({"type": names["customer"].get(cid, "")}, 0, "section", link=f"/customers/{cid}")
        running = 0
        for line, t in by_party[cid]:
            amt = _sign(t) * line.amount_cents
            running += amt
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "",
                   "item": names["item"].get(line.item_id, "") if line.item_id else "",
                   "memo": line.description or "", "qty": (_sign(t) * line.qty) if line.qty is not None else None,
                   "rate": line.rate, "amount": amt, "balance": running}, 1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {names['customer'].get(cid, '')}", "amount": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("sales_by_product_summary", "Sales by Product/Service Summary", "sales",
          "Quantity, sales, cost and margin per product or service.",
          options=("customer", "class", "location"))
def sales_by_product_summary(s: Session, p: Params) -> Report:
    rows = _sale_lines(s, p)
    names = entity_name_maps(s)["item"]
    agg: dict = defaultdict(lambda: [Decimal(0), 0])
    for line, t in rows:
        key = line.item_id
        agg[key][0] += _sign(t) * (line.qty or Decimal(0))
        agg[key][1] += _sign(t) * line.amount_cents
    cogs: dict = defaultdict(int)
    from pps_tools.books.services.accounts import system_account_id

    cogs_q = select(LedgerEntry.item_id, LedgerEntry.amount_cents, Account.type).join(
        Account, Account.id == LedgerEntry.account_id).where(LedgerEntry.auto == "cogs", Account.type == "cogs")
    if p.start:
        cogs_q = cogs_q.where(LedgerEntry.date >= p.start)
    if p.end:
        cogs_q = cogs_q.where(LedgerEntry.date <= p.end)
    if p.customer_id:
        cogs_q = cogs_q.where(LedgerEntry.customer_id.in_(customer_scope(s, p.customer_id)))
    for item_id, amt, _ in s.execute(cogs_q):
        cogs[item_id] += amt
    total_sales = sum(v[1] for v in agg.values())
    r = Report("sales_by_product_summary", "Sales by Product/Service Summary", period_label(p))
    r.columns = [Col("name", "", "text"), Col("qty", "Qty", "qty"), Col("amount", "Amount"),
                 Col("pct", "% of sales", "pct"), Col("avg", "Avg price", "rate"), Col("cogs", "COGS"),
                 Col("margin", "Gross margin"), Col("margin_pct", "Gross margin %", "pct")]
    for item_id in sorted(agg, key=lambda i: (i is None, names.get(i, "") or "")):
        qty, amt = agg[item_id]
        c = cogs.get(item_id, 0)
        r.add({"name": names.get(item_id, "Not specified") if item_id else "Not specified", "qty": qty,
               "amount": amt, "pct": pct(amt, total_sales),
               "avg": (Decimal(amt) / 100 / qty).quantize(Decimal("0.01")) if qty else None,
               "cogs": c or None, "margin": amt - c, "margin_pct": pct(amt - c, amt)}, 1, "data",
              link=report_link("sales_by_product_detail", p, item_id=item_id) if item_id else None)
    total_cogs = sum(cogs.values())
    r.add({"name": "TOTAL", "amount": total_sales, "pct": Decimal(100) if total_sales else None,
           "cogs": total_cogs, "margin": total_sales - total_cogs,
           "margin_pct": pct(total_sales - total_cogs, total_sales)}, 0, "grand")
    return r


@register("sales_by_product_detail", "Sales by Product/Service Detail", "sales",
          "Every sale, grouped by product or service.", options=("item", "customer"), default_preset="this_month")
def sales_by_product_detail(s: Session, p: Params) -> Report:
    rows = _sale_lines(s, p)
    names = entity_name_maps(s)
    r = Report("sales_by_product_detail", "Sales by Product/Service Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Customer", "text"), Col("memo", "Memo/Description", "text"), Col("qty", "Qty", "qty"),
                 Col("rate", "Sales price", "rate"), Col("amount", "Amount"), Col("balance", "Balance")]
    by_item: dict = defaultdict(list)
    for line, t in rows:
        by_item[line.item_id].append((line, t))
    grand = 0
    for item_id in sorted(by_item, key=lambda i: (i is None, names["item"].get(i, "") or "")):
        label = names["item"].get(item_id, "Not specified") if item_id else "Not specified"
        r.add({"type": label}, 0, "section")
        running = 0
        for line, t in by_item[item_id]:
            amt = _sign(t) * line.amount_cents
            running += amt
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "",
                   "name": names["customer"].get(t.customer_id, ""), "memo": line.description or "",
                   "qty": (_sign(t) * line.qty) if line.qty is not None else None, "rate": line.rate,
                   "amount": amt, "balance": running}, 1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {label}", "amount": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("estimates_by_customer", "Estimates by Customer", "sales", "Estimates and their status.",
          options=("customer",), default_preset="this_year")
def estimates_by_customer(s: Session, p: Params) -> Report:
    from pps_tools.books.services.transactions import status

    q = select(Transaction).where(Transaction.type == "estimate")
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.customer_id:
        q = q.where(Transaction.customer_id.in_(customer_scope(s, p.customer_id)))
    names = entity_name_maps(s)["customer"]
    r = Report("estimates_by_customer", "Estimates by Customer", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("status", "Status", "text"),
                 Col("expires", "Expires", "date"), Col("amount", "Amount")]
    by_party: dict = defaultdict(list)
    for t in s.scalars(q.order_by(Transaction.date)):
        by_party[t.customer_id].append(t)
    grand = 0
    for cid in sorted(by_party, key=lambda i: names.get(i, "").lower()):
        r.add({"num": names.get(cid, "")}, 0, "section")
        sub = 0
        for t in by_party[cid]:
            r.add({"date": t.date, "num": t.number or "", "status": status(t)[1], "expires": t.expiration_date,
                   "amount": t.total_cents}, 1, "data", link=txn_link(t.id))
            sub += t.total_cents
        r.add({"num": f"Total for {names.get(cid, '')}", "amount": sub}, 0, "subtotal")
        grand += sub
    r.add({"num": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("deposit_detail", "Deposit Detail", "banking", "Deposits and the payments in each.",
          options=("account",), default_preset="this_month")
def deposit_detail(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.type == "deposit", Transaction.voided.is_(False))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.account_id:
        q = q.where(Transaction.account_id == p.account_id)
    names = entity_name_maps(s)
    r = Report("deposit_detail", "Deposit Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Customer/Name", "text"), Col("memo", "Memo", "text"), Col("account", "Account", "text"),
                 Col("amount", "Amount")]
    grand = 0
    for dep in s.scalars(q.order_by(Transaction.date, Transaction.id)):
        r.add({"date": dep.date, "type": "Deposit", "num": dep.number or "", "memo": dep.memo or "",
               "account": dep.account.full_name if dep.account else "", "amount": dep.total_cents}, 0, "section",
              link=txn_link(dep.id))
        for link in dep.links_out:
            if link.link_type != "deposit":
                continue
            src = link.to_txn
            r.add({"date": src.date, "type": src.info.label, "num": src.number or src.ref_no or "",
                   "name": src.entity_name, "memo": src.memo or "", "amount": link.amount_cents}, 1, "data",
                  link=txn_link(src.id))
        for line in dep.lines:
            if line.kind != "account":
                continue
            ent = line.name_entity
            r.add({"date": dep.date, "type": "Deposit line", "num": line.ref_no or "",
                   "name": ent.display_name if ent else "", "memo": line.description or "",
                   "account": line.account.full_name if line.account else "", "amount": line.amount_cents},
                  1, "data")
        grand += dep.total_cents
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("unbilled_charges", "Unbilled Charges", "sales",
          "Billable expenses and delayed charges not yet on an invoice.", kind="list",
          options=("customer",))
def unbilled_charges(s: Session, p: Params) -> Report:
    q = (select(TransactionLine, Transaction).join(Transaction, Transaction.id == TransactionLine.txn_id)
         .where(TransactionLine.billable.is_(True), TransactionLine.billed_txn_id.is_(None),
                Transaction.voided.is_(False), Transaction.type.in_(PURCHASE_DOCS)))
    if p.customer_id:
        q = q.where(TransactionLine.customer_id.in_(customer_scope(s, p.customer_id)))
    names = entity_name_maps(s)
    rows = s.execute(q.order_by(Transaction.date)).all()
    delayed = s.scalars(select(Transaction).where(Transaction.type == "delayed_charge",
                                                  Transaction.status == "open", Transaction.voided.is_(False))).all()
    r = Report("unbilled_charges", "Unbilled Charges", "")
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Customer", "text"), Col("memo", "Memo/Description", "text"), Col("amount", "Amount")]
    by_party: dict = defaultdict(list)
    for line, t in rows:
        by_party[line.customer_id].append((t, line.description or "", line.amount_cents))
    for t in delayed:
        if p.customer_id and t.customer_id not in customer_scope(s, p.customer_id):
            continue
        by_party[t.customer_id].append((t, t.memo or "", t.total_cents))
    grand = 0
    for cid in sorted(by_party, key=lambda i: names["customer"].get(i, "").lower()):
        r.add({"type": names["customer"].get(cid, "")}, 0, "section", link=f"/customers/{cid}")
        sub = 0
        for t, memo, amt in by_party[cid]:
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "name": names["customer"].get(cid, ""),
                   "memo": memo, "amount": amt}, 1, "data", link=txn_link(t.id))
            sub += amt
        r.add({"type": f"Total for {names['customer'].get(cid, '')}", "amount": sub}, 0, "subtotal")
        grand += sub
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("customer_contact_list", "Customer Contact List", "sales", "Phone, email and address per customer.",
          kind="list")
def customer_contact_list(s: Session, p: Params) -> Report:
    r = Report("customer_contact_list", "Customer Contact List", "")
    r.columns = [Col("name", "Customer", "text"), Col("phone", "Phone", "text"), Col("email", "Email", "text"),
                 Col("contact", "Full name", "text"), Col("address", "Billing address", "text")]
    for c in s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)):
        r.add({"name": c.full_name, "phone": c.phone or c.mobile or "", "email": c.email or "",
               "contact": c.contact_name, "address": c.billing_address().replace("\n", ", ")}, 1, "data",
              link=f"/customers/{c.id}")
    return r


@register("vendor_contact_list", "Vendor Contact List", "expenses", "Phone, email and address per vendor.",
          kind="list")
def vendor_contact_list(s: Session, p: Params) -> Report:
    r = Report("vendor_contact_list", "Vendor Contact List", "")
    r.columns = [Col("name", "Vendor", "text"), Col("phone", "Phone", "text"), Col("email", "Email", "text"),
                 Col("account", "Account #", "text"), Col("address", "Address", "text")]
    for v in s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)):
        r.add({"name": v.display_name, "phone": v.phone or v.mobile or "", "email": v.email or "",
               "account": v.account_number or "", "address": v.billing_address().replace("\n", ", ")}, 1, "data",
              link=f"/vendors/{v.id}")
    return r


@register("product_service_list", "Product/Service List", "sales", "Products and services with prices.",
          kind="list")
def product_service_list(s: Session, p: Params) -> Report:
    r = Report("product_service_list", "Product/Service List", "")
    r.columns = [Col("name", "Product/Service", "text"), Col("sku", "SKU", "text"), Col("type", "Type", "text"),
                 Col("description", "Description", "text"), Col("price", "Price", "rate"), Col("cost", "Cost", "rate"),
                 Col("qty", "Qty on hand", "qty")]
    for it in s.scalars(select(Item).where(Item.active.is_(True)).order_by(Item.name)):
        r.add({"name": it.name, "sku": it.sku or "", "type": it.type_label, "description": it.description or "",
               "price": it.sales_price, "cost": it.cost, "qty": it.qty_on_hand if it.is_inventory else None},
              1, "data", link=f"/items/{it.id}")
    return r


@register("payment_method_list", "Payment Method List", "sales", "Payment methods you accept.", kind="list")
def payment_method_list(s: Session, p: Params) -> Report:
    r = Report("payment_method_list", "Payment Method List", "")
    r.columns = [Col("name", "Payment method", "text"), Col("kind", "Kind", "text"), Col("active", "Active", "text")]
    for pm in s.scalars(select(PaymentMethod).order_by(PaymentMethod.name)):
        r.add({"name": pm.name, "kind": pm.kind, "active": "Yes" if pm.active else "No"}, 1, "data")
    return r


@register("sales_by_class", "Sales by Class Summary", "sales", "Sales per class.", options=("basis",))
def sales_by_class(s: Session, p: Params) -> Report:
    return _by_party_summary(s, p, "sales_by_class", "Sales by Class Summary", "class", _income_ids(s), -1)


@register("sales_by_location", "Sales by Location Summary", "sales", "Sales per location.", options=("basis",))
def sales_by_location(s: Session, p: Params) -> Report:
    return _by_party_summary(s, p, "sales_by_location", "Sales by Location Summary", "location",
                             _income_ids(s), -1)


# -- expenses and vendors -------------------------------------------------------------------


@register("expenses_by_vendor_summary", "Expenses by Vendor Summary", "expenses", "Spending per vendor.",
          options=("columns", "basis", "class", "location"))
def expenses_by_vendor_summary(s: Session, p: Params) -> Report:
    return _by_party_summary(s, p, "expenses_by_vendor_summary", "Expenses by Vendor Summary", "vendor",
                             _expense_ids(s), 1)


@register("expenses_by_vendor_detail", "Expenses by Vendor Detail", "expenses", "Every expense, by vendor.",
          options=("vendor", "basis"), default_preset="this_month")
def expenses_by_vendor_detail(s: Session, p: Params) -> Report:
    agg = Aggregator.for_params(s, p)
    exp_ids = set(_expense_ids(s))
    accounts = {a.id: a.display_name for a in s.scalars(select(Account))}
    names = entity_name_maps(s)
    if p.basis == "cash":
        ents = [e for e in agg._cash() if e.account_id in exp_ids and (not p.start or e.date >= p.start)
                and (not p.end or e.date <= p.end)]
    else:
        q = select(LedgerEntry).where(LedgerEntry.account_id.in_(list(exp_ids)))
        if p.start:
            q = q.where(LedgerEntry.date >= p.start)
        if p.end:
            q = q.where(LedgerEntry.date <= p.end)
        ents = list(s.scalars(agg._filters_sql(q)))
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_({e.txn_id for e in ents})))} \
        if ents else {}
    by_vendor: dict = defaultdict(list)
    for e in ents:
        by_vendor[e.vendor_id].append(e)
    r = Report("expenses_by_vendor_detail", "Expenses by Vendor Detail", period_label(p), basis=p.basis)
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("memo", "Memo/Description", "text"), Col("account", "Account", "text"), Col("amount", "Amount"),
                 Col("balance", "Balance")]
    grand = 0
    for vid in sorted(by_vendor, key=lambda i: (i is None, names["vendor"].get(i, "") or "")):
        label = names["vendor"].get(vid, "Not specified") if vid else "Not specified"
        r.add({"type": label}, 0, "section", link=f"/vendors/{vid}" if vid else None)
        running = 0
        for e in sorted(by_vendor[vid], key=lambda e: (e.date, e.txn_id)):
            t = txns[e.txn_id]
            running += e.amount_cents
            r.add({"date": e.date, "type": TXN_TYPES[t.type].label, "num": t.number or "", "memo": e.memo or "",
                   "account": accounts.get(e.account_id, ""), "amount": e.amount_cents, "balance": running},
                  1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {label}", "amount": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("purchases_by_vendor_detail", "Purchases by Vendor Detail", "expenses",
          "Bills, expenses and checks by vendor, line by line.", options=("vendor", "item"),
          default_preset="this_month")
def purchases_by_vendor_detail(s: Session, p: Params) -> Report:
    rows = _sale_lines(s, p, PURCHASE_DOCS, party="vendor")
    names = entity_name_maps(s)
    accounts = {a.id: a.display_name for a in s.scalars(select(Account))}
    r = Report("purchases_by_vendor_detail", "Purchases by Vendor Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("item", "Product/Service or category", "text"), Col("memo", "Memo/Description", "text"),
                 Col("qty", "Qty", "qty"), Col("rate", "Rate", "rate"), Col("amount", "Amount"),
                 Col("balance", "Balance")]
    by_party: dict = defaultdict(list)
    for line, t in rows:
        by_party[t.vendor_id].append((line, t))
    grand = 0
    for vid in sorted(by_party, key=lambda i: (i is None, names["vendor"].get(i, "") or "")):
        label = names["vendor"].get(vid, "No vendor") if vid else "No vendor"
        r.add({"type": label}, 0, "section")
        running = 0
        for line, t in by_party[vid]:
            amt = _sign(t) * line.amount_cents
            running += amt
            what = names["item"].get(line.item_id) if line.item_id else accounts.get(line.account_id, "")
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "item": what or "",
                   "memo": line.description or "", "qty": line.qty, "rate": line.rate, "amount": amt,
                   "balance": running}, 1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {label}", "amount": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("purchases_by_product_detail", "Purchases by Product/Service Detail", "expenses",
          "What you bought, by product.", options=("item", "vendor"), default_preset="this_month")
def purchases_by_product_detail(s: Session, p: Params) -> Report:
    rows = [(ln, t) for ln, t in _sale_lines(s, p, PURCHASE_DOCS, party="vendor") if ln.item_id]
    names = entity_name_maps(s)
    r = Report("purchases_by_product_detail", "Purchases by Product/Service Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Vendor", "text"), Col("memo", "Memo/Description", "text"), Col("qty", "Qty", "qty"),
                 Col("rate", "Cost", "rate"), Col("amount", "Amount"), Col("balance", "Balance")]
    by_item: dict = defaultdict(list)
    for line, t in rows:
        by_item[line.item_id].append((line, t))
    grand = 0
    for item_id in sorted(by_item, key=lambda i: names["item"].get(i, "")):
        r.add({"type": names["item"].get(item_id, "")}, 0, "section")
        running = 0
        for line, t in by_item[item_id]:
            amt = _sign(t) * line.amount_cents
            running += amt
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "",
                   "name": names["vendor"].get(t.vendor_id, "") if t.vendor_id else t.entity_name,
                   "memo": line.description or "", "qty": line.qty, "rate": line.rate, "amount": amt,
                   "balance": running}, 1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {names['item'].get(item_id, '')}", "amount": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


@register("open_purchase_orders", "Open Purchase Order List", "expenses", "Purchase orders not yet received.",
          kind="list", options=("vendor",))
def open_purchase_orders(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.type == "purchase_order", Transaction.status == "open",
                                  Transaction.voided.is_(False))
    if p.vendor_id:
        q = q.where(Transaction.vendor_id == p.vendor_id)
    names = entity_name_maps(s)["vendor"]
    r = Report("open_purchase_orders", "Open Purchase Order List", "")
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("name", "Vendor", "text"),
                 Col("ship", "Expected", "date"), Col("amount", "Amount"), Col("open", "Open balance")]
    grand = open_total = 0
    for t in s.scalars(q.order_by(Transaction.date)):
        received = 0
        for ln in t.lines:
            if ln.kind == "item" and ln.qty and ln.received_qty:
                received += round(ln.amount_cents * min(ln.received_qty / ln.qty, Decimal(1)))
            elif ln.kind == "account" and ln.received_qty:
                received += min(int(ln.received_qty * 100), ln.amount_cents)
        open_amt = max(t.total_cents - received, 0)
        r.add({"date": t.date, "num": t.number or "", "name": names.get(t.vendor_id, ""), "ship": t.ship_date,
               "amount": t.total_cents, "open": open_amt}, 1, "data", link=txn_link(t.id))
        grand += t.total_cents
        open_total += open_amt
    r.add({"num": "TOTAL", "amount": grand, "open": open_total}, 0, "grand")
    return r


@register("check_detail", "Check Detail", "banking", "Checks written, with what each paid for.",
          options=("account",), default_preset="this_month")
def check_detail(s: Session, p: Params) -> Report:
    q = select(Transaction).join(Account, Account.id == Transaction.account_id).where(
        Transaction.type.in_(("check", "bill_payment", "expense")), Account.type == "bank",
        Transaction.voided.is_(False))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.account_id:
        q = q.where(Transaction.account_id == p.account_id)
    accounts = {a.id: a.display_name for a in s.scalars(select(Account))}
    r = Report("check_detail", "Check Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Name", "text"), Col("memo", "Memo", "text"), Col("account", "Account", "text"),
                 Col("amount", "Amount")]
    grand = 0
    for t in s.scalars(q.order_by(Transaction.date, Transaction.number)):
        if t.type == "expense" and t.payment_method and t.payment_method.kind != "check":
            continue
        r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "name": t.entity_name,
               "memo": t.memo or "", "account": accounts.get(t.account_id, ""), "amount": -t.total_cents},
              0, "section", link=txn_link(t.id))
        for ln in t.lines:
            if ln.kind in ("item", "account"):
                r.add({"memo": ln.description or "", "account": accounts.get(ln.account_id, "") if ln.account_id
                       else (ln.item.name if ln.item else ""), "amount": ln.amount_cents}, 1, "data")
        for link in t.links_out:
            if link.link_type == "bill_payment":
                r.add({"type": "Bill", "num": link.to_txn.number or "", "memo": f"Bill dated {link.to_txn.date:%m/%d/%Y}",
                       "amount": link.amount_cents}, 1, "data", link=txn_link(link.to_txn_id))
        grand += t.total_cents
    r.add({"type": "TOTAL", "amount": -grand}, 0, "grand")
    return r
