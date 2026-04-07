"""PrintPlace pricing parser.

PrintPlace has relatively accessible pricing with visible quantity tiers.
Budget-friendly positioning with bulk discount focus.
"""

from __future__ import annotations

import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.printplace")


class PrintPlaceParser(BaseParser):
    competitor_name = "printplace"

    def can_parse(self, url: str, html: str) -> bool:
        return "printplace.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: Pricing tables (PrintPlace often has visible tier tables)
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

        # Strategy 2: Select/option elements
        pairs = self._extract_prices_from_options(soup)
        for qty, price in pairs:
            if not any(p.quantity == qty and p.total_price == price for p in points):
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=f"option: qty={qty}, price=${price}",
                ))

        # Strategy 3: Look for per-unit pricing patterns
        text = soup.get_text()
        per_unit_pattern = r"(\d+(?:,\d{3})*)\s*(?:pieces?|pcs?|units?)?\s*[-–]\s*\$(\d+(?:\.\d{2})?)\s*(?:each|per|ea)"
        for match in re.finditer(per_unit_pattern, text, re.IGNORECASE):
            qty = int(match.group(1).replace(",", ""))
            unit_price = float(match.group(2))
            total = round(qty * unit_price, 2)
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=qty,
                total_price=total,
                unit_price=unit_price,
                raw_text=match.group(0).strip(),
            ))

        # Strategy 4: "X cents per" patterns common on PrintPlace
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*[¢c]\s*(?:per|each|\/)", text, re.IGNORECASE):
            cents = float(match.group(1))
            unit_price = cents / 100.0
            # Associate with common quantities
            for qty in [100, 500, 1000, 5000, 10000]:
                if not any(p.quantity == qty for p in points):
                    points.append(PricePoint(
                        competitor=self.competitor_name,
                        product=product,
                        quantity=qty,
                        total_price=round(qty * unit_price, 2),
                        unit_price=unit_price,
                        raw_text=f"cents-per: {match.group(0).strip()} @ qty {qty}",
                    ))
            break  # Only use the first cents-per pattern

        # Strategy 5: JSON-LD fallback
        if not points:
            offers = self._extract_prices_from_json_ld(soup)
            for offer in offers:
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=1,
                    total_price=offer["price"],
                    raw_text=f"json-ld: {offer.get('description', '')}",
                ))

        logger.info("PrintPlace parser found %d price points for %s", len(points), product)
        return points
