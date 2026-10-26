"""Pinterest: ads reporting and control, plus organic Pins (API v5).

Docs: https://developers.pinterest.com/docs/api/v5/
Money is in micro-units of the ad account's currency. Analytics only go
back 90 days, so longer ranges are clipped to what Pinterest can return.
Note: apps on Trial access can only create Pins visible to their creator;
publishing for real needs Standard access.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional

from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import (
    ACTIVE,
    OTHER,
    PAUSED,
    REMOVED,
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
)
from pps_tools.marketing.oauth import basic_auth, with_query
from pps_tools.marketing.platforms.base import Platform

API = "https://api.pinterest.com/v5"
AUTH_URL = "https://www.pinterest.com/oauth/"
SCOPES = "ads:read,ads:write,boards:read,boards:write,pins:read,pins:write,user_accounts:read"
COLUMNS = "SPEND_IN_MICRO_DOLLAR,PAID_IMPRESSION,CLICKTHROUGH_1,TOTAL_CONVERSIONS,TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR"
MAX_HISTORY_DAYS = 90
MAX_CAMPAIGNS_PER_REPORT = 250

STATUS_MAP = {"ACTIVE": ACTIVE, "PAUSED": PAUSED, "ARCHIVED": REMOVED, "DELETED_DRAFT": REMOVED}


class PinterestPlatform(Platform):
    key = "pinterest"
    name = "Pinterest"
    short_name = "Pinterest"
    networks = ("pinterest",)
    supports_ads = True
    supports_publish = True
    env_vars = ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET")
    docs_url = "https://developers.pinterest.com/docs/getting-started/set-up-app/"
    setup_steps = (
        "Create an app at https://developers.pinterest.com/apps (Trial access is granted first; request Standard access to publish publicly).",
        "Add the redirect URI shown below to the app.",
        "Copy the App ID and App secret key into PINTEREST_APP_ID / PINTEREST_APP_SECRET.",
    )

    def _auth(self) -> dict:
        return basic_auth(self.env("PINTEREST_APP_ID"), self.env("PINTEREST_APP_SECRET"))

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token()}"}

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        state = self.store.create_oauth_state(self.key)
        return with_query(
            AUTH_URL,
            {
                "client_id": self.env("PINTEREST_APP_ID"),
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
            },
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "Pinterest didn't send an authorization code.")
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri}
        if self.env("PINTEREST_CONTINUOUS_REFRESH").lower() in ("1", "true", "yes"):
            form["continuous_refresh"] = "true"  # only for apps created before 2025-09-25
        data = self.http.json("POST", f"{API}/oauth/token", headers=self._auth(), data=form)
        creds = self.token_bundle(data)
        user = self.http.json("GET", f"{API}/user_account", headers={"Authorization": f"Bearer {creds['access_token']}"})
        self.store.save_connection(self.key, creds, profile={"username": user.get("username")})

    def refresh_tokens(self, creds: dict) -> dict:
        # Each refresh returns a new refresh token too; token_bundle keeps the newest.
        data = self.http.json(
            "POST",
            f"{API}/oauth/token",
            headers=self._auth(),
            data={"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]},
        )
        return self.token_bundle(data, previous=creds)

    # -- requests ---------------------------------------------------------------

    def _paged(self, path: str, params: Optional[dict] = None) -> list[dict]:
        items: list[dict] = []
        query = dict(params or {})
        for _ in range(100):
            data = self.http.json("GET", f"{API}/{path}", headers=self._headers(), params=query)
            items.extend(data.get("items", []))
            bookmark = data.get("bookmark")
            if not bookmark:
                break
            query["bookmark"] = bookmark
        return items

    # -- ads --------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        return [
            AdAccount(
                platform=self.key,
                account_id=str(a["id"]),
                name=a.get("name") or str(a["id"]),
                currency=a.get("currency") or "USD",
                timezone=a.get("time_zone"),
                extra={"country": a.get("country")},
            )
            for a in self._paged("ad_accounts", {"page_size": 250})
        ]

    def _campaigns(self, account: AdAccount, statuses: list[str]) -> list[dict]:
        return self._paged(
            f"ad_accounts/{account.account_id}/campaigns", {"page_size": 250, "entity_statuses": statuses}
        )

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        campaigns = []
        for c in self._campaigns(account, ["ACTIVE", "PAUSED"]):
            daily = c.get("daily_spend_cap")
            lifetime = c.get("lifetime_spend_cap")
            raw = c.get("status", "")
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(c["id"]),
                    name=c.get("name") or str(c["id"]),
                    status=STATUS_MAP.get(raw, OTHER),
                    raw_status=c.get("summary_status") or raw,
                    objective=c.get("objective_type"),
                    daily_budget=daily / 1_000_000 if daily else None,
                    lifetime_budget=lifetime / 1_000_000 if lifetime else None,
                    currency=account.currency,
                    budget_editable=bool(daily),
                    extra={"cbo": c.get("is_campaign_budget_optimization")},
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        earliest = date.today() - timedelta(days=MAX_HISTORY_DAYS - 1)
        start = max(start, earliest)
        if start > end:
            return []
        names = {str(c["id"]): c.get("name") or str(c["id"]) for c in self._campaigns(account, ["ACTIVE", "PAUSED", "ARCHIVED"])}
        ids = list(names)
        rows = []
        for i in range(0, len(ids), MAX_CAMPAIGNS_PER_REPORT):
            data = self.http.json(
                "GET",
                f"{API}/ad_accounts/{account.account_id}/campaigns/analytics",
                headers=self._headers(),
                params={
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "campaign_ids": ids[i : i + MAX_CAMPAIGNS_PER_REPORT],
                    "columns": COLUMNS,
                    "granularity": "DAY",
                },
            )
            for r in data if isinstance(data, list) else []:
                cid = str(r.get("CAMPAIGN_ID"))
                rows.append(
                    MetricRow(
                        platform=self.key,
                        network="pinterest",
                        account_id=account.account_id,
                        campaign_id=cid,
                        campaign_name=names.get(cid, cid),
                        date=str(r.get("DATE", ""))[:10],
                        impressions=int(float(r.get("PAID_IMPRESSION") or 0)),
                        clicks=int(float(r.get("CLICKTHROUGH_1") or 0)),
                        spend=float(r.get("SPEND_IN_MICRO_DOLLAR") or 0) / 1_000_000,
                        conversions=float(r.get("TOTAL_CONVERSIONS") or 0),
                        conversion_value=float(r.get("TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR") or 0) / 1_000_000,
                        currency=account.currency,
                    )
                )
        return rows

    def _update(self, campaign: Campaign, changes: dict) -> None:
        data = self.http.json(
            "PATCH",
            f"{API}/ad_accounts/{campaign.account_id}/campaigns",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=[{"id": campaign.campaign_id, **changes}],
        )
        for item in data.get("items", []):
            for exc in item.get("exceptions") or []:
                raise PlatformAPIError(self.name, exc.get("message") or "Pinterest rejected the change.")

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._update(campaign, {"status": "PAUSED" if status == PAUSED else "ACTIVE"})

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        self._update(campaign, {"daily_spend_cap": int(round(amount * 1_000_000))})

    # -- Pins ---------------------------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        return [
            (
                PublishTarget(
                    platform=self.key,
                    network="pinterest",
                    target_id=str(b["id"]),
                    name=b.get("name") or str(b["id"]),
                    kind="board",
                    extra={"privacy": b.get("privacy")},
                ),
                None,
            )
            for b in self._paged("boards", {"page_size": 250})
        ]

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        if not content.image_url:
            raise PlatformAPIError(self.name, "Pins need an image.")
        body: dict = {
            "board_id": target.target_id,
            "description": content.text[:800],
            "media_source": {"source_type": "image_url", "url": content.image_url},
        }
        if content.title:
            body["title"] = content.title[:100]
        if content.link:
            body["link"] = content.link
        pin = self.http.json(
            "POST", f"{API}/pins", headers={**self._headers(), "Content-Type": "application/json"}, json=body
        )
        pin_id = pin.get("id")
        return PublishResult(
            ok=True,
            network="pinterest",
            target_id=target.target_id,
            remote_id=pin_id,
            url=f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None,
        )

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error_description") or data.get("error") or data)[:300]
        return str(data)[:300]
