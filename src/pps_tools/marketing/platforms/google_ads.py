"""Google Ads: reporting and campaign control through the Google Ads API (REST).

Docs: https://developers.google.com/google-ads/api
Developer tokens were retired in September 2026 — API access now comes
from the Google Cloud project that owns the OAuth client — so no
developer-token header is sent. Accounts reached through a manager (MCC)
are queried with the manager's id in the `login-customer-id` header.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Mapping, Optional

from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import ACTIVE, OTHER, PAUSED, REMOVED, AdAccount, Campaign, MetricRow
from pps_tools.marketing.oauth import with_query
from pps_tools.marketing.platforms.base import Platform

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/adwords"
DEFAULT_VERSION = "v26"

STATUS_MAP = {"ENABLED": ACTIVE, "PAUSED": PAUSED, "REMOVED": REMOVED}

CUSTOMER_QUERY = (
    "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
    "customer.time_zone, customer.manager, customer.test_account FROM customer"
)
CLIENTS_QUERY = (
    "SELECT customer_client.id, customer_client.descriptive_name, customer_client.currency_code, "
    "customer_client.time_zone, customer_client.manager, customer_client.level, customer_client.status "
    "FROM customer_client WHERE customer_client.level <= 1 AND customer_client.status = 'ENABLED'"
)
CAMPAIGNS_QUERY = (
    "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, "
    "campaign_budget.resource_name, campaign_budget.amount_micros, campaign_budget.period, "
    "campaign_budget.explicitly_shared, campaign_budget.reference_count "
    "FROM campaign WHERE campaign.status != 'REMOVED'"
)
METRICS_QUERY = (
    "SELECT segments.date, campaign.id, campaign.name, metrics.impressions, metrics.clicks, "
    "metrics.cost_micros, metrics.conversions, metrics.conversions_value "
    "FROM campaign WHERE segments.date BETWEEN '{start}' AND '{end}'"
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def format_customer_id(cid: str) -> str:
    d = _digits(cid)
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else d


class GoogleAdsPlatform(Platform):
    key = "google_ads"
    name = "Google Ads"
    short_name = "Google Ads"
    networks = ("google",)
    supports_ads = True
    supports_publish = False
    env_vars = ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET")
    docs_url = "https://developers.google.com/google-ads/api/docs/start"
    setup_steps = (
        "In Google Cloud Console, enable the Google Ads API for a project.",
        "On the project's Google Ads API page, apply for Explorer or Basic access (new projects can only reach test accounts).",
        "Create an OAuth client ID of type 'Web application' and add the redirect URI shown below.",
        "Copy the client ID and secret into GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET.",
        "Optional: set GOOGLE_ADS_LOGIN_CUSTOMER_ID to your manager (MCC) account id.",
    )

    @property
    def base(self) -> str:
        return f"https://googleads.googleapis.com/{self.env('GOOGLE_ADS_API_VERSION', DEFAULT_VERSION)}"

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        state = self.store.create_oauth_state(self.key)
        return with_query(
            AUTH_URL,
            {
                "client_id": self.env("GOOGLE_ADS_CLIENT_ID"),
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                # Both are needed to get a refresh token on every consent.
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            },
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "Google didn't send an authorization code.")
        data = self.http.json(
            "POST",
            TOKEN_URL,
            data={
                "code": code,
                "client_id": self.env("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": self.env("GOOGLE_ADS_CLIENT_SECRET"),
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if not data.get("refresh_token"):
            raise PlatformAPIError(
                self.name, "Google didn't return a refresh token. Remove the app's access in your Google Account and try again."
            )
        self.store.save_connection(self.key, self.token_bundle(data))

    def refresh_tokens(self, creds: dict) -> dict:
        data = self.http.json(
            "POST",
            TOKEN_URL,
            data={
                "client_id": self.env("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": self.env("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        return self.token_bundle(data, previous=creds)

    # -- requests ---------------------------------------------------------------

    def _headers(self, login_customer_id: Optional[str] = None) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "application/json"}
        if login_customer_id:
            headers["login-customer-id"] = _digits(login_customer_id)
        return headers

    def _login_for(self, account_id: str) -> Optional[str]:
        for acct in self.store.list_accounts(self.key):
            if acct.account_id == account_id:
                return acct.extra.get("login_customer_id")
        return _digits(self.env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")) or None

    def search(self, customer_id: str, query: str, login_customer_id: Optional[str] = None) -> list[dict]:
        """Run a GAQL query, following nextPageToken (pages are a fixed 10,000 rows)."""
        rows: list[dict] = []
        body: dict = {"query": query}
        for _ in range(100):
            data = self.http.json(
                "POST",
                f"{self.base}/customers/{_digits(customer_id)}/googleAds:search",
                headers=self._headers(login_customer_id),
                json=body,
                retry=True,
            )
            rows.extend(data.get("results", []))
            token = data.get("nextPageToken")
            if not token:
                break
            body = {"query": query, "pageToken": token}
        return rows

    # -- ads --------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        data = self.http.json("GET", f"{self.base}/customers:listAccessibleCustomers", headers=self._headers())
        accounts: dict[str, AdAccount] = {}
        for resource in data.get("resourceNames", []):
            cid = resource.split("/")[-1]
            try:
                info = self.search(cid, CUSTOMER_QUERY)
            except PlatformAPIError:
                continue  # e.g. a cancelled account the user can still "see"
            if not info:
                continue
            c = info[0].get("customer", {})
            if c.get("manager"):
                for row in self.search(cid, CLIENTS_QUERY, login_customer_id=cid):
                    cc = row.get("customerClient", {})
                    if cc.get("manager") or not cc.get("id"):
                        continue
                    accounts.setdefault(
                        str(cc["id"]),
                        AdAccount(
                            platform=self.key,
                            account_id=str(cc["id"]),
                            name=cc.get("descriptiveName") or format_customer_id(cc["id"]),
                            currency=cc.get("currencyCode") or "USD",
                            timezone=cc.get("timeZone"),
                            extra={"login_customer_id": cid, "manager_name": c.get("descriptiveName")},
                        ),
                    )
                continue
            test = bool(c.get("testAccount"))
            accounts[str(c.get("id", cid))] = AdAccount(
                platform=self.key,
                account_id=str(c.get("id", cid)),
                name=(c.get("descriptiveName") or format_customer_id(cid)) + (" (test account)" if test else ""),
                currency=c.get("currencyCode") or "USD",
                timezone=c.get("timeZone"),
                enabled=not test,
                extra={"test_account": test},
            )
        return list(accounts.values())

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        login = account.extra.get("login_customer_id") or self._login_for(account.account_id)
        campaigns = []
        for row in self.search(account.account_id, CAMPAIGNS_QUERY, login):
            c = row.get("campaign", {})
            b = row.get("campaignBudget", {})
            amount = int(b["amountMicros"]) / 1_000_000 if b.get("amountMicros") else None
            shared = bool(b.get("explicitlyShared")) or int(b.get("referenceCount") or 1) > 1
            daily = b.get("period", "DAILY") == "DAILY"
            raw = c.get("status", "")
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(c.get("id")),
                    name=c.get("name") or f"Campaign {c.get('id')}",
                    status=STATUS_MAP.get(raw, OTHER),
                    raw_status=raw,
                    objective=c.get("advertisingChannelType"),
                    daily_budget=amount if daily else None,
                    lifetime_budget=amount if not daily else None,
                    currency=account.currency,
                    budget_editable=bool(amount) and daily and not shared,
                    extra={"budget_resource": b.get("resourceName"), "shared_budget": shared},
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        login = account.extra.get("login_customer_id") or self._login_for(account.account_id)
        query = METRICS_QUERY.format(start=start.isoformat(), end=end.isoformat())
        rows = []
        for row in self.search(account.account_id, query, login):
            c, m = row.get("campaign", {}), row.get("metrics", {})
            rows.append(
                MetricRow(
                    platform=self.key,
                    network="google",
                    account_id=account.account_id,
                    campaign_id=str(c.get("id")),
                    campaign_name=c.get("name") or f"Campaign {c.get('id')}",
                    date=row.get("segments", {}).get("date", ""),
                    impressions=int(m.get("impressions", 0) or 0),
                    clicks=int(m.get("clicks", 0) or 0),
                    spend=int(m.get("costMicros", 0) or 0) / 1_000_000,
                    conversions=float(m.get("conversions", 0) or 0),
                    conversion_value=float(m.get("conversionsValue", 0) or 0),
                    currency=account.currency,
                )
            )
        return rows

    def set_status(self, campaign: Campaign, status: str) -> None:
        cid = _digits(campaign.account_id)
        self.http.json(
            "POST",
            f"{self.base}/customers/{cid}/campaigns:mutate",
            headers=self._headers(self._login_for(campaign.account_id)),
            json={
                "operations": [
                    {
                        "updateMask": "status",
                        "update": {
                            "resourceName": f"customers/{cid}/campaigns/{campaign.campaign_id}",
                            "status": "PAUSED" if status == PAUSED else "ENABLED",
                        },
                    }
                ]
            },
        )

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        resource = campaign.extra.get("budget_resource")
        if not resource:
            raise PlatformAPIError(self.name, "This campaign's budget couldn't be found.")
        if campaign.extra.get("shared_budget"):
            raise PlatformAPIError(self.name, "This campaign uses a shared budget; change it in Google Ads.")
        # Budgets must be a multiple of the currency's smallest unit (1 cent = 10,000 micros).
        micros = int(round(amount * 100)) * 10_000
        self.http.json(
            "POST",
            f"{self.base}/customers/{_digits(campaign.account_id)}/campaignBudgets:mutate",
            headers=self._headers(self._login_for(campaign.account_id)),
            json={"operations": [{"updateMask": "amountMicros", "update": {"resourceName": resource, "amountMicros": str(micros)}}]},
        )

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        if isinstance(data, list):  # searchStream-style arrays
            data = next((d for d in data if isinstance(d, dict) and d.get("error")), {})
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, str):  # OAuth endpoint errors
            return data.get("error_description") or err
        if not isinstance(err, dict):
            return str(data)[:300]
        messages = []
        for detail in err.get("details") or []:
            for e in detail.get("errors") or []:
                code = ", ".join(f"{k}: {v}" for k, v in (e.get("errorCode") or {}).items())
                messages.append(f"{e.get('message', '')} [{code}]" if code else e.get("message", ""))
        return "; ".join(m for m in messages if m) or err.get("message") or str(err)[:300]
