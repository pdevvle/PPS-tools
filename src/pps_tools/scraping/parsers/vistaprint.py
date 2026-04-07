"""Vistaprint pricing parser.

Note: Vistaprint uses a heavy JS pricing calculator. Static HTML scraping
can only extract base/starting prices from marketing copy. Full tier
extraction requires JS rendering (playwright) or API interception.
"""

from __future__ import annotations

import json
import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.vistaprint")


class VistaprintParser(BaseParser):
    competitor_name = "vistaprint"

    def can_parse(self, url: str, html: str) -> bool:
        return "vistaprint.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: Look for JSON-LD structured data
        offers = self._extract_prices_from_json_ld(soup)
        for offer in offers:
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=1,
                total_price=offer["price"],
                currency=offer.get("currency", "USD"),
                raw_text=f"json-ld: {offer.get('description', '')}",
            ))

        # Strategy 2: Look for embedded pricing data in script tags
        for script in soup.find_all("script"):
            if not script.string:
                continue
            # Vistaprint sometimes embeds pricing in __NEXT_DATA__ or similar
            if "__NEXT_DATA__" in script.string:
                points.extend(self._parse_next_data(script.string, product))
            # Look for pricing JSON objects
            elif "price" in script.string.lower() and "quantity" in script.string.lower():
                points.extend(self._parse_embedded_json(script.string, product))

        # Strategy 3: Extract "starting at" prices from visible content
        text = soup.get_text()
        starting_pattern = r"(?:starting\s+at|from)\s*\$(\d+(?:\.\d{2})?)"
        for match in re.finditer(starting_pattern, text, re.IGNORECASE):
            price = float(match.group(1))
            if 0.01 < price < 10000 and not any(p.total_price == price for p in points):
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=1,
                    total_price=price,
                    raw_text=match.group(0).strip(),
                ))

        # Strategy 4: Look for pricing in data attributes
        for elem in soup.find_all(attrs={"data-price": True}):
            price = self._extract_price(elem["data-price"])
            qty_attr = elem.get("data-quantity") or elem.get("data-qty")
            qty = int(qty_attr) if qty_attr and qty_attr.isdigit() else 1
            if price:
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=f"data-attr: price={price}, qty={qty}",
                ))

        if not points:
            logger.warning(
                "Vistaprint parser found no pricing data (site likely requires JS). "
                "Try using --js flag for full extraction. URL: %s", url
            )

        return points

    def _parse_next_data(self, script_text: str, product: str) -> list[PricePoint]:
        """Extract pricing from Next.js __NEXT_DATA__ JSON."""
        points = []
        try:
            match = re.search(r"__NEXT_DATA__\s*=\s*({.*?})\s*;?\s*$", script_text, re.DOTALL)
            if not match:
                return points
            data = json.loads(match.group(1))
            # Traverse the JSON looking for pricing structures
            points.extend(self._traverse_for_prices(data, product))
        except (json.JSONDecodeError, AttributeError):
            pass
        return points

    def _parse_embedded_json(self, script_text: str, product: str) -> list[PricePoint]:
        """Try to extract pricing from embedded JSON in script tags."""
        points = []
        # Look for JSON objects that contain price and quantity fields
        json_pattern = r'\{[^{}]*"(?:price|totalPrice)"[^{}]*\}'
        for match in re.finditer(json_pattern, script_text):
            try:
                data = json.loads(match.group(0))
                price = data.get("price") or data.get("totalPrice")
                qty = data.get("quantity") or data.get("qty") or 1
                if price:
                    points.append(PricePoint(
                        competitor=self.competitor_name,
                        product=product,
                        quantity=int(qty),
                        total_price=float(price),
                        raw_text=f"embedded-json: {match.group(0)[:200]}",
                    ))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return points

    def _traverse_for_prices(self, data, product: str, depth: int = 0) -> list[PricePoint]:
        """Recursively traverse JSON data looking for pricing structures."""
        points = []
        if depth > 10:
            return points

        if isinstance(data, dict):
            # Check if this dict looks like a price entry
            price = data.get("price") or data.get("totalPrice") or data.get("displayPrice")
            if price is not None:
                try:
                    price_val = float(str(price).replace("$", "").replace(",", ""))
                    qty = data.get("quantity") or data.get("qty") or 1
                    points.append(PricePoint(
                        competitor=self.competitor_name,
                        product=product,
                        quantity=int(qty),
                        total_price=price_val,
                        raw_text=f"next-data: {json.dumps(data)[:200]}",
                    ))
                except (ValueError, TypeError):
                    pass

            for value in data.values():
                points.extend(self._traverse_for_prices(value, product, depth + 1))

        elif isinstance(data, list):
            for item in data:
                points.extend(self._traverse_for_prices(item, product, depth + 1))

        return points
