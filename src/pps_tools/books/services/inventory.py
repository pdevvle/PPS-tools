"""FIFO inventory costing.

For one item at a time the engine replays every transaction that moves
stock, oldest first, keeping cost layers (quantity, value in cents).
Sales draw down the oldest layers and post cost of goods sold; customer
returns and count increases add a layer at the current average cost;
returns to a vendor leave at FIFO cost. Because the whole history is
replayed, back-dating a purchase re-costs every later sale, as QBO does.

Entries written here carry ``auto='cogs'``; the posting engine never
touches them.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pps_tools.books.models import Item, LedgerEntry, Transaction, TransactionLine
from pps_tools.books.money import round_cents
from pps_tools.books.services.accounts import system_account_id

RECEIPTS = ("bill", "expense", "check")
VENDOR_RETURNS = ("vendor_credit", "cc_credit")
SALES = ("invoice", "sales_receipt")
CUSTOMER_RETURNS = ("credit_memo", "refund_receipt")
ADJUSTMENTS = ("inventory_adjustment",)
MOVES_STOCK = RECEIPTS + VENDOR_RETURNS + SALES + CUSTOMER_RETURNS + ADJUSTMENTS
ZERO = Decimal(0)


@dataclass
class Layer:
    qty: Decimal
    value: int  # cents


@dataclass
class Movement:
    """One stock movement, for the inventory valuation detail report."""

    date: date
    txn_id: int
    txn_type: str
    number: Optional[str]
    name: str
    qty: Decimal
    value: int  # +in / -out, cents
    qty_on_hand: Decimal
    value_on_hand: int


class _Book:
    def __init__(self, fallback_unit_cost: Decimal):
        self.layers: deque[Layer] = deque()
        self.deficit_qty = ZERO  # sold but not yet received
        self.deficit_value = 0  # what that shortfall was costed at
        self.fallback = fallback_unit_cost  # cents per unit

    @property
    def qty(self) -> Decimal:
        return sum((layer.qty for layer in self.layers), ZERO) - self.deficit_qty

    @property
    def value(self) -> int:
        return sum(layer.value for layer in self.layers) - self.deficit_value

    def unit_cost(self) -> Decimal:
        qty = sum((layer.qty for layer in self.layers), ZERO)
        if qty > 0:
            return Decimal(sum(layer.value for layer in self.layers)) / qty
        return self.fallback

    def receive(self, qty: Decimal, value: int) -> int:
        """Add stock. Returns the cost correction (cents) for filling earlier
        oversold quantity at a different cost than it was sold at."""
        correction = 0
        if self.deficit_qty > 0 and qty > 0:
            fill = min(qty, self.deficit_qty)
            fill_value = value if fill == qty else round_cents(Decimal(value) * fill / qty / 100)
            booked = (self.deficit_value if fill == self.deficit_qty
                      else round_cents(Decimal(self.deficit_value) * fill / self.deficit_qty / 100))
            correction = fill_value - booked
            self.deficit_qty -= fill
            self.deficit_value -= booked
            qty -= fill
            value -= fill_value
        if qty > 0:
            self.layers.append(Layer(qty, value))
            self.fallback = Decimal(value) / qty
        return correction

    def issue(self, qty: Decimal) -> int:
        """Take ``qty`` out, oldest layers first. Returns its cost in cents."""
        cost = 0
        remaining = qty
        while remaining > 0 and self.layers:
            layer = self.layers[0]
            if remaining >= layer.qty:
                cost += layer.value
                remaining -= layer.qty
                self.fallback = (Decimal(layer.value) / layer.qty) if layer.qty else self.fallback
                self.layers.popleft()
            else:
                part = round_cents(Decimal(layer.value) * remaining / layer.qty / 100)
                layer.qty -= remaining
                layer.value -= part
                cost += part
                remaining = ZERO
        if remaining > 0:
            # Selling stock we don't have: cost it at the last known cost and
            # remember the shortfall until a receipt fills it.
            est = round_cents(self.fallback * remaining / 100)
            self.deficit_qty += remaining
            self.deficit_value += est
            cost += est
        return cost


def _accounts(s: Session, item: Item) -> tuple[int, int]:
    asset = item.asset_account_id or system_account_id(s, "inventory_asset")
    cogs = item.expense_account_id or system_account_id(s, "cogs")
    return asset, cogs


def _events(s: Session, item_id: int, as_of: Optional[date] = None):
    q = (select(TransactionLine, Transaction)
         .join(Transaction, Transaction.id == TransactionLine.txn_id)
         .where(TransactionLine.item_id == item_id, Transaction.voided.is_(False),
                Transaction.type.in_(MOVES_STOCK), TransactionLine.kind == "item"))
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    rows = s.execute(q).all()

    def order(row):
        line, txn = row
        incoming = txn.type in RECEIPTS + CUSTOMER_RETURNS or (
            txn.type in ADJUSTMENTS and (line.qty or ZERO) > 0)
        return (txn.date, 0 if incoming else 1, txn.id, line.position)

    return sorted(rows, key=order)


def recompute_items(s: Session, item_ids: Iterable[int]) -> None:
    for item_id in sorted({i for i in item_ids if i}):
        recompute_item(s, item_id)


def recompute_item(s: Session, item_id: int) -> None:
    s.flush()
    s.execute(delete(LedgerEntry).where(LedgerEntry.item_id == item_id, LedgerEntry.auto.isnot(None)))
    item = s.get(Item, item_id)
    if item is None or item.type != "inventory":
        return
    asset, cogs = _accounts(s, item)
    book = _Book((item.cost or ZERO) * 100)  # cents per unit
    adj_totals: dict[int, int] = {}

    def entry(txn: Transaction, line: TransactionLine, account_id: int, amount: int, qty: Decimal,
              memo: str, customer_id: Optional[int] = None) -> None:
        if amount == 0:
            return
        s.add(LedgerEntry(txn_id=txn.id, line_id=line.id, position=1000 + line.position, date=txn.date,
                          account_id=account_id, amount_cents=amount, item_id=item_id, qty=qty, memo=memo,
                          customer_id=customer_id, vendor_id=txn.vendor_id,
                          class_id=line.class_id or txn.class_id, location_id=line.location_id or txn.location_id,
                          auto="cogs"))

    for line, txn in _events(s, item_id):
        qty = line.qty or ZERO
        t = txn.type
        if t in RECEIPTS:
            if qty >= 0:
                correction = book.receive(qty, line.amount_cents)
                if correction:
                    # Stock sold before it arrived was costed too low (or high): true it up.
                    entry(txn, line, cogs, correction, ZERO, f"Cost correction: {item.name}")
                    entry(txn, line, asset, -correction, ZERO, f"Cost correction: {item.name}")
            else:
                cost = book.issue(-qty)
                variance = -line.amount_cents - cost
                entry(txn, line, asset, variance, ZERO, f"Return to vendor: {item.name}")
                entry(txn, line, cogs, -variance, ZERO, f"Return to vendor: {item.name}")
        elif t in VENDOR_RETURNS:
            cost = book.issue(qty)
            # The document credited inventory at the credit amount; leave at FIFO cost instead.
            variance = line.amount_cents - cost
            entry(txn, line, asset, variance, ZERO, f"Return to vendor: {item.name}")
            entry(txn, line, cogs, -variance, ZERO, f"Return to vendor: {item.name}")
        elif t in SALES:
            if qty >= 0:
                cost = book.issue(qty)
                entry(txn, line, cogs, cost, -qty, f"Cost of {item.name}", txn.customer_id)
                entry(txn, line, asset, -cost, -qty, f"Cost of {item.name}", txn.customer_id)
            else:
                value = round_cents(book.unit_cost() * -qty / 100)
                book.receive(-qty, value)
                entry(txn, line, asset, value, -qty, f"Returned {item.name}", txn.customer_id)
                entry(txn, line, cogs, -value, -qty, f"Returned {item.name}", txn.customer_id)
        elif t in CUSTOMER_RETURNS:
            if qty > 0:
                value = round_cents(book.unit_cost() * qty / 100)
                book.receive(qty, value)
                entry(txn, line, asset, value, qty, f"Returned {item.name}", txn.customer_id)
                entry(txn, line, cogs, -value, qty, f"Returned {item.name}", txn.customer_id)
        elif t in ADJUSTMENTS:
            adj_account = txn.account_id or system_account_id(s, "inventory_shrinkage")
            if qty > 0:
                value = round_cents(book.unit_cost() * qty / 100)
                book.receive(qty, value)
                entry(txn, line, asset, value, qty, f"Inventory adjustment: {item.name}")
                entry(txn, line, adj_account, -value, qty, f"Inventory adjustment: {item.name}")
                adj_totals[txn.id] = adj_totals.get(txn.id, 0) + value
            elif qty < 0:
                cost = book.issue(-qty)
                entry(txn, line, adj_account, cost, qty, f"Inventory adjustment: {item.name}")
                entry(txn, line, asset, -cost, qty, f"Inventory adjustment: {item.name}")
                adj_totals[txn.id] = adj_totals.get(txn.id, 0) - cost

    item.qty_on_hand = book.qty
    item.inventory_value_cents = book.value
    for txn_id, total in adj_totals.items():
        adj = s.get(Transaction, txn_id)
        if adj is not None:
            # An adjustment's total is the value it moved, summed over its items.
            others = [ln.item_id for ln in adj.lines if ln.item_id and ln.item_id != item_id]
            if not others:
                adj.total_cents = total
    s.flush()


def recompute_all(s: Session) -> int:
    ids = s.scalars(select(Item.id).where(Item.type == "inventory")).all()
    recompute_items(s, ids)
    return len(ids)


def history(s: Session, item_id: int, start: Optional[date] = None,
            end: Optional[date] = None) -> tuple[Decimal, int, list[Movement]]:
    """Movements for the valuation detail report: (opening qty, opening value, rows)."""
    item = s.get(Item, item_id)
    book = _Book(((item.cost or ZERO) if item else ZERO) * 100)
    opening_qty, opening_value = ZERO, 0
    rows: list[Movement] = []
    for line, txn in _events(s, item_id, end):
        before_qty, before_value = book.qty, book.value
        qty = line.qty or ZERO
        t = txn.type
        if t in RECEIPTS:
            if qty >= 0:
                book.receive(qty, line.amount_cents)
            else:
                book.issue(-qty)
        elif t in VENDOR_RETURNS or (t in SALES and qty >= 0):
            book.issue(qty)
        elif t in SALES:
            book.receive(-qty, round_cents(book.unit_cost() * -qty / 100))
        elif t in CUSTOMER_RETURNS and qty > 0:
            book.receive(qty, round_cents(book.unit_cost() * qty / 100))
        elif t in ADJUSTMENTS:
            if qty > 0:
                book.receive(qty, round_cents(book.unit_cost() * qty / 100))
            elif qty < 0:
                book.issue(-qty)
        if start is not None and txn.date < start:
            opening_qty, opening_value = book.qty, book.value
            continue
        rows.append(Movement(txn.date, txn.id, txn.type, txn.number, txn.entity_name, book.qty - before_qty,
                             book.value - before_value, book.qty, book.value))
    return opening_qty, opening_value, rows


def valuation_as_of(s: Session, item_id: int, as_of: Optional[date]) -> tuple[Decimal, int]:
    if as_of is None:
        item = s.get(Item, item_id)
        return (item.qty_on_hand or ZERO), item.inventory_value_cents or 0
    _, _, rows = history(s, item_id, None, as_of)
    if not rows:
        return ZERO, 0
    return rows[-1].qty_on_hand, rows[-1].value_on_hand
