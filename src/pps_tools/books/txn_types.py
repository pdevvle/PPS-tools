"""What each kind of transaction is: who it's with, which lines it carries,
which header account it uses, whether it posts, and how it sits in A/R or A/P.

Forms, the posting engine, the transaction lists and reports all read
this table, so adding a type means describing it here first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SALES_DEPOSIT_TYPES = ("bank", "other_current_asset")
PAY_FROM_TYPES = ("bank", "credit_card", "other_current_asset")
BALANCE_SHEET = ("bank", "ar", "other_current_asset", "fixed_asset", "other_asset", "ap", "credit_card",
                 "other_current_liability", "long_term_liability", "equity")


@dataclass(frozen=True)
class TxnType:
    code: str
    label: str
    plural: str
    slug: str
    section: str  # sales | expenses | banking | accounting | inventory | tax
    entity: Optional[str] = None  # customer | vendor | payee | agency
    posts: bool = True
    open_item: Optional[str] = None  # ar | ap
    # +1: creates something owed (invoice, bill). -1: a credit (payment, credit memo).
    open_sign: int = 0
    item_lines: bool = False
    account_lines: bool = False
    has_tax: bool = False
    has_terms: bool = False
    header_account: Optional[str] = None  # label of the header account field
    header_account_types: tuple[str, ...] = ()
    default_header_account: Optional[str] = None  # system key or pref name
    has_amount: bool = False  # a single amount rather than lines (payment, transfer)
    applies_to: tuple[str, ...] = ()  # transaction types it can be applied against
    link_type: Optional[str] = None
    number_seq: Optional[str] = None
    customer_facing: bool = False
    vendor_facing: bool = False
    # Sign of the posting relative to the "normal" document (credit memo = -1 of invoice).
    reverses: Optional[str] = None
    statuses: tuple[str, ...] = field(default_factory=tuple)
    icon: str = "doc"


TXN_TYPES: dict[str, TxnType] = {
    t.code: t
    for t in [
        TxnType("estimate", "Estimate", "Estimates", "estimates", "sales", entity="customer", posts=False,
                item_lines=True, has_tax=True, number_seq="estimate", customer_facing=True,
                statuses=("pending", "accepted", "rejected", "closed", "converted")),
        TxnType("invoice", "Invoice", "Invoices", "invoices", "sales", entity="customer",
                open_item="ar", open_sign=1, item_lines=True, has_tax=True, has_terms=True,
                number_seq="invoice", customer_facing=True),
        TxnType("sales_receipt", "Sales receipt", "Sales receipts", "sales-receipts", "sales",
                entity="customer", item_lines=True, has_tax=True, header_account="Deposit to",
                header_account_types=SALES_DEPOSIT_TYPES, default_header_account="undeposited_funds",
                number_seq="sales_receipt", customer_facing=True),
        TxnType("payment", "Payment", "Payments", "payments", "sales", entity="customer",
                open_item="ar", open_sign=-1, header_account="Deposit to",
                header_account_types=SALES_DEPOSIT_TYPES, default_header_account="undeposited_funds",
                has_amount=True, applies_to=("invoice",), link_type="payment", customer_facing=True),
        TxnType("credit_memo", "Credit memo", "Credit memos", "credit-memos", "sales", entity="customer",
                open_item="ar", open_sign=-1, item_lines=True, has_tax=True, applies_to=("invoice",),
                link_type="credit", number_seq="credit_memo", customer_facing=True, reverses="invoice"),
        TxnType("refund_receipt", "Refund receipt", "Refund receipts", "refunds", "sales",
                entity="customer", item_lines=True, has_tax=True, header_account="Refund from",
                header_account_types=PAY_FROM_TYPES, number_seq="refund_receipt", customer_facing=True,
                reverses="sales_receipt"),
        TxnType("customer_refund", "Customer refund", "Customer refunds", "customer-refunds", "sales",
                entity="customer", open_item="ar", open_sign=1, header_account="Refund from",
                header_account_types=PAY_FROM_TYPES, has_amount=True,
                applies_to=("credit_memo", "payment"), link_type="refund"),
        TxnType("delayed_charge", "Delayed charge", "Delayed charges", "delayed-charges", "sales",
                entity="customer", posts=False, item_lines=True, statuses=("open", "closed")),
        TxnType("delayed_credit", "Delayed credit", "Delayed credits", "delayed-credits", "sales",
                entity="customer", posts=False, item_lines=True, statuses=("open", "closed")),
        TxnType("purchase_order", "Purchase order", "Purchase orders", "purchase-orders", "expenses",
                entity="vendor", posts=False, item_lines=True, account_lines=True,
                number_seq="purchase_order", vendor_facing=True, statuses=("open", "closed")),
        TxnType("bill", "Bill", "Bills", "bills", "expenses", entity="vendor", open_item="ap", open_sign=1,
                item_lines=True, account_lines=True, has_terms=True),
        TxnType("vendor_credit", "Vendor credit", "Vendor credits", "vendor-credits", "expenses",
                entity="vendor", open_item="ap", open_sign=-1, item_lines=True, account_lines=True,
                applies_to=("bill",), link_type="vendor_credit", reverses="bill"),
        TxnType("bill_payment", "Bill payment", "Bill payments", "bill-payments", "expenses",
                entity="vendor", open_item="ap", open_sign=-1, header_account="Payment account",
                header_account_types=("bank", "credit_card"), has_amount=True, applies_to=("bill",),
                link_type="bill_payment", vendor_facing=True),
        TxnType("expense", "Expense", "Expenses", "expenses", "expenses", entity="payee",
                item_lines=True, account_lines=True, header_account="Payment account",
                header_account_types=PAY_FROM_TYPES),
        TxnType("check", "Check", "Checks", "checks", "expenses", entity="payee", item_lines=True,
                account_lines=True, header_account="Bank account", header_account_types=("bank",),
                vendor_facing=True),
        TxnType("cc_credit", "Credit card credit", "Credit card credits", "card-credits", "expenses",
                entity="payee", item_lines=True, account_lines=True, header_account="Credit card",
                header_account_types=("credit_card",), reverses="expense"),
        TxnType("deposit", "Deposit", "Deposits", "deposits", "banking", account_lines=True,
                header_account="Account", header_account_types=SALES_DEPOSIT_TYPES,
                applies_to=("payment", "sales_receipt", "refund_receipt"), link_type="deposit"),
        TxnType("transfer", "Transfer", "Transfers", "transfers", "banking", header_account="Transfer from",
                header_account_types=BALANCE_SHEET, has_amount=True),
        TxnType("cc_payment", "Credit card payment", "Credit card payments", "card-payments", "banking",
                entity="vendor", header_account="Bank account", header_account_types=("bank",),
                has_amount=True),
        TxnType("journal_entry", "Journal entry", "Journal entries", "journal-entries", "accounting",
                account_lines=True, number_seq="journal_entry"),
        TxnType("inventory_adjustment", "Inventory qty adjustment", "Inventory adjustments",
                "inventory-adjustments", "inventory", item_lines=True, header_account="Inventory adjustment account",
                # Equity for starting quantities, offset to Opening Balance Equity as in QBO.
                header_account_types=("cogs", "expense", "other_expense", "income", "other_income", "equity"),
                default_header_account="inventory_shrinkage", number_seq="inventory_adjustment"),
        TxnType("sales_tax_payment", "Sales tax payment", "Sales tax payments", "tax-payments", "tax",
                entity="agency", header_account="Payment account", header_account_types=PAY_FROM_TYPES,
                has_amount=True),
        TxnType("sales_tax_adjustment", "Sales tax adjustment", "Sales tax adjustments", "tax-adjustments",
                "tax", entity="agency", header_account="Adjustment account",
                header_account_types=("expense", "other_expense", "income", "other_income"),
                default_header_account="sales_tax_adjustments", has_amount=True),
    ]
}

BY_SLUG = {t.slug: t for t in TXN_TYPES.values()}

SALES_TYPES = [c for c, t in TXN_TYPES.items() if t.section == "sales"]
PURCHASE_TYPES = [c for c, t in TXN_TYPES.items() if t.section == "expenses"]
# Documents whose lines move money in or out of income/expense accounts.
SALES_DOCS = ("invoice", "sales_receipt", "credit_memo", "refund_receipt")
PURCHASE_DOCS = ("bill", "vendor_credit", "expense", "check", "cc_credit")
# Link types that settle an A/R or A/P balance.
SETTLE_LINKS = ("payment", "credit", "refund", "bill_payment", "vendor_credit")


def info(code: str) -> TxnType:
    return TXN_TYPES[code]
