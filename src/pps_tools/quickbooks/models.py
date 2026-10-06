"""Dataclasses for QBO transactions and accounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Account:
    """A QuickBooks Chart of Accounts entry."""

    id: str
    name: str
    account_type: str  # e.g., "Expense", "Income", "Cost of Goods Sold"
    account_sub_type: Optional[str] = None
    fully_qualified_name: Optional[str] = None
    active: bool = True

    @classmethod
    def from_qbo(cls, data: dict) -> "Account":
        return cls(
            id=str(data["Id"]),
            name=data["Name"],
            account_type=data.get("AccountType", ""),
            account_sub_type=data.get("AccountSubType"),
            fully_qualified_name=data.get("FullyQualifiedName"),
            active=data.get("Active", True),
        )


@dataclass
class Transaction:
    """A QBO transaction that needs (or has) a category assignment.

    Normalized view over QBO's Purchase / Expense / Deposit objects,
    since they share the core fields we care about for categorization.
    """

    id: str
    txn_type: str  # "Purchase", "Deposit", "JournalEntry", etc.
    sync_token: str  # required by QBO for updates
    txn_date: str
    amount: float
    payee_name: Optional[str] = None
    description: Optional[str] = None
    memo: Optional[str] = None
    payment_type: Optional[str] = None  # Cash / Check / CreditCard
    currency: str = "USD"
    # The line we might re-categorize. Most expenses have a single line.
    line_id: Optional[str] = None
    current_account_id: Optional[str] = None
    current_account_name: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_purchase(cls, data: dict) -> "Transaction":
        lines = data.get("Line", []) or []
        first_line = lines[0] if lines else {}
        detail = first_line.get("AccountBasedExpenseLineDetail", {}) or {}
        account_ref = detail.get("AccountRef", {}) or {}
        payee_ref = data.get("EntityRef", {}) or {}
        return cls(
            id=str(data["Id"]),
            txn_type="Purchase",
            sync_token=str(data.get("SyncToken", "0")),
            txn_date=data.get("TxnDate", ""),
            amount=float(data.get("TotalAmt", 0.0)),
            payee_name=payee_ref.get("name"),
            description=first_line.get("Description"),
            memo=data.get("PrivateNote"),
            payment_type=data.get("PaymentType"),
            currency=(data.get("CurrencyRef", {}) or {}).get("value", "USD"),
            line_id=first_line.get("Id"),
            current_account_id=account_ref.get("value"),
            current_account_name=account_ref.get("name"),
            raw=data,
        )

    def display_title(self) -> str:
        parts = [self.payee_name or self.description or self.memo or "(no description)"]
        return " — ".join(p for p in parts if p)
