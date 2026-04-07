"""PPS pricing calculator - ported from the GitHub calc-preview-test.html engine.

This reproduces the exact pricing logic from Priority Print Service's
production calculator to generate own-pricing data for comparison analysis.
"""

import math
import json
from pathlib import Path

# ── Paper definitions (from calc-preview-test.html) ──────────────────────

PAPERS_NC = [
    {"label": "70lb Uncoated Opaque Text", "val": 0.001, "price": 0.06, "factory": False, "coatable": False},
    {"label": "80lb Matte Text", "val": 0.002, "price": 0.069, "factory": False, "coatable": False},
    {"label": "100lb Gloss Text", "val": 0.003, "price": 0.085, "factory": False, "coatable": True},
    {"label": "50lb Offset Smooth Opaque", "val": 2.001, "price": 0.039, "factory": True, "coatable": False},
    {"label": "60lb Offset Smooth Opaque", "val": 2.002, "price": 0.042, "factory": True, "coatable": False},
    {"label": "80lb Offset Smooth Opaque", "val": 2.003, "price": 0.056, "factory": True, "coatable": False},
    {"label": "80lb Gloss Factory Coated", "val": 2.004, "price": 0.0525, "factory": True, "coatable": True},
    {"label": "100lb Matte Factory Coated", "val": 2.005, "price": 0.070, "factory": True, "coatable": True},
]

PAPERS_CS = [
    {"label": "80lb Opaque Uncoated", "val": 0.01, "price": 0.0919, "factory": False, "coatable": False},
    {"label": "80lb Matte Cardstock", "val": 0.02, "price": 0.1119, "factory": False, "coatable": True},
    {"label": "100lb Gloss Cardstock", "val": 0.03, "price": 0.1319, "factory": False, "coatable": True},
    {"label": "14pt Gloss C1S", "val": 1.01, "price": 0.1619, "factory": False, "coatable": True},
    {"label": "16pt Coated C2S", "val": 1.02, "price": 0.1919, "factory": False, "coatable": True},
    {"label": "80lb Gloss Factory Coated", "val": 2.21, "price": 0.13192, "factory": True, "coatable": True},
    {"label": "100lb Matte Factory Coated", "val": 2.22, "price": 0.145619, "factory": True, "coatable": True},
    {"label": "12pt C2S Factory Coated", "val": 2.23, "price": 0.155719, "factory": True, "coatable": True},
    {"label": "14pt C2S Factory Coated", "val": 2.24, "price": 0.169019, "factory": True, "coatable": True},
    {"label": "18pt C1S Factory Gloss", "val": 2.25, "price": 0.186719, "factory": True, "coatable": True},
]

COATINGS = [
    {"label": "No Additional Coating", "val": 0, "price": 0},
    {"label": "UV Gloss", "val": 750, "price": 0.03},
    {"label": "UV Matte", "val": 510, "price": 0.04},
]

# ── Production cost factors (from pps-config-admin.php) ──────────────────

PCF = {
    "printing_fullcolor_cost": 0.05,
    "printing_black_cost": 0.01,
    "labor_press_hr": 35,
    "labor_bindery_hr": 35,
    "labor_cutting_hr": 45,
    "labor_horizonspf20_hr": 50,
    "labor_horizonspf20_setup": 35,
    "press_printsperhour": 600,
    "bindery_morgana_impressionperhour": 750,
    "cutter_sheetsperhour": 15000,
    "horizonspf20_sheetsperhour": 4000,
    "cutterbasefee": 7.5,
    "sheetsturnaround": 2500,
    "backend_maximummarkup": 9,
    "backend_minimummarkup": 1.5,
    "easydiscount_max": 1500,
    "uvcoaterimpressionsperhour": 250,
    "roundcornerperhour": 75,
    "bundlesperhour": 50,
    "non_inventory_fee": 35,
    "bw_discount_rate": 0.3,
    "easy_discount_rate": 0.05,
    "common_discount_max": 1000,
    "bundling_base_fee": 7,
    "proof_hardcopy_cost": 35,
    "proof_digital_cost": 10,
    "sets_surcharge": 20,
    "bleed_minimum": 15,
    "two_staple_threshold": 5.25,
    "sheetsforlowcosthardcopyproof": 1500,
    "art_pagesperhour": 8,
    "art_newdesignmodifier": 0.5,
}

# Size presets: label -> (impositions, bind_edge)
SIZE_PRESETS = {
    "5.5x8.5": (4, 8.5),    # Opens to 8.5x11
    "8.5x11": (2, 11),       # Opens to 11x17
    "8.5x14": (2, 14),       # Opens to 14x17 (legal)
    "6x9": (4, 9),           # Opens to 12x9
    "5x7": (4, 7),           # Opens to 7x10
    "4x6": (8, 6),           # Opens to 8x6
    "4.25x5.5": (8, 5.5),   # Opens to 8.5x5.5
    "3.5x5.5": (8, 5.5),    # Opens to 7x5.5
    "9x12": (2, 12),         # Opens to 18x12
}

# Inventory papers (no surcharge)
INV_NC = [0.001, 0.002, 0.003]
INV_CS = [0.01, 0.02, 0.03, 1.01, 1.02]


def calculate_booklet_price(
    qty: int,
    pages: int,
    inside_paper: dict,
    inside_paper_type: str = "non-cardstock",
    inside_color: str = "full_color",
    cover_mode: str = "same",
    cover_paper: dict | None = None,
    cover_color: str = "full_color",
    size: str = "8.5x11",
    coating_val: int = 0,
    num_sets: int = 1,
    vivid: bool = False,
    bundling_val: int = 0,
    round_corner_val: int = 0,
) -> dict:
    """Calculate the total price for a saddlestitch booklet order.

    Reproduces the calc-preview-test.html calculate() function.
    """
    imp, bind_edge = SIZE_PRESETS.get(size, (2, 11))

    if cover_mode == "same":
        cvr = inside_paper
    else:
        cvr = cover_paper or inside_paper

    # Total sheets calculation
    tQ = qty * num_sets
    tP = pages * num_sets
    tS = (qty * pages / 4) / (imp / 2) * num_sets

    # Markup: logarithmic curve from max (9) down to min (1.5) as volume increases
    if tS > 0:
        dL = (0.6 * math.log(tS)) - 0.1447
    else:
        dL = 0
    mk = max(PCF["backend_maximummarkup"] - dL, PCF["backend_minimummarkup"])

    # Spine cost (used for round corner calc)
    spine = ((((tP / 2) * inside_paper["price"]) + cvr["price"]) * tQ) * 0.10

    # Cardstock inside pages OK (max 24 pages)
    cs_ok = pages <= 24
    cs_inside = inside_paper_type == "cardstock" and cs_ok

    # Cover scoring needed for cardstock covers
    cover_scoring_vals = [0.01, 0.02, 0.03, 1.01, 1.02, 2.21, 2.22, 2.23, 2.24, 2.25]
    cvr_scoring = cvr["val"] in cover_scoring_vals

    # Size-based flags
    is_standard = size in SIZE_PRESETS
    easy_size = is_standard and imp >= 4
    common_size = is_standard and size in ["5.5x8.5", "8.5x11"]

    two_staple_auto = bind_edge > PCF["two_staple_threshold"]

    q100 = qty >= 100
    q250 = qty > 250

    coat_paper = inside_paper if cover_mode == "same" else cvr
    coat_ok = coat_paper.get("coatable", False)

    coating = next((c for c in COATINGS if c["val"] == coating_val), COATINGS[0])

    # ── Cost components ──

    P = {}

    # Inside printing
    if inside_color == "bw":
        P["insidePrint"] = ((PCF["printing_black_cost"] * 2) * tS) * mk
    else:
        P["insidePrint"] = (
            ((PCF["printing_black_cost"] * 2) * tS) * mk
            + ((PCF["printing_fullcolor_cost"] * 2) * tS)
        )

    # Cover printing
    if cover_color == "bw":
        P["coverPrint"] = ((PCF["printing_black_cost"] * tS) * 2) / imp
    else:
        P["coverPrint"] = ((PCF["printing_fullcolor_cost"] * tS) * 2) / imp

    # Paper costs
    P["insidePaper"] = (inside_paper["price"] * tS) * mk
    P["coverPaper"] = ((cvr["price"] * tQ) / imp) * mk

    # Press labor
    P["press"] = (tS / PCF["press_printsperhour"]) * PCF["labor_press_hr"]

    # Cutting
    P["cutting"] = (
        ((tS * imp) / PCF["cutter_sheetsperhour"]) * (PCF["labor_cutting_hr"] + mk)
        + PCF["cutterbasefee"]
    )

    # Cover scoring
    P["scoreCover"] = (
        (tQ / PCF["bindery_morgana_impressionperhour"]) * PCF["labor_bindery_hr"]
        if cvr_scoring else 0
    )

    # Inside scoring (cardstock only)
    P["scoreInsides"] = (
        (((tS * (imp / 2)) - tQ) / PCF["bindery_morgana_impressionperhour"]) * PCF["labor_bindery_hr"]
        if cs_inside else 0
    )

    # Stitching (saddle stitch binding)
    P["stitching"] = (
        (((tS * imp) / 2) / PCF["horizonspf20_sheetsperhour"]) * PCF["labor_horizonspf20_hr"]
        + PCF["labor_horizonspf20_setup"]
    )

    # Two-staple surcharge (auto for large bind edges)
    P["twoStitch"] = math.ceil(P["stitching"] * 1) if (not two_staple_auto and False) else 0

    # Vivid printing
    P["vivid"] = math.ceil(P["press"]) if vivid else 0

    # Coating
    P["coat"] = 0
    if coating["val"] > 0 and coat_ok:
        sc = tQ / imp
        P["coat"] = math.ceil(
            (coating["price"] * sc * mk)
            + (((sc / PCF["uvcoaterimpressionsperhour"]) * PCF["labor_bindery_hr"]) * (coating["price"] * mk * 3))
            + PCF["labor_bindery_hr"]
        )

    # Bundling
    bundling_prices = {0: 500, 750: 25, 1500: 50, 3000: 100}
    bund_price = bundling_prices.get(bundling_val, 500)
    P["bundle"] = (
        math.ceil(((tQ / bund_price) / mk) * (PCF["labor_bindery_hr"] / PCF["bundlesperhour"]))
        + PCF["bundling_base_fee"]
        if bundling_val > 0 and q100 else 0
    )

    # Round corners
    corner_prices = {0: 0, 216: 0.2, 215: 0.15, 108: 0.1, 107: 0.075}
    rc_price = corner_prices.get(round_corner_val, 0)
    P["rc"] = (
        math.floor((spine / rc_price) / PCF["labor_bindery_hr"] * PCF["roundcornerperhour"])
        if rc_price > 0 else 0
    )

    # Sets surcharge
    P["sets"] = (num_sets * PCF["sets_surcharge"]) - PCF["sets_surcharge"]

    # Non-inventory paper surcharge
    is_inv_inside = (
        inside_paper["val"] in INV_CS if inside_paper_type == "cardstock"
        else inside_paper["val"] in INV_NC
    )
    cvr_inv_vals = INV_NC + INV_CS + [1.01, 1.02]
    is_inv = is_inv_inside and cvr["val"] in cvr_inv_vals
    P["nonInv"] = 0 if is_inv else PCF["non_inventory_fee"]

    # Discounts
    P["discBW"] = -(P["press"] * PCF["bw_discount_rate"]) if inside_color == "bw" else 0
    p_comp = P["insidePaper"] + P["coverPaper"] + P["insidePrint"] + P["coverPrint"]
    P["discEasy"] = -min(p_comp * PCF["easy_discount_rate"], PCF["easydiscount_max"]) if easy_size else 0
    P["discCommon"] = (
        -min(P["press"] + P["cutting"] + P["stitching"], PCF["common_discount_max"])
        if common_size and q250 else 0
    )

    total = sum(P.values())
    per_unit = total / tQ if tQ > 0 else 0

    return {
        "total": round(total, 2),
        "per_unit": round(per_unit, 4),
        "qty": tQ,
        "pages": pages,
        "size": size,
        "markup": round(mk, 3),
        "components": {k: round(v, 2) for k, v in P.items()},
        "paper": inside_paper["label"],
    }


def generate_brochure_pricing():
    """Generate standard brochure pricing at common quantity tiers.

    A 'brochure' in PPS terms is a saddlestitch booklet - typically
    a folded sheet (4 or 8 pages) on gloss text stock, full color.
    """
    results = []

    # Standard brochure configurations to price
    configs = [
        # Trifold brochure = 1 sheet folded = ~6 panels = modeled as 4-page booklet on 100lb gloss
        {
            "name": "Trifold Brochure (8.5x11, 100lb Gloss Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "paper_type": "non-cardstock",
            "pages": 4,
            "size": "8.5x11",
            "paper_label": "100lb_gloss",
        },
        # Bifold brochure = 1 sheet folded in half = 4 pages
        {
            "name": "Bifold Brochure (8.5x11, 100lb Gloss Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "paper_type": "non-cardstock",
            "pages": 4,
            "size": "8.5x11",
            "paper_label": "100lb_gloss",
        },
        # Trifold on 80lb Matte
        {
            "name": "Trifold Brochure (8.5x11, 80lb Matte Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "80lb Matte Text" in p["label"]),
            "paper_type": "non-cardstock",
            "pages": 4,
            "size": "8.5x11",
            "paper_label": "matte",
        },
        # 8-page booklet brochure on 100lb Gloss
        {
            "name": "8-Page Booklet (5.5x8.5, 100lb Gloss Text, Full Color)",
            "product": "booklets",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "paper_type": "non-cardstock",
            "pages": 8,
            "size": "5.5x8.5",
            "paper_label": "100lb_gloss",
        },
    ]

    quantities = [25, 50, 100, 250, 500, 1000, 2500]

    for config in configs:
        for qty in quantities:
            result = calculate_booklet_price(
                qty=qty,
                pages=config["pages"],
                inside_paper=config["paper"],
                inside_paper_type=config["paper_type"],
                inside_color="full_color",
                cover_mode="same",
                size=config["size"],
            )
            results.append({
                "config_name": config["name"],
                "product": config["product"],
                "quantity": qty,
                "total_price": result["total"],
                "per_unit": result["per_unit"],
                "pages": config["pages"],
                "size": config["size"],
                "paper_type": config["paper_label"],
                "markup": result["markup"],
                "components": result["components"],
            })

    return results


def export_own_pricing_json(results: list, output_path: Path):
    """Export as PPS own-pricing JSON for import into the tool."""
    own_prices = []
    for r in results:
        own_prices.append({
            "product": r["product"],
            "quantity": r["quantity"],
            "total_price": r["total_price"],
            "paper_type": r["paper_type"],
            "size": r["size"],
            "color_mode": "full_color",
            "sides": "double",
            "finish": "saddle_stitch" if r["pages"] > 4 else "tri_fold",
        })

    with open(output_path, "w") as f:
        json.dump(own_prices, f, indent=2)
    return len(own_prices)


if __name__ == "__main__":
    results = generate_brochure_pricing()

    print(f"\n{'='*80}")
    print("PPS Brochure Pricing (from production calculator)")
    print(f"{'='*80}\n")

    current_config = None
    for r in results:
        if r["config_name"] != current_config:
            current_config = r["config_name"]
            print(f"\n  {current_config}")
            print(f"  {'─'*60}")
            print(f"  {'Qty':>6}  {'Total':>10}  {'Per Unit':>10}  {'Markup':>7}")
            print(f"  {'─'*60}")

        print(f"  {r['quantity']:>6,}  ${r['total_price']:>9.2f}  ${r['per_unit']:>9.4f}  {r['markup']:>6.2f}x")

    # Export for import
    output = Path("data/pps_own_brochure_pricing.json")
    output.parent.mkdir(exist_ok=True)
    count = export_own_pricing_json(results, output)
    print(f"\n  Exported {count} price points to {output}")
