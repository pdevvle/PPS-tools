"""PsPrint pricing parser."""

from __future__ import annotations

import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.psprint")


class PsPrintParser(BaseParser):
    competitor_name = "psprint"

    def can_parse(self, url: str, html: str) -> bool:
        return "psprint.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: Pricing tables
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
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=qty,
                total_price=price,
                raw_text=f"option: qty={qty}, price=${price}",
            ))

        # Strategy 3: JSON-LD
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

        # Strategy 4: Starting prices
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

        logger.info("PsPrint parser found %d price points for %s", len(points), product)
        return points
