"""TikTok for Business: campaign reporting and control via the Marketing API v1.3.

Docs: https://business-api.tiktok.com/portal/docs
Responses always come back as HTTP 200 with a `code` field; anything but 0
is an error. Access tokens are long-lived and have no refresh flow.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Mapping, Optional

from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import ACTIVE, OTHER, PAUSED, REMOVED, AdAccount, Campaign, MetricRow
from pps_tools.marketing.oauth import with_query
from pps_tools.marketing.platforms.base import Platform

API = "https://business-api.tiktok.com/open_api/v1.3"
DEFAULT_AUTH_URL = "https://business-api.tiktok.com/portal/auth"
REPORT_METRICS = ["campaign_name", "spend", "impressions", "clicks", "conversion", "total_complete_payment_rate"]
MAX_REPORT_DAYS = 30  # daily breakdowns are limited to 30 days per request

TOKEN_ERRORS = {40102, 40104, 40105, 40106}


class TikTokPlatform(Platform):
    key = "tiktok"
    name = "TikTok"
    short_name = "TikTok"
    networks = ("tiktok",)
    supports_ads = True
    supports_publish = False
    env_vars = ("TIKTOK_APP_ID", "TIKTOK_APP_SECRET")
    docs_url = "https://business-api.tiktok.com/portal/docs"
    setup_steps = (
        "Create a developer app at https://business-api.tiktok.com/portal (My Apps).",
        "Grant it the Ad Account Management, Ads Management and Reporting scopes.",
        "Set the app's Advertiser redirect URL to the address shown below.",
        "Copy the App ID and Secret into TIKTOK_APP_ID / TIKTOK_APP_SECRET.",
    )

    def _call(self, method: str, path: str, params: Optional[dict] = None, body: Optional[dict] = None,
              auth: bool = True) -> dict:
        headers = {"Access-Token": self.access_token()} if auth else {}
        if params:
            # GET parameters that are lists or objects are sent as JSON strings.
            params = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
        payload = self.http.json(method, f"{API}/{path}", params=params, json=body, headers=headers)
        code = payload.get("code")
        if code not in (0, "0"):
            message = payload.get("message") or "Unknown error"
            if code in TOKEN_ERRORS:
                message = f"{message} — reconnect TikTok"
            raise PlatformAPIError(self.name, f"{message} (code {code})")
        return payload.get("data") or {}

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        state = self.store.create_oauth_state(self.key)
        return with_query(
            self.env("TIKTOK_AUTH_URL", DEFAULT_AUTH_URL),
            {"app_id": self.env("TIKTOK_APP_ID"), "state": state, "redirect_uri": self.redirect_uri},
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        self.check_state(args)
        auth_code = args.get("auth_code") or args.get("code")
        if not auth_code:
            raise PlatformAPIError(self.name, "TikTok didn't send an authorization code.")
        data = self._call(
            "POST",
            "oauth2/access_token/",
            body={"app_id": self.env("TIKTOK_APP_ID"), "secret": self.env("TIKTOK_APP_SECRET"), "auth_code": auth_code},
            auth=False,
        )
        creds = {
            "access_token": data["access_token"],
            "advertiser_ids": [str(a) for a in data.get("advertiser_ids") or []],
            "scope": data.get("scope"),
        }
        self.store.save_connection(self.key, creds)

    # -- ads --------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        ids = list(self.credentials().get("advertiser_ids") or [])
        if not ids:
            listed = self._call(
                "GET", "oauth2/advertiser/get/",
                params={"app_id": self.env("TIKTOK_APP_ID"), "secret": self.env("TIKTOK_APP_SECRET")},
            )
            ids = [str(a["advertiser_id"]) for a in listed.get("list", [])]
        accounts = []
        for i in range(0, len(ids), 50):
            info = self._call(
                "GET",
                "advertiser/info/",
                params={
                    "advertiser_ids": ids[i : i + 50],
                    "fields": ["advertiser_id", "name", "currency", "timezone", "display_timezone", "status"],
                },
            )
            for a in info.get("list", []):
                accounts.append(
                    AdAccount(
                        platform=self.key,
                        account_id=str(a["advertiser_id"]),
                        name=a.get("name") or str(a["advertiser_id"]),
                        currency=a.get("currency") or "USD",
                        timezone=a.get("display_timezone") or a.get("timezone"),
                        enabled=a.get("status", "STATUS_ENABLE") == "STATUS_ENABLE",
                        extra={"status": a.get("status")},
                    )
                )
        return accounts

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        campaigns = []
        page = 1
        while True:
            data = self._call(
                "GET", "campaign/get/", params={"advertiser_id": account.account_id, "page": page, "page_size": 1000}
            )
            for c in data.get("list", []):
                secondary = str(c.get("secondary_status") or "")
                op = c.get("operation_status")
                if "DELETE" in secondary:
                    status = REMOVED
                elif op == "ENABLE":
                    status = ACTIVE
                elif op == "DISABLE":
                    status = PAUSED
                else:
                    status = OTHER
                mode = c.get("budget_mode")
                budget = float(c["budget"]) if c.get("budget") not in (None, "") else None
                campaigns.append(
                    Campaign(
                        platform=self.key,
                        account_id=account.account_id,
                        campaign_id=str(c["campaign_id"]),
                        name=c.get("campaign_name") or str(c["campaign_id"]),
                        status=status,
                        raw_status=secondary or (op or ""),
                        objective=c.get("objective_type"),
                        daily_budget=budget if mode == "BUDGET_MODE_DAY" else None,
                        lifetime_budget=budget if mode == "BUDGET_MODE_TOTAL" else None,
                        currency=account.currency,
                        budget_editable=mode == "BUDGET_MODE_DAY",
                        extra={"budget_mode": mode},
                    )
                )
            info = data.get("page_info") or {}
            if page >= int(info.get("total_page") or 1):
                break
            page += 1
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        rows: list[MetricRow] = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=MAX_REPORT_DAYS - 1), end)
            rows.extend(self._report(account, chunk_start, chunk_end))
            chunk_start = chunk_end + timedelta(days=1)
        return rows

    def _report(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        rows = []
        page = 1
        while True:
            data = self._call(
                "GET",
                "report/integrated/get/",
                params={
                    "advertiser_id": account.account_id,
                    "report_type": "BASIC",
                    "data_level": "AUCTION_CAMPAIGN",
                    "dimensions": ["campaign_id", "stat_time_day"],
                    "metrics": REPORT_METRICS,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "page": page,
                    "page_size": 1000,
                },
            )
            for item in data.get("list", []):
                dims, m = item.get("dimensions") or {}, item.get("metrics") or {}
                rows.append(
                    MetricRow(
                        platform=self.key,
                        network="tiktok",
                        account_id=account.account_id,
                        campaign_id=str(dims.get("campaign_id")),
                        campaign_name=m.get("campaign_name") or str(dims.get("campaign_id")),
                        date=str(dims.get("stat_time_day", ""))[:10],
                        impressions=int(float(m.get("impressions") or 0)),
                        clicks=int(float(m.get("clicks") or 0)),
                        spend=float(m.get("spend") or 0),
                        conversions=float(m.get("conversion") or 0),
                        conversion_value=float(m.get("total_complete_payment_rate") or 0),
                        currency=account.currency,
                    )
                )
            info = data.get("page_info") or {}
            if page >= int(info.get("total_page") or 1):
                break
            page += 1
        return rows

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._call(
            "POST",
            "campaign/status/update/",
            body={
                "advertiser_id": campaign.account_id,
                "campaign_ids": [campaign.campaign_id],
                "operation_status": "DISABLE" if status == PAUSED else "ENABLE",
            },
        )

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        self._call(
            "POST",
            "campaign/update/",
            body={"advertiser_id": campaign.account_id, "campaign_id": campaign.campaign_id, "budget": round(amount, 2)},
        )
