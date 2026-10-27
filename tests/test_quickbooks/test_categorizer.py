"""Unit tests for the Claude-backed categorizer.

We stub out the Anthropic client so no network calls happen.
"""

from types import SimpleNamespace

import pytest

from pps_tools.quickbooks.categorizer import Categorizer, _extract_json
from pps_tools.quickbooks.models import Account, Transaction


class _StubClient:
    """Minimal stand-in for anthropic.Anthropic client."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.messages = SimpleNamespace(create=self._create)
        self.last_call = None

    def _create(self, **kwargs):
        self.last_call = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.response_text)]
        )


def _chart() -> list[Account]:
    return [
        Account(id="1", name="Office Supplies", account_type="Expense"),
        Account(id="2", name="Meals & Entertainment", account_type="Expense"),
        Account(id="3", name="Print Materials", account_type="Cost of Goods Sold"),
    ]


def _txn() -> Transaction:
    return Transaction(
        id="99", txn_type="Purchase", sync_token="0",
        txn_date="2025-03-01", amount=45.67,
        payee_name="Starbucks", description="morning coffee",
        line_id="1", current_account_name="Uncategorized Expense",
    )


def test_suggest_returns_valid_account():
    stub = _StubClient(
        '{"account_id": "2", "account_name": "Meals & Entertainment", '
        '"confidence": 0.82, "reasoning": "Coffee purchase from a cafe."}'
    )
    cat = Categorizer(accounts=_chart(), client=stub)
    s = cat.suggest(_txn())
    assert s.account_id == "2"
    assert s.account_name == "Meals & Entertainment"
    assert 0.0 <= s.confidence <= 1.0
    assert "coffee" in s.reasoning.lower()


def test_suggest_repairs_unknown_id_via_name_match():
    # Claude made up an id but the name matches our chart — we should reconcile.
    stub = _StubClient(
        '{"account_id": "999", "account_name": "Office Supplies", '
        '"confidence": 0.6, "reasoning": "Pens and paper."}'
    )
    cat = Categorizer(accounts=_chart(), client=stub)
    s = cat.suggest(_txn())
    assert s.account_id == "1"
    assert s.account_name == "Office Supplies"


def test_suggest_rejects_completely_hallucinated_account():
    stub = _StubClient(
        '{"account_id": "999", "account_name": "Alien Expenses", '
        '"confidence": 0.9, "reasoning": "Beam-me-up fee."}'
    )
    cat = Categorizer(accounts=_chart(), client=stub)
    with pytest.raises(ValueError):
        cat.suggest(_txn())


def test_suggest_handles_markdown_fenced_json():
    stub = _StubClient(
        "```json\n"
        '{"account_id": "3", "account_name": "Print Materials", '
        '"confidence": 0.7, "reasoning": "Paper stock."}\n'
        "```"
    )
    cat = Categorizer(accounts=_chart(), client=stub)
    s = cat.suggest(_txn())
    assert s.account_id == "3"


def test_extract_json_handles_prose_prefix():
    data = _extract_json('Sure! Here is the answer: {"a": 1, "b": "x"} — let me know.')
    assert data == {"a": 1, "b": "x"}
