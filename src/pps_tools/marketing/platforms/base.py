"""The interface every ad platform connector implements.

A connector knows how to:
    * walk the user through OAuth (or read keys from the environment),
    * find the ad accounts and publish targets the user can reach,
    * read campaigns and daily campaign metrics,
    * pause / enable a campaign and change its daily budget,
    * publish an organic post (where the platform allows it).

Everything is returned in the normalized shapes from `marketing.models`.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Mapping, Optional

import requests

from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.http import ApiClient, NotConnectedError, PlatformAPIError, default_error_message
from pps_tools.marketing.models import (
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
)
from pps_tools.marketing.store import Store


_REFRESH_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


class Platform:
    key: str = ""
    name: str = ""
    short_name: str = ""
    networks: tuple[str, ...] = ()
    supports_ads: bool = True
    supports_publish: bool = False
    # Environment variables that must be set before "Connect" can work.
    env_vars: tuple[str, ...] = ()
    docs_url: str = ""
    setup_steps: tuple[str, ...] = ()

    def __init__(
        self,
        store: Store,
        settings: MarketingSettings,
        session: Optional[requests.Session] = None,
    ):
        self.store = store
        self.settings = settings
        self.http = ApiClient(self.name, session=session, error_message=self.error_message)

    # -- configuration --------------------------------------------------------

    @staticmethod
    def env(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    @property
    def configured(self) -> bool:
        return not self.missing_env()

    def missing_env(self) -> list[str]:
        return [v for v in self.env_vars if not self.env(v)]

    @property
    def redirect_uri(self) -> str:
        return self.settings.redirect_uri(self.key)

    # -- connection -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.store.get_connection(self.key) is not None

    def profile(self) -> dict:
        conn = self.store.get_connection(self.key)
        return conn["profile"] if conn else {}

    def credentials(self) -> dict:
        conn = self.store.get_connection(self.key)
        if not conn:
            raise NotConnectedError(f"{self.name} is not connected.")
        return conn["credentials"]

    @staticmethod
    def _needs_refresh(creds: dict) -> bool:
        expires_at = creds.get("expires_at")
        return bool(expires_at and creds.get("refresh_token") and time.time() > float(expires_at) - 120)

    def access_token(self) -> str:
        """The current access token, refreshed first if it is about to expire.

        Refreshing is serialized per platform: Pinterest and X hand out a new
        refresh token each time (X's are single-use), so two threads refreshing
        with the same one would knock each other out.
        """
        creds = self.credentials()
        if self._needs_refresh(creds):
            with _REFRESH_LOCKS[self.key]:
                creds = self.credentials()  # another thread may have just refreshed
                if self._needs_refresh(creds):
                    creds = self.refresh_tokens(creds)
                    self.store.update_credentials(self.key, creds)
        return creds["access_token"]

    def refresh_tokens(self, creds: dict) -> dict:
        raise PlatformAPIError(self.name, "Access token expired; reconnect this platform.")

    @staticmethod
    def token_bundle(data: dict, previous: Optional[dict] = None) -> dict:
        """Normalize an OAuth token response into what we store."""
        bundle = dict(previous or {})
        bundle["access_token"] = data["access_token"]
        if data.get("refresh_token"):
            bundle["refresh_token"] = data["refresh_token"]
        if data.get("expires_in"):
            bundle["expires_at"] = time.time() + int(data["expires_in"])
        if data.get("refresh_token_expires_in"):
            bundle["refresh_expires_at"] = time.time() + int(data["refresh_token_expires_in"])
        if data.get("scope"):
            bundle["scope"] = data["scope"]
        return bundle

    def token_warning(self) -> Optional[str]:
        """A message for the Connections page when the user must reconnect soon."""
        conn = self.store.get_connection(self.key)
        if not conn:
            return None
        creds = conn["credentials"]
        deadline = creds.get("refresh_expires_at")
        if deadline is None and not creds.get("refresh_token"):
            deadline = creds.get("expires_at")
        if not deadline:
            return None
        days = (float(deadline) - time.time()) / 86400
        if days < 0:
            return "Access has expired — reconnect to keep syncing."
        if days < 7:
            return f"Access expires in {max(int(days), 0)} day(s) — reconnect soon."
        return None

    def authorization_url(self) -> str:
        """Where to send the browser to grant access (state is stored for the callback)."""
        raise NotImplementedError

    def complete_authorization(self, args: Mapping[str, str]) -> None:
        """Handle the OAuth callback: validate state, exchange the code, save the connection."""
        raise NotImplementedError

    def connect(self, args: Mapping[str, str]) -> None:
        self.complete_authorization(args)
        self.refresh_discovery()

    def refresh_discovery(self) -> None:
        if self.supports_ads:
            self.store.replace_accounts(self.key, self.discover_accounts())
        if self.supports_publish:
            self.store.replace_targets(self.key, self.discover_targets())
        self.store.cache_clear(f"metrics:{self.key}:")
        self.store.cache_clear(f"campaigns:{self.key}:")

    def disconnect(self) -> None:
        self.store.delete_connection(self.key)

    def check_state(self, args: Mapping[str, str]) -> dict:
        if args.get("error"):
            detail = args.get("error_description") or args.get("error_message") or args["error"]
            raise PlatformAPIError(self.name, f"Authorization was not granted: {detail}")
        data = self.store.pop_oauth_state(args.get("state", ""), self.key)
        if data is None:
            raise PlatformAPIError(self.name, "The sign-in link expired or was already used. Try connecting again.")
        return data

    # -- ads ------------------------------------------------------------------

    def discover_accounts(self) -> list[AdAccount]:
        return []

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        raise NotImplementedError

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        raise NotImplementedError

    def set_status(self, campaign: Campaign, status: str) -> None:
        raise PlatformAPIError(self.name, "Changing campaign status isn't supported here.")

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        raise PlatformAPIError(self.name, "Changing budgets isn't supported here.")

    # -- publishing -----------------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        return []

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        raise PlatformAPIError(self.name, "Publishing isn't supported here.")

    # -- errors ---------------------------------------------------------------

    def error_message(self, resp: requests.Response) -> str:
        """Turn an error response into a readable message (connectors override for odd shapes)."""
        return default_error_message(resp)


def daterange_days(start: date, end: date) -> list[date]:
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days
