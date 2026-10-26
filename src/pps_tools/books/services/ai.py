"""Optional help from Claude: categorizing bank transactions and reading receipts.

Off unless ANTHROPIC_API_KEY is set and the feature is on in Settings →
Advanced. What's sent: the transactions' dates, amounts and descriptions,
or the receipt image, plus account and vendor names so Claude can pick from
them. Every id Claude returns is checked against the books before it's used,
and nothing is posted: suggestions wait in For Review like any other.
"""

from __future__ import annotations

import base64
import json
import logging
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books import money
from pps_tools.books.models import Account, Attachment, BankFeedItem, Vendor
from pps_tools.books.services import attachments as attach_service
from pps_tools.books.services import prefs
from pps_tools.books.services.accounts import ordered_accounts
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError

log = logging.getLogger(__name__)

BATCH = 40
# If Claude's safeguards decline a request, the API retries it on a fallback model by itself.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CATEGORY_TYPES = ("income", "other_income", "cogs", "expense", "other_expense", "fixed_asset", "other_current_asset",
                  "long_term_liability", "other_current_liability", "equity")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class FeedSuggestion(BaseModel):
    item_id: int
    account_id: Optional[int]
    vendor_id: Optional[int]
    confidence: float
    reason: str


class FeedSuggestions(BaseModel):
    suggestions: list[FeedSuggestion]


class ReceiptLine(BaseModel):
    description: str
    amount: str


class ReceiptData(BaseModel):
    vendor_name: Optional[str]
    vendor_id: Optional[int]
    date: Optional[str]
    total: Optional[str]
    tax: Optional[str]
    tip: Optional[str]
    card_last4: Optional[str]
    category_id: Optional[int]
    memo: Optional[str]
    lines: list[ReceiptLine]


FEED_SYSTEM = """You categorize bank and credit card transactions for a small business's books.

For each transaction, choose the account it belongs in from the chart of accounts below, by id, and the vendor
by id if it is clearly one of the listed vendors. Money out (negative amounts) usually goes to an expense, cost
of goods sold, asset or liability account; money in (positive) to an income account. Leave account_id null when
you can't tell, and for transfers between the business's own accounts, credit card payments, and owner
deposits or draws, which the bookkeeper records differently. Use vendor_id only for an existing vendor; never
invent ids.

confidence is your probability (0 to 1) that the account is right. reason is a few words a bookkeeper would
recognize, like "Fuel purchase" or "Monthly software subscription".

Chart of accounts (id | name | type):
{accounts}

Vendors (id | name):
{vendors}"""

RECEIPT_SYSTEM = """You read receipts and bills for a small business's books.

Return what the document shows: the merchant's name, the date as YYYY-MM-DD, the total actually charged, any
sales tax and tip, the last four digits of the card if printed, and the line items. Write amounts as plain
numbers like 1234.50. Use null for anything the document doesn't show; don't estimate.

Pick vendor_id if the merchant is clearly one of the listed vendors, and category_id: the expense account
this purchase belongs in, from the list. memo is a short description of what was bought.

Expense accounts (id | name):
{categories}

Vendors (id | name):
{vendors}"""


def _client(config):
    import anthropic

    if not config.anthropic_api_key:
        raise BooksError("Set ANTHROPIC_API_KEY to use Claude.")
    return anthropic.Anthropic(api_key=config.anthropic_api_key)


def _ask(config, system: str, content, output_format, effort: str):
    """One structured-output request. Returns the parsed model, or None if Claude declined."""
    import anthropic

    client = _client(config)
    try:
        response = client.beta.messages.parse(
            model=config.ai_model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": effort},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_format=output_format,
        )
    except anthropic.AuthenticationError:
        raise BooksError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY.") from None
    except anthropic.RateLimitError:
        raise BooksError("Claude is busy (rate limited). Try again in a minute.") from None
    except anthropic.BadRequestError as exc:
        raise BooksError(f"Claude couldn't take that request: {exc.message}") from None
    except anthropic.APIStatusError as exc:
        raise BooksError(f"Claude returned an error ({exc.status_code}). Try again later.") from None
    except anthropic.APIConnectionError:
        raise BooksError("Couldn't reach Claude. Check the server's internet connection.") from None
    if response.stop_reason == "refusal":
        log.info("Claude declined (%s)", getattr(response.stop_details, "category", None))
        return None
    if response.stop_reason == "max_tokens":
        log.warning("Claude's answer was cut off at max_tokens")
        return None
    return response.parsed_output


# -- bank feed ----------------------------------------------------------------------------------


def categorize_feed(s: Session, items: list[BankFeedItem], config) -> int:
    """Suggest an account (and vendor) for feed items nothing else could place. Returns how many got one."""
    if not prefs.get(s, "ai_categorize"):
        return 0
    # Anything a rule, a match or history already placed is left alone; a payee history that found
    # the vendor but no account still gets an account suggestion.
    items = [it for it in items if it.status == "review" and not it.suggested_account_id
             and not it.suggested_match_txn_id and not it.suggested_rule_id]
    if not items:
        return 0
    accounts = [a for a in ordered_accounts(s, active_only=True) if a.type in CATEGORY_TYPES]
    vendors = s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all()
    account_ids = {a.id for a in accounts}
    vendor_ids = {v.id for v in vendors}
    system = FEED_SYSTEM.format(
        accounts="\n".join(f"{a.id} | {a.full_name} | {a.type_label}" for a in accounts),
        vendors="\n".join(f"{v.id} | {v.display_name}" for v in vendors) or "(none yet)")
    by_id = {it.id: it for it in items}
    placed = 0
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        rows = [{"item_id": it.id, "date": it.date.isoformat(), "amount": money.fmt_plain(it.amount_cents),
                 "description": it.description, "payee": it.payee, "bank_category": it.bank_category}
                for it in batch]
        content = "Categorize these transactions:\n" + "\n".join(json.dumps(r) for r in rows)
        result = _ask(config, system, content, FeedSuggestions, effort="low")
        if result is None:
            continue
        for sug in result.suggestions:
            item = by_id.get(sug.item_id)
            if item is None or item.suggested_account_id:
                continue
            account_id = sug.account_id if sug.account_id in account_ids else None
            vendor_id = sug.vendor_id if sug.vendor_id in vendor_ids else None
            if account_id is None:
                continue
            item.suggested_account_id = account_id
            item.suggested_vendor_id = item.suggested_vendor_id or vendor_id
            item.suggestion_source = "ai"
            item.suggestion_confidence = Decimal(str(round(min(max(sug.confidence, 0.0), 1.0), 2)))
            item.suggestion_reason = f"Claude: {sug.reason[:200]}"
            placed += 1
    s.flush()
    return placed


# -- receipts -----------------------------------------------------------------------------------------


def read_receipt(s: Session, config, att: Attachment) -> dict:
    """Read one receipt into ``att.extracted`` (the receipts page's form fields)."""
    ctype = att.content_type
    if ctype not in IMAGE_TYPES and ctype != "application/pdf":
        att.extracted = {"error": "Claude reads PNG, JPEG, GIF, WebP and PDF receipts. Enter this one by hand."}
        att.receipt_status = "reviewed"
        return att.extracted
    data = base64.standard_b64encode(attach_service.read(config, att)).decode("ascii")
    if ctype == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    else:
        block = {"type": "image", "source": {"type": "base64", "media_type": ctype, "data": data}}
    categories = [a for a in ordered_accounts(s, active_only=True) if a.type in ("expense", "cogs", "other_expense",
                                                                                    "fixed_asset")]
    vendors = s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all()
    system = RECEIPT_SYSTEM.format(categories="\n".join(f"{a.id} | {a.full_name}" for a in categories),
                                   vendors="\n".join(f"{v.id} | {v.display_name}" for v in vendors) or "(none yet)")
    result = _ask(config, system, [block, {"type": "text", "text": "Read this receipt."}], ReceiptData,
                  effort="medium")
    if result is None:
        att.extracted = {"error": "Claude couldn't read this receipt. Enter the details by hand."}
        att.receipt_status = "reviewed"
        return att.extracted
    out: dict = {"vendor": result.vendor_name, "memo": result.memo, "source": "claude",
                 "lines": [ln.model_dump() for ln in result.lines]}
    if result.vendor_id in {v.id for v in vendors}:
        out["vendor_id"] = result.vendor_id
    if result.category_id in {a.id for a in categories}:
        out["category_id"] = result.category_id
    try:
        when = parse_date(result.date) if result.date else None
        out["date"] = when.isoformat() if when else None
    except ValueError:
        out["date"] = None
    for key in ("total", "tax", "tip"):
        raw = getattr(result, key)
        try:
            out[key] = money.fmt_plain(money.cents(raw)) if raw else None
        except money.MoneyError:
            out[key] = None
    if result.card_last4 and result.card_last4.isdigit():
        acct = s.scalar(select(Account).where(Account.bank_last4 == result.card_last4[-4:], Account.active.is_(True)))
        if acct is not None:
            out["account_id"] = acct.id
    att.extracted = out
    att.receipt_status = "reviewed"
    s.flush()
    return out


def read_receipts(s: Session, config, limit: int = 10) -> int:
    """Read the newest unread receipts in the inbox. Returns how many were read."""
    if not prefs.get(s, "ai_receipts"):
        return 0
    todo = s.scalars(select(Attachment).where(Attachment.receipt_status == "inbox", Attachment.extracted.is_(None))
                     .order_by(Attachment.created_at.desc()).limit(limit)).all()
    read = 0
    for att in todo:
        if "error" not in read_receipt(s, config, att):
            read += 1
    return read
