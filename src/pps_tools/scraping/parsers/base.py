"""Abstract base parser for competitor pricing pages."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from bs4 import BeautifulSoup, Tag

from pps_tools.storage.models import PricePoint


class BaseParser(ABC):
    """Base class for all pricing page parsers."""

    competitor_name: str = ""

    @abstractmethod
    def can_parse(self, url: str, html: str) -> bool:
        """Return True if this parser can handle the given URL/HTML."""
        ...

    @abstractmethod
    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        """Parse pricing data from HTML. Returns list of PricePoint objects."""
        ...

    def _make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def _find_price_tables(self, soup: BeautifulSoup) -> list[Tag]:
        """Find HTML tables that look like pricing grids."""
        tables = []
        for table in soup.find_all("table"):
            text = table.get_text()
            # Look for dollar signs and numbers as indicators of pricing
            if re.search(r"\$\s*\d+", text):
                tables.append(table)
        return tables

    def _extract_price(self, text: str) -> float | None:
        """Extract a dollar price from text like '$29.99' or '29.99'."""
        match = re.search(r"\$?\s*(\d{1,6}(?:[,]\d{3})*(?:\.\d{1,2})?)", text)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                return float(price_str)
            except ValueError:
                return None
        return None

    def _extract_quantity(self, text: str) -> int | None:
        """Extract a quantity number from text like '500' or '1,000'."""
        match = re.search(r"(\d{1,6}(?:[,]\d{3})*)", text)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                return None
        return None

    def _extract_prices_from_options(self, soup: BeautifulSoup) -> list[tuple[int, float]]:
        """Extract quantity/price pairs from <select>/<option> elements."""
        pairs = []
        for select in soup.find_all("select"):
            select_name = (select.get("name", "") + select.get("id", "")).lower()
            if any(kw in select_name for kw in ["qty", "quantity", "amount"]):
                for option in select.find_all("option"):
                    text = option.get_text(strip=True)
                    value = option.get("value", "")
                    qty = self._extract_quantity(value) or self._extract_quantity(text)
                    price = self._extract_price(text)
                    if qty and price:
                        pairs.append((qty, price))
        return pairs

    def _extract_prices_from_json_ld(self, soup: BeautifulSoup) -> list[dict]:
        """Extract pricing from JSON-LD structured data."""
        import json

        offers = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        offers.extend(self._extract_offers_from_jsonld(item))
                else:
                    offers.extend(self._extract_offers_from_jsonld(data))
            except (json.JSONDecodeError, TypeError):
                continue
        return offers

    def _extract_offers_from_jsonld(self, data: dict) -> list[dict]:
        """Recursively extract offer data from JSON-LD."""
        offers = []
        if isinstance(data, dict):
            if data.get("@type") in ("Offer", "AggregateOffer"):
                price = data.get("price") or data.get("lowPrice")
                if price:
                    offers.append({
                        "price": float(price),
                        "currency": data.get("priceCurrency", "USD"),
                        "description": data.get("description", ""),
                    })
            # Check nested offers
            for key in ("offers", "hasOfferCatalog", "itemListElement"):
                nested = data.get(key)
                if isinstance(nested, list):
                    for item in nested:
                        offers.extend(self._extract_offers_from_jsonld(item))
                elif isinstance(nested, dict):
                    offers.extend(self._extract_offers_from_jsonld(nested))
        return offers
