"""Sales tax, 1099s, inventory, budgets, projects and time, banking, Stripe,
and accountant reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import (ACCOUNT_TYPES, Account, AuditLog, Budget, BudgetLine, Company, Customer,
                                    Employee, Item, LedgerEntry, Reconciliation, TaxAgency, TimeActivity,
                                    Transaction, TransactionLink, Vendor)
from pps_tools.books.money import round_cents
from pps_tools.books.services import dates as D
from pps_tools.books.services import inventory as inv_service
from pps_tools.books.services import prefs
from pps_tools.books.services import tax as tax_service
from pps_tools.books.services.accounts import ordered_accounts, system_account_id
from pps_tools.books.services.reports.engine import (Aggregator, Col, Params, Report, as_of_label, company_info,
                                                     customer_scope, entity_name_maps, pct, period_label, register,
                                                     report_link, txn_link)
from pps_tools.books.txn_types import TXN_TYPES

# -- sales tax ------------------------------------------------------------------------------


@register("sales_tax_liability", "Sales Tax Liability Report", "tax",
          "Taxable sales, tax collected, payments and what's due, by agency.",
          options=("agency",), default_preset="last_quarter")
def sales_tax_liability(s: Session, p: Params) -> Report:
    rows = tax_service.liability_by_rate(s, p.start, p.end)
    r = Report("sales_tax_liability", "Sales Tax Liability Report", period_label(p))
    r.columns = [Col("name", "", "text"), Col("rate", "Rate", "pct"), Col("taxable", "Taxable amount"),
                 Col("tax", "Tax amount")]
    by_agency: dict = defaultdict(list)
    for row in rows:
        by_agency[(row.agency_id, row.agency_name)].append(row)
    agencies = {a.id: a for a in s.scalars(select(TaxAgency))}
    for (agency_id, name), group in sorted(by_agency.items(), key=lambda kv: kv[0][1]):
        r.add({"name": name}, 0, "section")
        taxable = tax = 0
        for row in group:
            r.add({"name": row.rate_name, "rate": row.rate_pct, "taxable": row.taxable_cents, "tax": row.tax_cents},
                  1, "data")
            taxable += row.taxable_cents
            tax += row.tax_cents
        r.add({"name": f"Total {name}", "taxable": taxable, "tax": tax}, 0, "subtotal")
        if agency_id:
            adj = tax_service.adjustments_for_agency(s, agency_id, p.start, p.end)
            paid = tax_service.payments_to_agency(s, agency_id, p.start, p.end)
            if adj:
                r.add({"name": "Adjustments", "tax": adj}, 1, "data")
            if paid:
                r.add({"name": "Payments made in period", "tax": -paid}, 1, "data")
            due = tax_service.agency_balance(s, agency_id, p.end)
            r.add({"name": f"Balance owed to {name} as of {p.end:%m/%d/%Y}" if p.end else "Balance owed",
                   "tax": due}, 0, "total")
    for agency_id, agency in agencies.items():
        if not any(k[0] == agency_id for k in by_agency):
            due = tax_service.agency_balance(s, agency_id, p.end)
            if due:
                r.add({"name": agency.name}, 0, "section")
                r.add({"name": "Balance owed", "tax": due}, 0, "total")
    return r


@register("taxable_sales_summary", "Taxable Sales Summary", "tax", "Taxable and non-taxable sales by product.",
          default_preset="last_quarter")
def taxable_sales_summary(s: Session, p: Params) -> Report:
    from pps_tools.books.services.reports.sales import _sale_lines, _sign

    names = entity_name_maps(s)["item"]
    agg: dict = defaultdict(lambda: [0, 0])
    exempt_customers = set(s.scalars(select(Customer.id).where(Customer.taxable.is_(False))))
    for line, t in _sale_lines(s, p):
        taxable = line.taxable and t.customer_id not in exempt_customers and t.tax_rate_id
        agg[line.item_id][0 if taxable else 1] += _sign(t) * line.amount_cents
    r = Report("taxable_sales_summary", "Taxable Sales Summary", period_label(p))
    r.columns = [Col("name", "Product/Service", "text"), Col("taxable", "Taxable"), Col("nontaxable", "Non-taxable"),
                 Col("total", "Total")]
    gt = gn = 0
    for item_id in sorted(agg, key=lambda i: (i is None, names.get(i, "") or "")):
        tx, nt = agg[item_id]
        r.add({"name": names.get(item_id, "Not specified") if item_id else "Not specified", "taxable": tx,
               "nontaxable": nt, "total": tx + nt}, 1, "data")
        gt += tx
        gn += nt
    r.add({"name": "TOTAL", "taxable": gt, "nontaxable": gn, "total": gt + gn}, 0, "grand")
    return r


# -- 1099 -----------------------------------------------------------------------------------

BOXES_1099 = {
    "NEC-1": "NEC Box 1: Nonemployee compensation",
    "MISC-1": "MISC Box 1: Rents",
    "MISC-2": "MISC Box 2: Royalties",
    "MISC-3": "MISC Box 3: Other income",
    "MISC-6": "MISC Box 6: Medical and health care payments",
    "MISC-10": "MISC Box 10: Gross proceeds paid to an attorney",
}


def nec_threshold(s: Session, year: int) -> int:
    table = prefs.get(s, "nec_threshold_by_year") or {}
    years = sorted(int(y) for y in table)
    usable = [y for y in years if y <= year] or years[:1]
    if not usable:
        return 60000
    return round_cents(Decimal(str(table[str(usable[-1])])))


def payments_1099(s: Session, start: date, end: date) -> dict[int, dict[str, list[tuple]]]:
    """{vendor_id: {box: [(txn, amount_cents, account_name)]}} for 1099 vendors.

    Counts payments by cash, check or bank transfer. Card payments are left
    out: the card processor reports those on Form 1099-K.
    """
    vendors = set(s.scalars(select(Vendor.id).where(Vendor.track_1099.is_(True))))
    if not vendors:
        return {}
    accounts = {a.id: a for a in s.scalars(select(Account))}
    any_mapped = any(a.form_1099_box for a in accounts.values())

    def box_for(account_id: Optional[int]) -> Optional[str]:
        a = accounts.get(account_id)
        if a is None:
            return None
        if any_mapped:
            return a.form_1099_box
        return "NEC-1" if a.classification == "expense" else None

    def is_card(t: Transaction) -> bool:
        acct = accounts.get(t.account_id)
        return (acct is not None and acct.type == "credit_card") or (
            t.payment_method is not None and t.payment_method.kind == "card")

    out: dict = defaultdict(lambda: defaultdict(list))
    q = select(Transaction).where(Transaction.vendor_id.in_(vendors), Transaction.voided.is_(False),
                                  Transaction.date >= start, Transaction.date <= end,
                                  Transaction.type.in_(("expense", "check", "bill_payment")))
    for t in s.scalars(q):
        if is_card(t):
            continue
        if t.type in ("expense", "check"):
            for ln in t.lines:
                acct_id = ln.account_id
                if ln.item_id and ln.item is not None:
                    acct_id = ln.item.expense_account_id or acct_id
                box = box_for(acct_id)
                if box and ln.amount_cents:
                    out[t.vendor_id][box].append((t, ln.amount_cents, accounts[acct_id].name if acct_id else ""))
        else:
            for link in t.links_out:
                if link.link_type != "bill_payment":
                    continue
                bill = link.to_txn
                lines = [ln for ln in bill.lines if ln.kind in ("item", "account") and ln.amount_cents]
                total = sum(ln.amount_cents for ln in lines)
                if not total:
                    continue
                from pps_tools.books.money import allocate

                shares = allocate(link.amount_cents, [ln.amount_cents for ln in lines])
                for ln, share in zip(lines, shares):
                    acct_id = ln.account_id
                    if ln.item_id and ln.item is not None:
                        acct_id = ln.item.expense_account_id or acct_id
                    box = box_for(acct_id)
                    if box and share:
                        out[t.vendor_id][box].append((t, share, accounts[acct_id].name if acct_id else ""))
    return out


@register("contractor_1099_summary", "1099 Contractor Summary", "expenses",
          "What you paid each 1099 vendor this year, by box, and who's over the threshold.",
          default_preset="last_year")
def contractor_1099_summary(s: Session, p: Params) -> Report:
    start = p.start or date(date.today().year, 1, 1)
    end = p.end or date(start.year, 12, 31)
    data = payments_1099(s, start, end)
    threshold = nec_threshold(s, end.year)
    vendors = {v.id: v for v in s.scalars(select(Vendor).where(Vendor.track_1099.is_(True)))}
    used_boxes = sorted({box for boxes in data.values() for box in boxes}, key=list(BOXES_1099).index)
    r = Report("contractor_1099_summary", "1099 Contractor Summary", period_label(p))
    r.columns = [Col("name", "Vendor", "text"), Col("tin", "Tax ID", "text")] + [
        Col(b, BOXES_1099[b].split(":")[0]) for b in used_boxes] + [Col("total", "Total"),
                                                                    Col("file", "1099 needed", "text")]
    grand = defaultdict(int)
    for vid, v in sorted(vendors.items(), key=lambda kv: kv[1].display_name.lower()):
        boxes = data.get(vid, {})
        sums = {b: sum(a for _, a, _ in boxes.get(b, [])) for b in used_boxes}
        total = sum(sums.values())
        if not total and not p.include_zero:
            continue
        attorney = sums.get("MISC-10", 0)
        needed = total - attorney >= threshold or attorney >= 60000
        r.add({"name": v.display_name, "tin": v.masked_tax_id or "Missing", **sums, "total": total,
               "file": "Yes" if needed else "No"}, 1, "data",
              link=report_link("contractor_1099_detail", p, vendor_id=vid))
        for b in used_boxes:
            grand[b] += sums[b]
        grand["total"] += total
    r.add({"name": "TOTAL", **grand}, 0, "grand")
    r.notes.append(f"Reporting threshold for {end.year}: ${threshold / 100:,.0f} (Forms 1099-NEC and 1099-MISC). "
                   "Payments by credit or debit card are excluded; card processors report them on Form 1099-K.")
    if not any(a.form_1099_box for a in s.scalars(select(Account))):
        r.notes.append("No accounts are mapped to 1099 boxes yet, so all expense payments count as "
                       "nonemployee compensation. Map accounts under Settings → 1099 boxes.")
    return r


@register("contractor_1099_detail", "1099 Transaction Detail", "expenses",
          "The payments behind each 1099 vendor's totals.", options=("vendor",), default_preset="last_year")
def contractor_1099_detail(s: Session, p: Params) -> Report:
    start = p.start or date(date.today().year, 1, 1)
    end = p.end or date(start.year, 12, 31)
    data = payments_1099(s, start, end)
    vendors = {v.id: v for v in s.scalars(select(Vendor))}
    r = Report("contractor_1099_detail", "1099 Transaction Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("box", "Box", "text"), Col("account", "Account", "text"), Col("amount", "Amount")]
    grand = 0
    for vid in sorted(data, key=lambda i: vendors[i].display_name.lower()):
        if p.vendor_id and vid != p.vendor_id:
            continue
        r.add({"type": vendors[vid].display_name}, 0, "section")
        sub = 0
        for box, rows in data[vid].items():
            for t, amt, acct_name in sorted(rows, key=lambda x: x[0].date):
                r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "box": box, "account": acct_name,
                       "amount": amt}, 1, "data", link=txn_link(t.id))
                sub += amt
        r.add({"type": f"Total for {vendors[vid].display_name}", "amount": sub}, 0, "subtotal")
        grand += sub
    r.add({"type": "TOTAL", "amount": grand}, 0, "grand")
    return r


# -- inventory --------------------------------------------------------------------------------


@register("inventory_valuation_summary", "Inventory Valuation Summary", "inventory",
          "Quantity on hand and FIFO value per item.", kind="as_of", default_preset="today")
def inventory_valuation_summary(s: Session, p: Params) -> Report:
    as_of = p.end
    r = Report("inventory_valuation_summary", "Inventory Valuation Summary", as_of_label(as_of))
    r.columns = [Col("name", "Product", "text"), Col("sku", "SKU", "text"), Col("qty", "Qty", "qty"),
                 Col("value", "Asset value"), Col("avg", "Avg cost", "rate"), Col("price", "Sales price", "rate"),
                 Col("retail", "Retail value")]
    total_value = total_retail = 0
    for it in s.scalars(select(Item).where(Item.type == "inventory").order_by(Item.name)):
        qty, value = inv_service.valuation_as_of(s, it.id, as_of if as_of and as_of < date.today() else None)
        if not qty and not value and not it.active:
            continue
        retail = round_cents((it.sales_price or Decimal(0)) * qty)
        r.add({"name": it.name, "sku": it.sku or "", "qty": qty, "value": value,
               "avg": (Decimal(value) / 100 / qty).quantize(Decimal("0.0001")) if qty else None,
               "price": it.sales_price, "retail": retail}, 1, "data",
              link=report_link("inventory_valuation_detail", p, item_id=it.id, preset="this_year"))
        total_value += value
        total_retail += retail
    r.add({"name": "TOTAL", "value": total_value, "retail": total_retail}, 0, "grand")
    return r


@register("inventory_valuation_detail", "Inventory Valuation Detail", "inventory",
          "Every stock movement with running quantity and value.", options=("item",), default_preset="this_year")
def inventory_valuation_detail(s: Session, p: Params) -> Report:
    r = Report("inventory_valuation_detail", "Inventory Valuation Detail", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Name", "text"), Col("qty", "Qty", "qty"), Col("value", "Value"),
                 Col("on_hand", "Qty on hand", "qty"), Col("asset", "Asset value")]
    q = select(Item).where(Item.type == "inventory").order_by(Item.name)
    if p.item_id:
        q = q.where(Item.id == p.item_id)
    for it in s.scalars(q):
        opening_qty, opening_value, rows = inv_service.history(s, it.id, p.start, p.end)
        if not rows and not opening_qty:
            continue
        r.add({"type": it.name}, 0, "section", link=f"/items/{it.id}")
        r.add({"type": "Beginning balance", "on_hand": opening_qty, "asset": opening_value}, 1, "data")
        for m in rows:
            r.add({"date": m.date, "type": TXN_TYPES[m.txn_type].label, "num": m.number or "", "name": m.name,
                   "qty": m.qty, "value": m.value, "on_hand": m.qty_on_hand, "asset": m.value_on_hand}, 1, "data",
                  link=txn_link(m.txn_id))
        last = rows[-1] if rows else None
        r.add({"type": f"Total for {it.name}", "on_hand": last.qty_on_hand if last else opening_qty,
               "asset": last.value_on_hand if last else opening_value}, 0, "subtotal")
    return r


@register("physical_inventory_worksheet", "Physical Inventory Worksheet", "inventory",
          "A count sheet: quantity on hand with a blank to write the physical count.", kind="list")
def physical_inventory_worksheet(s: Session, p: Params) -> Report:
    r = Report("physical_inventory_worksheet", "Physical Inventory Worksheet", f"As of {date.today():%m/%d/%Y}")
    r.columns = [Col("name", "Product", "text"), Col("sku", "SKU", "text"), Col("description", "Description", "text"),
                 Col("vendor", "Preferred vendor", "text"), Col("qty", "Qty on hand", "qty"),
                 Col("reorder", "Reorder point", "qty"), Col("count", "Physical count", "text")]
    for it in s.scalars(select(Item).where(Item.type == "inventory", Item.active.is_(True)).order_by(Item.name)):
        r.add({"name": it.name, "sku": it.sku or "", "description": it.description or "",
               "vendor": it.preferred_vendor.display_name if it.preferred_vendor else "", "qty": it.qty_on_hand,
               "reorder": it.reorder_point, "count": "________"}, 1, "data")
    return r


@register("low_stock", "Products Low in Stock", "inventory", "Inventory at or below its reorder point.",
          kind="list")
def low_stock(s: Session, p: Params) -> Report:
    r = Report("low_stock", "Products Low in Stock", "")
    r.columns = [Col("name", "Product", "text"), Col("qty", "Qty on hand", "qty"), Col("reorder", "Reorder point", "qty"),
                 Col("vendor", "Preferred vendor", "text"), Col("cost", "Cost", "rate")]
    for it in s.scalars(select(Item).where(Item.type == "inventory", Item.active.is_(True)).order_by(Item.name)):
        if it.low_stock:
            r.add({"name": it.name, "qty": it.qty_on_hand, "reorder": it.reorder_point,
                   "vendor": it.preferred_vendor.display_name if it.preferred_vendor else "", "cost": it.cost},
                  1, "data", link=f"/items/{it.id}")
    return r


# -- budgets ----------------------------------------------------------------------------------


def _budget(s: Session, p: Params) -> Optional[Budget]:
    if p.budget_id:
        return s.get(Budget, p.budget_id)
    return s.scalars(select(Budget).where(Budget.active.is_(True)).order_by(Budget.fiscal_year.desc())).first()


def _budget_months(company: Company, budget: Budget) -> list[tuple[date, date, str]]:
    start = date(budget.fiscal_year, company.fiscal_year_start_month, 1)
    out = []
    for i in range(12):
        a = D.add_months(start, i)
        out.append((a, D.month_end(a), a.strftime("%b %Y")))
    return out


@register("budget_overview", "Budget Overview", "budgets", "Your budget by account and month.", kind="list")
def budget_overview(s: Session, p: Params) -> Report:
    company = company_info(s)
    budget = _budget(s, p)
    r = Report("budget_overview", "Budget Overview", budget.name if budget else "No budget yet")
    if budget is None:
        r.notes.append("Create a budget under Settings → Budgeting.")
        return r
    months = _budget_months(company, budget)
    r.columns = [Col("name", "", "text")] + [Col(f"m{i}", lbl) for i, (_, _, lbl) in enumerate(months)] + [
        Col("total", "Total")]
    amounts: dict = defaultdict(lambda: [0] * 12)
    for bl in budget.lines:
        if bl.subdivision_id is None:
            amounts[bl.account_id][bl.period - 1] += bl.amount_cents
    for a in ordered_accounts(s):
        if a.id not in amounts:
            continue
        vals = amounts[a.id]
        r.add({"name": a.display_name, **{f"m{i}": v for i, v in enumerate(vals)}, "total": sum(vals)}, 1, "data")
    return r


@register("budget_vs_actuals", "Budget vs. Actuals", "budgets", "How actual income and expenses compare to budget.",
          options=("budget", "basis"), kind="list")
def budget_vs_actuals(s: Session, p: Params) -> Report:
    company = company_info(s)
    budget = _budget(s, p)
    r = Report("budget_vs_actuals", "Budget vs. Actuals", budget.name if budget else "No budget yet", basis=p.basis)
    if budget is None:
        r.notes.append("Create a budget under Settings → Budgeting.")
        return r
    months = _budget_months(company, budget)
    start, end = months[0][0], months[-1][1]
    agg = Aggregator(s, p.basis)
    actual = agg.by_account(start, end)
    budgeted: dict = defaultdict(int)
    for bl in budget.lines:
        if bl.subdivision_id is None:
            budgeted[bl.account_id] += bl.amount_cents
    r.subtitle = f"{budget.name}: {start:%B %Y} – {end:%B %Y}"
    r.columns = [Col("name", "", "text"), Col("actual", "Actual"), Col("budget", "Budget"),
                 Col("over", "Over budget"), Col("pct", "% of budget", "pct")]
    sections = [("income", "Income", -1), ("cogs", "Cost of Goods Sold", 1), ("expense", "Expenses", 1),
                ("other_income", "Other Income", -1), ("other_expense", "Other Expenses", 1)]
    net_a = net_b = 0
    for acct_type, label, sign in sections:
        accts = [a for a in ordered_accounts(s, types=[acct_type]) if a.id in budgeted or actual.get(a.id)]
        if not accts:
            continue
        r.add({"name": label}, 0, "section")
        ta = tb = 0
        for a in accts:
            av = sign * actual.get(a.id, 0)
            bv = budgeted.get(a.id, 0)
            r.add({"name": a.display_name, "actual": av, "budget": bv, "over": av - bv, "pct": pct(av, bv)}, 1, "data",
                  link=report_link("transaction_detail_by_account", p, account_id=a.id, start=start, end=end,
                                   preset="custom"))
            ta += av
            tb += bv
        r.add({"name": f"Total {label}", "actual": ta, "budget": tb, "over": ta - tb, "pct": pct(ta, tb)}, 0,
              "subtotal")
        factor = 1 if sign == -1 else -1
        net_a += factor * ta
        net_b += factor * tb
    r.add({"name": "Net Income", "actual": net_a, "budget": net_b, "over": net_a - net_b, "pct": pct(net_a, net_b)},
          0, "grand")
    return r


# -- projects and time ----------------------------------------------------------------------------


def _time_cost(ta: TimeActivity) -> int:
    rate = None
    if ta.employee is not None:
        rate = ta.employee.cost_rate
    if rate is None:
        return 0
    return round_cents(rate * Decimal(ta.minutes) / Decimal(60))


@register("project_profitability", "Project Profitability Summary", "projects",
          "Income, costs and profit for each project.", options=("basis",), default_preset="all")
def project_profitability(s: Session, p: Params) -> Report:
    agg = Aggregator(s, p.basis)
    tot = agg.totals(p.start, p.end, "customer")
    types = dict(s.execute(select(Account.id, Account.type)).all())
    projects = s.scalars(select(Customer).where(Customer.is_project.is_(True)).order_by(Customer.display_name)).all()
    if not projects:
        projects = s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all()
    r = Report("project_profitability", "Project Profitability Summary", period_label(p), basis=p.basis)
    r.columns = [Col("name", "Project", "text"), Col("income", "Income"), Col("costs", "Costs"),
                 Col("labor", "Labor cost"), Col("profit", "Profit"), Col("margin", "Margin", "pct")]
    time_q = select(TimeActivity)
    if p.start:
        time_q = time_q.where(TimeActivity.date >= p.start)
    if p.end:
        time_q = time_q.where(TimeActivity.date <= p.end)
    labor: dict = defaultdict(int)
    for ta in s.scalars(time_q):
        if ta.customer_id:
            labor[ta.customer_id] += _time_cost(ta)
    grand = defaultdict(int)
    for c in projects:
        inc = cost = 0
        for (aid, cid), v in tot.items():
            if cid != c.id:
                continue
            cls = ACCOUNT_TYPES[types[aid]].classification
            if cls == "income":
                inc -= v
            elif cls == "expense":
                cost += v
        lab = labor.get(c.id, 0)
        if not inc and not cost and not lab:
            continue
        profit = inc - cost - lab
        r.add({"name": c.full_name, "income": inc, "costs": cost, "labor": lab, "profit": profit,
               "margin": pct(profit, inc)}, 1, "data", link=f"/projects/{c.id}" if c.is_project else f"/customers/{c.id}")
        for k, v in (("income", inc), ("costs", cost), ("labor", lab), ("profit", profit)):
            grand[k] += v
    r.add({"name": "TOTAL", **grand, "margin": pct(grand["profit"], grand["income"])}, 0, "grand")
    return r


def _time_report(s: Session, p: Params, key: str, title: str, group: str, unbilled: bool = False) -> Report:
    q = select(TimeActivity)
    if p.start:
        q = q.where(TimeActivity.date >= p.start)
    if p.end:
        q = q.where(TimeActivity.date <= p.end)
    if p.customer_id:
        q = q.where(TimeActivity.customer_id.in_(customer_scope(s, p.customer_id)))
    if p.employee_id:
        q = q.where(TimeActivity.employee_id == p.employee_id)
    if unbilled:
        q = q.where(TimeActivity.billable.is_(True), TimeActivity.billed_txn_id.is_(None))
    acts = s.scalars(q.order_by(TimeActivity.date)).all()
    r = Report(key, title, period_label(p))
    other = "customer" if group == "worker" else "worker"
    r.columns = [Col("date", "Date", "date"), Col(other, "Customer" if other == "customer" else "Employee", "text"),
                 Col("service", "Product/Service", "text"), Col("memo", "Description", "text"),
                 Col("billable", "Billable", "text"), Col("hours", "Duration", "qty"), Col("rate", "Rate", "rate"),
                 Col("amount", "Amount")]
    groups: dict = defaultdict(list)
    for ta in acts:
        gkey = ta.worker_name if group == "worker" else (ta.customer.display_name if ta.customer else "No customer")
        groups[gkey].append(ta)
    grand_h, grand_a = Decimal(0), 0
    for gname in sorted(groups):
        r.add({"date": None, other: gname}, 0, "section")
        hours, amount = Decimal(0), 0
        for ta in groups[gname]:
            amt = round_cents((ta.hourly_rate or Decimal(0)) * Decimal(ta.minutes) / Decimal(60)) if ta.billable else 0
            r.add({"date": ta.date, other: ta.customer.display_name if other == "customer" and ta.customer else
                   (ta.worker_name if other == "worker" else ""), "service": ta.item.name if ta.item else "",
                   "memo": ta.description or "", "billable": ta.status, "hours": ta.hours, "rate": ta.hourly_rate,
                   "amount": amt or None}, 1, "data", link=f"/time/{ta.id}")
            hours += ta.hours
            amount += amt
        r.add({other: f"Total for {gname}", "hours": hours, "amount": amount}, 0, "subtotal")
        grand_h += hours
        grand_a += amount
    r.add({other: "TOTAL", "hours": grand_h, "amount": grand_a}, 0, "grand")
    return r


@register("time_by_employee", "Time Activities by Employee Detail", "employees", "Hours logged per person.",
          options=("employee", "customer"), default_preset="this_month")
def time_by_employee(s: Session, p: Params) -> Report:
    return _time_report(s, p, "time_by_employee", "Time Activities by Employee Detail", "worker")


@register("time_by_customer", "Time Activities by Customer Detail", "projects", "Hours logged per customer.",
          options=("customer", "employee"), default_preset="this_month")
def time_by_customer(s: Session, p: Params) -> Report:
    return _time_report(s, p, "time_by_customer", "Time Activities by Customer Detail", "customer")


@register("unbilled_time", "Unbilled Time", "sales", "Billable hours not yet on an invoice.",
          options=("customer",), default_preset="all")
def unbilled_time(s: Session, p: Params) -> Report:
    return _time_report(s, p, "unbilled_time", "Unbilled Time", "customer", unbilled=True)


@register("employee_contact_list", "Employee Contact List", "employees", "Phone and email per employee.",
          kind="list")
def employee_contact_list(s: Session, p: Params) -> Report:
    r = Report("employee_contact_list", "Employee Contact List", "")
    r.columns = [Col("name", "Employee", "text"), Col("phone", "Phone", "text"), Col("email", "Email", "text"),
                 Col("address", "Address", "text"), Col("hired", "Hire date", "date")]
    for e in s.scalars(select(Employee).where(Employee.active.is_(True)).order_by(Employee.display_name)):
        r.add({"name": e.display_name, "phone": e.phone or e.mobile or "", "email": e.email or "",
               "address": e.billing_address().replace("\n", ", "), "hired": e.hire_date}, 1, "data",
              link=f"/employees/{e.id}")
    return r


@register("mileage_log", "Mileage Log", "employees", "Business miles and the standard-rate deduction.",
          default_preset="this_year")
def mileage_log(s: Session, p: Params) -> Report:
    from pps_tools.books.models import MileageTrip
    from pps_tools.books.services.mileage import rate_on

    q = select(MileageTrip)
    if p.start:
        q = q.where(MileageTrip.date >= p.start)
    if p.end:
        q = q.where(MileageTrip.date <= p.end)
    r = Report("mileage_log", "Mileage Log", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("vehicle", "Vehicle", "text"), Col("route", "Route", "text"),
                 Col("purpose", "Purpose", "text"), Col("miles", "Miles", "qty"), Col("rate", "Rate", "rate"),
                 Col("deduction", "Deduction")]
    total_miles, total_ded = Decimal(0), 0
    for trip in s.scalars(q.order_by(MileageTrip.date)):
        rate = rate_on(s, trip.date) if trip.purpose == "business" else None
        ded = round_cents(rate * trip.miles) if rate is not None else 0
        r.add({"date": trip.date, "vehicle": trip.vehicle.name if trip.vehicle else "",
               "route": " → ".join(x for x in (trip.start_location, trip.end_location) if x),
               "purpose": trip.purpose.title(), "miles": trip.miles, "rate": rate, "deduction": ded or None}, 1, "data",
              link=f"/mileage/{trip.id}")
        if trip.purpose == "business":
            total_miles += trip.miles
            total_ded += ded
    r.add({"route": "TOTAL business miles", "miles": total_miles, "deduction": total_ded}, 0, "grand")
    return r


# -- banking --------------------------------------------------------------------------------------


@register("uncleared_transactions", "Uncleared Transactions", "banking",
          "Bank and card entries not yet marked cleared.", kind="as_of", options=("account",),
          default_preset="today")
def uncleared_transactions(s: Session, p: Params) -> Report:
    as_of = p.end or date.today()
    q = select(LedgerEntry).join(Account, Account.id == LedgerEntry.account_id).where(
        Account.type.in_(("bank", "credit_card")), LedgerEntry.cleared == "", LedgerEntry.date <= as_of)
    if p.account_id:
        q = q.where(LedgerEntry.account_id == p.account_id)
    ents = s.scalars(q.order_by(LedgerEntry.account_id, LedgerEntry.date)).all()
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_({e.txn_id for e in ents})))} \
        if ents else {}
    accounts = {a.id: a for a in s.scalars(select(Account))}
    r = Report("uncleared_transactions", "Uncleared Transactions", as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Name", "text"), Col("memo", "Memo", "text"), Col("amount", "Amount")]
    by_acct: dict = defaultdict(list)
    for e in ents:
        by_acct[e.account_id].append(e)
    for aid, rows in by_acct.items():
        a = accounts[aid]
        r.add({"type": a.display_name}, 0, "section")
        sub = 0
        for e in rows:
            t = txns[e.txn_id]
            amt = e.amount_cents * a.normal
            r.add({"date": e.date, "type": t.info.label, "num": t.number or "", "name": t.entity_name,
                   "memo": e.memo or "", "amount": amt}, 1, "data", link=txn_link(t.id))
            sub += amt
        r.add({"type": f"Total for {a.display_name}", "amount": sub}, 0, "subtotal")
    return r


@register("missing_checks", "Missing Checks", "banking", "Gaps and duplicates in your check numbers.",
          options=("account",), default_preset="this_year")
def missing_checks(s: Session, p: Params) -> Report:
    q = select(Transaction).join(Account, Account.id == Transaction.account_id).where(
        Transaction.type.in_(("check", "bill_payment")), Account.type == "bank")
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.account_id:
        q = q.where(Transaction.account_id == p.account_id)
    checks = [t for t in s.scalars(q) if t.number and t.number.isdigit()]
    checks.sort(key=lambda t: (t.account_id, int(t.number)))
    r = Report("missing_checks", "Missing Checks", period_label(p))
    r.columns = [Col("num", "Num", "text"), Col("date", "Date", "date"), Col("name", "Payee", "text"),
                 Col("note", "", "text"), Col("amount", "Amount")]
    prev = None
    seen = set()
    for t in checks:
        n = int(t.number)
        if prev is not None and prev[0] == t.account_id and n > prev[1] + 1:
            missing = f"{prev[1] + 1}" if n == prev[1] + 2 else f"{prev[1] + 1}–{n - 1}"
            r.add({"num": missing, "note": "*** Missing ***"}, 1, "note")
        note = "*** Duplicate ***" if (t.account_id, n) in seen else ("Void" if t.voided else "")
        seen.add((t.account_id, n))
        r.add({"num": t.number, "date": t.date, "name": t.entity_name, "note": note,
               "amount": 0 if t.voided else t.total_cents}, 1, "data", link=txn_link(t.id))
        prev = (t.account_id, n)
    return r


@register("reconciliation_reports", "Reconciliation Reports", "banking", "Past reconciliations by account.",
          kind="list", options=("account",))
def reconciliation_reports(s: Session, p: Params) -> Report:
    q = select(Reconciliation).order_by(Reconciliation.account_id, Reconciliation.statement_date.desc())
    if p.account_id:
        q = q.where(Reconciliation.account_id == p.account_id)
    r = Report("reconciliation_reports", "Reconciliation Reports", "")
    r.columns = [Col("account", "Account", "text"), Col("date", "Statement ending", "date"),
                 Col("status", "Status", "text"), Col("completed", "Reconciled on", "text"),
                 Col("ending", "Ending balance"), Col("adj", "Adjustment")]
    for rec in s.scalars(q):
        adj = rec.adjustment_txn_id and s.get(Transaction, rec.adjustment_txn_id)
        r.add({"account": rec.account.full_name, "date": rec.statement_date,
               "status": "Reconciled" if rec.status == "completed" else "In progress",
               "completed": f"{rec.completed_at:%m/%d/%Y}" if rec.completed_at else "",
               "ending": rec.ending_balance_cents, "adj": adj.total_cents if adj else None}, 1, "data",
              link=f"/banking/reconcile/{rec.id}/report")
    return r


@register("stripe_fees", "Stripe Fees", "banking", "Card and ACH processing fees by month.",
          default_preset="this_year")
def stripe_fees(s: Session, p: Params) -> Report:
    fee_acct = system_account_id(s, "merchant_fees")
    q = select(LedgerEntry).join(Transaction, Transaction.id == LedgerEntry.txn_id).where(
        LedgerEntry.account_id == fee_acct, Transaction.source == "stripe")
    if p.start:
        q = q.where(LedgerEntry.date >= p.start)
    if p.end:
        q = q.where(LedgerEntry.date <= p.end)
    by_month: dict = defaultdict(lambda: [0, 0])
    for e in s.scalars(q):
        key = e.date.replace(day=1)
        by_month[key][0] += e.amount_cents
        by_month[key][1] += 1
    sales_q = select(func.coalesce(func.sum(Transaction.total_cents), 0)).where(
        Transaction.type == "payment", Transaction.source == "stripe", Transaction.voided.is_(False))
    r = Report("stripe_fees", "Stripe Fees", period_label(p))
    r.columns = [Col("month", "Month", "text"), Col("count", "Charges", "int"), Col("collected", "Collected"),
                 Col("fees", "Fees"), Col("rate", "Effective rate", "pct")]
    tf = tc = 0
    for m in sorted(by_month):
        fees, count = by_month[m]
        end = D.month_end(m)
        collected = int(s.scalar(sales_q.where(Transaction.date >= m, Transaction.date <= end)) or 0)
        r.add({"month": m.strftime("%B %Y"), "count": count, "collected": collected, "fees": fees,
               "rate": pct(fees, collected)}, 1, "data")
        tf += fees
        tc += collected
    r.add({"month": "TOTAL", "collected": tc, "fees": tf, "rate": pct(tf, tc)}, 0, "grand")
    return r


@register("stripe_payouts", "Stripe Payouts", "banking", "Each payout from Stripe to your bank.",
          default_preset="this_year")
def stripe_payouts(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.type == "transfer", Transaction.source == "stripe",
                                  Transaction.voided.is_(False))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    r = Report("stripe_payouts", "Stripe Payouts", period_label(p))
    r.columns = [Col("date", "Arrival date", "date"), Col("payout", "Payout", "text"), Col("to", "Deposited to", "text"),
                 Col("amount", "Amount")]
    total = 0
    for t in s.scalars(q.order_by(Transaction.date)):
        r.add({"date": t.date, "payout": t.stripe_object_id or "", "to": t.to_account.full_name if t.to_account else "",
               "amount": t.total_cents}, 1, "data", link=txn_link(t.id))
        total += t.total_cents
    r.add({"payout": "TOTAL", "amount": total}, 0, "grand")
    return r


# -- accountant -------------------------------------------------------------------------------------


@register("audit_log", "Audit Log", "accountant", "Every change to your books: who, when, what.",
          options=("search",), default_preset="last_30_days")
def audit_log(s: Session, p: Params) -> Report:
    q = select(AuditLog).order_by(AuditLog.ts.desc())
    if p.start:
        q = q.where(AuditLog.ts >= datetime.combine(p.start, datetime.min.time()))
    if p.end:
        q = q.where(AuditLog.ts < datetime.combine(p.end + timedelta(days=1), datetime.min.time()))
    if p.txn_type:
        q = q.where(AuditLog.txn_type == p.txn_type)
    r = Report("audit_log", "Audit Log", period_label(p))
    r.columns = [Col("ts", "Date changed", "text"), Col("user", "User", "text"), Col("action", "Event", "text"),
                 Col("type", "Type", "text"), Col("date", "Transaction date", "date"), Col("name", "Name", "text"),
                 Col("amount", "Amount"), Col("summary", "Details", "text")]
    needle = (p.search or "").lower()
    for a in s.scalars(q.limit(5000)):
        if needle and needle not in (a.summary or "").lower() and needle not in (a.name or "").lower():
            continue
        link = txn_link(a.object_id) if a.object_type == "transaction" and a.action != "delete" else None
        r.add({"ts": f"{a.ts:%m/%d/%Y %I:%M %p}", "user": a.user_name or "", "action": a.action.replace("_", " ").title(),
               "type": TXN_TYPES[a.txn_type].label if a.txn_type in TXN_TYPES else a.object_type.title(),
               "date": a.txn_date, "name": a.name or "", "amount": a.amount_cents, "summary": a.summary}, 1, "data",
              link=link or f"/audit/{a.id}")
    return r


@register("closing_date_exceptions", "Exceptions to Closing Date", "accountant",
          "Changes made to transactions dated in a closed period.", kind="list")
def closing_date_exceptions(s: Session, p: Params) -> Report:
    company = company_info(s)
    r = Report("closing_date_exceptions", "Exceptions to Closing Date",
               f"Closing date {company.closing_date:%m/%d/%Y}" if company.closing_date else "No closing date set")
    r.columns = [Col("ts", "Date changed", "text"), Col("user", "User", "text"), Col("action", "Event", "text"),
                 Col("type", "Type", "text"), Col("date", "Transaction date", "date"), Col("amount", "Amount"),
                 Col("summary", "Details", "text")]
    if not company.closing_date:
        return r
    closed_at = s.scalar(select(func.max(AuditLog.ts)).where(AuditLog.action == "close_books"))
    q = select(AuditLog).where(AuditLog.object_type == "transaction", AuditLog.txn_date <= company.closing_date)
    if closed_at:
        q = q.where(AuditLog.ts > closed_at)
    for a in s.scalars(q.order_by(AuditLog.ts.desc())):
        r.add({"ts": f"{a.ts:%m/%d/%Y %I:%M %p}", "user": a.user_name or "", "action": a.action.title(),
               "type": TXN_TYPES[a.txn_type].label if a.txn_type in TXN_TYPES else "", "date": a.txn_date,
               "amount": a.amount_cents, "summary": a.summary}, 1, "data", link=f"/audit/{a.id}")
    return r


@register("recent_transactions", "Recent Transactions", "accountant", "Transactions entered in the last few days.",
          default_preset="last_7_days")
def recent_transactions(s: Session, p: Params) -> Report:
    start = datetime.combine(p.start or date.today() - timedelta(days=6), datetime.min.time())
    end = datetime.combine((p.end or date.today()) + timedelta(days=1), datetime.min.time())
    q = select(Transaction).where(Transaction.created_at >= start, Transaction.created_at < end)
    r = Report("recent_transactions", "Recent Transactions", f"Entered {period_label(p).lower()}")
    r.columns = [Col("created", "Entered", "text"), Col("date", "Date", "date"), Col("type", "Transaction type", "text"),
                 Col("num", "Num", "text"), Col("name", "Name", "text"), Col("source", "Source", "text"),
                 Col("amount", "Amount")]
    for t in s.scalars(q.order_by(Transaction.created_at.desc())):
        r.add({"created": f"{t.created_at:%m/%d %I:%M %p}", "date": t.date, "type": t.info.label, "num": t.number or "",
               "name": t.entity_name, "source": t.source.replace("_", " ").title(),
               "amount": 0 if t.voided else t.total_cents}, 1, "data", link=txn_link(t.id))
    return r


@register("automatic_transactions", "Recent Automatic Transactions", "accountant",
          "What recurring templates, Stripe and bank rules created on their own.", default_preset="last_30_days")
def automatic_transactions(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.source.in_(("stripe", "recurring", "bank_rule", "api")))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    r = Report("automatic_transactions", "Recent Automatic Transactions", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Name", "text"), Col("source", "Created by", "text"), Col("review", "Needs review", "text"),
                 Col("amount", "Amount")]
    for t in s.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc())):
        r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "name": t.entity_name,
               "source": t.source.replace("_", " ").title(), "review": "Yes" if t.needs_review else "",
               "amount": 0 if t.voided else t.total_cents}, 1, "data", link=txn_link(t.id))
    return r


@register("transaction_list_with_splits", "Transaction List with Splits", "accountant",
          "Each transaction with every account it touched.", options=("txn_type",), default_preset="this_month")
def transaction_list_with_splits(s: Session, p: Params) -> Report:
    from pps_tools.books.services.reports.financial import journal

    r = journal(s, p)
    r.key, r.title = "transaction_list_with_splits", "Transaction List with Splits"
    return r
