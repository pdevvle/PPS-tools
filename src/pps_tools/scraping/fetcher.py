"""HTTP fetching with rate limiting and polite scraping."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from pps_tools.scraping.robots import can_fetch
from pps_tools.utils.config import get_settings

logger = logging.getLogger("pps_tools.scraping.fetcher")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    headers: dict
    success: bool
    error: str | None = None


class Fetcher:
    """HTTP client with rate limiting and robots.txt compliance."""

    def __init__(
        self,
        delay: float | None = None,
        respect_robots: bool = True,
        timeout: int = 30,
    ):
        settings = get_settings().get("scraping", {})
        self.delay = delay if delay is not None else settings.get("delay_between_requests", 2.0)
        self.respect_robots = respect_robots
        self.timeout = timeout
        self.max_retries = settings.get("max_retries", 3)

        user_agents = settings.get("user_agents", [])
        self.user_agent = random.choice(user_agents) if user_agents else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        self._last_request_time: dict[str, float] = {}

    def _rate_limit(self, url: str):
        """Enforce delay between requests to the same domain."""
        domain = urlparse(url).netloc
        last_time = self._last_request_time.get(domain, 0)
        elapsed = time.time() - last_time
        if elapsed < self.delay:
            wait = self.delay - elapsed
            logger.debug("Rate limiting: sleeping %.1fs for %s", wait, domain)
            time.sleep(wait)
        self._last_request_time[domain] = time.time()

    def fetch(self, url: str) -> FetchResult:
        """Fetch a URL with rate limiting and robots.txt compliance."""
        # Check robots.txt
        if self.respect_robots and not can_fetch(url, self.user_agent):
            logger.warning("Blocked by robots.txt: %s", url)
            return FetchResult(
                url=url, final_url=url, status_code=0, html="",
                headers={}, success=False, error="Blocked by robots.txt",
            )

        self._rate_limit(url)

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                return FetchResult(
                    url=url,
                    final_url=resp.url,
                    status_code=resp.status_code,
                    html=resp.text,
                    headers=dict(resp.headers),
                    success=resp.status_code == 200,
                    error=None if resp.status_code == 200 else f"HTTP {resp.status_code}",
                )
            except requests.RequestException as e:
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, e)
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        return FetchResult(
            url=url, final_url=url, status_code=0, html="",
            headers={}, success=False, error="Max retries exceeded",
        )

    def fetch_many(self, urls: list[str]) -> list[FetchResult]:
        """Fetch multiple URLs sequentially with rate limiting."""
        results = []
        for url in urls:
            results.append(self.fetch(url))
        return results
