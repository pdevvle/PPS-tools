# PPS Pricing Analysis — Session Summary & Handoff

## Context

This session analyzed and tuned pricing for Priority Print Service (priorityprintservice.com) across two product lines: **brochures** and **booklets**. The goal was to position PPS prices **slightly above all competitors** at every quantity tier.

The PPS-tools repo (`pdevvle/PPS-tools`, branch `claude/analyze-competitor-pricing-MQ8QA`) contains all the work. The live calculators live in a separate repo (`pdevvle/priorityprintservice.com`, branch `pps-pricing-config`).

---

## Brochure Calculator — DONE

### What was accomplished

The brochure calculator (`calc-brochure.html`) was fully tuned. An updated file is ready to push to the live site.

### Key findings

PPS brochure prices were originally way too cheap at small quantities and way too expensive at large quantities. The markup curve was reshaped to land PPS slightly above Vistaprint (the most expensive competitor) at every tier.

### Changes made to calc-brochure.html

Four changes:

**1. PCF values (line 51-52):**
```
backend_maximummarkup: 9 → 15.2
backend_minimummarkup: 1.5 → 3.5
easydiscount_max: 1500 → 0
```

**2. Markup curve formula (line 255):**
```
OLD: const dL = 0.7 * Math.log(pressSheets) + 0.5412;
NEW: const dL = 1.85 * Math.log(pressSheets) - 0.5;
```

**3. Print markup applied uniformly (lines 266-279):**
The old code only applied markup (`mk`) to the BW portion of frontPrint and not to backPrint at all. Now mk multiplies all printing costs uniformly.

**4. Removed $35 baseCost surcharge (lines 330-333):**
The `P.baseCost = (fold.val !== "flat" || qty <= 250) ? PCF.labor_bindery_hr : 0;` block was deleted entirely, along with the orphan `{l:"Base Cost",v:P.baseCost,g:"fee"}` display reference at line 436.

### Resulting brochure prices (8.5×11 trifold, 100lb Gloss, full color both sides)

| Qty | New PPS | Vistaprint | PPS vs VP |
|-----|---------|------------|-----------|
| 25 | $49 | $46 | +7% |
| 50 | $73 | $72 | +1% |
| 100 | $114 | $110 | +3% |
| 250 | $212 | $190 | +12% |
| 500 | $339 | $310 | +9% |
| 1,000 | $528 | $520 | +1% |
| 2,500 | $1,110 | $1,050 | +6% |

### Files in pps-tools repo

- **`data/calc-brochure.html`** — Complete updated file, ready to copy to priorityprintservice.com
- **`data/calc-brochure-markup-update.patch`** — Unified diff of the 4 changes
- **`data/PASTE-TO-OTHER-CHAT.md`** — Self-contained handoff instructions for another Claude session to push the file to the live repo
- **`data/competitor_brochure_pricing.json`** — Competitor brochure prices (6 competitors × 7 qty tiers)

### How to deploy

The updated `data/calc-brochure.html` needs to be copied to `calc-brochure.html` at the root of `pdevvle/priorityprintservice.com`, branch `pps-pricing-config`. The full instructions are in `data/PASTE-TO-OTHER-CHAT.md`. The previous session could not push there due to MCP allowlist restrictions (only `pdevvle/pps-tools` was allowed).

---

## Booklet Calculator — IN PROGRESS

### What was accomplished

Competitor booklet pricing data was generated and committed. Analysis of the current live formula was completed. Markup sweep was run. **The tuning is NOT yet applied** — awaiting direction on approach.

### The live booklet calculator

File: `calc-preview-test.html` on branch `pps-pricing-config` of `pdevvle/priorityprintservice.com`

Current PCF values:
```
backend_maximummarkup: 9
backend_minimummarkup: 1.5
easydiscount_max: 1500
common_discount_max: 1000
```

Current markup formula:
```javascript
const dL = (0.6 * Math.log(tS)) - 0.1447;
const mk = Math.max(PCF.backend_maximummarkup - dL, PCF.backend_minimummarkup);
```

Where `tS = (qty * pages / 4) / (imp / 2)` — total parent sheets, which scales with both quantity AND page count.

### Key formula details

**Sheet calculation:** `tS` for booklets includes page count. An 8.5x11 16-page booklet at 100 qty produces tS=400 parent sheets. A brochure at the same qty produces tS=50 (just qty/imp). This means the markup curve drops MUCH faster for booklets.

**Imposition:**
- 5.5x8.5: imp=4 (4-up, efficient)
- 8.5x11: imp=2 (2-up, uses 2x more paper)

**Print markup asymmetry (same issue as brochure calc):**
- insidePrint: BW portion gets markup, fullcolor addition does NOT
- coverPrint: NO markup at all
- This structurally limits how much the markup curve can influence total price

**Cutting formula quirk:** `((tS * imp) / cutter_sheetsperhour) * (labor_cutting_hr + mk)` — adds mk to the labor rate, so cutting cost increases with markup. This is unusual.

**Two active discounts:**
- `discEasy`: 5% off materials, capped at $1500. Only for 5.5x8.5 (imp >= 4)
- `discCommon`: Subtracts press+cutting+stitching, capped at $1000. Only for qty > 250

### Current PPS booklet prices vs Vistaprint

Using the CURRENT live formula with all discounts active:

**5.5x8.5 (4-up, cheaper):**

| Pages | Qty 25 | Qty 100 | Qty 250 | Qty 500 | Qty 1000 |
|-------|--------|---------|---------|---------|----------|
| 8pp | $70 (+10%) | $141 (+31%) | $271 (+54%) | $384 (+45%) | $718 (+74%) |
| 16pp | $91 (+4%) | $217 (+24%) | $448 (+44%) | $668 (+37%) | $1245 (+58%) |
| 32pp | $131 (-2%) | $361 (+17%) | $782 (+34%) | $1198 (+28%) | $2222 (+44%) |

**8.5x11 (2-up, more expensive):**

| Pages | Qty 25 | Qty 100 | Qty 250 | Qty 500 | Qty 1000 |
|-------|--------|---------|---------|---------|----------|
| 8pp | $97 (+27%) | $239 (+66%) | $498 (+100%) | $781 (+102%) | $1458 (+137%) |
| 16pp | $139 (+24%) | $390 (+58%) | $848 (+85%) | $1360 (+86%) | $2528 (+112%) |
| 32pp | $220 (+19%) | $678 (+49%) | $1509 (+72%) | $2439 (+72%) | $4511 (+92%) |

### The structural problem

Unlike brochures (one size, one sheet), booklets span 2 sizes × 3 page counts with wildly different material bases. A single log markup curve cannot compress all combinations into a tight "+5% above Vistaprint" band.

At 8.5x11 8pp 100qty: raw material cost at the minimum markup floor (mk=1.5) is ~$144 — which already equals Vistaprint's price. Any markup above 1.5 pushes PPS above VP. At small quantities where mk=5-6, PPS is 60-100%+ above VP.

At 5.5x8.5 32pp: 4-up imposition makes materials much cheaper, so PPS naturally lands closer to competitors (+2% to +21% in the sweep).

**Cost breakdown at 8.5x11 8pp 100qty (mk=5.97):**
- Materials with markup: $181 (76%) — raw paper $17 becomes $101 after 5.97x markup
- Labor: $58 (24%) — press $12 + cutting $9 + stitching $38
- Total: $239
- Vistaprint estimate: $144

### Sweep results

Best achievable with uniform print markup and no discounts:

| Config | PPS vs Vistaprint range |
|--------|------------------------|
| 5.5x8.5, 32pp | +2% to +21% (good) |
| 5.5x8.5, 16pp | +13% to +25% (OK) |
| 5.5x8.5, 8pp | +19% to +52% (high) |
| 8.5x11, 32pp | +15% to +66% (wide) |
| 8.5x11, 16pp | +35% to +68% (wide) |
| 8.5x11, 8pp | +39% to +73% (very wide) |

### Options for the user to decide

1. **Use as-is** — PPS is above everyone everywhere, just by bigger margins on 8.5x11 low page counts
2. **Add a size-based adjustment** — 8.5x11 gets a discount factor to bring it closer to competitors
3. **Tune separately** — different markup params for 5.5x8.5 vs 8.5x11
4. **Just tune for 8.5x11** since that's the main booklet product, and let 5.5x8.5 fall where it may

### Files in pps-tools repo

- **`data/competitor_booklet_pricing.json`** — 216 price points: 6 competitors × 2 sizes × 3 page counts × 6 quantities. Estimated from industry knowledge (same methodology as brochure data).

---

## Other changes made during this session

### Brochure cutting formula fix

The brochure cutting formula in `pps_calculator.py` had two bugs:
1. Stack height was treated as 3 inches with parent_sheets divided by 3 (producing hundreds of stacks). Fixed to **250 sheets per lift** (`cutter_stackheight_sheets`).
2. Cuts per stack included fold operations that are already billed in the folding line. Fixed to **spp × 4** (four trim cuts per up-value).

The user confirmed: ~250 sheets per cutter lift, cuts = size yield value × 4, folding NOT counted in cutting.

### Custom size surcharge

A 50% surcharge was added for non-common brochure/booklet sizes. Common sizes:
- Brochures: 4.25x5.5, 5.5x8.5, 8.5x11, 11x17
- Booklets: 4.25x5.5, 5.5x8.5, 8.5x11

Applied after total is computed: `if size not in COMMON: total *= 1.50`

### Markup curve iterations

The brochure markup went through several iterations:
1. Started at mkx=8, coef=1.1 (mid-pack positioning)
2. Moved to mkx=10, coef=0.9 (premium positioning)
3. Settled at mkx=15.8, coef=1.7 in pps_calculator.py (slightly above all)
4. For the live calc-brochure.html: mkx=15.2, coef=1.85, const=-0.5, mkn=3.5 (different formula structure requires different values)

**Important:** The Python calculator (`pps_calculator.py`) and the live HTML calculators use DIFFERENT formula structures with different constants. Values are NOT interchangeable between them.

---

## Competitor data source

All competitor pricing data (brochures and booklets) was **generated from Claude's industry knowledge**, not scraped from live websites. The data was committed by earlier steps in this same session. The network environment blocks all external web requests except GitHub and code registries, so live scraping was not possible.

The pps-tools repo has a full scraping infrastructure (`pps scrape-all`, `pps fetch`, parsers for each competitor) but it requires network access to competitor sites which this environment doesn't have.

---

## Repo structure (key files)

```
pdevvle/PPS-tools (branch: claude/analyze-competitor-pricing-MQ8QA)
├── src/pps_tools/
│   └── pps_calculator.py          # Python pricing engine (booklet + brochure)
├── pricing-comparison.html         # Browser-based brochure comparison tool
├── comp-panel-snippet.js           # React component with competitor data
├── data/
│   ├── calc-brochure.html                    # READY: updated live brochure calc
│   ├── calc-brochure-markup-update.patch     # Diff for brochure calc
│   ├── PASTE-TO-OTHER-CHAT.md                # Handoff: push brochure calc to live
│   ├── competitor_brochure_pricing.json      # Brochure competitor prices
│   ├── competitor_booklet_pricing.json       # Booklet competitor prices
│   └── competitor_pricing.json               # Other product competitor prices
├── config/
│   ├── competitors.yaml
│   └── products.yaml
└── pps_pricing.db                  # SQLite database (price_points, competitors, etc.)
```

```
pdevvle/priorityprintservice.com (branch: pps-pricing-config)
├── calc-brochure.html              # LIVE brochure calc (needs update from data/ above)
├── calc-preview-test.html          # LIVE booklet calc (needs tuning — not yet done)
├── pps-calculators.php             # WordPress plugin (loads calcs into product pages)
└── pps-config-admin.php            # Admin config (PCF defaults, paper defs, etc.)
```

---

## What's left to do

1. **Push brochure calc to live** — `data/calc-brochure.html` → `pdevvle/priorityprintservice.com` branch `pps-pricing-config`. Handoff doc ready at `data/PASTE-TO-OTHER-CHAT.md`.

2. **Decide booklet approach** — User needs to pick from the 4 options above (or suggest something else) before the booklet markup can be finalized.

3. **Tune and prepare booklet calc** — Once approach is decided, run the markup sweep, apply changes to `calc-preview-test.html`, create handoff doc.

4. **Push booklet calc to live** — Same process as brochure: commit updated file to pps-tools, handoff to another session with priorityprintservice.com access.
