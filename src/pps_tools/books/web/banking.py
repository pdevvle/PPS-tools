"""Banking: bank feed review, imports, rules, reconciliation, receipts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books import money
from pps_tools.books.models import (Account, Attachment, BankFeedItem, BankImportBatch, BankRule, Customer, LedgerEntry,
                                    Reconciliation, Tag, TrackingClass, Transaction, Vendor)
from pps_tools.books.services import banking as bank_service
from pps_tools.books.services.accounts import balances_by_account, ordered_accounts
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.services.importers.bankfiles import ParseError, parse
from pps_tools.books.web import core

bp = Blueprint("banking", __name__)


def _feed_accounts():
    s = core.db()
    return [a for a in ordered_accounts(s, active_only=True, types=["bank", "credit_card"])]


@bp.route("/banking")
@core.requires("banking.view")
def feed():
    s = core.db()
    accounts = _feed_accounts()
    if not accounts:
        flash("Add a bank or credit card account first.", "info")
        return redirect(url_for("accounting.account_new", type="bank"))
    account_id = request.args.get("account_id", type=int)
    counts = dict(s.execute(select(BankFeedItem.account_id, func.count(BankFeedItem.id))
                            .where(BankFeedItem.status == "review").group_by(BankFeedItem.account_id)).all())
    if account_id is None:
        account_id = next((a.id for a in accounts if counts.get(a.id)), accounts[0].id)
    account = s.get(Account, account_id) or abort(404)
    tab = request.args.get("tab", "review")
    statuses = {"review": ("review",), "categorized": ("added", "matched"), "excluded": ("excluded",)}[
        tab if tab in ("review", "categorized", "excluded") else "review"]
    q = select(BankFeedItem).where(BankFeedItem.account_id == account.id, BankFeedItem.status.in_(statuses))
    needle = (request.args.get("q") or "").strip()
    if needle:
        q = q.where(BankFeedItem.description.ilike(f"%{needle}%"))
    direction = request.args.get("dir")
    if direction == "in":
        q = q.where(BankFeedItem.amount_cents > 0)
    elif direction == "out":
        q = q.where(BankFeedItem.amount_cents < 0)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    page, offset, pages = core.paginate(total, 50)
    items = s.scalars(q.order_by(BankFeedItem.date.desc(), BankFeedItem.id.desc()).offset(offset).limit(50)).all()
    matches = {it.id: bank_service.find_matches(s, it) for it in items} if tab == "review" else {}
    books = balances_by_account(s).get(account.id, 0) * account.normal
    batch = s.scalars(select(BankImportBatch).where(BankImportBatch.account_id == account.id,
                                                    BankImportBatch.statement_balance_cents.isnot(None))
                      .order_by(BankImportBatch.created_at.desc()).limit(1)).first()
    all_accounts = ordered_accounts(s, active_only=True)
    return render_template(
        "banking/feed.html", accounts=accounts, account=account, counts=counts, tab=tab, items=items, page=page,
        pages=pages, total=total, matches=matches, books=books, bank_balance=batch.statement_balance_cents if batch else None,
        bank_balance_date=batch.statement_balance_date if batch else None,
        categories=[a for a in all_accounts if a.id != account.id and a.type not in ("ar", "ap")],
        vendors=s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
        customers=s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all(),
        classes=s.scalars(select(TrackingClass).where(TrackingClass.active.is_(True))).all(),
        tags=s.scalars(select(Tag)).all(), config_ai=bool(core.config().anthropic_api_key))


def _item(item_id: int) -> BankFeedItem:
    return core.db().get(BankFeedItem, item_id) or abort(404)


@bp.route("/banking/item/<int:item_id>", methods=["POST"])
@core.requires("banking.edit")
def act(item_id: int):
    s = core.db()
    item = _item(item_id)
    action = core.f("action")
    user = core.current_user()
    try:
        if action == "add":
            vendor_id = customer_id = None
            payee = core.f("payee") or ""
            if payee.startswith("vendor:"):
                vendor_id = int(payee.split(":")[1])
            elif payee.startswith("customer:"):
                customer_id = int(payee.split(":")[1])
            elif payee.startswith("new:"):
                name = payee[4:].strip() or item.payee
                existing = s.scalar(select(Vendor).where(func.lower(Vendor.display_name) == name.lower()))
                if existing is None:
                    existing = Vendor(display_name=name)
                    s.add(existing)
                    s.flush()
                vendor_id = existing.id
            splits = None
            if core.f("mode") == "split":
                splits = []
                for row in core.indexed_rows("sp"):
                    if row.get("account_id"):
                        splits.append({"account_id": int(row["account_id"]),
                                       "amount_cents": money.cents(row.get("amount") or "0"),
                                       "description": row.get("description") or None,
                                       "customer_id": int(row["customer_id"]) if row.get("customer_id") else None})
            txn = bank_service.add_from_feed(
                s, item, user, account_id=core.f_int("account_id"), vendor_id=vendor_id, customer_id=customer_id,
                memo=core.f("memo"), splits=splits, kind="transfer" if core.f("mode") == "transfer" else None,
                class_id=core.f_int("class_id"), tag_ids=[int(t) for t in request.form.getlist("tag_ids")])
            if core.f_bool("make_rule"):
                _rule_from_item(s, item, txn)
            flash(f"Added {txn.info.label.lower()} for {money.fmt(abs(item.amount_cents))}.", "success")
        elif action == "match":
            kind = core.f("match_kind")
            target = s.get(Transaction, core.f_int("match_id") or 0)
            if kind == "invoice" and target is not None:
                bank_service.receive_for_invoice(s, item, target, user)
                flash(f"Recorded payment for invoice {target.number}.", "success")
            elif kind == "bill" and target is not None:
                bank_service.pay_bill(s, item, target, user)
                flash(f"Recorded payment of bill {target.number or ''}.", "success")
            elif kind in ("undeposited", "undeposited_all"):
                ids = [int(x) for x in (core.f("match_ids") or "").split(",") if x.isdigit()]
                bank_service.deposit_waiting(s, item, ids, user)
                flash("Recorded the deposit.", "success")
            else:
                ids = [int(x) for x in (core.f("match_ids") or str(core.f_int("match_id") or "")).split(",") if x.isdigit()]
                bank_service.match(s, item, ids, user)
                flash("Matched.", "success")
        elif action == "exclude":
            bank_service.exclude(s, item, user)
            flash("Excluded.", "info")
        elif action == "undo":
            bank_service.undo(s, item, user)
            flash("Sent back to For review.", "info")
        elif action == "restore":
            item.status = "review"
            bank_service.suggest(s, item)
        s.commit()
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("banking.feed", account_id=item.account_id))


def _rule_from_item(s, item: BankFeedItem, txn: Transaction) -> None:
    keyword = (item.payee or item.description or "")[:40]
    line = next((ln for ln in txn.lines if ln.account_id), None)
    rule = BankRule(name=f"{keyword}", direction="in" if item.amount_cents > 0 else "out",
                    account_ids=[item.account_id], conditions=[{"field": "description", "op": "contains",
                                                                 "value": keyword.split(" ")[0] if keyword else ""}],
                    action="transfer" if txn.type in ("transfer", "cc_payment") else (
                        "deposit" if item.amount_cents > 0 else "expense"),
                    vendor_id=txn.vendor_id, customer_id=txn.customer_id,
                    account_id=line.account_id if line else txn.to_account_id,
                    position=(s.scalar(select(func.max(BankRule.position))) or 0) + 1)
    s.add(rule)


@bp.route("/banking/batch", methods=["POST"])
@core.requires("banking.edit")
def batch():
    s = core.db()
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    action = core.f("action")
    done = errors = 0
    for item in (s.get(BankFeedItem, i) for i in ids):
        if item is None or item.status != "review":
            continue
        try:
            if action == "accept":
                if item.suggestion_source == "match" and item.suggested_match_txn_id:
                    m = s.get(Transaction, item.suggested_match_txn_id)
                    if m.type == "invoice":
                        bank_service.receive_for_invoice(s, item, m, core.current_user())
                    elif m.type == "bill":
                        bank_service.pay_bill(s, item, m, core.current_user())
                    elif m.type in ("payment", "sales_receipt") and m.account_id != item.account_id:
                        bank_service.deposit_waiting(s, item, [m.id], core.current_user())
                    else:
                        bank_service.match(s, item, [m.id], core.current_user())
                elif item.suggested_rule is not None:
                    bank_service.add_from_rule(s, item, item.suggested_rule, core.current_user())
                elif item.suggested_account_id:
                    bank_service.add_from_feed(s, item, core.current_user(), account_id=item.suggested_account_id,
                                               vendor_id=item.suggested_vendor_id,
                                               customer_id=item.suggested_customer_id)
                else:
                    continue
            elif action == "exclude":
                bank_service.exclude(s, item, core.current_user())
            done += 1
        except BooksError:
            errors += 1
    s.commit()
    flash(f"{'Accepted' if action == 'accept' else 'Excluded'} {done}." + (f" {errors} need a closer look." if errors else ""),
          "success" if done else "info")
    return redirect(request.referrer or url_for("banking.feed"))


@bp.route("/banking/suggest/<int:account_id>", methods=["POST"])
@core.requires("banking.edit")
def resuggest(account_id: int):
    """Re-run rules, matching and history (and AI, if configured) on everything in For review."""
    s = core.db()
    items = s.scalars(select(BankFeedItem).where(BankFeedItem.account_id == account_id,
                                                 BankFeedItem.status == "review")).all()
    for it in items:
        bank_service.suggest(s, it)
    used_ai = 0
    if core.f_bool("ai"):
        from pps_tools.books.services import ai

        try:
            used_ai = ai.categorize_feed(s, [it for it in items if not it.suggestion_source], core.config())
        except BooksError as exc:
            flash(str(exc), "error")
    s.commit()
    flash(f"Refreshed suggestions for {len(items)} transactions" + (f"; Claude suggested {used_ai}." if used_ai else "."),
          "success")
    return redirect(url_for("banking.feed", account_id=account_id))


# -- import ------------------------------------------------------------------------------------


@bp.route("/banking/import", methods=["GET", "POST"])
@core.requires("banking.edit")
def import_file():
    s = core.db()
    accounts = _feed_accounts()
    if request.method == "POST":
        account = s.get(Account, core.f_int("account_id") or 0)
        upload = request.files.get("file")
        if account is None or upload is None or not upload.filename:
            flash("Choose an account and a file.", "error")
            return redirect(url_for("banking.import_file"))
        data = upload.read()
        options = {}
        for key in ("date_col", "desc_col", "amount_col", "debit_col", "credit_col"):
            if core.f(key) not in (None, ""):
                options[key] = int(core.f(key))
        if core.f("date_format"):
            options["date_format"] = core.f("date_format")
        if core.f("flip_sign"):
            options["flip_sign"] = core.f("flip_sign") == "1"
        try:
            stmt = parse(upload.filename, data, card=account.type == "credit_card", csv_options=options or None)
            start = parse_date(core.f("start")) if core.f("start") else None
            result = bank_service.import_statement(s, account, stmt, source=upload.filename.rsplit(".", 1)[-1].lower(),
                                                   filename=upload.filename, user=core.current_user(), start=start)
            s.commit()
        except (ParseError, BooksError, ValueError) as exc:
            s.rollback()
            flash(f"Couldn't import {upload.filename}: {exc}", "error")
            return render_template("banking/import.html", accounts=accounts, mapping=True, account_id=account.id)
        flash(f"Imported {result.added} transactions into {account.name}"
              + (f", skipped {result.duplicates} already imported" if result.duplicates else "")
              + (f", {result.auto_added} added automatically by rules" if result.auto_added else "") + ".", "success")
        return redirect(url_for("banking.feed", account_id=account.id))
    return render_template("banking/import.html", accounts=accounts, mapping=False,
                           account_id=request.args.get("account_id", type=int))


# -- rules -------------------------------------------------------------------------------------


@bp.route("/banking/rules")
@core.requires("banking.view")
def rules():
    s = core.db()
    rows = s.scalars(select(BankRule).order_by(BankRule.position, BankRule.id)).all()
    return render_template("banking/rules.html", rules=rows)


@bp.route("/banking/rules/new", methods=["GET", "POST"])
@core.requires("banking.edit")
def rule_new():
    return _rule_form(BankRule(direction="out", match_all=True, conditions=[], action="expense", account_ids=[],
                               splits=[], tag_ids=[], active=True))


@bp.route("/banking/rules/<int:rule_id>", methods=["GET", "POST"])
@core.requires("banking.edit")
def rule_edit(rule_id: int):
    return _rule_form(core.db().get(BankRule, rule_id) or abort(404))


def _rule_form(rule: BankRule):
    s = core.db()
    if request.method == "POST":
        if core.f("delete") and rule.id:
            s.delete(rule)
            s.commit()
            flash("Rule deleted.", "success")
            return redirect(url_for("banking.rules"))
        try:
            rule.name = core.f("name") or ""
            if not rule.name:
                raise ValidationError("Name the rule.")
            rule.direction = core.f("direction") or "out"
            rule.account_ids = [int(a) for a in request.form.getlist("account_ids") if a.isdigit()]
            rule.match_all = core.f("match") != "any"
            conds = []
            for row in core.indexed_rows("cond"):
                if row.get("value") or row.get("field") == "amount":
                    if row.get("field") == "amount" and not row.get("value"):
                        continue
                    conds.append({"field": row.get("field", "description"), "op": row.get("op", "contains"),
                                  "value": row.get("value", ""), "value2": row.get("value2", "")})
            if not conds:
                raise ValidationError("Add at least one condition.")
            rule.conditions = conds
            rule.action = core.f("action") or "expense"
            rule.account_id = core.f_int("category_id")
            payee = core.f("payee") or ""
            rule.vendor_id = int(payee.split(":")[1]) if payee.startswith("vendor:") else None
            rule.customer_id = int(payee.split(":")[1]) if payee.startswith("customer:") else None
            rule.class_id = core.f_int("class_id")
            rule.memo = core.f("memo") or None
            rule.auto_add = core.f_bool("auto_add")
            rule.active = core.f_bool("active") if rule.id else True
            rule.position = core.f_int("position") or rule.position or (s.scalar(select(func.max(BankRule.position))) or 0) + 1
            splits = []
            for row in core.indexed_rows("split"):
                if row.get("account_id") and row.get("percent"):
                    splits.append({"account_id": int(row["account_id"]), "percent": row["percent"]})
            if splits and sum(Decimal(sp["percent"]) for sp in splits) != 100:
                raise ValidationError("Split percentages must add up to 100.")
            rule.splits = splits
            if rule.action not in ("exclude",) and not rule.account_id and not splits:
                raise ValidationError("Choose the category (or split) the rule assigns.")
            if rule.id is None:
                s.add(rule)
            s.commit()
        except (BooksError, ArithmeticError, ValueError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_rule(rule), 422
        flash(f"Rule “{rule.name}” saved. It applies to new bank transactions; use Refresh suggestions for ones "
              "already waiting.", "success")
        return redirect(url_for("banking.rules"))
    return _render_rule(rule)


def _render_rule(rule: BankRule):
    s = core.db()
    return render_template(
        "banking/rule_form.html", rule=rule, feed_accounts=_feed_accounts(),
        categories=[a for a in ordered_accounts(s, active_only=True) if a.type not in ("ar", "ap")],
        vendors=s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
        customers=s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all(),
        classes=s.scalars(select(TrackingClass)).all())


# -- reconcile -----------------------------------------------------------------------------------


@bp.route("/banking/reconcile", methods=["GET", "POST"])
@core.requires("reconcile")
def reconcile_start():
    s = core.db()
    accounts = [a for a in ordered_accounts(s, active_only=True) if a.type in ("bank", "credit_card",
                                                                               "other_current_asset", "other_current_liability",
                                                                               "long_term_liability")]
    if request.method == "POST":
        account = s.get(Account, core.f_int("account_id") or 0) or abort(400)
        try:
            when = parse_date(core.f("statement_date"))
            rec = bank_service.start_reconciliation(s, account, when, money.cents(core.f("ending_balance") or "0"),
                                                    money.cents(core.f("service_charge") or "0"),
                                                    money.cents(core.f("interest") or "0"))
            s.commit()
        except (BooksError, ValueError, money.MoneyError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("banking.reconcile_start"))
        return redirect(url_for("banking.reconcile", rec_id=rec.id))
    account_id = request.args.get("account_id", type=int)
    history = s.scalars(select(Reconciliation).order_by(Reconciliation.statement_date.desc()).limit(30)).all()
    beginning = {a.id: bank_service.reconciled_balance(s, a.id) for a in accounts}
    in_progress = {r.account_id: r for r in s.scalars(select(Reconciliation).where(Reconciliation.status == "in_progress"))}
    last = {}
    for r in s.scalars(select(Reconciliation).where(Reconciliation.status == "completed")
                       .order_by(Reconciliation.statement_date)):
        last[r.account_id] = r
    return render_template("banking/reconcile_start.html", accounts=accounts, account_id=account_id, history=history,
                           beginning=beginning, in_progress=in_progress, last=last)


@bp.route("/banking/reconcile/<int:rec_id>", methods=["GET", "POST"])
@core.requires("reconcile")
def reconcile(rec_id: int):
    s = core.db()
    rec = s.get(Reconciliation, rec_id) or abort(404)
    if rec.status == "completed":
        return redirect(url_for("banking.reconcile_report", rec_id=rec.id))
    acct = s.get(Account, rec.account_id)
    if request.method == "POST":
        ids = request.form.getlist("cleared")
        if core.f("save") == "later":
            for e in bank_service.reconcile_candidates(s, rec):
                e.cleared = "C" if str(e.id) in ids else ("" if e.cleared == "C" else e.cleared)
            s.commit()
            flash("Progress saved. Pick up where you left off any time.", "info")
            return redirect(url_for("banking.reconcile_start"))
        try:
            bank_service.finish_reconciliation(s, rec, ids, core.current_user(), adjust=core.f_bool("adjust"))
            s.commit()
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("banking.reconcile", rec_id=rec.id))
        flash(f"{acct.name} reconciled through {rec.statement_date:%m/%d/%Y}.", "success")
        return redirect(url_for("banking.reconcile_report", rec_id=rec.id))
    entries = bank_service.reconcile_candidates(s, rec)
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_({e.txn_id for e in entries})))} \
        if entries else {}
    return render_template("banking/reconcile.html", rec=rec, acct=acct, entries=entries, txns=txns)


@bp.route("/banking/reconcile/<int:rec_id>/report")
@core.requires("reports.view")
def reconcile_report(rec_id: int):
    s = core.db()
    rec = s.get(Reconciliation, rec_id) or abort(404)
    acct = s.get(Account, rec.account_id)
    cleared = s.scalars(select(LedgerEntry).where(LedgerEntry.reconciliation_id == rec.id)
                        .order_by(LedgerEntry.date)).all()
    uncleared = s.scalars(select(LedgerEntry).where(LedgerEntry.account_id == acct.id, LedgerEntry.cleared != "R",
                                                    LedgerEntry.date <= rec.statement_date)
                          .order_by(LedgerEntry.date)).all()
    after = s.scalars(select(LedgerEntry).where(LedgerEntry.account_id == acct.id, LedgerEntry.cleared != "R",
                                                LedgerEntry.date > rec.statement_date).order_by(LedgerEntry.date)).all()
    ids = {e.txn_id for e in cleared + uncleared + after}
    txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_(ids)))} if ids else {}
    register_balance = sum(e.amount_cents for e in s.scalars(select(LedgerEntry).where(
        LedgerEntry.account_id == acct.id, LedgerEntry.date <= rec.statement_date))) * acct.normal
    return render_template("banking/reconcile_report.html", rec=rec, acct=acct, cleared=cleared, uncleared=uncleared,
                           after=after, txns=txns, register_balance=register_balance)


@bp.route("/banking/reconcile/<int:rec_id>/undo", methods=["POST"])
@core.requires("close_books")
def reconcile_undo(rec_id: int):
    s = core.db()
    rec = s.get(Reconciliation, rec_id) or abort(404)
    try:
        bank_service.undo_reconciliation(s, rec, core.current_user())
        s.commit()
        flash("Reconciliation undone. Its transactions are back to cleared.", "success")
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
        return redirect(url_for("banking.reconcile_report", rec_id=rec.id))
    return redirect(url_for("banking.reconcile", rec_id=rec.id))


# -- receipts ------------------------------------------------------------------------------------


@bp.route("/receipts", methods=["GET", "POST"])
@core.requires("banking.view")
def receipts():
    s = core.db()
    from pps_tools.books.services import attachments as attach_service

    if request.method == "POST":
        if not core.can("banking.edit"):
            abort(403)
        count = 0
        for fs in request.files.getlist("files"):
            if fs and fs.filename:
                try:
                    attach_service.store(s, core.config(), fs.filename, fs.read(), fs.mimetype, core.current_user(),
                                         receipt=True)
                    count += 1
                except BooksError as exc:
                    flash(str(exc), "error")
        s.commit()
        if count and core.config().anthropic_api_key:
            from pps_tools.books.services import ai

            try:
                read = ai.read_receipts(s, core.config(), limit=count)
                s.commit()
                if read:
                    flash(f"Read {read} receipt{'s' if read != 1 else ''} with Claude.", "info")
            except BooksError as exc:
                flash(str(exc), "error")
        flash(f"Uploaded {count} receipt{'s' if count != 1 else ''}.", "success" if count else "error")
        return redirect(url_for("banking.receipts"))
    inbox = s.scalars(select(Attachment).where(Attachment.receipt_status.in_(("inbox", "reviewed")))
                      .order_by(Attachment.created_at.desc())).all()
    done = s.scalars(select(Attachment).where(Attachment.receipt_status == "used")
                     .order_by(Attachment.created_at.desc()).limit(20)).all()
    return render_template("banking/receipts.html", inbox=inbox, done=done, accounts=_feed_accounts(),
                           categories=[a for a in ordered_accounts(s, active_only=True)
                                       if a.type in ("expense", "cogs", "other_expense", "fixed_asset")],
                           vendors=s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
                           ai=bool(core.config().anthropic_api_key))


@bp.route("/receipts/<int:att_id>", methods=["POST"])
@core.requires("banking.edit")
def receipt_action(att_id: int):
    s = core.db()
    att = s.get(Attachment, att_id) or abort(404)
    action = core.f("action")
    from pps_tools.books.services import attachments as attach_service
    from pps_tools.books.services import transactions as tx

    try:
        if action == "delete":
            att.receipt_status = None
            if not att.links:
                s.delete(att)
            s.commit()
            flash("Receipt removed.", "info")
        elif action == "read":
            from pps_tools.books.services import ai

            ai.read_receipt(s, core.config(), att)
            s.commit()
        elif action == "create":
            vendor_id = core.f_int("vendor_id")
            name = core.f("new_vendor")
            if not vendor_id and name:
                v = s.scalar(select(Vendor).where(func.lower(Vendor.display_name) == name.lower()))
                if v is None:
                    v = Vendor(display_name=name)
                    s.add(v)
                    s.flush()
                vendor_id = v.id
            txn = tx.save(s, {"type": "expense", "date": core.f("date"), "account_id": core.f_int("account_id"),
                              "payee": f"vendor:{vendor_id}" if vendor_id else "",
                              "memo": core.f("memo"), "lines": [{"kind": "account", "account_id": core.f_int("category_id"),
                                                                 "amount": core.f("amount"),
                                                                 "description": core.f("memo")}]},
                          user=core.current_user())
            attach_service.link(s, att, "transaction", txn.id)
            att.receipt_status = "used"
            # If the bank already shows this charge, match it instead of double counting.
            item = s.scalars(select(BankFeedItem).where(BankFeedItem.account_id == txn.account_id,
                                                        BankFeedItem.status == "review",
                                                        BankFeedItem.amount_cents == -txn.total_cents)).first()
            if item is not None:
                bank_service.match(s, item, [txn.id], core.current_user())
            s.commit()
            flash(f"Expense saved and receipt attached{' and matched to the bank line' if item else ''}.", "success")
        elif action == "attach":
            target = s.get(Transaction, core.f_int("txn_id") or 0)
            if target is None:
                raise ValidationError("Transaction not found.")
            attach_service.link(s, att, "transaction", target.id)
            att.receipt_status = "used"
            s.commit()
            flash("Receipt attached.", "success")
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
    return redirect(url_for("banking.receipts"))
