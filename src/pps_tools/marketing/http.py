"""HTTP plumbing shared by the platform connectors."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class PlatformAPIError(RuntimeError):
    """A platform rejected a request. `message` is written for the dashboard user."""

    def __init__(self, platform: str, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(f"{platform}: {message}")
        self.platform = platform
        self.message = message
        self.status = status
        self.body = body[:2000]


class NotConnectedError(RuntimeError):
    pass


def default_error_message(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:300] or resp.reason or f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)
        for key in ("message", "error_description", "error", "detail"):
            if data.get(key):
                return str(data[key])
    return str(data)[:300]


class ApiClient:
    """A thin wrapper over requests with timeouts, light retries and readable errors."""

    def __init__(
        self,
        platform: str,
        session: Optional[requests.Session] = None,
        timeout: float = 45,
        max_retries: int = 2,
        error_message: Optional[Callable[[requests.Response], str]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.platform = platform
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.error_message = error_message or default_error_message
        self.sleep = sleep

    def request(self, method: str, url: str, retry: Optional[bool] = None, **kwargs) -> requests.Response:
        """Send a request; raise PlatformAPIError on any non-2xx answer.

        Only reads are retried (GET by default, or POST reports that pass
        retry=True): replaying a write could double-post or double-apply a
        budget change.
        """
        kwargs.setdefault("timeout", self.timeout)
        retryable = method.upper() == "GET" if retry is None else retry
        attempt = 0
        while True:
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                if retryable and attempt < self.max_retries:
                    attempt += 1
                    self.sleep(min(2 ** attempt, 8))
                    continue
                raise PlatformAPIError(self.platform, f"Network error: {exc}") from exc

            if retryable and resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                attempt += 1
                delay = _retry_after(resp) or min(2 ** attempt, 8)
                logger.info("%s: HTTP %s, retrying in %ss", self.platform, resp.status_code, delay)
                self.sleep(delay)
                continue

            if not resp.ok:
                raise PlatformAPIError(
                    self.platform,
                    f"{self.error_message(resp)} (HTTP {resp.status_code})",
                    status=resp.status_code,
                    body=resp.text,
                )
            return resp

    def download_image(self, url: str, max_bytes: int = 5 * 1024 * 1024) -> tuple[bytes, str]:
        """Fetch an image the user linked to, for platforms that want the bytes uploaded."""
        if not url.lower().startswith(("https://", "http://")):
            raise PlatformAPIError(self.platform, "Image URL must start with https://")
        try:
            resp = self.session.get(url, stream=True, timeout=self.timeout)
        except requests.RequestException as exc:
            raise PlatformAPIError(self.platform, f"Couldn't download the image: {exc}") from exc
        with resp:
            if not resp.ok:
                raise PlatformAPIError(self.platform, f"Couldn't download the image (HTTP {resp.status_code}).")
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                raise PlatformAPIError(self.platform, "The image URL doesn't point to an image.")
            data = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise PlatformAPIError(
                        self.platform, f"The image is larger than {max_bytes // (1024 * 1024)} MB."
                    )
        return bytes(data), content_type

    def json(self, method: str, url: str, **kwargs) -> dict:
        resp = self.request(method, url, **kwargs)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise PlatformAPIError(
                self.platform, f"Unexpected non-JSON response from {url}", status=resp.status_code, body=resp.text
            ) from exc


def _retry_after(resp: requests.Response) -> Optional[float]:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), 30.0)
    except ValueError:
        return None
