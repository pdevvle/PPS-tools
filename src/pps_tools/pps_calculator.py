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
    "backend_maximummarkup": 8,
    "backend_minimummarkup": 1.5,
    "easydiscount_max": 0,
    "uvcoaterimpressionsperhour": 250,
    "roundcornerperhour": 75,
    "bundlesperhour": 50,
    "non_inventory_fee": 35,
    "bw_discount_rate": 0.3,
    "easy_discount_rate": 0.05,
    "common_discount_max": 0,
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

    # Markup: logarithmic curve from max down to min as volume increases
    if tS > 0:
        dL = (1.1 * math.log(tS)) - 0.1447
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


# ── Brochure & Flat Printing Calculator ──────────────────────────────────
# Ported from wcpa-forms-lists-export brochures and flat printing form.
# This is a DIFFERENT calculator from the booklet one above.
# Brochures are single sheets that get folded (not saddle-stitched).

# Fold types and their panel multiplier (determines cuts needed)
FOLD_TYPES = {
    "flat": {"label": "Flat - No Folding", "panels": 1, "folds": 0},
    "bifold": {"label": "Bifold (2 Panel)", "panels": 2, "folds": 1},
    "trifold": {"label": "Trifold (3 Panel)", "panels": 3, "folds": 2},
    "accordion3": {"label": "Accordion (3 Panel)", "panels": 3, "folds": 2},
    "gatefold": {"label": "Gate Fold (3 Panel)", "panels": 3, "folds": 2},
    "accordion4": {"label": "Accordion (4 Panel)", "panels": 4, "folds": 3},
    "rollfold": {"label": "Roll Fold (4 Panel)", "panels": 4, "folds": 3},
    "doublegate": {"label": "Double Gate Fold (4 Panel)", "panels": 4, "folds": 3},
    "doubleparallel": {"label": "Double Parallel Fold (4 Panel)", "panels": 4, "folds": 3},
}

# Brochure sheet sizes: unfolded size -> (longest, shortest, sheets_per_parent)
# Parent sheet is 13x19 for standard, oversize for larger
BROCHURE_SIZES = {
    "8.5x11": {"longest": 11, "shortest": 8.5, "sheets_per_parent": 2, "label": "8.5x11"},
    "8.5x14": {"longest": 14, "shortest": 8.5, "sheets_per_parent": 1, "label": "8.5x14"},
    "11x17": {"longest": 17, "shortest": 11, "sheets_per_parent": 1, "label": "11x17"},
    "6x9": {"longest": 9, "shortest": 6, "sheets_per_parent": 4, "label": "6x9"},
    "5.5x8.5": {"longest": 8.5, "shortest": 5.5, "sheets_per_parent": 4, "label": "5.5x8.5"},
    "4x6": {"longest": 6, "shortest": 4, "sheets_per_parent": 8, "label": "4x6"},
    "4.25x5.5": {"longest": 5.5, "shortest": 4.25, "sheets_per_parent": 8, "label": "4.25x5.5"},
    "3.5x5": {"longest": 5, "shortest": 3.5, "sheets_per_parent": 8, "label": "3.5x5"},
}

# Additional PCF values for brochure calc (from pps-config-admin.php)
PCF_BROCHURE = {
    **PCF,
    "cutter_stackheight_inches": 3,
    "cutter_cyclesperhour": 200,
    "labor_gw_hour": 35,
    "speed_gwperhr": 750,
    "labor_gw_setup": 15,
    "easydiscount_factor": 0.05,
}


def calculate_brochure_price(
    qty: int,
    paper: dict,
    size: str = "8.5x11",
    fold: str = "trifold",
    front_color: str = "full_color",
    back_color: str = "full_color",
    coating_val: int = 0,
    num_sets: int = 1,
    vivid: bool = False,
) -> dict:
    """Calculate the total price for a brochure/flat print order.

    Ported from the WCPA brochures & flat printing form formulas.
    """
    sz = BROCHURE_SIZES.get(size, BROCHURE_SIZES["8.5x11"])
    fold_info = FOLD_TYPES.get(fold, FOLD_TYPES["trifold"])
    coating = next((c for c in COATINGS if c["val"] == coating_val), COATINGS[0])
    is_flat = fold == "flat"

    tQ = qty * num_sets
    spp = sz["sheets_per_parent"]  # sheets per parent (13x19)
    parent_sheets = math.ceil(tQ / spp)

    # Paper cost: price per parent sheet * number of parent sheets
    # paper["price"] is cost per 13x19 sheet
    paper_cost_raw = paper["price"] * parent_sheets

    # Print cost per side
    front_cost_raw = (
        PCF_BROCHURE["printing_black_cost"] if front_color == "bw"
        else PCF_BROCHURE["printing_fullcolor_cost"]
    ) * parent_sheets

    back_cost_raw = (
        PCF_BROCHURE["printing_black_cost"] if back_color == "bw"
        else PCF_BROCHURE["printing_fullcolor_cost"]
    ) * parent_sheets

    print_cost_raw = front_cost_raw + back_cost_raw

    # Markup calculation (same log curve as booklet calc)
    if parent_sheets > 0:
        dL = (1.1 * math.log(parent_sheets)) - 0.1447
    else:
        dL = 0
    mk = max(PCF_BROCHURE["backend_maximummarkup"] - dL, PCF_BROCHURE["backend_minimummarkup"])

    P = {}

    # Paper + print with markup
    P["paper"] = paper_cost_raw * mk
    P["printing"] = print_cost_raw * mk

    # Press labor
    P["press"] = (parent_sheets / PCF_BROCHURE["press_printsperhour"]) * PCF_BROCHURE["labor_press_hr"]

    # Cutting labor: sheets / stack height -> stacks, stacks / cycles per hour -> hours
    # Number of cuts depends on spp (how many pieces per parent sheet)
    cuts_per_sheet = max(1, spp - 1) + fold_info["folds"]
    stacks = math.ceil(parent_sheets / PCF_BROCHURE["cutter_stackheight_inches"])
    P["cutting"] = (
        ((stacks * cuts_per_sheet) / PCF_BROCHURE["cutter_cyclesperhour"]) * PCF_BROCHURE["labor_cutting_hr"]
        + PCF_BROCHURE["cutterbasefee"]
    )

    # Folding/scoring (bindery) - only if not flat
    if not is_flat:
        P["folding"] = (
            (tQ / PCF_BROCHURE["bindery_morgana_impressionperhour"]) * PCF_BROCHURE["labor_bindery_hr"]
            + (PCF_BROCHURE["labor_bindery_hr"] / 3)  # setup time
        )
    else:
        P["folding"] = 0

    # Vivid enhancement
    P["vivid"] = math.ceil(P["press"]) if vivid else 0

    # Coating
    P["coat"] = 0
    if coating["val"] > 0 and paper.get("coatable", False):
        P["coat"] = math.ceil(
            (coating["price"] * tQ * mk)
            + (((tQ / PCF_BROCHURE["uvcoaterimpressionsperhour"]) * PCF_BROCHURE["labor_bindery_hr"])
               * (coating["price"] * mk * 3))
            + PCF_BROCHURE["labor_bindery_hr"]
        )

    # Non-inventory fee
    is_inv = paper["val"] in INV_NC or paper["val"] in INV_CS
    P["nonInv"] = 0 if is_inv else PCF_BROCHURE["non_inventory_fee"]

    # Sets surcharge
    P["sets"] = (num_sets * PCF_BROCHURE["sets_surcharge"]) - PCF_BROCHURE["sets_surcharge"]

    # Discounts
    # Easy discount for standard sizes (flat gets a smaller discount)
    is_standard = size in BROCHURE_SIZES and spp >= 2
    if is_standard and is_flat:
        P["discEasy"] = -min(
            (P["paper"] + P["printing"]) * PCF_BROCHURE["easydiscount_factor"],
            PCF_BROCHURE["easydiscount_max"] / 10,
        )
    elif is_standard:
        P["discEasy"] = -min(
            P["press"] + P["cutting"] + P["folding"],
            PCF_BROCHURE["easydiscount_max"] / 10,
        )
    else:
        P["discEasy"] = 0

    total = sum(P.values())
    per_unit = total / tQ if tQ > 0 else 0

    return {
        "total": round(total, 2),
        "per_unit": round(per_unit, 4),
        "qty": tQ,
        "size": size,
        "fold": fold_info["label"],
        "markup": round(mk, 3),
        "components": {k: round(v, 2) for k, v in P.items()},
        "paper": paper["label"],
    }


def generate_brochure_pricing():
    """Generate brochure pricing using the brochure & flat printing calculator.

    Uses the WCPA brochures form logic (not the booklet/saddlestitch calc).
    """
    results = []

    configs = [
        {
            "name": "Trifold Brochure (8.5x11, 100lb Gloss Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "fold": "trifold",
            "size": "8.5x11",
            "paper_label": "100lb_gloss",
        },
        {
            "name": "Bifold Brochure (8.5x11, 100lb Gloss Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "fold": "bifold",
            "size": "8.5x11",
            "paper_label": "100lb_gloss",
        },
        {
            "name": "Trifold Brochure (8.5x11, 80lb Matte Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "80lb Matte Text" in p["label"]),
            "fold": "trifold",
            "size": "8.5x11",
            "paper_label": "matte",
        },
        {
            "name": "Flat Print (8.5x11, 100lb Gloss Text, Full Color)",
            "product": "flyers",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "fold": "flat",
            "size": "8.5x11",
            "paper_label": "100lb_gloss",
        },
        {
            "name": "4-Panel Roll Fold (8.5x14, 100lb Gloss Text, Full Color)",
            "product": "brochures",
            "paper": next(p for p in PAPERS_NC if "100lb Gloss Text" in p["label"]),
            "fold": "rollfold",
            "size": "8.5x14",
            "paper_label": "100lb_gloss",
        },
    ]

    quantities = [25, 50, 100, 250, 500, 1000, 2500]

    for config in configs:
        for qty in quantities:
            result = calculate_brochure_price(
                qty=qty,
                paper=config["paper"],
                size=config["size"],
                fold=config["fold"],
            )
            results.append({
                "config_name": config["name"],
                "product": config["product"],
                "quantity": qty,
                "total_price": result["total"],
                "per_unit": result["per_unit"],
                "size": config["size"],
                "fold": result["fold"],
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
            "finish": r.get("fold", "tri_fold"),
        })

    with open(output_path, "w") as f:
        json.dump(own_prices, f, indent=2)
    return len(own_prices)


def get_competitor_prices(product: str) -> dict[int, dict[str, float]]:
    """Fetch competitor prices from the database, keyed by quantity.

    Returns {quantity: {competitor_name: total_price, ...}, ...}
    """
    try:
        from pps_tools.storage.queries import get_latest_prices
    except ImportError:
        return {}

    prices: dict[int, dict[str, float]] = {}
    for pp in get_latest_prices(product=product):
        prices.setdefault(pp.quantity, {})[pp.competitor] = pp.total_price
    return prices


def print_comparison(results: list):
    """Print PPS pricing with competitor comparison for each configuration."""
    # Group results by config
    configs: dict[str, list] = {}
    for r in results:
        configs.setdefault(r["config_name"], []).append(r)

    # Pre-fetch competitor prices for each product type we need
    comp_cache: dict[str, dict[int, dict[str, float]]] = {}
    for r in results:
        prod = r["product"]
        if prod not in comp_cache:
            comp_cache[prod] = get_competitor_prices(prod)

    print(f"\n{'='*100}")
    print("PPS Brochure & Flat Pricing vs Competitors")
    print(f"{'='*100}")

    for config_name, rows in configs.items():
        product = rows[0]["product"]
        comp_by_qty = comp_cache.get(product, {})

        # Collect all competitor names across quantities
        all_competitors = sorted({
            name for qty_prices in comp_by_qty.values() for name in qty_prices
        })

        print(f"\n  {config_name}")
        print(f"  Product category: {product}")

        if all_competitors:
            # Build header
            comp_headers = [f"{c[:10]:>10}" for c in all_competitors]
            header = f"  {'Qty':>6}  {'PPS':>10}  " + "  ".join(comp_headers) + "   Position"
            print(f"  {'─'*len(header)}")
            print(header)
            print(f"  {'─'*len(header)}")

            for r in rows:
                qty = r["quantity"]
                pps = r["total_price"]
                comp_prices = comp_by_qty.get(qty, {})

                # Format competitor columns
                cols = []
                for c in all_competitors:
                    if c in comp_prices:
                        cp = comp_prices[c]
                        cols.append(f"${cp:>8.0f}  ")
                    else:
                        cols.append(f"{'--':>10} ")

                # Determine position
                all_prices = {"PPS": pps}
                all_prices.update(comp_prices)
                ranked = sorted(all_prices.items(), key=lambda x: x[1])
                position = next(i for i, (name, _) in enumerate(ranked, 1) if name == "PPS")
                total = len(ranked)

                if position == 1:
                    pos_str = f"#1 of {total} (cheapest)"
                elif position == total:
                    pos_str = f"#{position} of {total} (most expensive)"
                else:
                    pos_str = f"#{position} of {total}"

                print(f"  {qty:>6,}  ${pps:>9.2f}  " + "".join(cols) + f"  {pos_str}")
        else:
            # No competitor data - just show PPS prices
            print(f"  {'─'*50}")
            print(f"  {'Qty':>6}  {'Total':>10}  {'Per Unit':>10}  {'Markup':>7}")
            print(f"  {'─'*50}")
            for r in rows:
                print(f"  {r['quantity']:>6,}  ${r['total_price']:>9.2f}  ${r['per_unit']:>9.4f}  {r['markup']:>6.2f}x")

    print()


if __name__ == "__main__":
    results = generate_brochure_pricing()
    print_comparison(results)

    # Export for import
    output = Path("data/pps_own_brochure_pricing.json")
    output.parent.mkdir(exist_ok=True)
    count = export_own_pricing_json(results, output)
    print(f"\n  Exported {count} price points to {output}")
