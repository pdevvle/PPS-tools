"""Claude-assisted categorization and receipt reading, with a fake API client."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from pps_tools.books.models import Account, BankFeedItem, Vendor
from pps_tools.books.services import ai
from pps_tools.books.services import attachments as attach_service
from pps_tools.books.services import banking
from pps_tools.books.services.errors import BooksError
from pps_tools.books.services.importers.bankfiles import BankLine, Statement


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        stop, parsed = reply
        return SimpleNamespace(stop_reason=stop, stop_details=None, parsed_output=parsed)


def fake_client(monkeypatch, replies):
    messages = FakeMessages(replies)
    monkeypatch.setattr(ai, "_client", lambda config: SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    return messages


@pytest.fixture
def cfg(tmp_path):
    return SimpleNamespace(anthropic_api_key="sk-ant-test", ai_model="claude-opus-5-5", data_dir=tmp_path,
                           attachments_dir=tmp_path / "attachments")


def _feed(s, b, *lines):
    checking = b.acct("Checking")
    stmt = Statement(lines=[BankLine(date=date(2026, 3, d), amount_cents=amt, description=desc, external_id=f"x{d}")
                            for d, amt, desc in lines])
    banking.import_statement(s, checking, stmt, source="csv")
    return s.scalars(select(BankFeedItem).order_by(BankFeedItem.id)).all()


def test_categorize_feed_keeps_only_real_ids(s, b, cfg, monkeypatch):
    fuel_vendor = b.vendor("Fuel Stop")
    items = _feed(s, b, (2, -4750, "FUEL STOP 57442"), (3, -1999, "MYSTERY CHARGE"), (4, -500, "TRANSFER TO SAVINGS"))
    vehicle = b.acct("Vehicle Expenses")
    messages = fake_client(monkeypatch, [("end_turn", ai.FeedSuggestions(suggestions=[
        ai.FeedSuggestion(item_id=items[0].id, account_id=vehicle.id, vendor_id=fuel_vendor.id, confidence=0.93,
                          reason="Fuel purchase"),
        ai.FeedSuggestion(item_id=items[1].id, account_id=999999, vendor_id=None, confidence=0.4, reason="Unknown"),
        ai.FeedSuggestion(item_id=items[2].id, account_id=None, vendor_id=None, confidence=0.2, reason="Transfer"),
    ]))])
    placed = ai.categorize_feed(s, items, cfg)
    assert placed == 1
    assert items[0].suggested_account_id == vehicle.id and items[0].suggested_vendor_id == fuel_vendor.id
    assert items[0].suggestion_source == "ai" and items[0].suggestion_reason == "Claude: Fuel purchase"
    assert items[1].suggestion_source is None  # an id that isn't in the chart is ignored
    assert items[2].suggestion_source is None
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["betas"] == [ai.FALLBACK_BETA] and call["output_format"] is ai.FeedSuggestions
    assert call["output_config"] == {"effort": "low"}
    assert "FUEL STOP 57442" in call["messages"][0]["content"]
    assert f"{vehicle.id} | " in call["system"][0]["text"]


def test_categorize_feed_skips_items_already_suggested_and_handles_refusal(s, b, cfg, monkeypatch):
    rent = b.acct("Rent & Lease")
    b.vendor("Landlord")
    items = _feed(s, b, (5, -240000, "RIVERSIDE PROPERTIES RENT"))
    items[0].suggestion_source = "rule"
    items[0].suggested_account_id = rent.id
    messages = fake_client(monkeypatch, [])
    assert ai.categorize_feed(s, items, cfg) == 0
    assert messages.calls == []
    items[0].suggestion_source = items[0].suggested_account_id = None
    fake_client(monkeypatch, [("refusal", None)])
    assert ai.categorize_feed(s, items, cfg) == 0


def test_categorize_feed_off_in_settings(s, b, cfg, monkeypatch):
    from pps_tools.books.services import prefs

    prefs.set_many(s, {"ai_categorize": False})
    items = _feed(s, b, (6, -1200, "COFFEE"))
    messages = fake_client(monkeypatch, [])
    assert ai.categorize_feed(s, items, cfg) == 0 and messages.calls == []


def test_api_errors_become_friendly_messages(s, b, cfg, monkeypatch):
    import anthropic
    import httpx2 as httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)
    fake_client(monkeypatch, [err])
    items = _feed(s, b, (7, -999, "SOMETHING"))
    with pytest.raises(BooksError, match="rate limited"):
        ai.categorize_feed(s, items, cfg)


def test_read_receipt_fills_the_form_fields(s, b, cfg, monkeypatch):
    office = b.acct("Office Supplies & Software")
    store = b.vendor("Downtown Office Supply")
    card = b.acct("Business Credit Card")
    card.bank_last4 = "4242"
    att = attach_service.store(s, cfg, "receipt.png", b"\x89PNG fake", "image/png", receipt=True)
    messages = fake_client(monkeypatch, [("end_turn", ai.ReceiptData(
        vendor_name="Downtown Office Supply", vendor_id=store.id, date="03/14/2026", total="$1,034.50", tax="58.50",
        tip=None, card_last4="4242", category_id=office.id, memo="Printer paper and toner",
        lines=[ai.ReceiptLine(description="Toner", amount="976.00")]))])
    out = ai.read_receipt(s, cfg, att)
    assert out["date"] == "2026-03-14" and out["total"] == "1034.50" and out["tax"] == "58.50"
    assert out["vendor_id"] == store.id and out["category_id"] == office.id and out["account_id"] == card.id
    assert att.receipt_status == "reviewed"
    block = messages.calls[0]["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"
    assert messages.calls[0]["output_config"] == {"effort": "medium"}


def test_read_receipt_rejects_unsupported_files(s, b, cfg, monkeypatch):
    att = attach_service.store(s, cfg, "receipt.heic", b"heic", "image/heic", receipt=True)
    messages = fake_client(monkeypatch, [])
    out = ai.read_receipt(s, cfg, att)
    assert "error" in out and messages.calls == []


def test_unknown_ids_from_a_receipt_are_dropped(s, b, cfg, monkeypatch):
    att = attach_service.store(s, cfg, "bill.pdf", b"%PDF-1.4 fake", "application/pdf", receipt=True)
    fake_client(monkeypatch, [("end_turn", ai.ReceiptData(
        vendor_name="New Place", vendor_id=424242, date="not a date", total="12", tax=None, tip=None,
        card_last4=None, category_id=313131, memo=None, lines=[]))])
    out = ai.read_receipt(s, cfg, att)
    assert "vendor_id" not in out and "category_id" not in out and out["date"] is None and out["total"] == "12.00"
    assert out["vendor"] == "New Place"


def test_vendor_and_account_lists_reach_the_prompt(s, b, cfg, monkeypatch):
    b.vendor("Paper Source")
    items = _feed(s, b, (8, -5000, "PAPER"))
    messages = fake_client(monkeypatch, [("end_turn", ai.FeedSuggestions(suggestions=[]))])
    ai.categorize_feed(s, items, cfg)
    system = messages.calls[0]["system"][0]["text"]
    vid = s.scalar(select(Vendor.id).where(Vendor.display_name == "Paper Source"))
    assert f"{vid} | Paper Source" in system
    assert s.scalar(select(Account.id).where(Account.name == "Paper & Stock")) is not None
