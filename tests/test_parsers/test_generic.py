"""Tests for the generic parser."""

from pps_tools.scraping.parsers.generic import GenericParser


def test_parse_pricing_table(sample_html_pricing_table):
    """Test parsing a standard pricing table."""
    parser = GenericParser()
    points = parser.parse("https://example.com/pricing", sample_html_pricing_table, "business_cards")

    assert len(points) >= 4
    quantities = [p.quantity for p in points]
    assert 100 in quantities
    assert 500 in quantities
    assert 1000 in quantities

    # Check prices
    for p in points:
        if p.quantity == 100:
            assert p.total_price == 29.99
        elif p.quantity == 500:
            assert p.total_price == 79.99


def test_parse_json_ld(sample_html_json_ld):
    """Test parsing JSON-LD structured data."""
    parser = GenericParser()
    points = parser.parse("https://example.com/cards", sample_html_json_ld, "business_cards")

    assert len(points) > 0
    prices = [p.total_price for p in points]
    assert 9.99 in prices


def test_parse_options(sample_html_options):
    """Test parsing select/option elements."""
    parser = GenericParser()
    points = parser.parse("https://example.com/order", sample_html_options, "business_cards")

    assert len(points) >= 3
    quantities = [p.quantity for p in points]
    assert 100 in quantities
    assert 250 in quantities
    assert 500 in quantities


def test_parse_starting_at():
    """Test parsing 'starting at' price patterns."""
    html = """
    <html><body>
        <h1>Business Cards</h1>
        <p>Premium quality business cards starting at $14.99</p>
        <p>Flyers from $29.99 for full-color printing</p>
    </body></html>
    """
    parser = GenericParser()
    points = parser.parse("https://example.com/cards", html, "business_cards")

    assert len(points) >= 1
    prices = [p.total_price for p in points]
    assert 14.99 in prices


def test_parse_inline_prices():
    """Test parsing inline quantity-price patterns."""
    html = """
    <html><body>
        <p>Get 500 for $49.99 or 1000 for $79.99</p>
    </body></html>
    """
    parser = GenericParser()
    points = parser.parse("https://example.com/cards", html, "business_cards")

    assert len(points) >= 2
    qty_price = {p.quantity: p.total_price for p in points}
    assert qty_price.get(500) == 49.99
    assert qty_price.get(1000) == 79.99


def test_can_parse_always_true():
    """Generic parser should always return True for can_parse."""
    parser = GenericParser()
    assert parser.can_parse("https://anything.com", "<html></html>") is True


def test_guess_competitor():
    """Test competitor name guessing from URL."""
    parser = GenericParser()
    assert parser._guess_competitor("https://www.vistaprint.com/cards") == "vistaprint"
    assert parser._guess_competitor("https://gotprint.com/order") == "gotprint"
