"""Chart of accounts, account registers, journal entries, closing the books."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books import money
from pps_tools.books.models import ACCOUNT_TYPES, DETAIL_TYPES, Account, LedgerEntry, Transaction
from pps_tools.books.services import audit, closing
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import (account_in_use, balances_by_account, ordered_accounts,
                                               system_account_id, validate_account)
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError
from pps_tools.books.services.reports.financial import _split_map
from pps_tools.books.web import core
from pps_tools.books.web.sales import filtered_txns

bp = Blueprint("accounting", __name__)


@bp.route("/accounts")
@core.requires("accounting.view")
def chart():
    s = core.db()
    show = request.args.get("show", "active")
    accounts = ordered_accounts(s, active_only=(show == "active"))
    if show == "inactive":
        accounts = [a for a in accounts if not a.active]
    needle = (request.args.get("q") or "").strip().lower()
    if needle:
        accounts = [a for a in accounts if needle in a.full_name.lower() or needle in (a.number or "")]
    filt = request.args.get("type")
    if filt in ACCOUNT_TYPES:
        accounts = [a for a in accounts if a.type == filt]
    from pps_tools.books.services.reports.engine import rollup

    # A parent's balance includes its sub-accounts, as in QBO.
    bals = rollup(ordered_accounts(s), balances_by_account(s))
    return render_template("accounting/chart.html", accounts=accounts, bals=bals, show=show, types=ACCOUNT_TYPES)


@bp.route("/accounts/new", methods=["GET", "POST"])
@core.requires("accounting.edit")
def account_new():
    acct = Account(type=request.args.get("type", "expense"), active=True)
    if acct.type not in ACCOUNT_TYPES:
        acct.type = "expense"
    return _account_form(acct)


@bp.route("/accounts/<int:account_id>/edit", methods=["GET", "POST"])
@core.requires("accounting.edit")
def account_edit(account_id: int):
    acct = core.db().get(Account, account_id) or abort(404)
    return _account_form(acct)


def _account_form(acct: Account):
    s = core.db()
    if request.method == "POST":
        is_new = acct.id is None
        try:
            acct.name = core.f("name") or ""
            acct.number = core.f("number") or None
            new_type = core.f("type") or acct.type
            if not is_new and new_type != acct.type and acct.system_key:
                from pps_tools.books.services.errors import ValidationError

                raise ValidationError("The type of a system account can't be changed.", "type")
            if not is_new and new_type != acct.type and ACCOUNT_TYPES[new_type].classification != \
                    ACCOUNT_TYPES[acct.type].classification and account_in_use(s, acct.id):
                from pps_tools.books.services.errors import ValidationError

                raise ValidationError("This account has transactions, so it can only change to a type in the same "
                                      "group (asset, liability, equity, income or expense).", "type")
            acct.type = new_type
            acct.detail_type = core.f("detail_type") or None
            acct.parent_id = core.f_int("parent_id")
            acct.description = core.f("description") or None
            acct.bank_name = core.f("bank_name") or None
            acct.bank_last4 = core.f("bank_last4") or None
            acct.tax_line = core.f("tax_line") or None
            acct.form_1099_box = core.f("form_1099_box") or None
            if core.f("next_check_number"):
                acct.next_check_number = int(core.f("next_check_number"))
            if not is_new:
                acct.active = core.f_bool("active")
                if not acct.active and acct.system_key:
                    from pps_tools.books.services.errors import ValidationError

                    raise ValidationError("System accounts can't be made inactive.")
            validate_account(s, acct)
            if is_new:
                s.add(acct)
            s.flush()
            opening = money.cents(core.f("opening_balance") or "0")
            if is_new and opening and acct.is_balance_sheet:
                as_of = core.f("opening_balance_date") or date.today().isoformat()
                obe = system_account_id(s, "opening_balance_equity")
                debit = opening if acct.normal == 1 else -opening
                lines = [{"account_id": acct.id, "debit_cents": debit} if debit > 0 else
                         {"account_id": acct.id, "credit_cents": -debit},
                         {"account_id": obe, "credit_cents": debit} if debit > 0 else
                         {"account_id": obe, "debit_cents": -debit}]
                tx.save(s, {"type": "journal_entry", "date": as_of, "memo": f"Opening balance for {acct.name}",
                            "lines": lines}, user=core.current_user(), source="opening")
            audit.record(s, core.current_user(), "create" if is_new else "update", "account", acct.id,
                         name=acct.full_name, summary=f"{'Added' if is_new else 'Updated'} account {acct.full_name}")
            s.commit()
        except (BooksError, money.MoneyError, ValueError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_account(acct), 422
        flash(f"Account {acct.full_name} saved.", "success")
        return redirect(core.safe_next(url_for("accounting.chart")))
    return _render_account(acct)


def _render_account(acct: Account):
    s = core.db()
    parents = [a for a in ordered_accounts(s, active_only=True) if a.id != acct.id]
    from pps_tools.books.services.reports.other import BOXES_1099

    return render_template("accounting/account_form.html", acct=acct, types=ACCOUNT_TYPES, detail_types=DETAIL_TYPES,
                           parents=parents, boxes=BOXES_1099,
                           in_use=bool(acct.id and account_in_use(s, acct.id)))


@bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
@core.requires("accounting.edit")
def account_delete(account_id: int):
    s = core.db()
    acct = s.get(Account, account_id) or abort(404)
    if acct.system_key:
        flash("System accounts can't be deleted.", "error")
    elif account_in_use(s, acct.id):
        flash("This account has transactions. Make it inactive instead.", "error")
    elif acct.children:
        flash("Move or delete its sub-accounts first.", "error")
    else:
        name = acct.full_name
        s.delete(acct)
        audit.record(s, core.current_user(), "delete", "account", account_id, name=name, summary=f"Deleted account {name}")
        s.commit()
        flash(f"Deleted {name}.", "success")
        return redirect(url_for("accounting.chart"))
    return redirect(url_for("accounting.account_edit", account_id=account_id))


@bp.route("/accounts/<int:account_id>/register")
@core.requires("accounting.view")
def register(account_id: int):
    """Every transaction in a balance-sheet account with a running balance."""
    s = core.db()
    acct = s.get(Account, account_id) or abort(404)
    from pps_tools.books.services.accounts import descendant_ids

    ids = descendant_ids(s, acct.id)
    start = parse_date(request.args.get("start")) if request.args.get("start") else None
    end = parse_date(request.args.get("end")) if request.args.get("end") else None
    q = select(LedgerEntry).where(LedgerEntry.account_id.in_(ids))
    if end:
        q = q.where(LedgerEntry.date <= end)
    cleared = request.args.get("cleared")
    entries = s.scalars(q.order_by(LedgerEntry.date, LedgerEntry.txn_id, LedgerEntry.position)).all()
    running = 0
    rows = []
    for e in entries:
        running += e.amount_cents * acct.normal
        if start and e.date < start:
            continue
        if cleared == "uncleared" and e.cleared:
            continue
        if cleared == "cleared" and not e.cleared:
            continue
        rows.append((e, running))
    opening = 0
    if start:
        opening = sum(e.amount_cents for e in entries if e.date < start) * acct.normal
    txn_ids = {e.txn_id for e, _ in rows}
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_(txn_ids)))} if txn_ids else {}
    splits = _split_map(s, txn_ids)
    rows.reverse()  # newest first, as a register reads
    total = len(rows)
    page, offset, pages = core.paginate(total, 100)
    return render_template("accounting/register.html", acct=acct, rows=rows[offset:offset + 100], txns=txns,
                           splits=splits, page=page, pages=pages, opening=opening, start=start, end=end,
                           balance=running, cleared=cleared)


@bp.route("/accounts/<int:account_id>/cleared/<int:entry_id>", methods=["POST"])
@core.requires("reconcile")
def toggle_cleared(account_id: int, entry_id: int):
    s = core.db()
    e = s.get(LedgerEntry, entry_id) or abort(404)
    if e.cleared == "R":
        flash("That entry is reconciled. Undo the reconciliation to change it.", "error")
    else:
        e.cleared = "" if e.cleared == "C" else "C"
        s.commit()
    return redirect(request.referrer or url_for("accounting.register", account_id=account_id))


@bp.route("/journal-entries")
@core.requires("accounting.view")
def journal_entries():
    rows, total, page, pages, sums = filtered_txns(("journal_entry",))
    return render_template("accounting/journal_entries.html", rows=rows, total=total, page=page, pages=pages)


@bp.route("/accounting/close", methods=["GET", "POST"])
@core.requires("close_books")
def close_books():
    s = core.db()
    company = core.company()
    if request.method == "POST":
        when = parse_date(core.f("closing_date")) if core.f("closing_date") else None
        pw = request.form.get("closing_password")
        clear_pw = core.f_bool("clear_password")
        closing.set_closing(s, when, password="" if clear_pw else (pw if pw else None))
        audit.record(s, core.current_user(), "close_books", "company", 1,
                     summary=f"Closing date set to {when:%m/%d/%Y}" if when else "Closing date removed")
        s.commit()
        flash(f"Books closed through {when:%m/%d/%Y}." if when else "Closing date removed.", "success")
        return redirect(url_for("accounting.close_books"))
    from pps_tools.books.services.dates import fiscal_year_start
    from datetime import timedelta

    suggested = fiscal_year_start(core.today(), company.fiscal_year_start_month) - timedelta(days=1)
    return render_template("accounting/close.html", company=company, suggested=suggested)
