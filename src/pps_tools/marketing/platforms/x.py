"""X (Twitter): posts via API v2 and campaign reporting via the X Ads API.

Docs: https://docs.x.com/x-api and https://docs.x.com/x-ads-api
Two kinds of credentials, because X still requires OAuth 1.0a for the
Ads API while recommending OAuth 2.0 for everything else:

* OAuth 2.0 (X_CLIENT_ID / X_CLIENT_SECRET) — the "Connect" button; used to post.
* OAuth 1.0a user keys (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN,
  X_ACCESS_TOKEN_SECRET) — needed for ads reporting; can also post.

Posting through the API is pay-per-use: X bills each post, and posts that
contain a link cost much more than plain ones.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import (
    ACTIVE,
    OTHER,
    PAUSED,
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
)
from pps_tools.marketing.oauth import percent_encode, basic_auth, oauth1_header, pkce_pair, with_query
from pps_tools.marketing.platforms.base import Platform

API = "https://api.x.com/2"
AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
SCOPES = "tweet.read tweet.write users.read media.write offline.access"
DEFAULT_ADS_VERSION = "12"
OAUTH1_ENV = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
STATS_MAX_DAYS = 7
STATS_MAX_ENTITIES = 20


def _series(metrics: dict, key: str, n: int) -> list[float]:
    """A per-day metric array; null (no delivery) becomes zeros."""
    values = metrics.get(key)
    if isinstance(values, dict):  # conversion metrics come as an object of arrays
        values = values.get("metric")
    if not isinstance(values, list):
        return [0.0] * n
    return [float(v or 0) for v in values] + [0.0] * (n - len(values))


def _conversion_value(metrics: dict, n: int) -> list[float]:
    purchases = metrics.get("conversion_purchases")
    if isinstance(purchases, dict) and isinstance(purchases.get("sale_amount"), list):
        return [float(v or 0) / 1_000_000 for v in purchases["sale_amount"]] + [0.0] * n
    return [0.0] * n


class XPlatform(Platform):
    key = "x"
    name = "X (Twitter)"
    short_name = "X"
    networks = ("x",)
    supports_ads = True
    supports_publish = True
    env_vars = ("X_CLIENT_ID", "X_CLIENT_SECRET")
    docs_url = "https://docs.x.com/x-api/introduction"
    setup_steps = (
        "In the X developer console, create a project + app and add prepaid API credits (posting is pay-per-use).",
        "Under User authentication settings, enable OAuth 2.0 (Web App, confidential client) and add the redirect URI shown below.",
        "Copy the OAuth 2.0 Client ID and Secret into X_CLIENT_ID / X_CLIENT_SECRET.",
        "For ads reporting, get Ads API access, then copy the app's API key/secret and your access token/secret into "
        "X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET.",
    )

    @property
    def configured(self) -> bool:
        return not self.missing_env() or self.has_api_keys

    @property
    def has_api_keys(self) -> bool:
        return all(self.env(v) for v in OAUTH1_ENV)

    @property
    def ads_base(self) -> str:
        return f"https://ads-api.x.com/{self.env('X_ADS_API_VERSION', DEFAULT_ADS_VERSION)}"

    # -- OAuth 2.0 (connect button) -------------------------------------------------

    def authorization_url(self) -> str:
        verifier, challenge = pkce_pair()
        state = self.store.create_oauth_state(self.key, {"verifier": verifier})
        return with_query(
            AUTH_URL,
            {
                "response_type": "code",
                "client_id": self.env("X_CLIENT_ID"),
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        data = self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "X didn't send an authorization code.")
        tokens = self.http.json(
            "POST",
            TOKEN_URL,
            headers=basic_auth(self.env("X_CLIENT_ID"), self.env("X_CLIENT_SECRET")),
            data={
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code_verifier": data.get("verifier", ""),
            },
        )
        creds = self.token_bundle(tokens)
        creds["mode"] = "oauth2"
        me = self.http.json("GET", f"{API}/users/me", headers={"Authorization": f"Bearer {creds['access_token']}"})
        self.store.save_connection(self.key, creds, profile=me.get("data") or {})

    def connect_with_keys(self) -> None:
        """Connect using the OAuth 1.0a keys from the environment (no browser round-trip)."""
        if not self.has_api_keys:
            raise PlatformAPIError(self.name, "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET first.")
        url = f"{API}/users/me"
        me = self.http.json("GET", url, headers={"Authorization": self._oauth1("GET", url)})
        self.store.save_connection(self.key, {"mode": "oauth1"}, profile=me.get("data") or {})
        self.refresh_discovery()

    def refresh_tokens(self, creds: dict) -> dict:
        # Refresh tokens are single-use; token_bundle stores the new one.
        data = self.http.json(
            "POST",
            TOKEN_URL,
            headers=basic_auth(self.env("X_CLIENT_ID"), self.env("X_CLIENT_SECRET")),
            data={"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]},
        )
        bundle = self.token_bundle(data, previous=creds)
        bundle["mode"] = "oauth2"
        return bundle

    # -- signing -------------------------------------------------------------------------

    def _oauth1(self, method: str, url: str, params: Optional[dict] = None) -> str:
        return oauth1_header(
            method,
            url,
            self.env("X_API_KEY"),
            self.env("X_API_SECRET"),
            self.env("X_ACCESS_TOKEN"),
            self.env("X_ACCESS_TOKEN_SECRET"),
            params=params,
        )

    def _user_auth(self, method: str, url: str) -> str:
        """Auth header for v2 user-context calls: OAuth 2.0 when connected that way, else the keys."""
        creds = self.credentials()
        if creds.get("mode") == "oauth2":
            return f"Bearer {self.access_token()}"
        if self.has_api_keys:
            return self._oauth1(method, url)
        raise PlatformAPIError(self.name, "Reconnect X: no usable credentials are stored.")

    def _ads(self, method: str, path: str, params: Optional[dict] = None) -> dict:
        """Call the Ads API, signing query parameters with OAuth 1.0a."""
        if not self.has_api_keys:
            raise PlatformAPIError(self.name, "Ads reporting needs the X_API_KEY / X_ACCESS_TOKEN keys in .env.")
        url = f"{self.ads_base}/{path}"
        params = {k: str(v) for k, v in (params or {}).items() if v is not None}
        query = "&".join(f"{percent_encode(k)}={percent_encode(v)}" for k, v in params.items())
        return self.http.json(
            method,
            f"{url}?{query}" if query else url,
            headers={"Authorization": self._oauth1(method, url, params)},
        )

    def _ads_paged(self, path: str, params: Optional[dict] = None) -> list[dict]:
        items: list[dict] = []
        query = dict(params or {})
        for _ in range(50):
            data = self._ads("GET", path, query)
            items.extend(data.get("data", []))
            cursor = data.get("next_cursor")
            if not cursor:
                break
            query["cursor"] = cursor
        return items

    # -- ads ----------------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        if not self.has_api_keys:
            return []
        accounts = []
        for a in self._ads_paged("accounts", {"count": 1000}):
            if a.get("deleted"):
                continue
            accounts.append(
                AdAccount(
                    platform=self.key,
                    account_id=str(a["id"]),
                    name=a.get("name") or str(a["id"]),
                    currency="USD",  # accounts carry no currency; campaigns do
                    timezone=a.get("timezone"),
                    extra={"approval_status": a.get("approval_status")},
                )
            )
        return accounts

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        campaigns = []
        for c in self._ads_paged(f"accounts/{account.account_id}/campaigns", {"count": 1000}):
            if c.get("deleted"):
                continue
            daily = c.get("daily_budget_amount_local_micro")
            total = c.get("total_budget_amount_local_micro")
            raw = c.get("entity_status", "")
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(c["id"]),
                    name=c.get("name") or str(c["id"]),
                    status={"ACTIVE": ACTIVE, "PAUSED": PAUSED}.get(raw, OTHER),
                    raw_status=c.get("effective_status") or raw,
                    objective=c.get("objective"),
                    daily_budget=daily / 1_000_000 if daily else None,
                    lifetime_budget=total / 1_000_000 if total else None,
                    currency=c.get("currency") or account.currency,
                    budget_editable=bool(daily),
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        campaigns = {c.campaign_id: c for c in self.list_campaigns(account)}
        if not campaigns:
            return []
        try:
            tz = ZoneInfo(account.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        ids = list(campaigns)
        rows = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=STATS_MAX_DAYS - 1), end)
            days = [chunk_start + timedelta(days=i) for i in range((chunk_end - chunk_start).days + 1)]
            # DAY granularity must start and end on midnight in the account's time zone.
            start_time = datetime.combine(chunk_start, time(0), tz).isoformat()
            end_time = datetime.combine(chunk_end + timedelta(days=1), time(0), tz).isoformat()
            for i in range(0, len(ids), STATS_MAX_ENTITIES):
                data = self._ads(
                    "GET",
                    f"stats/accounts/{account.account_id}",
                    {
                        "entity": "CAMPAIGN",
                        "entity_ids": ",".join(ids[i : i + STATS_MAX_ENTITIES]),
                        "start_time": start_time,
                        "end_time": end_time,
                        "granularity": "DAY",
                        "metric_groups": "ENGAGEMENT,BILLING,WEB_CONVERSION",
                        "placement": "ALL_ON_TWITTER",
                    },
                )
                rows.extend(self._parse_stats(account, campaigns, data, days))
            chunk_start = chunk_end + timedelta(days=1)
        return rows

    def _parse_stats(self, account: AdAccount, campaigns: dict, data: dict, days: list[date]) -> list[MetricRow]:
        rows = []
        n = len(days)
        for item in data.get("data", []):
            cid = str(item.get("id"))
            campaign = campaigns.get(cid)
            for seg in item.get("id_data") or []:
                m = seg.get("metrics") or {}
                impressions = _series(m, "impressions", n)
                clicks = _series(m, "clicks", n)
                spend = _series(m, "billed_charge_local_micro", n)
                purchases = _series(m, "conversion_purchases", n)
                signups = _series(m, "conversion_sign_ups", n)
                value = _conversion_value(m, n)
                for i, day in enumerate(days):
                    if not (impressions[i] or clicks[i] or spend[i]):
                        continue
                    rows.append(
                        MetricRow(
                            platform=self.key,
                            network="x",
                            account_id=account.account_id,
                            campaign_id=cid,
                            campaign_name=campaign.name if campaign else cid,
                            date=day.isoformat(),
                            impressions=int(impressions[i]),
                            clicks=int(clicks[i]),
                            spend=spend[i] / 1_000_000,
                            conversions=purchases[i] + signups[i],
                            conversion_value=value[i],
                            currency=campaign.currency if campaign else account.currency,
                        )
                    )
        return rows

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._ads(
            "PUT",
            f"accounts/{campaign.account_id}/campaigns/{campaign.campaign_id}",
            {"entity_status": "PAUSED" if status == PAUSED else "ACTIVE"},
        )

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        self._ads(
            "PUT",
            f"accounts/{campaign.account_id}/campaigns/{campaign.campaign_id}",
            {"daily_budget_amount_local_micro": int(round(amount * 100)) * 10_000},
        )

    # -- posting ---------------------------------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        profile = self.profile()
        if not profile.get("id"):
            return []
        handle = f"@{profile['username']}" if profile.get("username") else profile.get("name", "X account")
        return [(PublishTarget(self.key, "x", str(profile["id"]), handle, "profile"), None)]

    def _upload_image(self, image_url: str) -> str:
        blob, content_type = self.http.download_image(image_url)
        url = f"{API}/media/upload"
        data = self.http.json(
            "POST",
            url,
            headers={"Authorization": self._user_auth("POST", url)},
            files={"media": ("image", blob, content_type)},
            data={"media_category": "tweet_image"},
        )
        media_id = (data.get("data") or {}).get("id") or data.get("media_id_string")
        if not media_id:
            raise PlatformAPIError(self.name, "X didn't return a media id for the image.")
        return str(media_id)

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        body: dict = {"text": content.text}
        if content.image_url:
            body["media"] = {"media_ids": [self._upload_image(content.image_url)]}
        url = f"{API}/tweets"
        data = self.http.json(
            "POST", url, headers={"Authorization": self._user_auth("POST", url), "Content-Type": "application/json"}, json=body
        )
        post_id = (data.get("data") or {}).get("id")
        username = self.profile().get("username")
        return PublishResult(
            ok=True,
            network="x",
            target_id=target.target_id,
            remote_id=post_id,
            url=f"https://x.com/{username or 'i'}/status/{post_id}" if post_id else None,
        )

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        if not isinstance(data, dict):
            return str(data)[:300]
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(str(e.get("message") or e.get("detail") or e) for e in errors)[:300]
        return str(data.get("detail") or data.get("title") or data.get("error_description") or data.get("error") or data)[:300]
