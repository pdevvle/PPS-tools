"""Tests for the scrape-all command."""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pps_tools.commands.scrape_all import scrape_all


@pytest.fixture
def mock_db_rows():
    """Sample pricing URL rows from the database."""
    return [
        {
            "url": "https://www.gotprint.com/products/brochures/order",
            "url_id": 1,
            "is_dynamic": False,
            "competitor_name": "gotprint",
            "competitor_id": 1,
            "product_name": "brochures",
            "product_id": 1,
        },
        {
            "url": "https://www.vistaprint.com/brochures",
            "url_id": 2,
            "is_dynamic": True,
            "competitor_name": "vistaprint",
            "competitor_id": 2,
            "product_name": "brochures",
            "product_id": 1,
        },
    ]


class TestScrapeAllSkipDynamic:
    def test_skips_dynamic_without_js(self, mock_db_rows):
        runner = CliRunner()

        with patch("pps_tools.commands.scrape_all.get_connection") as mock_conn:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.fetchall.return_value = mock_db_rows
            mock_conn.return_value = ctx

            with patch("pps_tools.commands.scrape_all.Fetcher") as mock_fetcher_cls:
                mock_fetcher = MagicMock()
                mock_fetcher_cls.return_value = mock_fetcher

                # Static URL succeeds
                from pps_tools.scraping.fetcher import FetchResult
                mock_fetcher.fetch.return_value = FetchResult(
                    url=mock_db_rows[0]["url"],
                    final_url=mock_db_rows[0]["url"],
                    status_code=200,
                    html="<html><body>No pricing</body></html>",
                    headers={},
                    success=True,
                )

                with patch("pps_tools.commands.scrape_all.get_parser_for_url") as mock_parser:
                    mock_parser.return_value = None  # No parser found

                    result = runner.invoke(scrape_all, ["--no-save"])

                # Should only fetch the static URL (gotprint), not vistaprint
                assert mock_fetcher.fetch.call_count == 1
                assert "Skipping" in result.output or "skipped" in result.output.lower()


class TestScrapeAllQuietMode:
    def test_quiet_prints_single_line(self, mock_db_rows):
        runner = CliRunner()

        with patch("pps_tools.commands.scrape_all.get_connection") as mock_conn:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.fetchall.return_value = []
            mock_conn.return_value = ctx

            result = runner.invoke(scrape_all, ["--quiet"])
            # Should be minimal output
            assert "Scrape Summary" not in result.output
