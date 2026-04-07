"""MOO pricing parser.

MOO has premium positioning with unique card options. Their site is
moderately JS-dependent but often has structured pricing data.
"""

from __future__ import annotations

import json
import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.moo")


class MooParser(BaseParser):
    competitor_name = "moo"

    def can_parse(self, url: str, html: str) -> bool:
        return "moo.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: JSON-LD (MOO often has good structured data)
        offers = self._extract_prices_from_json_ld(soup)
        for offer in offers:
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=1,
                total_price=offer["price"],
                raw_text=f"json-ld: {offer.get('description', '')}",
            ))

        # Strategy 2: Look for pricing in embedded JSON/script data
        for script in soup.find_all("script"):
            if not script.string:
                continue
            if "price" in script.string.lower():
                # MOO may embed pricing in React/Next.js data
                try:
                    json_objects = re.findall(r'\{[^{}]*"price"\s*:\s*[\d.]+[^{}]*\}', script.string)
                    for obj_str in json_objects:
                        obj = json.loads(obj_str)
                        price = obj.get("price")
                        qty = obj.get("quantity", 1)
                        if price and float(price) > 0:
                            points.append(PricePoint(
                                competitor=self.competitor_name,
                                product=product,
                                quantity=int(qty),
                                total_price=float(price),
                                raw_text=f"script-json: {obj_str[:200]}",
                            ))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

        # Strategy 3: Visible pricing on page
        # MOO often shows "X for $Y" patterns
        text = soup.get_text()
        for match in re.finditer(r"(\d+)\s+(?:cards?|for)\s+\$(\d+(?:\.\d{2})?)", text, re.IGNORECASE):
            qty = int(match.group(1))
            price = float(match.group(2))
            if qty > 0 and price > 0:
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=match.group(0).strip(),
                ))

        # Strategy 4: Pricing elements with specific CSS classes
        for elem in soup.find_all(class_=re.compile(r"price|cost", re.IGNORECASE)):
            price = self._extract_price(elem.get_text())
            if price and not any(p.total_price == price for p in points):
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=1,
                    total_price=price,
                    raw_text=f"css-class: {elem.get_text(strip=True)[:100]}",
                ))

        if not points:
            logger.warning("MOO parser found no pricing. URL: %s", url)

        return points
