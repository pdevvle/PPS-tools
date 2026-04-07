"""Generic fallback parser using heuristics to find pricing data."""

from __future__ import annotations

import logging
import re

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.storage.models import PricePoint

logger = logging.getLogger("pps_tools.scraping.parsers.generic")


class GenericParser(BaseParser):
    """Fallback parser that uses heuristics to detect pricing in any page."""

    competitor_name = "generic"

    def can_parse(self, url: str, html: str) -> bool:
        # Generic parser is always the last resort
        return True

    def parse(self, url: str, html: str, product: str) -> list[PricePoint]:
        soup = self._make_soup(html)
        points: list[PricePoint] = []
        competitor = self._guess_competitor(url)

        # Strategy 1: Look for pricing tables
        for table in self._find_price_tables(soup):
            points.extend(self._parse_price_table(table, competitor, product))

        # Strategy 2: Look for select/option elements with quantities and prices
        if not points:
            pairs = self._extract_prices_from_options(soup)
            for qty, price in pairs:
                points.append(PricePoint(
                    competitor=competitor,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=f"qty={qty}, price=${price}",
                ))

        # Strategy 3: Look for JSON-LD structured data
        if not points:
            offers = self._extract_prices_from_json_ld(soup)
            for offer in offers:
                points.append(PricePoint(
                    competitor=competitor,
                    product=product,
                    quantity=1,
                    total_price=offer["price"],
                    currency=offer.get("currency", "USD"),
                    raw_text=offer.get("description", ""),
                ))

        # Strategy 4: Scan for "starting at $X" or "from $X" patterns
        if not points:
            points.extend(self._find_starting_prices(soup, competitor, product))

        # Strategy 5: Look for quantity-price patterns in page text
        if not points:
            points.extend(self._find_inline_prices(soup, competitor, product))

        logger.info(
            "Generic parser found %d price points for %s/%s",
            len(points), competitor, product,
        )
        return points

    def _guess_competitor(self, url: str) -> str:
        """Guess competitor name from URL domain."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.lower()
        # Strip www. and .com
        name = domain.replace("www.", "").split(".")[0]
        return name

    def _parse_price_table(self, table, competitor: str, product: str) -> list[PricePoint]:
        """Try to parse a pricing table into PricePoint objects."""
        points = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return points

        # Try to identify header row
        header_row = rows[0]
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

        qty_col = None
        price_col = None
        for i, h in enumerate(headers):
            if any(kw in h for kw in ["qty", "quantity", "amount", "count"]):
                qty_col = i
            if any(kw in h for kw in ["price", "cost", "total", "$"]):
                price_col = i

        # If we can't identify columns from headers, try heuristic on data rows
        if qty_col is None or price_col is None:
            for row in rows[1:3]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                for i, cell in enumerate(cells):
                    if qty_col is None and re.match(r"^\d{1,6}(,\d{3})*$", cell.replace(" ", "")):
                        qty_col = i
                    if price_col is None and re.search(r"\$", cell):
                        price_col = i

        if qty_col is None or price_col is None:
            return points

        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) <= max(qty_col, price_col):
                continue

            qty = self._extract_quantity(cells[qty_col])
            price = self._extract_price(cells[price_col])
            if qty and price:
                points.append(PricePoint(
                    competitor=competitor,
                    product=product,
                    quantity=qty,
                    total_price=price,
                    raw_text=f"table: {' | '.join(cells)}",
                ))

        return points

    def _find_starting_prices(self, soup, competitor: str, product: str) -> list[PricePoint]:
        """Find 'starting at $X' or 'from $X' patterns."""
        points = []
        text = soup.get_text()

        patterns = [
            r"(?:starting\s+(?:at|from)|from|as\s+low\s+as)\s*\$(\d+(?:\.\d{2})?)",
            r"\$(\d+(?:\.\d{2})?)\s*(?:and up|starting|per\s+\d+)",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                price = float(match.group(1))
                if 0.01 < price < 100000:
                    points.append(PricePoint(
                        competitor=competitor,
                        product=product,
                        quantity=1,
                        total_price=price,
                        raw_text=match.group(0).strip(),
                    ))

        return points

    def _find_inline_prices(self, soup, competitor: str, product: str) -> list[PricePoint]:
        """Find quantity-price pairs in text like '500 for $49.99'."""
        points = []
        text = soup.get_text()

        patterns = [
            r"(\d{1,6}(?:,\d{3})*)\s+(?:for|@|at)\s+\$(\d+(?:\.\d{2})?)",
            r"\$(\d+(?:\.\d{2})?)\s+(?:for|per)\s+(\d{1,6}(?:,\d{3})*)",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                groups = match.groups()
                # Determine which group is quantity and which is price
                if pattern.startswith(r"(\d"):
                    qty = int(groups[0].replace(",", ""))
                    price = float(groups[1])
                else:
                    price = float(groups[0])
                    qty = int(groups[1].replace(",", ""))

                if qty > 0 and 0.01 < price < 100000:
                    points.append(PricePoint(
                        competitor=competitor,
                        product=product,
                        quantity=qty,
                        total_price=price,
                        raw_text=match.group(0).strip(),
                    ))

        return points
