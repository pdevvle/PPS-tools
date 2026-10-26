"""Meta: Facebook + Instagram ads (Marketing API) and organic posts (Pages + Instagram).

Docs: https://developers.facebook.com/docs/marketing-api
One Facebook Login covers both networks. Ads spend is split into
Facebook / Instagram / other placements with the publisher_platform
breakdown, so the dashboard can show Instagram as its own channel even
though it shares Meta's ad accounts.
"""

from __future__ import annotations

import json
from datetime import date
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
from pps_tools.marketing.oauth import with_query
from pps_tools.marketing.platforms.base import Platform

DEFAULT_VERSION = "v26.0"
SCOPES = (
    "ads_read",
    "ads_management",
    "business_management",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
)
# Currencies Meta counts in whole units; every other currency is in cents.
WHOLE_UNIT_CURRENCIES = {"CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"}

STATUS_MAP = {"ACTIVE": ACTIVE, "PAUSED": PAUSED, "DELETED": REMOVED, "ARCHIVED": REMOVED}
PLACEMENTS = {"facebook": "facebook", "instagram": "instagram"}

# Purchases are reported under several overlapping action types; use the first
# one present and never add them together. Same for leads.
PURCHASE_ACTIONS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")

INSIGHT_FIELDS = "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values,account_currency"


def currency_factor(currency: str) -> int:
    return 1 if (currency or "").upper() in WHOLE_UNIT_CURRENCIES else 100


def _first_action(items: Optional[list], types: tuple[str, ...]) -> tuple[Optional[str], float]:
    values = {a.get("action_type"): a.get("value") for a in items or []}
    for t in types:
        if values.get(t) not in (None, ""):
            return t, float(values[t])
    return None, 0.0


def _action_value(items: Optional[list], action_type: Optional[str]) -> float:
    if not action_type:
        return 0.0
    for a in items or []:
        if a.get("action_type") == action_type:
            return float(a.get("value") or 0)
    return 0.0


def conversions_from(row: dict) -> tuple[float, float]:
    """(conversions, conversion value) from an insights row's actions."""
    purchase_type, purchases = _first_action(row.get("actions"), PURCHASE_ACTIONS)
    lead_type, leads = _first_action(row.get("actions"), LEAD_ACTIONS)
    value = _action_value(row.get("action_values"), purchase_type) + _action_value(row.get("action_values"), lead_type)
    return purchases + leads, value


class MetaPlatform(Platform):
    key = "meta"
    name = "Meta (Facebook & Instagram)"
    short_name = "Meta"
    networks = ("facebook", "instagram")
    supports_ads = True
    supports_publish = True
    env_vars = ("META_APP_ID", "META_APP_SECRET")
    docs_url = "https://developers.facebook.com/docs/marketing-api/get-started"
    setup_steps = (
        "Create a Business-type app at https://developers.facebook.com/apps and add Facebook Login and the Marketing API.",
        "In Facebook Login settings, add the redirect URI shown below (Meta requires https outside localhost).",
        "Request ads_read, ads_management, pages_manage_posts and instagram_content_publish (App Review is needed for live use).",
        "Copy the App ID and App Secret into META_APP_ID / META_APP_SECRET.",
        "Optional: for Facebook Login for Business, create a configuration and set META_LOGIN_CONFIG_ID.",
    )

    @property
    def version(self) -> str:
        return self.env("META_GRAPH_VERSION", DEFAULT_VERSION)

    @property
    def graph(self) -> str:
        return f"https://graph.facebook.com/{self.version}"

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        state = self.store.create_oauth_state(self.key)
        params = {
            "client_id": self.env("META_APP_ID"),
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
        }
        config_id = self.env("META_LOGIN_CONFIG_ID")
        if config_id:
            params["config_id"] = config_id
        else:
            params["scope"] = ",".join(SCOPES)
        return with_query(f"https://www.facebook.com/{self.version}/dialog/oauth", params)

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "Facebook didn't send an authorization code.")
        app_id, secret = self.env("META_APP_ID"), self.env("META_APP_SECRET")
        short = self.http.json(
            "GET",
            f"{self.graph}/oauth/access_token",
            params={"client_id": app_id, "redirect_uri": self.redirect_uri, "client_secret": secret, "code": code},
        )
        # Swap the ~1 hour token for a ~60 day one; Page tokens derived from it don't expire.
        long_lived = self.http.json(
            "GET",
            f"{self.graph}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": secret,
                "fb_exchange_token": short["access_token"],
            },
        )
        creds = self.token_bundle(long_lived if long_lived.get("access_token") else short)
        me = self.http.json("GET", f"{self.graph}/me", params={"fields": "id,name", "access_token": creds["access_token"]})
        self.store.save_connection(self.key, creds, profile={"id": me.get("id"), "name": me.get("name")})

    # -- requests ---------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None, token: Optional[str] = None) -> dict:
        query = dict(params or {})
        query["access_token"] = token or self.access_token()
        return self.http.json("GET", f"{self.graph}/{path}", params=query)

    def _post(self, path: str, data: dict, token: Optional[str] = None) -> dict:
        form = dict(data)
        form["access_token"] = token or self.access_token()
        return self.http.json("POST", f"{self.graph}/{path}", data=form)

    def _paged(self, path: str, params: Optional[dict] = None, token: Optional[str] = None) -> list[dict]:
        """Follow paging.next until it runs out (a short page doesn't mean the end)."""
        data = self._get(path, params, token)
        items = list(data.get("data", []))
        for _ in range(200):
            nxt = (data.get("paging") or {}).get("next")
            if not nxt:
                break
            data = self.http.json("GET", nxt)
            items.extend(data.get("data", []))
        return items

    # -- ads --------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        accounts = []
        for a in self._paged(
            "me/adaccounts", {"fields": "id,account_id,name,currency,account_status,timezone_name", "limit": 200}
        ):
            accounts.append(
                AdAccount(
                    platform=self.key,
                    account_id=a["id"],
                    name=a.get("name") or a["id"],
                    currency=a.get("currency") or "USD",
                    timezone=a.get("timezone_name"),
                    enabled=int(a.get("account_status", 1)) == 1,
                    extra={"account_status": a.get("account_status")},
                )
            )
        return accounts

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        factor = currency_factor(account.currency)
        campaigns = []
        for c in self._paged(
            f"{account.account_id}/campaigns",
            {
                "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget",
                "effective_status": json.dumps(["ACTIVE", "PAUSED", "IN_PROCESS", "WITH_ISSUES"]),
                "limit": 200,
            },
        ):
            daily = int(c.get("daily_budget") or 0)
            lifetime = int(c.get("lifetime_budget") or 0)
            raw = c.get("effective_status") or c.get("status", "")
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(c["id"]),
                    name=c.get("name") or c["id"],
                    status=STATUS_MAP.get(c.get("status", ""), OTHER),
                    raw_status=raw,
                    objective=c.get("objective"),
                    daily_budget=daily / factor if daily else None,
                    lifetime_budget=lifetime / factor if lifetime else None,
                    currency=account.currency,
                    # Zero campaign budget means the budgets live on the ad sets.
                    budget_editable=daily > 0,
                    extra={"budget_level": "campaign" if (daily or lifetime) else "ad_set"},
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        rows = []
        for r in self._paged(
            f"{account.account_id}/insights",
            {
                "level": "campaign",
                "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
                "time_increment": 1,
                "fields": INSIGHT_FIELDS,
                "breakdowns": "publisher_platform",
                "use_unified_attribution_setting": "true",
                "limit": 500,
            },
        ):
            conversions, value = conversions_from(r)
            rows.append(
                MetricRow(
                    platform=self.key,
                    network=PLACEMENTS.get(str(r.get("publisher_platform", "")).lower(), "other"),
                    account_id=account.account_id,
                    campaign_id=str(r.get("campaign_id")),
                    campaign_name=r.get("campaign_name") or str(r.get("campaign_id")),
                    date=r.get("date_start", ""),
                    impressions=int(float(r.get("impressions") or 0)),
                    clicks=int(float(r.get("clicks") or 0)),
                    spend=float(r.get("spend") or 0),
                    conversions=conversions,
                    conversion_value=value,
                    currency=r.get("account_currency") or account.currency,
                )
            )
        return rows

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._post(campaign.campaign_id, {"status": "PAUSED" if status == PAUSED else "ACTIVE"})

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        minor = int(round(amount * currency_factor(campaign.currency)))
        self._post(campaign.campaign_id, {"daily_budget": str(minor)})

    # -- Page + Instagram publishing ------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        targets: list[tuple[PublishTarget, Optional[dict]]] = []
        pages = self._paged(
            "me/accounts", {"fields": "id,name,access_token,tasks,instagram_business_account{id,username}", "limit": 100}
        )
        for page in pages:
            secret = {"access_token": page.get("access_token")}
            tasks = page.get("tasks")
            if tasks is None or "CREATE_CONTENT" in tasks:
                targets.append((PublishTarget(self.key, "facebook", str(page["id"]), page.get("name", ""), "page"), secret))
            ig = page.get("instagram_business_account")
            if ig and ig.get("id"):
                handle = f"@{ig['username']}" if ig.get("username") else f"Instagram for {page.get('name', '')}"
                targets.append(
                    (
                        PublishTarget(
                            self.key, "instagram", str(ig["id"]), handle, "instagram_account",
                            extra={"page_id": str(page["id"])},
                        ),
                        secret,
                    )
                )
        return targets

    def _page_token(self, target: PublishTarget) -> str:
        secret = self.store.target_secret(self.key, target.network, target.target_id) or {}
        if not secret.get("access_token"):
            raise PlatformAPIError(self.name, "No Page access token stored; reconnect Meta.")
        return secret["access_token"]

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        token = self._page_token(target)
        if target.network == "instagram":
            return self._publish_instagram(target, content, token)
        if content.image_url and not content.link:
            data = self._post(f"{target.target_id}/photos", {"url": content.image_url, "caption": content.text}, token)
            post_id = data.get("post_id") or data.get("id")
        else:
            form = {"message": content.text}
            if content.link:
                form["link"] = content.link
            post_id = self._post(f"{target.target_id}/feed", form, token).get("id")
        url = None
        if post_id:
            try:
                url = self._get(str(post_id), {"fields": "permalink_url"}, token).get("permalink_url")
            except PlatformAPIError:
                url = f"https://www.facebook.com/{post_id}"
        return PublishResult(ok=True, network="facebook", target_id=target.target_id, remote_id=post_id, url=url)

    def _publish_instagram(self, target: PublishTarget, content: PostContent, token: str) -> PublishResult:
        if not content.image_url:
            raise PlatformAPIError(self.name, "Instagram posts need an image.")
        container = self._post(f"{target.target_id}/media", {"image_url": content.image_url, "caption": content.text}, token)
        creation_id = container.get("id")
        if not creation_id:
            raise PlatformAPIError(self.name, "Instagram didn't accept the image.")
        # Image containers are usually ready at once; give processing up to ~40s.
        for _ in range(20):
            status = self._get(str(creation_id), {"fields": "status_code,status"}, token)
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise PlatformAPIError(self.name, f"Instagram couldn't process the image: {status.get('status') or code}")
            self.http.sleep(2)
        published = self._post(f"{target.target_id}/media_publish", {"creation_id": creation_id}, token)
        media_id = published.get("id")
        url = None
        if media_id:
            try:
                url = self._get(str(media_id), {"fields": "permalink"}, token).get("permalink")
            except PlatformAPIError:
                pass
        return PublishResult(ok=True, network="instagram", target_id=target.target_id, remote_id=media_id, url=url)

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        err = data.get("error") if isinstance(data, dict) else None
        if not isinstance(err, dict):
            return str(data)[:300]
        message = err.get("error_user_msg") or err.get("message") or "Unknown error"
        if err.get("code") == 190:
            message += " — reconnect Meta"
        return message
