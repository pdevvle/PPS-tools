"""Claude-backed category suggester for QBO transactions.

Given a transaction (vendor, description, amount) and the business's
chart of accounts, Claude picks the best-fit expense/income account
and explains its reasoning. We return the *account id* so the web
dashboard can submit it verbatim back to QBO.

Uses prompt caching on the chart of accounts and the system prompt,
since those stay constant across a review session.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic

from pps_tools.quickbooks.models import Account, Transaction

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an expert bookkeeper helping a small business categorize
transactions in QuickBooks Online. For each transaction, pick the single best-fit
account from the provided Chart of Accounts.

Rules:
- Only pick accounts that actually appear in the chart. Never invent an account.
- Prefer the most specific account that applies.
- For expense transactions, prefer Expense / Cost of Goods Sold accounts.
- For income (deposit) transactions, prefer Income accounts.
- If the transaction could plausibly belong to several accounts, pick the most
  likely one and reflect that in a lower confidence score.
- If there is genuinely not enough information, set confidence low and note what
  additional info would disambiguate it.

Return JSON with this exact shape:
{
  "account_id": "<id from the chart>",
  "account_name": "<name from the chart>",
  "confidence": <float between 0 and 1>,
  "reasoning": "<one or two sentences>"
}
"""


@dataclass
class Suggestion:
    account_id: str
    account_name: str
    confidence: float
    reasoning: str
    model: str

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "model": self.model,
        }


class Categorizer:
    def __init__(
        self,
        accounts: list[Account],
        client: Optional[Anthropic] = None,
        model: str = DEFAULT_MODEL,
        business_context: Optional[str] = None,
    ):
        self.accounts = accounts
        self.client = client or Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.business_context = business_context or os.environ.get(
            "QBO_BUSINESS_CONTEXT",
            "A small print services business (commercial printing, brochures, booklets, business cards).",
        )
        self._accounts_by_id = {a.id: a for a in accounts}

    # -- prompt construction ---------------------------------------------------

    def _accounts_block(self) -> str:
        # Compact, deterministic serialization — this block is cache-stable.
        rows = []
        for a in self.accounts:
            qualified = a.fully_qualified_name or a.name
            sub = f" / {a.account_sub_type}" if a.account_sub_type else ""
            rows.append(f"- id={a.id} | {a.account_type}{sub} | {qualified}")
        return "\n".join(rows)

    def _txn_block(self, txn: Transaction) -> str:
        lines = [
            f"Date: {txn.txn_date}",
            f"Type: {txn.txn_type}",
            f"Amount: {txn.amount:.2f} {txn.currency}",
        ]
        if txn.payee_name:
            lines.append(f"Payee/Vendor: {txn.payee_name}")
        if txn.payment_type:
            lines.append(f"Payment method: {txn.payment_type}")
        if txn.description:
            lines.append(f"Line description: {txn.description}")
        if txn.memo:
            lines.append(f"Memo: {txn.memo}")
        if txn.current_account_name:
            lines.append(f"Currently posted to: {txn.current_account_name}")
        return "\n".join(lines)

    # -- main entrypoint -------------------------------------------------------

    def suggest(self, txn: Transaction) -> Suggestion:
        system = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": f"Business context: {self.business_context}",
            },
            {
                "type": "text",
                "text": "Chart of Accounts:\n" + self._accounts_block(),
                "cache_control": {"type": "ephemeral"},
            },
        ]
        user = (
            "Categorize this transaction. Respond with JSON only.\n\n"
            + self._txn_block(txn)
        )

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        payload = _extract_json(text)

        account_id = str(payload.get("account_id", ""))
        account_name = payload.get("account_name", "")
        # Reconcile against our actual chart — never trust hallucinated ids.
        if account_id not in self._accounts_by_id:
            matched = _match_by_name(self.accounts, account_name)
            if matched is None:
                raise ValueError(
                    f"Claude returned an account not in the chart: id={account_id!r} name={account_name!r}"
                )
            account_id = matched.id
            account_name = matched.name
        else:
            account_name = self._accounts_by_id[account_id].name

        return Suggestion(
            account_id=account_id,
            account_name=account_name,
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=str(payload.get("reasoning", "")),
            model=self.model,
        )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model's response."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fences
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _match_by_name(accounts: list[Account], name: str) -> Optional[Account]:
    if not name:
        return None
    lname = name.strip().lower()
    for a in accounts:
        if a.name.lower() == lname or (a.fully_qualified_name or "").lower() == lname:
            return a
    return None
