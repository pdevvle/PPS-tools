"""Turning a Receive Payment / Pay Bills screen into applications.

The screen works the way QBO's does: each open invoice gets the total
being applied to it, each available credit the amount of it to use, and
"amount received" is the cash. Credits are used first, oldest invoice
first; cash covers the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from pps_tools.books.services.errors import ValidationError
from pps_tools.books.money import fmt


@dataclass
class Split:
    applications: list[dict]  # [{"txn_id", "amount_cents"}] cash applied
    credits: list[dict]  # [{"txn_id": credit, "target_id": invoice, "amount_cents"}]
    unapplied_cents: int


def split(targets: list[tuple[int, int]], credits: list[tuple[int, int]], cash_cents: int) -> Split:
    """``targets``: [(invoice_id, amount applied)], ``credits``: [(credit_id, amount used)]."""
    targets = [(t, a) for t, a in targets if a > 0]
    credits = [(c, a) for c, a in credits if a > 0]
    applied_total = sum(a for _, a in targets)
    credit_total = sum(a for _, a in credits)
    use_credit = min(credit_total, applied_total)
    cash_needed = applied_total - use_credit
    if cash_needed > cash_cents:
        raise ValidationError(
            f"You're applying {fmt(applied_total)} but only received {fmt(cash_cents)}"
            + (f" plus {fmt(use_credit)} in credits." if use_credit else "."), "amount")
    credit_rows: list[dict] = []
    cash_rows: list[dict] = []
    pool = [[cid, amt] for cid, amt in credits]
    remaining_credit = use_credit
    for target_id, amount in targets:
        need = amount
        while need > 0 and remaining_credit > 0 and pool:
            cid, avail = pool[0]
            use = min(need, avail, remaining_credit)
            credit_rows.append({"txn_id": cid, "target_id": target_id, "amount_cents": use})
            need -= use
            remaining_credit -= use
            pool[0][1] -= use
            if pool[0][1] == 0:
                pool.pop(0)
        if need > 0:
            cash_rows.append({"txn_id": target_id, "amount_cents": need})
    used_cash = sum(r["amount_cents"] for r in cash_rows)
    return Split(cash_rows, credit_rows, cash_cents - used_cash)
