"""UPrinting pricing parser.

UPrinting uses a custom product builder which is largely JS-driven.
Static parsing extracts starting prices and any visible tier information.
"""

from __future__ import annotations

import json
import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.uprinting")


class UPrintingParser(BaseParser):
    competitor_name = "uprinting"

    def can_parse(self, url: str, html: str) -> bool:
        return "uprinting.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: Look for pricing data in embedded scripts
        for script in soup.find_all("script"):
            if not script.string:
                continue
            # UPrinting sometimes embeds product config with pricing
            if "productConfig" in script.string or "pricing" in script.string.lower():
                try:
                    json_match = re.search(r"(?:productConfig|pricingData)\s*=\s*({.*?});",
                                           script.string, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(1))
                        points.extend(self._extract_from_config(data, product))
                except (json.JSONDecodeError, AttributeError):
                    pass

        # Strategy 2: JSON-LD structured data
        offers = self._extract_prices_from_json_ld(soup)
        for offer in offers:
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=1,
                total_price=offer["price"],
                raw_text=f"json-ld: {offer.get('description', '')}",
            ))

        # Strategy 3: Starting prices from visible content
        text = soup.get_text()
        for match in re.finditer(
            r"(?:starting\s+at|from|as\s+low\s+as)\s*\$(\d+(?:\.\d{2})?)",
            text, re.IGNORECASE,
        ):
            price = float(match.group(1))
            if 0.01 < price < 10000 and not any(p.total_price == price for p in points):
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=1,
                    total_price=price,
                    raw_text=match.group(0).strip(),
                ))

        # Strategy 4: Pricing tables
        for table in self._find_price_tables(soup):
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                qty = None
                price = None
                for cell in cells:
                    if qty is None:
                        qty = self._extract_quantity(cell)
                    if price is None:
                        price = self._extract_price(cell)
                if qty and price:
                    points.append(PricePoint(
                        competitor=self.competitor_name,
                        product=product,
                        quantity=qty,
                        total_price=price,
                        raw_text=f"table: {' | '.join(cells)}",
                    ))

        if not points:
            logger.warning(
                "UPrinting parser found no pricing data (site likely requires JS). "
                "Try using --js flag. URL: %s", url
            )

        return points

    def _extract_from_config(self, data: dict, product: str) -> list[PricePoint]:
        """Extract pricing from UPrinting's product configuration JSON."""
        points = []
        if isinstance(data, dict):
            prices = data.get("prices") or data.get("pricing") or {}
            if isinstance(prices, dict):
                for qty_str, price_val in prices.items():
                    try:
                        qty = int(qty_str)
                        price = float(price_val)
                        points.append(PricePoint(
                            competitor=self.competitor_name,
                            product=product,
                            quantity=qty,
                            total_price=price,
                            raw_text=f"config: qty={qty}, price={price}",
                        ))
                    except (ValueError, TypeError):
                        continue
            elif isinstance(prices, list):
                for item in prices:
                    if isinstance(item, dict):
                        qty = item.get("quantity") or item.get("qty")
                        price = item.get("price") or item.get("total")
                        if qty and price:
                            points.append(PricePoint(
                                competitor=self.competitor_name,
                                product=product,
                                quantity=int(qty),
                                total_price=float(price),
                                raw_text=f"config-list: {item}",
                            ))
        return points
