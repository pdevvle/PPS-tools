"""LinkedIn: Campaign Manager reporting + control, and Company Page posts.

Uses the versioned Marketing API (api.linkedin.com/rest), which needs a
`LinkedIn-Version: YYYYMM` header on every call. Docs:
https://learn.microsoft.com/en-us/linkedin/marketing/
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Optional
from urllib.parse import quote

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

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com/rest"
DEFAULT_VERSION = "202610"
SCOPES = (
    "r_ads",
    "r_ads_reporting",
    "rw_ads",
    "r_organization_admin",
    "w_organization_social",
)

STATUS_MAP = {
    "ACTIVE": ACTIVE,
    "PAUSED": PAUSED,
    "ARCHIVED": REMOVED,
    "CANCELED": REMOVED,
    "REMOVED": REMOVED,
    "PENDING_DELETION": REMOVED,
}

# Little Text Format reserves these characters in post commentary.
_RESERVED = set("|{}@[]()<>\\*_~")


def escape_commentary(text: str) -> str:
    """Escape Little Text Format, keeping #hashtags clickable."""
    out = []
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in _RESERVED or (ch == "#" and not (nxt.isalnum() or nxt == "_")):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _restli_date(d: date) -> str:
    return f"(year:{d.year},month:{d.month},day:{d.day})"


class LinkedInPlatform(Platform):
    key = "linkedin"
    name = "LinkedIn"
    short_name = "LinkedIn"
    networks = ("linkedin",)
    supports_ads = True
    supports_publish = True
    env_vars = ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET")
    docs_url = "https://learn.microsoft.com/en-us/linkedin/marketing/"
    setup_steps = (
        "Create an app at https://www.linkedin.com/developers/apps and link it to your Company Page.",
        "Request the Advertising API and Community Management API products for the app.",
        "Under Auth, add the redirect URL shown below.",
        "Copy the Client ID and Client Secret into LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET.",
    )

    @property
    def version(self) -> str:
        return self.env("LINKEDIN_API_VERSION", DEFAULT_VERSION)

    def _headers(self, **extra: str) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "LinkedIn-Version": self.version,
            "X-Restli-Protocol-Version": "2.0.0",
            **extra,
        }

    def _get(self, url: str) -> dict:
        return self.http.json("GET", url, headers=self._headers())

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        state = self.store.create_oauth_state(self.key)
        return with_query(
            AUTH_URL,
            {
                "response_type": "code",
                "client_id": self.env("LINKEDIN_CLIENT_ID"),
                "redirect_uri": self.redirect_uri,
                "state": state,
                "scope": " ".join(SCOPES),
            },
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "LinkedIn didn't send an authorization code.")
        data = self.http.json(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.env("LINKEDIN_CLIENT_ID"),
                "client_secret": self.env("LINKEDIN_CLIENT_SECRET"),
                "redirect_uri": self.redirect_uri,
            },
        )
        self.store.save_connection(self.key, self.token_bundle(data))

    def refresh_tokens(self, creds: dict) -> dict:
        data = self.http.json(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": self.env("LINKEDIN_CLIENT_ID"),
                "client_secret": self.env("LINKEDIN_CLIENT_SECRET"),
            },
        )
        return self.token_bundle(data, previous=creds)

    # -- ads --------------------------------------------------------------------

    def _paged(self, url: str) -> list[dict]:
        """Follow LinkedIn's cursor pagination (metadata.nextPageToken)."""
        elements: list[dict] = []
        page_url = url
        for _ in range(50):
            data = self._get(page_url)
            elements.extend(data.get("elements", []))
            token = (data.get("metadata") or {}).get("nextPageToken")
            if not token:
                break
            page_url = f"{url}&pageToken={quote(token, safe='')}"
        return elements

    def discover_accounts(self) -> list[AdAccount]:
        accounts = []
        for el in self._paged(f"{API}/adAccounts?q=search&pageSize=1000"):
            if el.get("test"):
                continue
            accounts.append(
                AdAccount(
                    platform=self.key,
                    account_id=str(el["id"]),
                    name=el.get("name") or f"Account {el['id']}",
                    currency=el.get("currency") or "USD",
                    enabled=el.get("status") == "ACTIVE",
                    extra={"status": el.get("status"), "type": el.get("type")},
                )
            )
        return accounts

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        url = (
            f"{API}/adAccounts/{account.account_id}/adCampaigns?q=search"
            "&search=(status:(values:List(ACTIVE,PAUSED,COMPLETED)))&pageSize=1000"
        )
        campaigns = []
        for el in self._paged(url):
            daily = el.get("dailyBudget") or {}
            total = el.get("totalBudget") or {}
            raw = el.get("status", "")
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(el["id"]),
                    name=el.get("name") or f"Campaign {el['id']}",
                    status=STATUS_MAP.get(raw, OTHER),
                    raw_status=raw,
                    objective=el.get("objectiveType"),
                    daily_budget=float(daily["amount"]) if daily.get("amount") else None,
                    lifetime_budget=float(total["amount"]) if total.get("amount") else None,
                    currency=daily.get("currencyCode") or total.get("currencyCode") or account.currency,
                    budget_editable=bool(daily.get("amount")),
                    extra={"type": el.get("type")},
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        names = {c.campaign_id: c.name for c in self.list_campaigns(account)}
        account_urn = quote(f"urn:li:sponsoredAccount:{account.account_id}", safe="")
        # Rest.li syntax characters ( ) , : must stay unencoded, so the query is built by hand.
        query = (
            "q=analytics&pivot=CAMPAIGN&timeGranularity=DAILY"
            f"&dateRange=(start:{_restli_date(start)},end:{_restli_date(end)})"
            f"&accounts=List({account_urn})"
            "&fields=dateRange,pivotValues,impressions,clicks,costInLocalCurrency,"
            "externalWebsiteConversions,conversionValueInLocalCurrency"
        )
        data = self._get(f"{API}/adAnalytics?{query}")
        rows = []
        for el in data.get("elements", []):
            pivots = el.get("pivotValues") or []
            if not pivots:
                continue
            campaign_id = str(pivots[0]).rsplit(":", 1)[-1]
            d = (el.get("dateRange") or {}).get("start") or {}
            if not d:
                continue
            rows.append(
                MetricRow(
                    platform=self.key,
                    network="linkedin",
                    account_id=account.account_id,
                    campaign_id=campaign_id,
                    campaign_name=names.get(campaign_id, f"Campaign {campaign_id}"),
                    date=date(int(d["year"]), int(d["month"]), int(d["day"])).isoformat(),
                    impressions=int(el.get("impressions") or 0),
                    clicks=int(el.get("clicks") or 0),
                    spend=float(el.get("costInLocalCurrency") or 0),
                    conversions=float(el.get("externalWebsiteConversions") or 0),
                    conversion_value=float(el.get("conversionValueInLocalCurrency") or 0),
                    currency=account.currency,
                )
            )
        return rows

    def _patch_campaign(self, campaign: Campaign, patch: dict) -> None:
        self.http.request(
            "POST",
            f"{API}/adAccounts/{campaign.account_id}/adCampaigns/{campaign.campaign_id}",
            headers=self._headers(**{"X-RestLi-Method": "PARTIAL_UPDATE", "Content-Type": "application/json"}),
            json={"patch": {"$set": patch}},
        )

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._patch_campaign(campaign, {"status": "PAUSED" if status == PAUSED else "ACTIVE"})

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        self._patch_campaign(
            campaign, {"dailyBudget": {"amount": f"{amount:.2f}", "currencyCode": campaign.currency}}
        )

    # -- Company Page posts -------------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        try:
            data = self._get(f"{API}/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=100")
        except PlatformAPIError:
            # Ads work without Page admin rights; posting just won't be offered.
            return []
        ids = []
        for el in data.get("elements", []):
            urn = el.get("organization") or el.get("organizationTarget") or ""
            if urn.startswith("urn:li:organization:"):
                ids.append(urn.rsplit(":", 1)[-1])
        if not ids:
            return []
        names: dict = {}
        try:
            looked_up = self._get(f"{API}/organizations?ids=List({','.join(ids)})")
            names = looked_up.get("results") or {}
        except PlatformAPIError:
            pass
        return [
            (
                PublishTarget(
                    platform=self.key,
                    network="linkedin",
                    target_id=org_id,
                    name=(names.get(org_id) or {}).get("localizedName") or f"Organization {org_id}",
                    kind="organization",
                ),
                None,
            )
            for org_id in ids
        ]

    def _upload_image(self, owner: str, image_url: str) -> str:
        blob, _ = self.http.download_image(image_url)
        init = self.http.json(
            "POST",
            f"{API}/images?action=initializeUpload",
            headers=self._headers(**{"Content-Type": "application/json"}),
            json={"initializeUploadRequest": {"owner": owner}},
        )
        value = init.get("value") or {}
        if not value.get("uploadUrl") or not value.get("image"):
            raise PlatformAPIError(self.name, "LinkedIn didn't return an image upload URL.")
        self.http.request(
            "PUT", value["uploadUrl"], data=blob, headers={"Authorization": f"Bearer {self.access_token()}"}
        )
        return value["image"]

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        author = f"urn:li:organization:{target.target_id}"
        body: dict = {
            "author": author,
            "commentary": escape_commentary(content.text),
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if content.link:
            article = {"source": content.link, "title": (content.title or content.link)[:399]}
            body["content"] = {"article": article}
        elif content.image_url:
            body["content"] = {"media": {"id": self._upload_image(author, content.image_url)}}
        resp = self.http.request(
            "POST", f"{API}/posts", headers=self._headers(**{"Content-Type": "application/json"}), json=body
        )
        urn = resp.headers.get("x-restli-id")
        return PublishResult(
            ok=True,
            network="linkedin",
            target_id=target.target_id,
            remote_id=urn,
            url=f"https://www.linkedin.com/feed/update/{urn}/" if urn else None,
        )

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error_description") or data.get("error") or data)[:300]
        return str(data)[:300]
