"""GotPrint pricing parser.

GotPrint uses a more traditional order form. Pricing is often visible
in HTML option tags and dropdowns, making it more amenable to static parsing.
"""

from __future__ import annotations

import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.gotprint")


class GotPrintParser(BaseParser):
    competitor_name = "gotprint"

    def can_parse(self, url: str, html: str) -> bool:
        return "gotprint.com" in url.lower()

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []

        # Strategy 1: Extract from select/option elements (quantity selectors)
        pairs = self._extract_prices_from_options(soup)
        for qty, price in pairs:
            points.append(PricePoint(
                competitor=self.competitor_name,
                product=product,
                quantity=qty,
                total_price=price,
                raw_text=f"option: qty={qty}, price=${price}",
            ))

        # Strategy 2: Look for pricing tables
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

        # Strategy 3: Look for pricing in JavaScript variables
        for script in soup.find_all("script"):
            if not script.string:
                continue
            # GotPrint sometimes stores pricing in JS arrays/objects
            price_array = re.findall(
                r"(?:prices?|costs?)\s*(?:=|\[)\s*\[([^\]]+)\]",
                script.string, re.IGNORECASE,
            )
            for arr in price_array:
                numbers = re.findall(r"[\d.]+", arr)
                # Try to pair quantities with prices
                for num_str in numbers:
                    try:
                        val = float(num_str)
                        if val > 0 and val < 100000:
                            points.append(PricePoint(
                                competitor=self.competitor_name,
                                product=product,
                                quantity=1,
                                total_price=val,
                                raw_text=f"js-array: {num_str}",
                            ))
                    except ValueError:
                        continue

        # Strategy 4: Look for pricing data attributes on form elements
        for elem in soup.find_all(["input", "div", "span"], attrs={"data-price": True}):
            price = self._extract_price(elem["data-price"])
            qty_attr = elem.get("data-qty") or elem.get("data-quantity")
            qty = int(qty_attr) if qty_attr and qty_attr.isdigit() else None
            if price and qty:
                points.append(PricePoint(
                    competitor=self.competitor_name,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=f"data-attr: {elem.get('data-price')}",
                ))

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

        logger.info("GotPrint parser found %d price points for %s", len(points), product)
        return points
