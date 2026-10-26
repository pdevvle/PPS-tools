"""Bank feeds, bank rules, matching, and reconciliation.

Downloaded or imported bank lines wait in "For review". Each gets a
suggestion — a rule that fires, a match to something already in the books,
or the category used last time for the same payee — and the user adds,
matches or excludes it. Adding creates a real transaction whose bank-side
ledger entry is marked cleared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.db import atomic, utcnow
from pps_tools.books.models import (Account, BankFeedItem, BankImportBatch, BankRule, LedgerEntry, Reconciliation,
                                    Transaction, User, Vendor)
from pps_tools.books.money import allocate, round_cents
from pps_tools.books.services import audit
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.services.importers.bankfiles import Statement, clean_payee


# -- import -------------------------------------------------------------------------------------


@dataclass
class ImportResult:
    batch: BankImportBatch
    added: int
    duplicates: int
    auto_added: int


@atomic
def import_statement(s: Session, account: Account, stmt: Statement, source: str, filename: Optional[str] = None,
                     user: Optional[User] = None, start: Optional[date] = None) -> ImportResult:
    if account.type not in ("bank", "credit_card"):
        raise ValidationError("Bank transactions can only be imported into bank and credit card accounts.")
    batch = BankImportBatch(account_id=account.id, source=source, filename=filename,
                            statement_balance_cents=stmt.balance_cents, statement_balance_date=stmt.balance_date,
                            user_id=user.id if user else None)
    s.add(batch)
    s.flush()
    existing = set(s.scalars(select(BankFeedItem.external_id).where(BankFeedItem.account_id == account.id)))
    added = dup = 0
    new_items: list[BankFeedItem] = []
    for line in stmt.lines:
        if start and line.date < start:
            continue
        if line.external_id in existing:
            dup += 1
            continue
        existing.add(line.external_id)
        item = BankFeedItem(account_id=account.id, batch_id=batch.id, source=source, external_id=line.external_id,
                            date=line.date, amount_cents=line.amount_cents, description=line.description[:500],
                            payee=(line.payee or clean_payee(line.description))[:200], memo=line.memo,
                            check_number=line.check_number, bank_category=line.category, raw=line.raw or None)
        s.add(item)
        new_items.append(item)
        added += 1
    batch.imported_count = added
    batch.duplicate_count = dup
    s.flush()
    auto = 0
    for item in new_items:
        suggest(s, item)
        rule = item.suggested_rule
        if rule is not None and rule.auto_add and item.suggestion_source == "rule" and rule.action != "exclude":
            try:
                add_from_rule(s, item, rule, user)
                auto += 1
            except ValidationError:
                pass
        elif rule is not None and rule.auto_add and rule.action == "exclude":
            exclude(s, item, user)
            auto += 1
    audit.record(s, user, "import", "bank_feed", batch.id,
                 summary=f"Imported {added} bank transactions into {account.name} ({dup} duplicates skipped)")
    return ImportResult(batch, added, dup, auto)


# -- rules ----------------------------------------------------------------------------------------


def _text_for(item: BankFeedItem, field: str) -> str:
    if field == "payee":
        return item.payee or ""
    if field == "memo":
        return item.memo or ""
    if field == "bank_text":
        return " ".join(x for x in (item.description, item.memo, item.payee) if x)
    return item.description or ""


def condition_matches(cond: dict, item: BankFeedItem) -> bool:
    field = cond.get("field", "description")
    op = cond.get("op", "contains")
    value = str(cond.get("value", "") or "")
    if field == "amount":
        amt = abs(item.amount_cents)
        try:
            target = round_cents(Decimal(value.replace(",", "").replace("$", "") or "0"))
            target2 = round_cents(Decimal(str(cond.get("value2", "0")).replace(",", "").replace("$", "") or "0"))
        except ArithmeticError:
            return False
        return {"equals": amt == target, "gt": amt > target, "lt": amt < target,
                "between": target <= amt <= target2}.get(op, False)
    text = _text_for(item, field).lower()
    v = value.lower()
    if op == "contains":
        return v in text
    if op == "not_contains":
        return v not in text
    if op == "equals":
        return text.strip() == v.strip()
    if op == "starts_with":
        return text.startswith(v)
    if op == "ends_with":
        return text.endswith(v)
    if op == "regex":
        try:
            return re.search(value, _text_for(item, field), flags=re.I) is not None
        except re.error:
            return False
    return False


def rule_matches(rule: BankRule, item: BankFeedItem) -> bool:
    if not rule.active:
        return False
    if rule.account_ids and item.account_id not in [int(a) for a in rule.account_ids]:
        return False
    if rule.direction == "in" and item.amount_cents <= 0:
        return False
    if rule.direction == "out" and item.amount_cents >= 0:
        return False
    conds = rule.conditions or []
    if not conds:
        return False
    results = [condition_matches(c, item) for c in conds]
    return all(results) if rule.match_all else any(results)


def first_rule(s: Session, item: BankFeedItem) -> Optional[BankRule]:
    for rule in s.scalars(select(BankRule).where(BankRule.active.is_(True)).order_by(BankRule.position, BankRule.id)):
        if rule_matches(rule, item):
            return rule
    return None


# -- suggestions ----------------------------------------------------------------------------------


def find_matches(s: Session, item: BankFeedItem, limit: int = 5) -> list[dict]:
    """Transactions already in the books this bank line could be.

    Same account, same amount, not cleared, within -30/+10 days — or an open
    invoice/bill for the amount (the deposit pays it)."""
    out: list[dict] = []
    acct = s.get(Account, item.account_id)
    # Feed amounts are signed money-in/out; ledger entries are debit-positive. For a bank
    # account money in is a debit, and for a card a charge (money out) is a credit — the
    # same sign either way.
    ledger_amount = item.amount_cents
    taken = set(s.scalars(select(BankFeedItem.txn_id).where(BankFeedItem.status.in_(("added", "matched")),
                                                            BankFeedItem.txn_id.isnot(None))))
    q = (select(LedgerEntry).where(LedgerEntry.account_id == item.account_id, LedgerEntry.amount_cents == ledger_amount,
                                   LedgerEntry.cleared == "", LedgerEntry.date >= item.date - timedelta(days=30),
                                   LedgerEntry.date <= item.date + timedelta(days=10)))
    for e in s.scalars(q):
        if e.txn_id in taken:
            continue
        t = s.get(Transaction, e.txn_id)
        days = abs((t.date - item.date).days)
        out.append({"kind": "txn", "txn": t, "score": 100 - days - (0 if (t.number or "") == (item.check_number or "-")
                                                                     else 5)})
    # Deposits waiting in Payments to deposit whose total equals this deposit.
    if item.amount_cents > 0 and acct is not None and acct.type == "bank":
        uf = system_account_id(s, "undeposited_funds")
        waiting = [t for t in tx.deposit_candidates(s) if t.account_id == uf]
        exact = [t for t in waiting if t.total_cents == item.amount_cents]
        for t in exact:
            out.append({"kind": "undeposited", "txn": t, "score": 80 - abs((t.date - item.date).days)})
        if not exact and waiting:
            total = sum(t.total_cents for t in waiting if t.date <= item.date)
            if total == item.amount_cents:
                out.append({"kind": "undeposited_all", "txns": [t for t in waiting if t.date <= item.date],
                            "score": 75})
        for inv in s.scalars(select(Transaction).where(Transaction.type == "invoice",
                                                       Transaction.balance_cents == item.amount_cents,
                                                       Transaction.voided.is_(False))):
            out.append({"kind": "invoice", "txn": inv, "score": 60})
    if item.amount_cents < 0:
        for bill in s.scalars(select(Transaction).where(Transaction.type == "bill",
                                                        Transaction.balance_cents == -item.amount_cents,
                                                        Transaction.voided.is_(False))):
            out.append({"kind": "bill", "txn": bill, "score": 60})
    out.sort(key=lambda m: -m["score"])
    return out[:limit]


def history_suggestion(s: Session, item: BankFeedItem) -> Optional[tuple[Optional[int], Optional[int], Optional[int]]]:
    """(account_id, vendor_id, customer_id) used the last time this payee came through."""
    payee = (item.payee or "").strip()
    if not payee:
        return None
    prev = s.scalars(select(BankFeedItem).where(
        BankFeedItem.payee == payee, BankFeedItem.status == "added", BankFeedItem.txn_id.isnot(None),
        BankFeedItem.id != item.id).order_by(BankFeedItem.date.desc()).limit(1)).first()
    if prev is not None and prev.txn is not None:
        t = prev.txn
        line = next((ln for ln in t.lines if ln.kind in ("account", "item") and ln.account_id), None)
        account_id = line.account_id if line else (t.to_account_id if t.type == "transfer" else None)
        return account_id, t.vendor_id, t.customer_id
    vendor = s.scalar(select(Vendor).where(func.lower(Vendor.display_name) == payee.lower()))
    if vendor is not None:
        return vendor.default_expense_account_id, vendor.id, None
    return None


def suggest(s: Session, item: BankFeedItem) -> None:
    item.suggested_rule_id = item.suggested_account_id = item.suggested_vendor_id = None
    item.suggested_customer_id = item.suggested_match_txn_id = None
    item.suggestion_source = item.suggestion_reason = None
    item.suggestion_confidence = None
    matches = find_matches(s, item, limit=1)
    if matches and matches[0]["kind"] == "txn":
        m = matches[0]["txn"]
        item.suggested_match_txn_id = m.id
        item.suggestion_source = "match"
        item.suggestion_reason = f"Matches {m.info.label.lower()} {m.number or ''} on {m.date:%m/%d/%Y}".replace("  ", " ")
        item.suggestion_confidence = Decimal("0.95")
        return
    rule = first_rule(s, item)
    if rule is not None:
        item.suggested_rule_id = rule.id
        item.suggestion_source = "rule"
        item.suggested_account_id = rule.account_id
        item.suggested_vendor_id = rule.vendor_id
        item.suggested_customer_id = rule.customer_id
        item.suggestion_reason = f"Rule “{rule.name}”"
        item.suggestion_confidence = Decimal("0.9")
        return
    hist = history_suggestion(s, item)
    if hist is not None:
        item.suggested_account_id, item.suggested_vendor_id, item.suggested_customer_id = hist
        if item.suggested_account_id or item.suggested_vendor_id:
            item.suggestion_source = "history"
            item.suggestion_reason = "Same payee as before"
            item.suggestion_confidence = Decimal("0.75")
            return
    if matches:
        m = matches[0]
        if m["kind"] in ("invoice", "bill", "undeposited"):
            item.suggested_match_txn_id = m["txn"].id
            item.suggestion_source = "match"
            item.suggestion_reason = {"invoice": "Could be payment for", "bill": "Could pay",
                                      "undeposited": "Could be the deposit of"}[m["kind"]] + \
                f" {m['txn'].info.label.lower()} {m['txn'].number or ''}".rstrip()
            item.suggestion_confidence = Decimal("0.6")


# -- actions --------------------------------------------------------------------------------------


def _clear_bank_entry(s: Session, txn: Transaction, account_id: int) -> None:
    s.flush()
    for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == txn.id, LedgerEntry.account_id == account_id)):
        if e.cleared == "":
            e.cleared = "C"


def _payee_fields(vendor_id: Optional[int], customer_id: Optional[int]) -> dict:
    if vendor_id:
        return {"payee": f"vendor:{vendor_id}", "vendor_id": vendor_id}
    if customer_id:
        return {"payee": f"customer:{customer_id}", "customer_id": customer_id}
    return {"payee": ""}


@atomic
def add_from_feed(s: Session, item: BankFeedItem, user: Optional[User], account_id: Optional[int] = None,
                  vendor_id: Optional[int] = None, customer_id: Optional[int] = None, memo: Optional[str] = None,
                  splits: Optional[list[dict]] = None, kind: Optional[str] = None,
                  class_id: Optional[int] = None, location_id: Optional[int] = None,
                  tag_ids: Optional[list[int]] = None, source: str = "bank_feed") -> Transaction:
    """Turn a bank line into an expense, deposit, transfer, or credit card payment."""
    if item.status != "review":
        raise ValidationError("That bank transaction was already handled.")
    bank = s.get(Account, item.account_id)
    amount = abs(item.amount_cents)
    money_in = item.amount_cents > 0
    category = s.get(Account, account_id) if account_id else None
    if not splits and category is None:
        raise ValidationError("Choose a category or account.")
    if category is not None and category.type in ("ar", "ap"):
        raise ValidationError("To record a customer payment or a bill payment, use Find match instead.")
    memo = memo if memo is not None else item.description
    base = {"date": item.date.isoformat(), "memo": memo, "class_id": class_id, "location_id": location_id,
            "tag_ids": tag_ids or [], "allow_duplicate": True}
    # A transfer between two balance-sheet accounts.
    if kind == "transfer" or (category is not None and category.type in ("bank", "credit_card", "other_current_asset",
                                                                           "fixed_asset", "other_asset",
                                                                           "long_term_liability", "equity",
                                                                           "other_current_liability")
                              and not splits):
        if category is None:
            raise ValidationError("Choose the other account for the transfer.")
        if bank.type == "bank" and category.type == "credit_card" and not money_in:
            data = {**base, "type": "cc_payment", "account_id": bank.id, "to_account_id": category.id,
                    "amount_cents": amount, "vendor_id": vendor_id}
        elif bank.type == "credit_card" and category.type == "bank" and money_in:
            data = {**base, "type": "cc_payment", "account_id": category.id, "to_account_id": bank.id,
                    "amount_cents": amount, "vendor_id": vendor_id}
        else:
            src, dst = (category.id, bank.id) if money_in else (bank.id, category.id)
            data = {**base, "type": "transfer", "account_id": src, "to_account_id": dst, "amount_cents": amount}
    else:
        lines = []
        if splits:
            shares = [sp for sp in splits if sp.get("account_id")]
            cents_given = [sp.get("amount_cents") for sp in shares]
            if all(c is not None for c in cents_given) and sum(cents_given) == amount:
                amounts = cents_given
            else:
                weights = [Decimal(str(sp.get("percent") or 0)) for sp in shares]
                amounts = allocate(amount, weights)
            for sp, amt in zip(shares, amounts):
                lines.append({"kind": "account", "account_id": sp["account_id"], "amount_cents": amt,
                              "description": sp.get("description") or memo, "class_id": sp.get("class_id") or class_id,
                              "customer_id": sp.get("customer_id"), "billable": bool(sp.get("billable"))})
        else:
            lines.append({"kind": "account", "account_id": category.id, "amount_cents": amount, "description": memo,
                          "class_id": class_id, "customer_id": customer_id if not money_in else None})
        if money_in and bank.type == "bank":
            for ln in lines:
                if customer_id:
                    ln["name"] = f"customer:{customer_id}"
                elif vendor_id:
                    ln["name"] = f"vendor:{vendor_id}"
            data = {**base, "type": "deposit", "account_id": bank.id, "lines": lines, "deposits": []}
        elif money_in:
            data = {**base, "type": "cc_credit", "account_id": bank.id, "lines": lines,
                    **_payee_fields(vendor_id, customer_id)}
        else:
            ttype = "check" if (item.check_number and bank.type == "bank") else "expense"
            data = {**base, "type": ttype, "account_id": bank.id, "lines": lines, **_payee_fields(vendor_id, None)}
            if ttype == "check":
                data["number"] = item.check_number
            if customer_id and not splits:
                data["lines"][0]["customer_id"] = customer_id
    txn = tx.save(s, data, user=user, source=source)
    _clear_bank_entry(s, txn, bank.id)
    item.status = "added"
    item.txn_id = txn.id
    item.reviewed_at = utcnow()
    item.reviewed_by_id = user.id if user else None
    return txn


def add_from_rule(s: Session, item: BankFeedItem, rule: BankRule, user: Optional[User]) -> Transaction:
    splits = None
    if rule.splits:
        splits = [{"account_id": sp.get("account_id"), "percent": sp.get("percent"), "class_id": sp.get("class_id")}
                  for sp in rule.splits]
    txn = add_from_feed(s, item, user, account_id=rule.account_id, vendor_id=rule.vendor_id,
                        customer_id=rule.customer_id, memo=rule.memo or None, splits=splits,
                        kind="transfer" if rule.action == "transfer" else None, class_id=rule.class_id,
                        location_id=rule.location_id, tag_ids=rule.tag_ids or [], source="bank_rule")
    rule.times_applied = (rule.times_applied or 0) + 1
    return txn


@atomic
def match(s: Session, item: BankFeedItem, txn_ids: Iterable[int], user: Optional[User]) -> list[Transaction]:
    """Match the bank line to transactions already entered (marks them cleared)."""
    if item.status != "review":
        raise ValidationError("That bank transaction was already handled.")
    txns = [s.get(Transaction, int(i)) for i in txn_ids]
    txns = [t for t in txns if t is not None]
    if not txns:
        raise ValidationError("Choose what this matches.")
    bank_total = 0
    for t in txns:
        for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == t.id, LedgerEntry.account_id == item.account_id)):
            bank_total += e.amount_cents
    if bank_total != item.amount_cents:
        raise ValidationError(f"Those transactions total {bank_total / 100:,.2f} in this account, "
                              f"but the bank shows {item.amount_cents / 100:,.2f}.")
    for t in txns:
        _clear_bank_entry(s, t, item.account_id)
    item.status = "matched"
    item.txn_id = txns[0].id
    item.reviewed_at = utcnow()
    item.reviewed_by_id = user.id if user else None
    return txns


@atomic
def deposit_waiting(s: Session, item: BankFeedItem, payment_ids: list[int], user: Optional[User]) -> Transaction:
    """A bank deposit that is a batch of payments sitting in Payments to deposit."""
    total = sum(s.get(Transaction, i).total_cents for i in payment_ids)
    if total != item.amount_cents:
        raise ValidationError("The payments selected don't add up to the deposit.")
    dep = tx.save(s, {"type": "deposit", "date": item.date.isoformat(), "account_id": item.account_id,
                      "deposits": payment_ids, "memo": item.description, "lines": []}, user=user, source="bank_feed")
    _clear_bank_entry(s, dep, item.account_id)
    item.status = "added"
    item.txn_id = dep.id
    item.reviewed_at = utcnow()
    return dep


@atomic
def receive_for_invoice(s: Session, item: BankFeedItem, invoice: Transaction, user: Optional[User]) -> Transaction:
    pay = tx.save(s, {"type": "payment", "customer_id": invoice.customer_id, "date": item.date.isoformat(),
                      "account_id": item.account_id, "amount_cents": item.amount_cents, "memo": item.description,
                      "applications": [{"txn_id": invoice.id, "amount_cents": item.amount_cents}]}, user=user,
                  source="bank_feed")
    _clear_bank_entry(s, pay, item.account_id)
    item.status = "added"
    item.txn_id = pay.id
    item.reviewed_at = utcnow()
    return pay


@atomic
def pay_bill(s: Session, item: BankFeedItem, bill: Transaction, user: Optional[User]) -> Transaction:
    pay = tx.save(s, {"type": "bill_payment", "vendor_id": bill.vendor_id, "date": item.date.isoformat(),
                      "account_id": item.account_id, "amount_cents": -item.amount_cents,
                      "number": item.check_number, "memo": item.description, "allow_duplicate": True,
                      "applications": [{"txn_id": bill.id, "amount_cents": -item.amount_cents}]}, user=user,
                  source="bank_feed")
    _clear_bank_entry(s, pay, item.account_id)
    item.status = "added"
    item.txn_id = pay.id
    item.reviewed_at = utcnow()
    return pay


def exclude(s: Session, item: BankFeedItem, user: Optional[User] = None) -> None:
    item.status = "excluded"
    item.reviewed_at = utcnow()
    item.reviewed_by_id = user.id if user else None


@atomic
def undo(s: Session, item: BankFeedItem, user: Optional[User] = None) -> None:
    """Send a handled line back to For review. Added transactions are deleted; matches are un-cleared."""
    if item.status == "added" and item.txn_id:
        txn = s.get(Transaction, item.txn_id)
        item.txn_id = None
        if txn is not None:
            tx.delete(s, txn, user=user, closing_password="")
    elif item.status == "matched" and item.txn_id:
        txn = s.get(Transaction, item.txn_id)
        if txn is not None:
            for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == txn.id,
                                                         LedgerEntry.account_id == item.account_id)):
                if e.cleared == "C":
                    e.cleared = ""
    item.status = "review"
    item.txn_id = None
    item.reviewed_at = None
    suggest(s, item)


# -- reconciliation ---------------------------------------------------------------------------------


def reconciled_balance(s: Session, account_id: int, through: Optional[date] = None) -> int:
    """Balance of entries already reconciled (the next statement's beginning balance)."""
    acct = s.get(Account, account_id)
    q = select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
        LedgerEntry.account_id == account_id, LedgerEntry.cleared == "R")
    if through:
        q = q.where(LedgerEntry.date <= through)
    return int(s.scalar(q) or 0) * acct.normal


def start_reconciliation(s: Session, account: Account, statement_date: date, ending_cents: int,
                         service_charge: int = 0, interest: int = 0) -> Reconciliation:
    open_rec = s.scalar(select(Reconciliation).where(Reconciliation.account_id == account.id,
                                                     Reconciliation.status == "in_progress"))
    if open_rec is not None:
        open_rec.statement_date = statement_date
        open_rec.ending_balance_cents = ending_cents
        open_rec.service_charge_cents = service_charge
        open_rec.interest_earned_cents = interest
        return open_rec
    rec = Reconciliation(account_id=account.id, statement_date=statement_date, ending_balance_cents=ending_cents,
                         beginning_balance_cents=reconciled_balance(s, account.id), service_charge_cents=service_charge,
                         interest_earned_cents=interest)
    s.add(rec)
    s.flush()
    return rec


def reconcile_candidates(s: Session, rec: Reconciliation) -> list[LedgerEntry]:
    """Unreconciled entries in the account dated on or before the statement date."""
    return list(s.scalars(select(LedgerEntry).where(
        LedgerEntry.account_id == rec.account_id, LedgerEntry.cleared != "R",
        LedgerEntry.date <= rec.statement_date).order_by(LedgerEntry.date, LedgerEntry.id)))


@atomic
def finish_reconciliation(s: Session, rec: Reconciliation, cleared_ids: Iterable[int], user: Optional[User],
                          adjust: bool = False) -> Reconciliation:
    acct = s.get(Account, rec.account_id)
    ids = {int(i) for i in cleared_ids}
    # Bank charges and interest from the statement become transactions first.
    extra_ids = set()
    if rec.service_charge_cents:
        fee = tx.save(s, {"type": "expense" if acct.type == "bank" else "expense", "date": rec.statement_date.isoformat(),
                          "account_id": acct.id, "memo": "Service charge (reconciliation)", "allow_duplicate": True,
                          "lines": [{"kind": "account", "account_id": _bank_fee_account(s),
                                     "amount_cents": rec.service_charge_cents}]}, user=user, source="reconcile")
        extra_ids |= {e.id for e in fee.entries if e.account_id == acct.id}
    if rec.interest_earned_cents and acct.type == "bank":
        interest = tx.save(s, {"type": "deposit", "date": rec.statement_date.isoformat(), "account_id": acct.id,
                               "memo": "Interest earned (reconciliation)", "deposits": [],
                               "lines": [{"account_id": _interest_account(s),
                                          "amount_cents": rec.interest_earned_cents}]}, user=user, source="reconcile")
        extra_ids |= {e.id for e in interest.entries if e.account_id == acct.id}
    s.flush()
    candidates = {e.id: e for e in reconcile_candidates(s, rec)}
    chosen = [candidates[i] for i in ids | extra_ids if i in candidates]
    cleared_total = rec.beginning_balance_cents + sum(e.amount_cents for e in chosen) * acct.normal
    diff = rec.ending_balance_cents - cleared_total
    if diff and not adjust:
        raise ValidationError(f"Still off by {diff / 100:,.2f}. Check off more transactions, or finish with an "
                              "adjustment to Reconciliation Discrepancies.")
    if diff:
        disc = system_account_id(s, "reconciliation_discrepancies")
        amount = diff * acct.normal  # debit-positive change needed in the account
        lines = [{"account_id": acct.id, "debit_cents": amount} if amount > 0 else {"account_id": acct.id,
                                                                                   "credit_cents": -amount},
                 {"account_id": disc, "credit_cents": amount} if amount > 0 else {"account_id": disc,
                                                                                 "debit_cents": -amount}]
        je = tx.save(s, {"type": "journal_entry", "date": rec.statement_date.isoformat(),
                         "memo": f"Reconciliation adjustment, statement {rec.statement_date:%m/%d/%Y}", "lines": lines},
                     user=user, source="reconcile")
        rec.adjustment_txn_id = je.id
        s.flush()
        chosen += [e for e in je.entries if e.account_id == acct.id]
    for e in chosen:
        e.cleared = "R"
        e.reconciliation_id = rec.id
    rec.cleared_balance_cents = rec.ending_balance_cents
    rec.status = "completed"
    rec.completed_at = utcnow()
    rec.completed_by_id = user.id if user else None
    audit.record(s, user, "reconcile", "account", acct.id, name=acct.full_name,
                 summary=f"Reconciled {acct.full_name} through {rec.statement_date:%m/%d/%Y}"
                         + (f" with a {diff / 100:,.2f} adjustment" if diff else ""))
    return rec


@atomic
def undo_reconciliation(s: Session, rec: Reconciliation, user: Optional[User]) -> None:
    later = s.scalar(select(Reconciliation.id).where(Reconciliation.account_id == rec.account_id,
                                                     Reconciliation.status == "completed",
                                                     Reconciliation.statement_date > rec.statement_date))
    if later:
        raise ValidationError("Undo the later reconciliations of this account first.")
    for e in s.scalars(select(LedgerEntry).where(LedgerEntry.reconciliation_id == rec.id)):
        e.cleared = "C"
        e.reconciliation_id = None
    rec.status = "in_progress"
    rec.completed_at = None
    audit.record(s, user, "unreconcile", "account", rec.account_id,
                 summary=f"Undid reconciliation through {rec.statement_date:%m/%d/%Y}")


def _bank_fee_account(s: Session) -> int:
    acct = s.scalar(select(Account).where(Account.name == "Bank Fees & Service Charges"))
    return acct.id if acct else system_account_id(s, "merchant_fees")


def _interest_account(s: Session) -> int:
    acct = s.scalar(select(Account).where(Account.name == "Interest Earned"))
    if acct is None:
        acct = Account(name="Interest Earned", type="other_income", detail_type="Interest Earned")
        s.add(acct)
        s.flush()
    return acct.id
