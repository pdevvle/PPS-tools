"""Company preferences with defaults.

Stored as one JSON blob on the company row; reading a key that was never
set returns the default here, so new preferences need no migration.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from pps_tools.books.models import Company

DEFAULTS: dict[str, Any] = {
    # Sales form content
    "default_terms_id": None,
    "default_invoice_message": "Thank you for your business!",
    "default_estimate_message": "We look forward to working with you.",
    "default_statement_message": "",
    "show_shipping_fields": True,
    "show_discount_field": True,
    "discount_before_tax": True,
    "shipping_taxable": False,
    "show_service_date": False,
    "show_sku": False,
    "custom_transaction_numbers": True,
    "deposit_to_undeposited_funds": True,
    "auto_apply_credits": True,
    "auto_apply_payments": True,
    "track_inventory": True,
    "track_classes": "off",  # off | per_line | per_transaction
    "track_locations": False,
    "location_label": "Location",
    "track_projects": True,
    "track_time": True,
    "warn_duplicate_check_numbers": True,
    "warn_duplicate_bill_numbers": True,
    "default_bill_terms_id": None,
    "billable_expenses": True,
    "default_markup_pct": "0",
    "time_billable_by_default": True,
    "allow_negative_inventory": True,
    # Invoice look
    "invoice_accent_color": "#2c7a3f",
    "invoice_font": "Helvetica",
    "invoice_footer": "",
    "invoice_show_logo": True,
    "invoice_show_payment_link": True,
    # Email templates. Placeholders: {customer} {company} {number} {amount} {due_date} {link}
    "email_invoice_subject": "Invoice {number} from {company}",
    "email_invoice_body": ("Dear {customer},\n\nHere's invoice {number} for {amount}, due {due_date}.\n\n"
                           "View and pay online: {link}\n\nThank you for your business!\n{company}"),
    "email_estimate_subject": "Estimate {number} from {company}",
    "email_estimate_body": ("Dear {customer},\n\nPlease review estimate {number} for {amount}.\n\n"
                            "View and accept online: {link}\n\nThanks,\n{company}"),
    "email_receipt_subject": "Receipt {number} from {company}",
    "email_receipt_body": "Dear {customer},\n\nThank you for your payment of {amount}.\n\n{company}",
    "email_statement_subject": "Statement from {company}",
    "email_statement_body": ("Dear {customer},\n\nYour statement is attached. Balance due: {amount}.\n\n"
                             "Pay online: {link}\n\n{company}"),
    "email_po_subject": "Purchase order {number} from {company}",
    "email_po_body": "Hello {vendor},\n\nPlease find purchase order {number} attached.\n\n{company}",
    "email_reminder_subject": "Reminder: invoice {number} from {company}",
    "email_reminder_body": ("Dear {customer},\n\nJust a reminder that invoice {number} for {amount} "
                            "was due {due_date}.\n\nPay online: {link}\n\nThank you,\n{company}"),
    # Automations
    "progress_invoicing": True,  # several invoices from one estimate, each for part of it
    "reminders_enabled": False,
    "reminder_days": [3, 15, 30],  # days after due date
    "late_fees_enabled": False,
    "late_fee_type": "fixed",  # fixed | percent
    "late_fee_value": "25.00",
    "late_fee_days": 30,
    # Stripe
    "stripe_enabled": False,
    "stripe_card": True,
    "stripe_ach": True,
    "stripe_allow_partial": False,
    "stripe_payout_account_id": None,
    "stripe_fee_account": "merchant_fees",
    "stripe_save_cards": True,
    "stripe_statement_descriptor": "",
    # Mileage: IRS business standard mileage rate, dollars per mile, by the
    # date each rate took effect (IR-2025-128 set 2026 at 72.5 cents).
    "mileage_rates": [["2024-01-01", "0.67"], ["2025-01-01", "0.70"], ["2026-01-01", "0.725"]],
    # 1099-NEC/MISC reporting threshold by tax year: $600 through 2025,
    # $2,000 from 2026 (One Big Beautiful Bill Act; indexed from 2027).
    # Later years reuse the latest entry until you add one.
    "nec_threshold_by_year": {"2025": "600", "2026": "2000"},
    # AI
    "ai_categorize": True,
    "ai_receipts": True,
    # Report defaults
    "report_basis": None,  # None -> company.accounting_method
}


def get(s: Session, key: str) -> Any:
    company = s.get(Company, 1)
    prefs = (company.prefs if company else None) or {}
    if key in prefs:
        return prefs[key]
    return copy.deepcopy(DEFAULTS.get(key))


def get_all(s: Session) -> dict[str, Any]:
    company = s.get(Company, 1)
    merged = copy.deepcopy(DEFAULTS)
    merged.update((company.prefs if company else None) or {})
    return merged


def set_many(s: Session, values: dict[str, Any]) -> None:
    company = s.get(Company, 1)
    if company is None:
        raise RuntimeError("company not set up")
    prefs = dict(company.prefs or {})
    prefs.update(values)
    company.prefs = prefs  # reassign so SQLAlchemy sees the JSON change
