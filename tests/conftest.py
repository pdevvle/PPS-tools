"""Shared test fixtures."""

import tempfile
from pathlib import Path

import pytest

from pps_tools.storage.database import init_db, get_connection


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test_pricing.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def sample_html_pricing_table():
    """Sample HTML with a pricing table."""
    return """
    <html>
    <body>
        <table>
            <tr><th>Quantity</th><th>Price</th></tr>
            <tr><td>100</td><td>$29.99</td></tr>
            <tr><td>250</td><td>$49.99</td></tr>
            <tr><td>500</td><td>$79.99</td></tr>
            <tr><td>1,000</td><td>$129.99</td></tr>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_json_ld():
    """Sample HTML with JSON-LD pricing data."""
    return """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "Product",
            "name": "Business Cards",
            "offers": {
                "@type": "AggregateOffer",
                "lowPrice": "9.99",
                "highPrice": "129.99",
                "priceCurrency": "USD"
            }
        }
        </script>
    </head>
    <body>
        <h1>Business Cards starting at $9.99</h1>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_options():
    """Sample HTML with select/option pricing."""
    return """
    <html>
    <body>
        <form>
            <select name="quantity">
                <option value="100">100 - $19.99</option>
                <option value="250">250 - $34.99</option>
                <option value="500">500 - $59.99</option>
            </select>
        </form>
    </body>
    </html>
    """
