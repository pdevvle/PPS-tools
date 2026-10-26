"""Financial statements and ledger reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import ACCOUNT_TYPES, Account, LedgerEntry, Transaction
from pps_tools.books.services import cash_basis
from pps_tools.books.services import dates as D
from pps_tools.books.services.accounts import ordered_accounts, system_account_id
from pps_tools.books.services.reports.engine import (DIM_COLUMNS, Aggregator, Col, ColumnSpec, Params,
                                                     Report, Row, account_tree, as_of_label, company_info,
                                                     compare_range, customer_scope, entity_name_maps, pct,
                                                     period_columns, period_label, register, report_link,
                                                     rollup, txn_link)
from pps_tools.books.txn_types import TXN_TYPES

PL_SECTIONS = [
    ("income", "Income"),
    ("cogs", "Cost of Goods Sold"),
    ("expense", "Expenses"),
    ("other_income", "Other Income"),
    ("other_expense", "Other Expenses"),
]
CREDIT_NATURE = {"income", "other_income"}

BS_LAYOUT = [
    ("Assets", [
        ("Current Assets", [("bank", "Bank Accounts"), ("ar", "Accounts Receivable"),
                            ("other_current_asset", "Other Current Assets")]),
        (None, [("fixed_asset", "Fixed Assets")]),
        (None, [("other_asset", "Other Assets")]),
    ]),
    ("Liabilities and Equity", [
        ("Liabilities", [
            ("Current Liabilities", [("ap", "Accounts Payable"), ("credit_card", "Credit Cards"),
                                     ("other_current_liability", "Other Current Liabilities")]),
            (None, [("long_term_liability", "Long-Term Liabilities")]),
        ]),
        (None, [("equity", "Equity")]),
    ]),
]


def _dim_columns(s: Session, p: Params, agg: Aggregator, types: list[str]) -> tuple[list[ColumnSpec], dict]:
    """One column per customer/class/location... that has activity, plus Total."""
    dim = p.columns
    totals = agg.totals(p.start, p.end, dim)
    acct_types = dict(s.execute(select(Account.id, Account.type)).all())
    used = set()
    for (aid, dv), v in totals.items():
        if v and acct_types.get(aid) in types:
            used.add(dv)
    names = entity_name_maps(s)[dim]
    ordered = sorted([d for d in used if d is not None], key=lambda d: (names.get(d, "") or "").lower())
    cols = [ColumnSpec(f"d{d}", names.get(d, f"#{d}"), p.start, p.end, dim_value=d, kind="dim") for d in ordered]
    if None in used:
        cols.append(ColumnSpec("dnone", "Not specified", p.start, p.end, dim_value=None, kind="dim"))
    cols.append(ColumnSpec("total", "Total", p.start, p.end, is_total=True, kind="total"))
    values: dict[str, dict[int, int]] = {c.key: defaultdict(int) for c in cols}
    for (aid, dv), v in totals.items():
        key = f"d{dv}" if dv is not None else "dnone"
        if key in values:
            values[key][aid] += v
        values["total"][aid] += v
    return cols, values


def _pl_values(s: Session, p: Params, agg: Aggregator) -> tuple[list[ColumnSpec], dict[str, dict[int, int]]]:
    company = company_info(s)
    pl_types = [t for t, _ in PL_SECTIONS]
    if p.columns in DIM_COLUMNS:
        cols, values = _dim_columns(s, p, agg, pl_types)
    else:
        cols = period_columns(p, company.fiscal_year_start_month)
        values = {c.key: agg.by_account(c.start, c.end) for c in cols}
    if p.compare in ("prev_year", "prev_period") and p.columns == "total":
        cs, ce, label = compare_range(p)
        if cs:
            prev = ColumnSpec("prev", f"{label} ({cs:%b %d, %Y}–{ce:%b %d, %Y})", cs, ce, kind="compare")
            values["prev"] = agg.by_account(cs, ce)
            cols = [ColumnSpec("total", f"{p.start:%b %d, %Y}–{p.end:%b %d, %Y}" if p.start and p.end else "Total",
                               p.start, p.end, is_total=True, kind="total"), prev]
    return cols, values


def _report_columns(cols: list[ColumnSpec], p: Params, first: str = "Account") -> list[Col]:
    out = [Col("name", first, "text")]
    for c in cols:
        out.append(Col(c.key, c.label))
        if p.pct in ("income", "expense", "column") and c.kind != "compare":
            out.append(Col(f"{c.key}_pct", "% of Income" if p.pct == "income" else
                           ("% of Expense" if p.pct == "expense" else "% of Column"), "pct"))
    if any(c.kind == "compare" for c in cols):
        out.append(Col("chg", "$ Change"))
        out.append(Col("chg_pct", "% Change", "pct"))
    return out


@register("profit_and_loss", "Profit and Loss", "business",
          "Income and expenses for a period, and the net income they leave.",
          options=("columns", "compare", "pct", "basis", "customer", "class", "location", "item"))
def profit_and_loss(s: Session, p: Params) -> Report:
    agg = Aggregator.for_params(s, p)
    cols, values = _pl_values(s, p, agg)
    r = Report("profit_and_loss", "Profit and Loss", period_label(p), basis=p.basis)
    r.columns = _report_columns(cols, p)
    pl_types = [t for t, _ in PL_SECTIONS]
    used = {aid for vals in values.values() for aid, v in vals.items() if v}
    accounts = account_tree(s, pl_types, used)
    by_id = {a.id: a for a in accounts}

    def disp(acct_type: str, debit_sum: int) -> int:
        return -debit_sum if acct_type in CREDIT_NATURE else debit_sum

    section_totals: dict[str, dict[str, int]] = {}
    income_total = {c.key: sum(-values[c.key].get(a.id, 0) for a in accounts if a.type == "income") for c in cols}
    expense_total = {c.key: sum(values[c.key].get(a.id, 0) for a in accounts if a.type in ("expense", "cogs"))
                     for c in cols}

    def add_pct(cells: dict) -> None:
        for c in cols:
            if c.kind == "compare":
                continue
            if p.pct == "income":
                cells[f"{c.key}_pct"] = pct(cells.get(c.key, 0), income_total[c.key])
            elif p.pct == "expense":
                cells[f"{c.key}_pct"] = pct(cells.get(c.key, 0), expense_total[c.key])
        if "prev" in values:
            cur, prev = cells.get("total", 0), cells.get("prev", 0)
            cells["chg"] = cur - prev
            cells["chg_pct"] = pct(cur - prev, abs(prev)) if prev else None

    def drill(acct: Account, c: ColumnSpec) -> str:
        extra = {}
        if c.kind == "dim":
            extra[p.columns + "_id"] = c.dim_value
        return report_link("transaction_detail_by_account", p, account_id=acct.id, start=c.start, end=c.end,
                           preset="custom", columns="total", compare="none", pct="none", **extra)

    blocks: dict[str, list] = {}
    for acct_type, label in PL_SECTIONS:
        sec_accounts = [a for a in accounts if a.type == acct_type]
        totals = {c.key: sum(disp(acct_type, values[c.key].get(a.id, 0)) for a in sec_accounts) for c in cols}
        section_totals[acct_type] = totals
        active = any(values[c.key].get(a.id) for a in sec_accounts for c in cols)
        if not active and not p.include_zero and acct_type not in ("income", "expense"):
            blocks[acct_type] = []
            continue
        block = Report(r.key, r.title)
        block.add({"name": label}, 0, "section")
        _account_rows(block, sec_accounts, by_id, values, cols, lambda v, t=acct_type: disp(t, v), p, add_pct,
                      drill)
        cells = {"name": f"Total {label}", **totals}
        add_pct(cells)
        block.add(cells, 0, "subtotal")
        blocks[acct_type] = block.rows

    def total_row(name: str, vals: dict[str, int], kind: str = "total") -> Row:
        cells = {"name": name, **vals}
        add_pct(cells)
        return Row(cells, 0, kind)

    inc, cogs, exp = section_totals["income"], section_totals["cogs"], section_totals["expense"]
    oinc, oexp = section_totals["other_income"], section_totals["other_expense"]
    gp = {c.key: inc[c.key] - cogs[c.key] for c in cols}
    noi = {c.key: gp[c.key] - exp[c.key] for c in cols}
    noti = {c.key: oinc[c.key] - oexp[c.key] for c in cols}
    r.rows = blocks["income"] + blocks["cogs"] + [total_row("Gross Profit", gp)] + blocks["expense"] \
        + [total_row("Net Operating Income", noi)]
    if blocks["other_income"] or blocks["other_expense"]:
        r.rows += blocks["other_income"] + blocks["other_expense"] + [total_row("Net Other Income", noti)]
    r.rows.append(total_row("Net Income", {c.key: noi[c.key] + noti[c.key] for c in cols}, "grand"))
    return r


def _account_rows(r: Report, accounts: list[Account], by_id: dict[int, Account], values: dict[str, dict[int, int]],
                  cols: list[ColumnSpec], disp, p: Params, add_pct, drill, base_level: int = 1) -> None:
    """Account rows with sub-accounts nested under a parent and its total."""
    ids = {a.id for a in accounts}
    children: dict[Optional[int], list[Account]] = defaultdict(list)
    for a in accounts:
        parent = a.parent_id if a.parent_id in ids else None
        children[parent].append(a)
    rolled = {c.key: rollup(accounts, {aid: v for aid, v in values[c.key].items() if aid in ids}) for c in cols}

    def emit(a: Account, level: int) -> None:
        own = {c.key: disp(values[c.key].get(a.id, 0)) for c in cols}
        total = {c.key: disp(rolled[c.key].get(a.id, 0)) for c in cols}
        kids = children.get(a.id, [])
        if not p.include_zero and not any(total.values()) and not any(
                values[c.key].get(k.id) for k in kids for c in cols):
            return
        if kids and p.show_subaccounts:
            cells = {"name": a.display_name, **own}
            add_pct(cells)
            r.add(cells, level, "data", links={c.key: drill(a, c) for c in cols})
            for k in kids:
                emit(k, level + 1)
            cells = {"name": f"Total {a.display_name}", **total}
            add_pct(cells)
            r.add(cells, level, "subtotal")
        else:
            cells = {"name": a.display_name, **total}
            add_pct(cells)
            r.add(cells, level, "data", links={c.key: drill(a, c) for c in cols})

    for a in children.get(None, []):
        emit(a, base_level)


# -- balance sheet --------------------------------------------------------------------


def _bs_columns(p: Params, fy: int) -> list[ColumnSpec]:
    end = p.end or date.today()
    if p.columns in ("month", "quarter", "year") and p.start:
        fn = {"month": D.month_periods, "quarter": lambda a, b: D.quarter_periods(a, b, fy),
              "year": lambda a, b: D.year_periods(a, b, fy)}[p.columns]
        cols = [ColumnSpec(f"c{i}", f"As of {b:%b %d, %Y}", None, b) for i, (a, b, _) in enumerate(fn(p.start, end))]
        return cols
    cols = [ColumnSpec("total", "Total" if p.compare == "none" else f"As of {end:%b %d, %Y}", None, end,
                       is_total=True)]
    if p.compare in ("prev_year", "prev_period"):
        if p.compare == "prev_year":
            try:
                prev_end = end.replace(year=end.year - 1)
            except ValueError:
                prev_end = end - timedelta(days=365)
        else:
            prev_end = (p.start - timedelta(days=1)) if p.start else end - timedelta(days=30)
        cols.append(ColumnSpec("prev", f"As of {prev_end:%b %d, %Y}", None, prev_end, kind="compare"))
    return cols


def balance_sheet_values(s: Session, agg: Aggregator, as_of: date, fy_start_month: int) -> dict[int, int]:
    """Debit-positive balances as of the date, with prior years' income in
    Retained Earnings and this year's as a pseudo-account (key 0)."""
    balances = agg.by_account(None, as_of)
    types = dict(s.execute(select(Account.id, Account.type)).all())
    fy_start = D.fiscal_year_start(as_of, fy_start_month)
    out: dict[int, int] = defaultdict(int)
    prior_pl = 0
    for aid, v in balances.items():
        t = types.get(aid)
        if t is None:
            continue
        if ACCOUNT_TYPES[t].classification in ("income", "expense"):
            continue
        out[aid] += v
    pl_before = agg.by_account(None, fy_start - timedelta(days=1))
    for aid, v in pl_before.items():
        if ACCOUNT_TYPES[types.get(aid, "expense")].classification in ("income", "expense"):
            prior_pl += v
    pl_this_year = agg.by_account(fy_start, as_of)
    current = sum(v for aid, v in pl_this_year.items()
                  if ACCOUNT_TYPES[types.get(aid, "expense")].classification in ("income", "expense"))
    out[system_account_id(s, "retained_earnings")] += prior_pl
    out[0] = current  # Net Income (debit-positive; shown negated)
    return dict(out)


@register("balance_sheet", "Balance Sheet", "business",
          "What you own, what you owe, and equity, as of a date.", kind="as_of",
          options=("columns", "compare", "basis", "class", "location"), default_preset="this_year_to_date")
def balance_sheet(s: Session, p: Params) -> Report:
    company = company_info(s)
    agg = Aggregator(s, p.basis, class_id=p.class_id, location_id=p.location_id)
    cols = _bs_columns(p, company.fiscal_year_start_month)
    values = {c.key: balance_sheet_values(s, agg, c.end, company.fiscal_year_start_month) for c in cols}
    r = Report("balance_sheet", "Balance Sheet", as_of_label(p.end), basis=p.basis)
    r.columns = [Col("name", "", "text")] + [Col(c.key, c.label) for c in cols]
    if any(c.kind == "compare" for c in cols):
        r.columns += [Col("chg", "$ Change"), Col("chg_pct", "% Change", "pct")]
    used = {aid for vals in values.values() for aid, v in vals.items() if v}
    bs_types = [t for t, info in ACCOUNT_TYPES.items() if info.classification in ("asset", "liability", "equity")]
    accounts = account_tree(s, bs_types, used)
    by_id = {a.id: a for a in accounts}

    def add_chg(cells):
        if "prev" in values:
            cur, prev = cells.get("total", 0), cells.get("prev", 0)
            cells["chg"] = cur - prev
            cells["chg_pct"] = pct(cur - prev, abs(prev)) if prev else None

    def drill(acct: Account, c: ColumnSpec) -> str:
        return report_link("transaction_detail_by_account", p, account_id=acct.id, start=None, end=c.end,
                           preset="custom", columns="total", compare="none")

    def type_block(acct_type: str, label: str, level: int, sign: int) -> dict[str, int]:
        sec = [a for a in accounts if a.type == acct_type]
        totals = {c.key: sign * sum(values[c.key].get(a.id, 0) for a in sec) for c in cols}
        if acct_type == "equity":
            totals = {c.key: totals[c.key] - values[c.key].get(0, 0) for c in cols}
        if not sec and not any(totals.values()):
            return totals
        if not any(values[c.key].get(a.id) for a in sec for c in cols) and not any(totals.values()) \
                and not p.include_zero:
            return totals
        r.add({"name": label}, level, "section")
        _account_rows(r, sec, by_id, values, cols, lambda v: sign * v, p, add_chg, drill, base_level=level + 1)
        if acct_type == "equity":
            cells = {"name": "Net Income", **{c.key: -values[c.key].get(0, 0) for c in cols}}
            add_chg(cells)
            r.add(cells, level + 1, "data",
                  links={c.key: report_link("profit_and_loss", p,
                                            start=D.fiscal_year_start(c.end, company.fiscal_year_start_month),
                                            end=c.end, preset="custom", columns="total", compare="none")
                         for c in cols})
        cells = {"name": f"Total {label}", **totals}
        add_chg(cells)
        r.add(cells, level, "subtotal")
        return totals

    def group(spec, level: int, sign: int) -> dict[str, int]:
        title, parts = spec
        if title:
            r.add({"name": title}, level, "section")
        inner = level + (1 if title else 0)
        acc = {c.key: 0 for c in cols}
        for part in parts:
            if isinstance(part, tuple) and isinstance(part[1], list):
                sub = group(part, inner, sign)
            else:
                acct_type, label = part
                sub = type_block(acct_type, label, inner, sign)
            for k in acc:
                acc[k] += sub.get(k, 0)
        if title:
            cells = {"name": f"Total {title}", **acc}
            add_chg(cells)
            r.add(cells, level, "subtotal" if level else "total")
        return acc

    assets = group(BS_LAYOUT[0], 0, 1)
    r.rows[-1].kind = "grand"
    r.rows[-1].cells["name"] = "Total Assets"
    r.blank()
    liab_eq = group(BS_LAYOUT[1], 0, -1)
    r.rows[-1].kind = "grand"
    r.rows[-1].cells["name"] = "Total Liabilities and Equity"
    diff = {k: assets[k] - liab_eq[k] for k in assets}
    if any(diff.values()):
        r.notes.append("Assets and liabilities + equity differ by "
                       + ", ".join(f"{v / 100:,.2f}" for v in diff.values())
                       + ". This usually means entries were imported without a balancing account.")
    return r


# -- trial balance --------------------------------------------------------------------------


@register("trial_balance", "Trial Balance", "accountant",
          "Every account's debit or credit balance; the two columns total the same.", kind="as_of",
          options=("basis",))
def trial_balance(s: Session, p: Params) -> Report:
    company = company_info(s)
    as_of = p.end or date.today()
    agg = Aggregator(s, p.basis)
    fy_start = D.fiscal_year_start(as_of, company.fiscal_year_start_month)
    bs = balance_sheet_values(s, agg, as_of, company.fiscal_year_start_month)
    bs.pop(0, None)
    pl = agg.by_account(fy_start, as_of)
    types = dict(s.execute(select(Account.id, Account.type)).all())
    values: dict[int, int] = defaultdict(int)
    for aid, v in bs.items():
        values[aid] += v
    for aid, v in pl.items():
        if ACCOUNT_TYPES[types[aid]].classification in ("income", "expense"):
            values[aid] += v
    r = Report("trial_balance", "Trial Balance", as_of_label(as_of), basis=p.basis)
    r.columns = [Col("name", "", "text"), Col("debit", "Debit"), Col("credit", "Credit")]
    total_dr = total_cr = 0
    for a in ordered_accounts(s):
        v = values.get(a.id, 0)
        if not v and not p.include_zero:
            continue
        link = report_link("transaction_detail_by_account", p, account_id=a.id,
                           start=fy_start if not a.is_balance_sheet else None, end=as_of, preset="custom")
        r.add({"name": a.display_name, "debit": v if v > 0 else None, "credit": -v if v < 0 else None},
              1, "data", link=link)
        total_dr += max(v, 0)
        total_cr += max(-v, 0)
    r.add({"name": "TOTAL", "debit": total_dr, "credit": total_cr}, 0, "grand")
    return r


# -- statement of cash flows ----------------------------------------------------------------


@register("cash_flow", "Statement of Cash Flows", "business",
          "Where cash came from and went: operating, investing and financing.",
          options=("columns",))
def cash_flow(s: Session, p: Params) -> Report:
    company = company_info(s)
    cols = period_columns(p, company.fiscal_year_start_month)
    agg = Aggregator(s, "accrual")
    accounts = ordered_accounts(s)
    uf = system_account_id(s, "undeposited_funds")
    re_id = system_account_id(s, "retained_earnings")

    def is_cash(a: Account) -> bool:
        return a.type == "bank" or a.id == uf

    r = Report("cash_flow", "Statement of Cash Flows", period_label(p))
    r.columns = [Col("name", "", "text")] + [Col(c.key, c.label) for c in cols]
    period_vals = {c.key: agg.by_account(c.start, c.end) for c in cols}

    acct_by_id = {a.id: a for a in accounts}
    net_income = {c.key: -sum(v for aid, v in period_vals[c.key].items()
                              if aid in acct_by_id and not acct_by_id[aid].is_balance_sheet) for c in cols}

    def section(title: str, kinds: tuple[str, ...], include_ni: bool) -> dict[str, int]:
        r.add({"name": title}, 0, "section")
        totals = {c.key: 0 for c in cols}
        if include_ni:
            r.add({"name": "Net Income", **net_income}, 1, "data",
                  links={c.key: report_link("profit_and_loss", p, start=c.start, end=c.end, preset="custom",
                                            columns="total") for c in cols})
            for c in cols:
                totals[c.key] += net_income[c.key]
            r.add({"name": "Adjustments to reconcile Net Income to Net Cash provided by operations:"}, 1, "section")
        for a in accounts:
            if not a.is_balance_sheet or is_cash(a):
                continue
            kind = ACCOUNT_TYPES[a.type].cash_flow
            if a.id == re_id:
                kind = "financing"
            if kind not in kinds:
                continue
            vals = {c.key: -period_vals[c.key].get(a.id, 0) for c in cols}
            if not any(vals.values()):
                continue
            r.add({"name": a.display_name, **vals}, 2 if include_ni else 1, "data",
                  links={c.key: report_link("transaction_detail_by_account", p, account_id=a.id, start=c.start,
                                            end=c.end, preset="custom", columns="total") for c in cols})
            for c in cols:
                totals[c.key] += vals[c.key]
        label = {"Operating Activities": "Net cash provided by operating activities",
                 "Investing Activities": "Net cash provided by investing activities",
                 "Financing Activities": "Net cash provided by financing activities"}[title]
        r.add({"name": label, **totals}, 0, "subtotal")
        return totals

    op = section("Operating Activities", ("operating",), True)
    inv = section("Investing Activities", ("investing",), False)
    fin = section("Financing Activities", ("financing",), False)
    net = {c.key: op[c.key] + inv[c.key] + fin[c.key] for c in cols}
    r.add({"name": "Net cash increase for period", **net}, 0, "total")
    cash_ids = [a.id for a in accounts if is_cash(a)]
    begin = {}
    for c in cols:
        before = c.start - timedelta(days=1) if c.start else None
        begin[c.key] = sum(agg.by_account(None, before).get(aid, 0) for aid in cash_ids) if before else 0
    r.add({"name": "Cash at beginning of period", **begin}, 0, "data")
    r.add({"name": "Cash at end of period", **{k: begin[k] + net[k] for k in net}}, 0, "grand")
    return r


# -- detail reports over ledger entries -------------------------------------------------------


def _split_map(s: Session, txn_ids: set[int]) -> dict[int, dict[int, str]]:
    """For each transaction, per entry account, the 'split' column: the other
    account when there's exactly one, else '-Split-'."""
    if not txn_ids:
        return {}
    names = {a.id: a.display_name for a in s.scalars(select(Account))}
    per_txn: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for tid, aid, amt in s.execute(select(LedgerEntry.txn_id, LedgerEntry.account_id, LedgerEntry.amount_cents)
                                   .where(LedgerEntry.txn_id.in_(list(txn_ids)))):
        per_txn[tid].append((aid, amt))
    out: dict[int, dict[int, str]] = {}
    for tid, rows in per_txn.items():
        accts = {aid for aid, _ in rows}
        m = {}
        for aid in accts:
            others = accts - {aid}
            m[aid] = names.get(next(iter(others)), "") if len(others) == 1 else ("-Split-" if others else "")
        out[tid] = m
    return out


def _entry_name(e, txn: Transaction, names: dict[str, dict[int, str]]) -> str:
    if e.customer_id:
        return names["customer"].get(e.customer_id, "")
    if e.vendor_id:
        return names["vendor"].get(e.vendor_id, "")
    if e.employee_id:
        return names["employee"].get(e.employee_id, "")
    return txn.entity_name


def _ledger_rows(s: Session, p: Params, account_ids: Optional[list[int]], start: Optional[date],
                 end: Optional[date]):
    """Ledger entries (accrual or cash) in the period, with their transactions."""
    agg = Aggregator.for_params(s, p)
    if p.basis == "cash":
        ents = [e for e in agg._cash() if (start is None or e.date >= start) and (end is None or e.date <= end)
                and (account_ids is None or e.account_id in account_ids)]
    else:
        q = select(LedgerEntry).where(*([LedgerEntry.date >= start] if start else []),
                                      *([LedgerEntry.date <= end] if end else []))
        if account_ids is not None:
            q = q.where(LedgerEntry.account_id.in_(account_ids))
        q = agg._filters_sql(q)
        ents = list(s.scalars(q))
    txn_ids = {e.txn_id for e in ents}
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_(list(txn_ids))))} \
        if txn_ids else {}
    if p.txn_type:
        ents = [e for e in ents if txns[e.txn_id].type == p.txn_type]
    if p.search:
        needle = p.search.lower()
        ents = [e for e in ents if needle in (e.memo or "").lower() or needle in (txns[e.txn_id].number or "").lower()
                or needle in txns[e.txn_id].entity_name.lower()]
    ents.sort(key=lambda e: (e.date, e.txn_id, getattr(e, "position", 0) or 0))
    return ents, txns


DETAIL_COLS = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
               Col("name", "Name", "text"), Col("memo", "Memo/Description", "text"), Col("split", "Split", "text"),
               Col("amount", "Amount"), Col("balance", "Balance")]


def _detail_by_account(s: Session, p: Params, key: str, title: str, with_opening: bool,
                       types: Optional[list[str]] = None) -> Report:
    company = company_info(s)
    names = entity_name_maps(s)
    accounts = ordered_accounts(s, types=types)
    if p.account_id:
        from pps_tools.books.services.accounts import descendant_ids

        keep = set(descendant_ids(s, p.account_id))
        accounts = [a for a in accounts if a.id in keep]
    ids = [a.id for a in accounts]
    ents, txns = _ledger_rows(s, p, ids, p.start, p.end)
    splits = _split_map(s, {e.txn_id for e in ents}) if p.basis != "cash" else {}
    by_acct: dict[int, list] = defaultdict(list)
    for e in ents:
        by_acct[e.account_id].append(e)
    agg = Aggregator.for_params(s, p)
    opening: dict[int, int] = {}
    if with_opening and p.start:
        before = p.start - timedelta(days=1)
        bal_all = agg.by_account(None, before)
        fy_start = D.fiscal_year_start(p.start, company.fiscal_year_start_month)
        pl_ytd = agg.by_account(fy_start, before) if fy_start <= before else {}
        for a in accounts:
            opening[a.id] = bal_all.get(a.id, 0) if a.is_balance_sheet else pl_ytd.get(a.id, 0)
    r = Report(key, title, period_label(p), basis=p.basis)
    r.columns = list(DETAIL_COLS) if with_opening else [c for c in DETAIL_COLS]
    grand = 0
    for a in accounts:
        rows = by_acct.get(a.id, [])
        open_bal = opening.get(a.id, 0)
        if not rows and not open_bal:
            continue
        sign = a.normal if p.group_by != "raw" else 1
        r.add({"name": a.display_name}, 0, "section", link=f"/accounts/{a.id}/register" if a.is_balance_sheet else None)
        running = sign * open_bal
        if with_opening and p.start:
            r.add({"date": None, "type": "Beginning Balance", "balance": running}, 1, "data")
        total = 0
        for e in rows:
            t = txns[e.txn_id]
            amt = sign * e.amount_cents
            running += amt
            total += amt
            r.add({"date": e.date, "type": TXN_TYPES[t.type].label, "num": t.number or "",
                   "name": _entry_name(e, t, names), "memo": e.memo or t.memo or "",
                   "split": splits.get(t.id, {}).get(e.account_id, ""), "amount": amt, "balance": running},
                  1, "data", link=txn_link(t.id))
        r.add({"name": f"Total for {a.display_name}", "amount": total,
               "balance": running if with_opening else None}, 0, "subtotal")
        grand += total
    return r


@register("general_ledger", "General Ledger", "accountant",
          "Every transaction in every account, with running balances.",
          options=("basis", "account", "customer", "vendor", "class", "location", "txn_type", "search"),
          default_preset="this_month")
def general_ledger(s: Session, p: Params) -> Report:
    return _detail_by_account(s, p, "general_ledger", "General Ledger", True)


@register("transaction_detail_by_account", "Transaction Detail by Account", "accountant",
          "Transactions grouped by account for a period.",
          options=("basis", "account", "customer", "vendor", "class", "location", "item", "txn_type", "search"),
          default_preset="this_month")
def transaction_detail_by_account(s: Session, p: Params) -> Report:
    return _detail_by_account(s, p, "transaction_detail_by_account", "Transaction Detail by Account", False)


@register("profit_and_loss_detail", "Profit and Loss Detail", "business",
          "Every income and expense transaction for a period, by account.",
          options=("basis", "customer", "vendor", "class", "location"), default_preset="this_month")
def profit_and_loss_detail(s: Session, p: Params) -> Report:
    return _detail_by_account(s, p, "profit_and_loss_detail", "Profit and Loss Detail", False,
                              types=[t for t, _ in PL_SECTIONS])


@register("balance_sheet_detail", "Balance Sheet Detail", "business",
          "Activity in every balance sheet account, with balances.", options=("basis",),
          default_preset="this_month")
def balance_sheet_detail(s: Session, p: Params) -> Report:
    bs_types = [t for t, info in ACCOUNT_TYPES.items() if info.classification in ("asset", "liability", "equity")]
    return _detail_by_account(s, p, "balance_sheet_detail", "Balance Sheet Detail", True, types=bs_types)


@register("journal", "Journal", "accountant", "Debits and credits of every transaction.",
          options=("txn_type", "search"), default_preset="this_month")
def journal(s: Session, p: Params) -> Report:
    names = entity_name_maps(s)
    accts = {a.id: a.display_name for a in s.scalars(select(Account))}
    ents, txns = _ledger_rows(s, p.copy(basis="accrual"), None, p.start, p.end)
    r = Report("journal", "Journal", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Name", "text"), Col("memo", "Memo/Description", "text"),
                 Col("account", "Account", "text"), Col("debit", "Debit"), Col("credit", "Credit")]
    by_txn: dict[int, list] = defaultdict(list)
    for e in ents:
        by_txn[e.txn_id].append(e)
    total_dr = total_cr = 0
    for tid in sorted(by_txn, key=lambda t: (txns[t].date, t)):
        t = txns[tid]
        first = True
        dr = cr = 0
        for e in sorted(by_txn[tid], key=lambda e: (-(e.amount_cents > 0), e.position)):
            cells = {"account": accts.get(e.account_id, ""), "memo": e.memo or "",
                     "name": _entry_name(e, t, names),
                     "debit": e.amount_cents if e.amount_cents > 0 else None,
                     "credit": -e.amount_cents if e.amount_cents < 0 else None}
            if first:
                cells.update({"date": t.date, "type": TXN_TYPES[t.type].label, "num": t.number or ""})
                first = False
            r.add(cells, 1, "data", link=txn_link(t.id))
            dr += max(e.amount_cents, 0)
            cr += max(-e.amount_cents, 0)
        r.add({"debit": dr, "credit": cr}, 1, "subtotal")
        total_dr += dr
        total_cr += cr
    r.add({"name": "TOTAL", "debit": total_dr, "credit": total_cr}, 0, "grand")
    return r


@register("transaction_list", "Transaction List by Date", "accountant",
          "One line per transaction, in date order.",
          options=("txn_type", "customer", "vendor", "account", "search"), default_preset="this_month")
def transaction_list(s: Session, p: Params) -> Report:
    q = select(Transaction).where(*([Transaction.date >= p.start] if p.start else []),
                                  *([Transaction.date <= p.end] if p.end else []))
    if p.txn_type:
        q = q.where(Transaction.type == p.txn_type)
    if p.customer_id:
        q = q.where(Transaction.customer_id.in_(customer_scope(s, p.customer_id)))
    if p.vendor_id:
        q = q.where(Transaction.vendor_id == p.vendor_id)
    txns = s.scalars(q.order_by(Transaction.date, Transaction.id)).all()
    if p.account_id:
        ids = set(s.scalars(select(LedgerEntry.txn_id).where(LedgerEntry.account_id == p.account_id)))
        txns = [t for t in txns if t.id in ids or t.account_id == p.account_id]
    if p.search:
        needle = p.search.lower()
        txns = [t for t in txns if needle in (t.memo or "").lower() or needle in (t.number or "").lower()
                or needle in t.entity_name.lower()]
    accts = {a.id: a.display_name for a in s.scalars(select(Account))}
    splits = _split_map(s, {t.id for t in txns})
    r = Report("transaction_list", "Transaction List by Date", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("posting", "Posting", "text"), Col("name", "Name", "text"),
                 Col("memo", "Memo/Description", "text"), Col("account", "Account", "text"),
                 Col("split", "Split", "text"), Col("amount", "Amount")]
    for t in txns:
        main = t.account_id or t.ar_ap_account_id
        r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "posting": "Yes" if t.info.posts
               and not t.voided else "No", "name": t.entity_name, "memo": t.memo or "",
               "account": accts.get(main, "") if main else "",
               "split": splits.get(t.id, {}).get(main, "") if main else "",
               "amount": 0 if t.voided else t.total_cents}, 1, "data", link=txn_link(t.id))
    return r


@register("account_list", "Account List", "accountant", "Your chart of accounts with balances.", kind="list")
def account_list(s: Session, p: Params) -> Report:
    from pps_tools.books.services.accounts import balances_by_account

    bals = balances_by_account(s)
    r = Report("account_list", "Account List", "")
    r.columns = [Col("number", "Number", "text"), Col("name", "Account", "text"), Col("type", "Type", "text"),
                 Col("detail", "Detail type", "text"), Col("description", "Description", "text"),
                 Col("balance", "Balance")]
    for a in ordered_accounts(s):
        r.add({"number": a.number or "", "name": a.full_name, "type": a.type_label, "detail": a.detail_type or "",
               "description": a.description or "",
               "balance": bals.get(a.id, 0) * a.normal if a.is_balance_sheet else None},
              a.depth, "data", link=f"/accounts/{a.id}/register" if a.is_balance_sheet else None)
    return r


@register("pl_by_month", "Profit and Loss by Month", "business", "Income and expenses month by month.",
          options=("basis", "class", "location"))
def pl_by_month(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="month"))
    r.key, r.title = "pl_by_month", "Profit and Loss by Month"
    return r


@register("pl_by_customer", "Profit and Loss by Customer", "business", "Income and expenses per customer.",
          options=("basis", "class", "location"))
def pl_by_customer(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="customer"))
    r.key, r.title = "pl_by_customer", "Profit and Loss by Customer"
    return r


@register("pl_by_class", "Profit and Loss by Class", "business", "Income and expenses per class.",
          options=("basis", "location"))
def pl_by_class(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="class"))
    r.key, r.title = "pl_by_class", "Profit and Loss by Class"
    return r


@register("pl_by_location", "Profit and Loss by Location", "business", "Income and expenses per location.",
          options=("basis", "class"))
def pl_by_location(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="location"))
    r.key, r.title = "pl_by_location", "Profit and Loss by Location"
    return r


@register("pl_comparison", "Profit and Loss Comparison", "business",
          "This period against the same period last year.", options=("basis", "class", "location"))
def pl_comparison(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="total", compare="prev_year" if p.compare == "none" else p.compare))
    r.key, r.title = "pl_comparison", "Profit and Loss Comparison"
    return r


@register("pl_pct_income", "Profit and Loss as % of Total Income", "business",
          "Each line as a share of income.", options=("basis", "columns"))
def pl_pct_income(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(pct="income"))
    r.key, r.title = "pl_pct_income", "Profit and Loss as % of Total Income"
    return r


@register("quarterly_pl", "Quarterly Profit and Loss Summary", "business", "Income and expenses by quarter.",
          options=("basis",), default_preset="this_year")
def quarterly_pl(s: Session, p: Params) -> Report:
    r = profit_and_loss(s, p.copy(columns="quarter"))
    r.key, r.title = "quarterly_pl", "Quarterly Profit and Loss Summary"
    return r


@register("balance_sheet_comparison", "Balance Sheet Comparison", "business",
          "Balances now against a year ago.", kind="as_of", options=("basis",))
def balance_sheet_comparison(s: Session, p: Params) -> Report:
    r = balance_sheet(s, p.copy(compare="prev_year" if p.compare == "none" else p.compare, columns="total"))
    r.key, r.title = "balance_sheet_comparison", "Balance Sheet Comparison"
    return r


@register("business_snapshot", "Business Snapshot", "business",
          "Income, expenses, and balances at a glance.", options=())
def business_snapshot(s: Session, p: Params) -> Report:
    pl = profit_and_loss(s, p.copy(columns="total", compare="prev_year", pct="none"))
    r = Report("business_snapshot", "Business Snapshot", period_label(p))
    r.columns = [Col("name", "", "text"), Col("total", "This period"), Col("prev", "Last year")]
    for row in pl.rows:
        if row.kind in ("subtotal", "total", "grand"):
            r.add({"name": row.cells.get("name"), "total": row.cells.get("total"), "prev": row.cells.get("prev")},
                  0, row.kind)
    return r


def net_income(s: Session, start: Optional[date], end: Optional[date], basis: str = "accrual") -> int:
    agg = Aggregator(s, basis)
    types = dict(s.execute(select(Account.id, Account.type)).all())
    return -sum(v for aid, v in agg.by_account(start, end).items()
                if ACCOUNT_TYPES[types[aid]].classification in ("income", "expense"))


def pl_summary(s: Session, start: Optional[date], end: Optional[date], basis: str = "accrual") -> dict[str, int]:
    agg = Aggregator(s, basis)
    types = dict(s.execute(select(Account.id, Account.type)).all())
    out = {"income": 0, "cogs": 0, "expense": 0, "other_income": 0, "other_expense": 0}
    for aid, v in agg.by_account(start, end).items():
        t = types[aid]
        if t in out:
            out[t] += -v if t in CREDIT_NATURE else v
    out["net"] = out["income"] + out["other_income"] - out["cogs"] - out["expense"] - out["other_expense"]
    return out
