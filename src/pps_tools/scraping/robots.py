"""Robots.txt compliance checker."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger("pps_tools.scraping.robots")

_cache: dict[str, RobotFileParser] = {}


def can_fetch(url: str, user_agent: str = "*") -> bool:
    """Check if the URL is allowed by the site's robots.txt."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in _cache:
        parser = RobotFileParser()
        try:
            resp = requests.get(robots_url, timeout=10)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                # If robots.txt not found, assume everything is allowed
                parser.allow_all = True
        except requests.RequestException:
            parser.allow_all = True
            logger.debug("Could not fetch robots.txt for %s, allowing all", parsed.netloc)

        _cache[robots_url] = parser

    return _cache[robots_url].can_fetch(user_agent, url)


def clear_cache():
    """Clear the robots.txt cache."""
    _cache.clear()
