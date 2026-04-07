"""Parser registry for competitor pricing pages."""

from __future__ import annotations

from pps_tools.scraping.parsers.base import BaseParser
from pps_tools.scraping.parsers.generic import GenericParser
from pps_tools.scraping.parsers.vistaprint import VistaprintParser
from pps_tools.scraping.parsers.gotprint import GotPrintParser
from pps_tools.scraping.parsers.uprinting import UPrintingParser
from pps_tools.scraping.parsers.printplace import PrintPlaceParser
from pps_tools.scraping.parsers.psprint import PsPrintParser
from pps_tools.scraping.parsers.moo import MooParser
from pps_tools.scraping.parsers.overnightprints import OvernightPrintsParser

# Ordered by specificity: site-specific first, generic last
PARSERS: list[BaseParser] = [
    VistaprintParser(),
    GotPrintParser(),
    UPrintingParser(),
    PrintPlaceParser(),
    PsPrintParser(),
    MooParser(),
    OvernightPrintsParser(),
    GenericParser(),
]


def get_parser_for_url(url: str, html: str) -> BaseParser | None:
    """Find the appropriate parser for a given URL and HTML content."""
    for parser in PARSERS:
        if parser.can_parse(url, html):
            return parser
    return None
