"""QuickBooks Online OAuth2 + REST API client.

Handles the OAuth2 authorization code flow, token persistence,
automatic refresh, and the minimal REST surface we need:

    - list Chart of Accounts
    - query Purchase transactions
    - update a Purchase to change its expense account

Intuit API reference: https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlencode

import requests

from pps_tools.quickbooks.models import Account, Transaction

logger = logging.getLogger(__name__)

AUTH_BASE = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

# Sandbox vs production base URLs are the same path, different host.
PROD_API = "https://quickbooks.api.intuit.com"
SANDBOX_API = "https://sandbox-quickbooks.api.intuit.com"

DEFAULT_SCOPE = "com.intuit.quickbooks.accounting"


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    realm_id: str
    expires_at: float  # epoch seconds
    refresh_expires_at: float

    @classmethod
    def from_response(cls, data: dict, realm_id: str) -> "Tokens":
        now = time.time()
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            realm_id=realm_id,
            expires_at=now + int(data.get("expires_in", 3600)) - 60,
            refresh_expires_at=now + int(data.get("x_refresh_token_expires_in", 8726400)) - 60,
        )


class QBOAuth:
    """OAuth2 helper — app-level credentials + token persistence."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        environment: str = "production",
        token_path: Optional[Path] = None,
    ):
        self.client_id = client_id or os.environ.get("QBO_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("QBO_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.environ.get(
            "QBO_REDIRECT_URI", "http://localhost:5000/oauth/callback"
        )
        self.environment = environment or os.environ.get("QBO_ENVIRONMENT", "production")
        self.api_base = SANDBOX_API if self.environment == "sandbox" else PROD_API
        self.token_path = Path(token_path or os.environ.get("QBO_TOKEN_PATH", ".qbo_tokens.json"))

    # -- PKCE-less authorization code flow (Intuit supports plain state) -------

    def authorize_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """Return (url, state) — redirect the user to `url`."""
        state = state or secrets.token_urlsafe(24)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": DEFAULT_SCOPE,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{AUTH_BASE}?{urlencode(params)}", state

    def _basic_auth_header(self) -> dict:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    def exchange_code(self, code: str, realm_id: str) -> Tokens:
        resp = requests.post(
            TOKEN_URL,
            headers={**self._basic_auth_header(), "Accept": "application/json"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        resp.raise_for_status()
        tokens = Tokens.from_response(resp.json(), realm_id)
        self.save(tokens)
        return tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        resp = requests.post(
            TOKEN_URL,
            headers={**self._basic_auth_header(), "Accept": "application/json"},
            data={"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        refreshed = Tokens.from_response(resp.json(), tokens.realm_id)
        self.save(refreshed)
        return refreshed

    # -- Persistence (local file; gitignored). Good enough for a single-user tool.

    def save(self, tokens: Tokens) -> None:
        self.token_path.write_text(json.dumps(asdict(tokens), indent=2))
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

    def load(self) -> Optional[Tokens]:
        if not self.token_path.exists():
            return None
        data = json.loads(self.token_path.read_text())
        return Tokens(**data)

    def clear(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()


class QBOClient:
    """Minimal REST client for the QBO Accounting API."""

    def __init__(self, auth: QBOAuth, tokens: Optional[Tokens] = None, minor_version: int = 70):
        self.auth = auth
        self.tokens = tokens or auth.load()
        if self.tokens is None:
            raise RuntimeError("Not connected to QuickBooks. Run the OAuth flow first.")
        self.minor_version = minor_version

    # -- low-level request with auto-refresh ------------------------------------

    def _ensure_fresh(self) -> None:
        if time.time() >= self.tokens.expires_at:
            logger.info("QBO access token expired; refreshing")
            self.tokens = self.auth.refresh(self.tokens)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        self._ensure_fresh()
        url = f"{self.auth.api_base}/v3/company/{self.tokens.realm_id}{path}"
        params = kwargs.pop("params", {}) or {}
        params.setdefault("minorversion", self.minor_version)
        headers = {
            "Authorization": f"Bearer {self.tokens.access_token}",
            "Accept": "application/json",
            **kwargs.pop("headers", {}),
        }
        resp = requests.request(method, url, headers=headers, params=params, timeout=60, **kwargs)
        if resp.status_code == 401:
            # One retry on refresh race
            self.tokens = self.auth.refresh(self.tokens)
            headers["Authorization"] = f"Bearer {self.tokens.access_token}"
            resp = requests.request(method, url, headers=headers, params=params, timeout=60, **kwargs)
        if not resp.ok:
            raise QBOAPIError(resp.status_code, resp.text)
        return resp.json() if resp.text else {}

    def query(self, sql: str) -> dict:
        return self._request("GET", "/query", params={"query": sql})

    # -- high-level helpers -----------------------------------------------------

    def list_accounts(self, only_active: bool = True) -> list[Account]:
        sql = "SELECT * FROM Account"
        if only_active:
            sql += " WHERE Active = true"
        sql += " MAXRESULTS 1000"
        data = self.query(sql)
        rows = (data.get("QueryResponse", {}) or {}).get("Account", [])
        return [Account.from_qbo(r) for r in rows]

    def list_purchases(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 200,
    ) -> list[Transaction]:
        where = []
        if start_date:
            where.append(f"TxnDate >= '{start_date}'")
        if end_date:
            where.append(f"TxnDate <= '{end_date}'")
        sql = "SELECT * FROM Purchase"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDERBY TxnDate DESC MAXRESULTS {min(limit, 1000)}"
        data = self.query(sql)
        rows = (data.get("QueryResponse", {}) or {}).get("Purchase", [])
        return [Transaction.from_purchase(r) for r in rows]

    def list_uncategorized_purchases(
        self,
        uncategorized_account_names: Iterable[str] = (
            "Uncategorized Expense",
            "Uncategorized Asset",
            "Ask My Accountant",
        ),
        **kwargs,
    ) -> list[Transaction]:
        """Fetch purchases whose line is posted to an 'uncategorized' account."""
        names = {n.lower() for n in uncategorized_account_names}
        return [
            t for t in self.list_purchases(**kwargs)
            if (t.current_account_name or "").lower() in names
        ]

    def update_purchase_category(self, txn: Transaction, new_account_id: str) -> Transaction:
        """Sparse update: change the first line's AccountRef to `new_account_id`."""
        if not txn.line_id:
            raise ValueError(f"Transaction {txn.id} has no line to update")
        body = {
            "Id": txn.id,
            "SyncToken": txn.sync_token,
            "sparse": True,
            "Line": [
                {
                    "Id": txn.line_id,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    # QBO requires Amount on sparse line updates
                    "Amount": txn.amount,
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": new_account_id},
                    },
                }
            ],
        }
        data = self._request("POST", "/purchase", json=body)
        updated = data.get("Purchase", {})
        return Transaction.from_purchase(updated) if updated else txn


class QBOAPIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"QBO API {status}: {body[:500]}")
        self.status = status
        self.body = body
