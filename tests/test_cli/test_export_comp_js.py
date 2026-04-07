"""Tests for the export-comp-js command."""

import json

import pytest

from pps_tools.commands.export_comp_js import build_comp_data, render_js, _build_spec_string
from pps_tools.storage.models import PricePoint


SAMPLE_PRODUCTS_CONFIG = {
    "brochures": {
        "display_name": "Brochures",
        "default_specs": {
            "size": "8.5x11",
            "paper_type": "100lb_gloss",
            "color_mode": "full_color",
            "sides": "double",
            "finish": "tri_fold",
        },
    },
    "business_cards": {
        "display_name": "Business Cards",
        "default_specs": {
            "size": "3.5x2",
            "paper_type": "14pt",
            "color_mode": "full_color",
            "sides": "double",
            "finish": "none",
        },
    },
}


def _make_points():
    """Create sample PricePoints for testing."""
    return [
        PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=62.0),
        PricePoint(competitor="vistaprint", product="brochures", quantity=100, total_price=110.0),
        PricePoint(competitor="gotprint", product="brochures", quantity=250, total_price=100.0),
        PricePoint(competitor="vistaprint", product="brochures", quantity=250, total_price=190.0),
        PricePoint(competitor="gotprint", product="business_cards", quantity=500, total_price=22.0),
        PricePoint(competitor="vistaprint", product="business_cards", quantity=500, total_price=30.0),
    ]


class TestBuildSpecString:
    def test_brochures_spec(self):
        result = _build_spec_string("brochures", SAMPLE_PRODUCTS_CONFIG)
        assert "8.5x11" in result
        assert "100lb gloss" in result
        assert "full color" in result
        assert "both sides" in result
        assert "tri-fold" in result

    def test_business_cards_spec(self):
        result = _build_spec_string("business_cards", SAMPLE_PRODUCTS_CONFIG)
        assert "3.5x2" in result
        assert "14pt" in result
        # finish=none should be excluded
        assert "none" not in result

    def test_unknown_product(self):
        result = _build_spec_string("unknown_product", SAMPLE_PRODUCTS_CONFIG)
        assert result == ""


class TestBuildCompData:
    def test_basic_structure(self):
        points = _make_points()
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG)

        assert "brochures" in result
        assert "business_cards" in result
        assert "spec" in result["brochures"]
        assert "tiers" in result["brochures"]

    def test_tiers_grouped_by_quantity(self):
        points = _make_points()
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG)

        brochure_tiers = result["brochures"]["tiers"]
        assert 100 in brochure_tiers
        assert 250 in brochure_tiers
        assert "gotprint" in brochure_tiers[100]
        assert "vistaprint" in brochure_tiers[100]

    def test_rounded_prices(self):
        points = [
            PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=62.49),
        ]
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG, round_prices=True)
        assert result["brochures"]["tiers"][100]["gotprint"] == 62

    def test_unrounded_prices(self):
        points = [
            PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=62.49),
        ]
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG, round_prices=False)
        assert result["brochures"]["tiers"][100]["gotprint"] == 62.49

    def test_tiers_sorted_by_quantity(self):
        points = [
            PricePoint(competitor="gotprint", product="brochures", quantity=500, total_price=160.0),
            PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=62.0),
            PricePoint(competitor="gotprint", product="brochures", quantity=250, total_price=100.0),
        ]
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG)
        tier_keys = list(result["brochures"]["tiers"].keys())
        assert tier_keys == [100, 250, 500]

    def test_dedup_keeps_lowest(self):
        points = [
            PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=65.0),
            PricePoint(competitor="gotprint", product="brochures", quantity=100, total_price=62.0),
        ]
        result = build_comp_data(points, SAMPLE_PRODUCTS_CONFIG)
        assert result["brochures"]["tiers"][100]["gotprint"] == 62

    def test_empty_input(self):
        result = build_comp_data([], SAMPLE_PRODUCTS_CONFIG)
        assert result == {}


class TestRenderJs:
    def test_valid_js_output(self):
        comp_data = {
            "brochures": {
                "spec": "8.5x11, 100lb gloss",
                "tiers": {100: {"gotprint": 62}},
            }
        }
        js = render_js(comp_data)
        assert js.startswith("//")
        assert "const COMP_DATA = " in js
        assert js.rstrip().endswith(";")

    def test_parseable_json_payload(self):
        comp_data = {
            "brochures": {
                "spec": "test",
                "tiers": {100: {"gotprint": 62, "vistaprint": 110}},
            }
        }
        js = render_js(comp_data)
        # Extract JSON between = and ;
        json_part = js.split(" = ", 1)[1].rstrip().rstrip(";")
        parsed = json.loads(json_part)
        assert "brochures" in parsed

    def test_custom_var_name(self):
        js = render_js({"test": {"spec": "", "tiers": {}}}, var_name="MY_PRICES")
        assert "const MY_PRICES = " in js
