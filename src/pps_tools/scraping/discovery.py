"""Web search integration for discovering competitor pricing URLs."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from pps_tools.scraping.fetcher import Fetcher
from pps_tools.utils.config import get_competitors, get_products

logger = logging.getLogger("pps_tools.scraping.discovery")


def build_search_queries(
    competitor: str | None = None,
    product: str | None = None,
) -> list[dict]:
    """Build search queries for competitor pricing pages.

    Returns list of dicts with keys: competitor, product, query, domain.
    """
    competitors = get_competitors()
    products = get_products()

    if competitor:
        competitors = {k: v for k, v in competitors.items() if k == competitor}
    if product:
        products = {k: v for k, v in products.items() if k == product}

    queries = []
    for comp_name, comp_info in competitors.items():
        domain = urlparse(comp_info["base_url"]).netloc
        for prod_name, prod_info in products.items():
            query = f"{comp_info['display_name']} {prod_info['display_name']} pricing order"
            queries.append({
                "competitor": comp_name,
                "product": prod_name,
                "query": query,
                "domain": domain,
            })

    return queries


def search_for_urls(
    query: str,
    domain: str,
    max_results: int = 5,
    fetcher: Fetcher | None = None,
) -> list[str]:
    """Search the web for pricing URLs matching a query.

    Uses DuckDuckGo HTML search as a free, no-API-key fallback.
    Returns URLs filtered to the competitor's domain.
    """
    if fetcher is None:
        fetcher = Fetcher(respect_robots=False, delay=3.0)

    search_url = f"https://html.duckduckgo.com/html/?q={query}+site:{domain}"
    result = fetcher.fetch(search_url)

    if not result.success:
        logger.warning("Search failed for query '%s': %s", query, result.error)
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(result.html, "lxml")
    urls = []

    for link in soup.select("a.result__a"):
        href = link.get("href", "")
        # DuckDuckGo wraps URLs; extract the actual URL
        actual_url = _extract_ddg_url(href)
        if actual_url and domain in actual_url:
            urls.append(actual_url)
            if len(urls) >= max_results:
                break

    # Also check result snippets for direct URLs
    for snippet in soup.select("a.result__url"):
        text = snippet.get_text(strip=True)
        if domain in text and text.startswith("http"):
            if text not in urls:
                urls.append(text)
                if len(urls) >= max_results:
                    break

    logger.info("Found %d URLs for query '%s'", len(urls), query)
    return urls


def _extract_ddg_url(href: str) -> str | None:
    """Extract the actual URL from a DuckDuckGo redirect link."""
    if not href:
        return None

    # DuckDuckGo uses uddg parameter for the actual URL
    match = re.search(r"uddg=([^&]+)", href)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))

    # If it's already a direct URL
    if href.startswith("http"):
        return href

    return None


def discover_pricing_urls(
    competitor: str | None = None,
    product: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Discover pricing URLs for competitors via web search.

    Returns list of dicts with: competitor, product, url, source.
    """
    queries = build_search_queries(competitor, product)
    fetcher = Fetcher(respect_robots=False, delay=3.0)
    discovered = []

    for q in queries:
        # First check if we already have config URLs
        competitors = get_competitors()
        comp_info = competitors.get(q["competitor"], {})
        config_urls = comp_info.get("pricing_urls", {})

        if q["product"] in config_urls:
            discovered.append({
                "competitor": q["competitor"],
                "product": q["product"],
                "url": config_urls[q["product"]],
                "source": "config",
            })

        # Then search for additional URLs
        urls = search_for_urls(q["query"], q["domain"], max_results, fetcher)
        for url in urls:
            if not any(d["url"] == url for d in discovered):
                discovered.append({
                    "competitor": q["competitor"],
                    "product": q["product"],
                    "url": url,
                    "source": "search",
                })

    return discovered
