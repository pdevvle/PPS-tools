"""Chart of accounts: account types, detail types and the Account table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pps_tools.books.db import Base, utcnow


@dataclass(frozen=True)
class AccountType:
    code: str
    label: str
    classification: str  # asset | liability | equity | income | expense
    normal: int  # +1 debit-normal, -1 credit-normal
    section: str  # balance-sheet or P&L section heading
    cash_flow: str  # cash | operating | investing | financing | income
    order: int


ACCOUNT_TYPES: dict[str, AccountType] = {
    t.code: t
    for t in [
        AccountType("bank", "Bank", "asset", 1, "Bank Accounts", "cash", 10),
        AccountType("ar", "Accounts receivable (A/R)", "asset", 1, "Accounts Receivable", "operating", 20),
        AccountType("other_current_asset", "Other Current Assets", "asset", 1, "Other Current Assets", "operating", 30),
        AccountType("fixed_asset", "Fixed Assets", "asset", 1, "Fixed Assets", "investing", 40),
        AccountType("other_asset", "Other Assets", "asset", 1, "Other Assets", "investing", 50),
        AccountType("ap", "Accounts payable (A/P)", "liability", -1, "Accounts Payable", "operating", 60),
        AccountType("credit_card", "Credit Card", "liability", -1, "Credit Cards", "operating", 70),
        AccountType("other_current_liability", "Other Current Liabilities", "liability", -1,
                    "Other Current Liabilities", "operating", 80),
        AccountType("long_term_liability", "Long Term Liabilities", "liability", -1,
                    "Long-Term Liabilities", "financing", 90),
        AccountType("equity", "Equity", "equity", -1, "Equity", "financing", 100),
        AccountType("income", "Income", "income", -1, "Income", "income", 110),
        AccountType("cogs", "Cost of Goods Sold", "expense", 1, "Cost of Goods Sold", "income", 120),
        AccountType("expense", "Expenses", "expense", 1, "Expenses", "income", 130),
        AccountType("other_income", "Other Income", "income", -1, "Other Income", "income", 140),
        AccountType("other_expense", "Other Expense", "expense", 1, "Other Expenses", "income", 150),
    ]
}

BALANCE_SHEET_TYPES = [c for c, t in ACCOUNT_TYPES.items() if t.classification in ("asset", "liability", "equity")]
PL_TYPES = [c for c, t in ACCOUNT_TYPES.items() if t.classification in ("income", "expense")]

DETAIL_TYPES: dict[str, list[str]] = {
    "bank": ["Cash on hand", "Checking", "Money Market", "Rents Held in Trust", "Savings",
             "Trust account", "Payment processor clearing"],
    "ar": ["Accounts Receivable (A/R)"],
    "other_current_asset": [
        "Allowance for Bad Debts", "Development Costs", "Employee Cash Advances", "Inventory",
        "Investment - Mortgage/Real Estate Loans", "Investment - Tax-Exempt Securities",
        "Investment - U.S. Government Obligations", "Investments - Other", "Loans To Officers",
        "Loans to Others", "Loans to Stockholders", "Other Current Assets", "Prepaid Expenses",
        "Retainage", "Undeposited Funds"],
    "fixed_asset": [
        "Accumulated Amortization", "Accumulated Depletion", "Accumulated Depreciation", "Buildings",
        "Depletable Assets", "Furniture & Fixtures", "Intangible Assets", "Land",
        "Leasehold Improvements", "Machinery & Equipment", "Other fixed assets", "Vehicles"],
    "other_asset": [
        "Accumulated Amortization of Other Assets", "Goodwill", "Lease Buyout", "Licenses",
        "Organizational Costs", "Other Long-term Assets", "Security Deposits"],
    "ap": ["Accounts Payable (A/P)"],
    "credit_card": ["Credit Card"],
    "other_current_liability": [
        "Customer Deposits", "Federal Income Tax Payable", "Insurance Payable", "Line of Credit",
        "Loan Payable", "Other Current Liabilities", "Payroll Clearing", "Payroll Tax Payable",
        "Prepaid Expenses Payable", "Rents in trust - Liability", "Sales Tax Payable",
        "State/Local Income Tax Payable", "Trust Accounts - Liabilities", "Undistributed Tips"],
    "long_term_liability": ["Notes Payable", "Other Long Term Liabilities", "Shareholder Notes Payable"],
    "equity": [
        "Accumulated Adjustment", "Common Stock", "Estimated Taxes", "Healthcare",
        "Opening Balance Equity", "Owner's Equity", "Paid-In Capital or Surplus",
        "Partner Contributions", "Partner Distributions", "Partner's Equity", "Personal Expense",
        "Personal Income", "Preferred Stock", "Retained Earnings", "Treasury Stock"],
    "income": [
        "Discounts/Refunds Given", "Non-Profit Income", "Other Primary Income",
        "Sales of Product Income", "Service/Fee Income", "Unapplied Cash Payment Income"],
    "other_income": [
        "Dividend Income", "Interest Earned", "Other Investment Income",
        "Other Miscellaneous Income", "Tax-Exempt Interest"],
    "cogs": [
        "Cost of labor - COS", "Equipment Rental - COS", "Other Costs of Services - COS",
        "Shipping, Freight & Delivery - COS", "Supplies & Materials - COGS"],
    "expense": [
        "Advertising/Promotional", "Auto", "Bad Debts", "Bank Charges", "Charitable Contributions",
        "Communication", "Cost of Labor", "Dues & subscriptions", "Entertainment",
        "Entertainment Meals", "Equipment Rental", "Finance costs", "Insurance", "Interest Paid",
        "Legal & Professional Fees", "Office/General Administrative Expenses",
        "Other Business Expenses", "Other Miscellaneous Service Cost", "Payroll Expenses",
        "Promotional Meals", "Rent or Lease of Buildings", "Repair & Maintenance",
        "Shipping, Freight & Delivery", "Supplies & Materials", "Taxes Paid", "Travel",
        "Travel Meals", "Unapplied Cash Bill Payment Expense", "Utilities"],
    "other_expense": [
        "Amortization", "Depreciation", "Exchange Gain or Loss", "Gas And Fuel", "Home Office",
        "Other Miscellaneous Expense", "Other Vehicle Expenses", "Parking and Tolls",
        "Penalties & Settlements", "Vehicle", "Vehicle Insurance", "Vehicle Lease",
        "Vehicle Loan Interest", "Vehicle Repairs"],
}

# Accounts the software itself relies on. Created by setup, never deletable.
SYSTEM_ACCOUNTS = {
    "ar": ("Accounts Receivable (A/R)", "ar", "Accounts Receivable (A/R)"),
    "ap": ("Accounts Payable (A/P)", "ap", "Accounts Payable (A/P)"),
    "undeposited_funds": ("Payments to deposit", "other_current_asset", "Undeposited Funds"),
    "inventory_asset": ("Inventory Asset", "other_current_asset", "Inventory"),
    "uncategorized_asset": ("Uncategorized Asset", "other_current_asset", "Other Current Assets"),
    "sales_tax_payable": ("Sales Tax Payable", "other_current_liability", "Sales Tax Payable"),
    "opening_balance_equity": ("Opening Balance Equity", "equity", "Opening Balance Equity"),
    "retained_earnings": ("Retained Earnings", "equity", "Retained Earnings"),
    "uncategorized_income": ("Uncategorized Income", "income", "Other Primary Income"),
    "discounts_given": ("Discounts Given", "income", "Discounts/Refunds Given"),
    "refunds_given": ("Refunds & Allowances", "income", "Discounts/Refunds Given"),
    "shipping_income": ("Shipping Income", "income", "Service/Fee Income"),
    "late_fee_income": ("Late Fee Income", "income", "Service/Fee Income"),
    "sales_income": ("Sales", "income", "Sales of Product Income"),
    "services_income": ("Services", "income", "Service/Fee Income"),
    "cogs": ("Cost of Goods Sold", "cogs", "Supplies & Materials - COGS"),
    "inventory_shrinkage": ("Inventory Shrinkage", "cogs", "Supplies & Materials - COGS"),
    "uncategorized_expense": ("Uncategorized Expense", "expense", "Other Miscellaneous Service Cost"),
    "reconciliation_discrepancies": ("Reconciliation Discrepancies", "other_expense",
                                     "Other Miscellaneous Expense"),
    "exchange_gain_loss": ("Exchange Gain or Loss", "other_expense", "Exchange Gain or Loss"),
    "stripe_clearing": ("Stripe Balance", "bank", "Payment processor clearing"),
    "merchant_fees": ("Merchant Processing Fees", "expense", "Bank Charges"),
    "chargebacks": ("Chargebacks & Disputes", "expense", "Bad Debts"),
    "sales_tax_adjustments": ("Sales Tax Adjustments", "other_expense", "Other Miscellaneous Expense"),
}


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40), index=True)
    detail_type: Mapped[Optional[str]] = mapped_column(String(80))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    system_key: Mapped[Optional[str]] = mapped_column(String(40), unique=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    bank_name: Mapped[Optional[str]] = mapped_column(String(120))
    bank_last4: Mapped[Optional[str]] = mapped_column(String(8))
    # IRS form line for tax-prep exports, e.g. "Schedule C: Line 8 Advertising".
    tax_line: Mapped[Optional[str]] = mapped_column(String(120))
    # 1099 box this account's vendor payments land in, e.g. "NEC-1", "MISC-1".
    form_1099_box: Mapped[Optional[str]] = mapped_column(String(16))
    # Next check number to print for bank accounts.
    next_check_number: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    parent: Mapped[Optional["Account"]] = relationship(remote_side="Account.id", back_populates="children")
    children: Mapped[list["Account"]] = relationship(back_populates="parent", order_by="Account.name")

    @property
    def type_info(self) -> AccountType:
        return ACCOUNT_TYPES[self.type]

    @property
    def type_label(self) -> str:
        return ACCOUNT_TYPES[self.type].label

    @property
    def classification(self) -> str:
        return ACCOUNT_TYPES[self.type].classification

    @property
    def normal(self) -> int:
        return ACCOUNT_TYPES[self.type].normal

    @property
    def is_balance_sheet(self) -> bool:
        return self.classification in ("asset", "liability", "equity")

    @property
    def full_name(self) -> str:
        names = []
        node: Optional[Account] = self
        guard = 0
        while node is not None and guard < 20:
            names.append(node.name)
            node = node.parent
            guard += 1
        return ":".join(reversed(names))

    @property
    def display_name(self) -> str:
        return f"{self.number} {self.full_name}" if self.number else self.full_name

    @property
    def depth(self) -> int:
        d, node = 0, self.parent
        while node is not None and d < 20:
            d += 1
            node = node.parent
        return d

    @property
    def is_register_account(self) -> bool:
        """Accounts with a check-register style view (QBO: all balance-sheet accounts)."""
        return self.is_balance_sheet

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.id} {self.full_name} ({self.type})>"
