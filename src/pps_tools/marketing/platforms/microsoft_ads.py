"""Microsoft Advertising (Bing): reporting and campaign control via the REST API v13.

Docs: https://learn.microsoft.com/en-us/advertising/guides/
Microsoft moved this API to REST/JSON in 2026 (SOAP retires in January
2027). Every call carries a developer token next to the OAuth token, and
campaign and reporting calls also name the customer and account they act
on. Ids travel as JSON strings. Performance data only comes from
asynchronous reports: submit one, poll until it is ready, then download a
zipped CSV.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Optional

from pps_tools.marketing.http import PlatformAPIError, default_error_message
from pps_tools.marketing.models import ACTIVE, OTHER, PAUSED, REMOVED, AdAccount, Campaign, MetricRow
from pps_tools.marketing.oauth import pkce_pair, with_query
from pps_tools.marketing.platforms.base import Platform

LOGIN_URL = "https://login.microsoftonline.com"
SCOPE = "https://ads.microsoft.com/msads.manage offline_access"
CUSTOMER_API = "https://clientcenter.api.bingads.microsoft.com/CustomerManagement/v13"
CAMPAIGN_API = "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13"
REPORTING_API = "https://reporting.api.bingads.microsoft.com/Reporting/v13"

ACCOUNTS_PAGE_SIZE = 1000
# Without a type only Search campaigns come back, and there is no "all" value.
CAMPAIGN_TYPES = "Search, Shopping, Audience, PerformanceMax"
# BudgetPaused (Microsoft stopped it when the budget ran out) and Suspended stay OTHER.
STATUS_MAP = {"Active": ACTIVE, "Paused": PAUSED, "BudgetAndManualPaused": PAUSED, "Deleted": REMOVED}
LIFETIME_BUDGET = "LifetimeBudgetStandard"

# "Conversions" is deprecated in favor of "ConversionsQualified".
REPORT_COLUMNS = [
    "TimePeriod", "AccountId", "CampaignId", "CampaignName", "Impressions", "Clicks", "Spend",
    "ConversionsQualified", "Revenue", "CurrencyCode",
]
# Seconds between status checks. A small account's report is usually ready within seconds.
POLL_DELAYS = (1, 1, 2, 3, 5, 5, 8, 10, 15, 15, 15, 20)
MAX_REPORT_BYTES = 200 * 1024 * 1024

# Accounts and reports use separate time zone lists that spell these four zones differently.
REPORT_TIME_ZONES = {
    "AthensBuckarestIstanbul": "AthensIslandanbulMinsk",
    "IslamabadKarachiTashkent": "IslandamabadKarachiTashkent",
    "SolomonIslandNewCaledonia": "MagadanSolomonIslandNewCaledonia",
    "MidwayIslandAndSamoa": "MidwayIslandandSamoa",
}


def _number(value: Optional[str]) -> float:
    """Report cells: '1,234.50' -> 1234.5; blanks and '--' -> 0."""
    try:
        return float((value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _report_date(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _objective(campaign_type: Optional[str]) -> Optional[str]:
    """PerformanceMax -> PERFORMANCE_MAX, the shape the UI formats."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", campaign_type).upper() if campaign_type else None


def _has_id(value) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def earliest_today() -> date:
    """Today's date where it is earliest (UTC-12), so a report never asks for a day
    that hasn't started in the account's time zone; Microsoft rejects end dates
    after today."""
    return datetime.now(timezone(timedelta(hours=-12))).date()


def read_report(content: bytes) -> list[dict]:
    """Rows of a downloaded report: a zip holding one CSV (a bare CSV works too)."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            if not files:
                return []
            if files[0].file_size > MAX_REPORT_BYTES:
                raise ValueError("report file is too large")
            content = archive.read(files[0])
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def error_text(errors: list[dict]) -> str:
    parts = []
    for e in errors:
        message = e.get("Message") or e.get("Details") or e.get("Detail") or "Unknown error"
        parts.append(f"{message} [{e['ErrorCode']}]" if e.get("ErrorCode") else message)
    return "; ".join(parts)[:500]


class MicrosoftAdsPlatform(Platform):
    key = "microsoft_ads"
    name = "Microsoft Advertising"
    short_name = "Microsoft Ads"
    networks = ("microsoft",)
    supports_ads = True
    supports_publish = False
    env_vars = ("MICROSOFT_ADS_CLIENT_ID", "MICROSOFT_ADS_CLIENT_SECRET", "MICROSOFT_ADS_DEVELOPER_TOKEN")
    docs_url = "https://learn.microsoft.com/en-us/advertising/guides/get-started"
    setup_steps = (
        "Sign in to the Microsoft Advertising Developer Portal (https://developers.ads.microsoft.com) with your Microsoft Advertising login and request a developer token.",
        "In the Azure portal, open Microsoft Entra ID → App registrations and register an app for 'Accounts in any organizational directory and personal Microsoft accounts'.",
        "Under Authentication, add a Web platform with the redirect URI shown below. Under Certificates & secrets, create a client secret.",
        "Copy the Application (client) ID, the secret's value and the developer token into MICROSOFT_ADS_CLIENT_ID / MICROSOFT_ADS_CLIENT_SECRET / MICROSOFT_ADS_DEVELOPER_TOKEN.",
    )

    @property
    def login_base(self) -> str:
        return f"{LOGIN_URL}/{self.env('MICROSOFT_ADS_TENANT', 'common')}/oauth2/v2.0"

    # -- OAuth ------------------------------------------------------------------

    def authorization_url(self) -> str:
        # PKCE is recommended by Microsoft even for web apps with a secret.
        verifier, challenge = pkce_pair()
        state = self.store.create_oauth_state(self.key, {"verifier": verifier})
        return with_query(
            f"{self.login_base}/authorize",
            {
                "client_id": self.env("MICROSOFT_ADS_CLIENT_ID"),
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "response_mode": "query",
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                # People often have several Microsoft accounts; let them pick the one with the ads.
                "prompt": "select_account",
            },
        )

    def _token_request(self, params: dict) -> dict:
        return self.http.json(
            "POST",
            f"{self.login_base}/token",
            data={
                "client_id": self.env("MICROSOFT_ADS_CLIENT_ID"),
                "client_secret": self.env("MICROSOFT_ADS_CLIENT_SECRET"),
                "scope": SCOPE,
                **params,
            },
        )

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        data = self.check_state(args)
        code = args.get("code")
        if not code:
            raise PlatformAPIError(self.name, "Microsoft didn't send an authorization code.")
        tokens = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": data.get("verifier", ""),
            }
        )
        if not tokens.get("refresh_token"):
            raise PlatformAPIError(self.name, "Microsoft didn't return a refresh token. Try connecting again.")
        creds = self.token_bundle(tokens)
        user = self._user(token=creds["access_token"])
        names = user.get("Name") or {}
        full_name = " ".join(n for n in (names.get("FirstName"), names.get("LastName")) if n)
        profile = {"user_id": str(user.get("Id") or ""), "name": full_name or user.get("UserName")}
        self.store.save_connection(self.key, creds, profile=profile)

    def refresh_tokens(self, creds: dict) -> dict:
        # Each refresh hands out a new refresh token; token_bundle keeps the latest.
        data = self._token_request({"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]})
        return self.token_bundle(data, previous=creds)

    # -- requests ---------------------------------------------------------------

    def _headers(self, customer_id: Optional[str] = None, account_id: Optional[str] = None,
                 token: Optional[str] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {token or self.access_token()}",
            "DeveloperToken": self.env("MICROSOFT_ADS_DEVELOPER_TOKEN"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if account_id:
            headers["CustomerId"] = str(customer_id or "")
            headers["CustomerAccountId"] = str(account_id)
        return headers

    def _customer_for(self, account_id: str) -> Optional[str]:
        for acct in self.store.list_accounts(self.key):
            if acct.account_id == account_id:
                return acct.extra.get("customer_id")
        return None

    def _post(self, url: str, body: dict, account: Optional[AdAccount] = None, token: Optional[str] = None) -> dict:
        """POST a read (these are safe to retry: queries, report submit and poll)."""
        headers = self._headers(
            account.extra.get("customer_id") if account else None,
            account.account_id if account else None,
            token,
        )
        return self.http.json("POST", url, headers=headers, json=body, retry=True)

    def _user(self, token: Optional[str] = None) -> dict:
        return self._post(f"{CUSTOMER_API}/User/Query", {"UserId": None}, token=token).get("User") or {}

    # -- ads --------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        user_id = self.profile().get("user_id") or str(self._user().get("Id") or "")
        if not user_id:
            raise PlatformAPIError(self.name, "Couldn't look up your Microsoft Advertising user.")
        accounts = []
        for page in range(50):
            data = self._post(
                f"{CUSTOMER_API}/Accounts/Search",
                {
                    "Predicates": [{"Field": "UserId", "Operator": "Equals", "Value": user_id}],
                    "PageInfo": {"Index": page, "Size": ACCOUNTS_PAGE_SIZE},
                },
            )
            batch = data.get("Accounts") or []
            for a in batch:
                status = a.get("AccountLifeCycleStatus")
                accounts.append(
                    AdAccount(
                        platform=self.key,
                        account_id=str(a["Id"]),
                        name=a.get("Name") or a.get("Number") or str(a["Id"]),
                        currency=a.get("CurrencyCode") or "USD",
                        # Closed, unapproved and draft accounts start switched off.
                        enabled=status in (None, "Active", "Pause"),
                        extra={
                            "customer_id": str(a.get("ParentCustomerId") or ""),
                            "number": a.get("Number"),
                            "status": status,
                            "time_zone": a.get("TimeZone"),
                        },
                    )
                )
            if len(batch) < ACCOUNTS_PAGE_SIZE:
                break
        return accounts

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        data = self._post(
            f"{CAMPAIGN_API}/Campaigns/QueryByAccountId",
            {"AccountId": account.account_id, "CampaignType": CAMPAIGN_TYPES},
            account,
        )
        campaigns = []
        for c in data.get("Campaigns") or []:
            raw = c.get("Status") or ""
            amount = float(c["DailyBudget"]) if c.get("DailyBudget") is not None else None
            # A lifetime budget's amount is reported in DailyBudget too.
            lifetime = c.get("BudgetType") == LIFETIME_BUDGET
            shared = _has_id(c.get("BudgetId"))
            experiment = _has_id(c.get("ExperimentId"))
            campaigns.append(
                Campaign(
                    platform=self.key,
                    account_id=account.account_id,
                    campaign_id=str(c.get("Id")),
                    name=c.get("Name") or f"Campaign {c.get('Id')}",
                    status=STATUS_MAP.get(raw, OTHER),
                    raw_status=raw,
                    objective=_objective(c.get("CampaignType")),
                    daily_budget=None if lifetime else amount,
                    lifetime_budget=amount if lifetime else None,
                    currency=account.currency,
                    budget_editable=bool(amount) and not (lifetime or shared or experiment),
                    extra={
                        "customer_id": account.extra.get("customer_id"),
                        "budget_type": c.get("BudgetType"),
                        "shared_budget": shared,
                        "experiment": experiment,
                    },
                )
            )
        return campaigns

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        end = min(end, earliest_today())
        if start > end:
            return []
        report_time = {
            "CustomDateRangeStart": {"Day": start.day, "Month": start.month, "Year": start.year},
            "CustomDateRangeEnd": {"Day": end.day, "Month": end.month, "Year": end.year},
        }
        # Report in the account's own time zone, like the Microsoft Advertising UI (the default is Pacific).
        zone = account.extra.get("time_zone")
        if zone:
            report_time["ReportTimeZone"] = REPORT_TIME_ZONES.get(zone, zone)
        request = {
            "Type": "CampaignPerformanceReportRequest",
            "ReportName": "PPS Marketing Hub",
            "Format": "Csv",
            "FormatVersion": "2.0",
            "ExcludeReportHeader": True,
            "ExcludeReportFooter": True,
            "ExcludeColumnHeaders": False,
            "ReturnOnlyCompleteData": False,
            "Aggregation": "Daily",
            "Columns": REPORT_COLUMNS,
            "Scope": {"AccountIds": [account.account_id]},
            "Time": report_time,
        }
        submitted = self._post(f"{REPORTING_API}/GenerateReport/Submit", {"ReportRequest": request}, account)
        report_id = submitted.get("ReportRequestId")
        if not report_id:
            raise PlatformAPIError(self.name, "Microsoft didn't accept the report request.")
        url = self._wait_for_report(account, report_id)
        if not url:
            return []  # no activity in the date range
        try:
            records = read_report(self.http.request("GET", url).content)
        except (ValueError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
            raise PlatformAPIError(self.name, f"Couldn't read the performance report ({exc}).") from exc
        rows = []
        for r in records:
            day = _report_date(r.get("TimePeriod"))
            campaign_id = (r.get("CampaignId") or "").strip()
            if not day or not campaign_id:
                continue
            rows.append(
                MetricRow(
                    platform=self.key,
                    network="microsoft",
                    account_id=account.account_id,
                    campaign_id=campaign_id,
                    campaign_name=r.get("CampaignName") or f"Campaign {campaign_id}",
                    date=day,
                    impressions=int(_number(r.get("Impressions"))),
                    clicks=int(_number(r.get("Clicks"))),
                    spend=_number(r.get("Spend")),
                    conversions=_number(r.get("ConversionsQualified")),
                    conversion_value=_number(r.get("Revenue")),
                    currency=(r.get("CurrencyCode") or "").strip() or account.currency,
                )
            )
        return rows

    def _wait_for_report(self, account: AdAccount, report_id: str) -> Optional[str]:
        """The download URL once the report is built (None when there's no data)."""
        for delay in POLL_DELAYS:
            self.http.sleep(delay)
            data = self._post(f"{REPORTING_API}/GenerateReport/Poll", {"ReportRequestId": report_id}, account)
            status = data.get("ReportRequestStatus") or {}
            if status.get("Status") == "Success":
                return status.get("ReportDownloadUrl")
            if status.get("Status") == "Error":
                raise PlatformAPIError(self.name, "Microsoft couldn't build the performance report. Try again in a few minutes.")
        raise PlatformAPIError(self.name, "The performance report is taking longer than usual. Try again in a minute.")

    def _update_campaign(self, campaign: Campaign, changes: dict) -> None:
        customer_id = campaign.extra.get("customer_id") or self._customer_for(campaign.account_id)
        data = self.http.json(
            "PUT",
            f"{CAMPAIGN_API}/Campaigns",
            headers=self._headers(customer_id, campaign.account_id),
            json={"AccountId": campaign.account_id, "Campaigns": [{"Id": campaign.campaign_id, **changes}]},
        )
        errors = [e for e in data.get("PartialErrors") or [] if isinstance(e, dict)]
        if errors:
            raise PlatformAPIError(self.name, error_text(errors))

    def set_status(self, campaign: Campaign, status: str) -> None:
        if campaign.extra.get("experiment"):
            raise PlatformAPIError(self.name, "This is an experiment campaign; it follows its base campaign's status.")
        self._update_campaign(campaign, {"Status": "Paused" if status == PAUSED else "Active"})

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        if campaign.extra.get("shared_budget"):
            raise PlatformAPIError(self.name, "This campaign uses a shared budget; change it in Microsoft Advertising.")
        if campaign.extra.get("experiment"):
            raise PlatformAPIError(self.name, "This is an experiment campaign; change its base campaign's budget instead.")
        if campaign.extra.get("budget_type") == LIFETIME_BUDGET:
            raise PlatformAPIError(self.name, "This campaign has a lifetime budget; change it in Microsoft Advertising.")
        self._update_campaign(campaign, {"DailyBudget": round(amount, 2)})

    def error_message(self, resp) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300] or f"HTTP {resp.status_code}"
        if not isinstance(data, dict):
            return str(data)[:300]
        if isinstance(data.get("error"), str):  # sign-in (Microsoft identity platform) errors
            # The description ends with trace and correlation ids on later lines.
            text = (data.get("error_description") or data["error"]).strip()
            return text.splitlines()[0] if text else "Sign-in failed"
        fault = data.get("ApplicationFault")
        if not isinstance(fault, dict):
            fault = data
        errors = []
        for key in ("OperationErrors", "BatchErrors", "Errors", "PartialErrors"):
            errors.extend(e for e in fault.get(key) or [] if isinstance(e, dict))
        if errors:
            return error_text(errors)
        return fault.get("Message") or default_error_message(resp)
