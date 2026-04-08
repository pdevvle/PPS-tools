# Handoff: Push updated calc-brochure.html to priorityprintservice.com

**For whoever is reading this (probably a future Claude session):** The work is done. You just need to transfer one file from this repo into a different repo that the previous session couldn't write to.

## What the user wants

The live brochure calculator at `https://pdevvle.github.io/priorityprintservice.com/calc-brochure.html` should produce prices that are **slightly above every competitor at every quantity tier**. The previous session tuned the markup curve, fixed a formula asymmetry, and removed the $35 baseCost surcharge. The finished HTML file is sitting in this `pps-tools` repo ready to be copied into the `priorityprintservice.com` repo.

## Your job

Copy the file **`data/calc-brochure.html`** from this repo (`pdevvle/PPS-tools`, branch `claude/analyze-competitor-pricing-MQ8QA`) to the path **`calc-brochure.html`** at the root of `pdevvle/priorityprintservice.com` repo, branch **`pps-pricing-config`**, committing on top of whatever is there.

**Important:** Do not modify the content of `data/calc-brochure.html`. It's already complete — the file should be uploaded byte-for-byte.

## How to do it

You most likely have `mcp__github__create_or_update_file` available. Steps:

1. Read the file `data/calc-brochure.html` from this `pps-tools` repo (local path `/home/user/PPS-tools/data/calc-brochure.html` if you're in the same working directory; otherwise fetch it from GitHub via `mcp__github__get_file_contents` with `owner=pdevvle, repo=PPS-tools, path=data/calc-brochure.html, ref=claude/analyze-competitor-pricing-MQ8QA`).

2. Get the current SHA of the destination file via `mcp__github__get_file_contents` with `owner=pdevvle, repo=priorityprintservice.com, path=calc-brochure.html, ref=pps-pricing-config`. You need the SHA for the update call.

3. Upload via `mcp__github__create_or_update_file`:
   - `owner`: `pdevvle`
   - `repo`: `priorityprintservice.com`
   - `branch`: `pps-pricing-config`
   - `path`: `calc-brochure.html`
   - `content`: the full file content from step 1
   - `sha`: the SHA from step 2
   - `message`: something like `Reprice brochure calculator: slightly above all competitors at every tier`

4. Confirm success to the user. The live GitHub Pages site rebuilds automatically within a minute or two.

## If you get an allowlist error

If you see "Access denied: repository pdevvle/priorityprintservice.com is not configured for this session", then **this session also has the restriction**. In that case, tell the user:

> "I'm still blocked by the same restriction the previous chat hit. The file is ready at `data/calc-brochure.html` in pps-tools. To unblock me, you'll need someone with access to the Claude Code session config to add `pdevvle/priorityprintservice.com` to the allowed repositories list. Or I can walk you through the GitHub web editor (3 minutes, no coding)."

## What changed vs. the current live file

Four changes were made to the original `calc-brochure.html` (diff is also available at `data/calc-brochure-markup-update.patch`):

### 1. PCF values (around line 51-52)

```diff
-  backend_maximummarkup:9, backend_minimummarkup:1.5,
-  easydiscount_factor:0.05, easydiscount_max:1500,
+  backend_maximummarkup:15.2, backend_minimummarkup:3.5,
+  easydiscount_factor:0.05, easydiscount_max:0,
```

### 2. Markup curve formula (around line 255)

```diff
-  const dL = 0.7 * Math.log(pressSheets) + 0.5412;
+  const dL = 1.85 * Math.log(pressSheets) - 0.5;
```

### 3. Print markup applied uniformly (around lines 266-279)

The previous code applied markup only to the BW portion of `frontPrint` and not to `backPrint` at all — asymmetric and structurally limited the achievable markup shape. Now `mk` multiplies all printing costs:

```diff
-  // Printing — front has markup on BW base, back does not
+  // Printing — markup applied uniformly to all printing costs
   if (c.frontColor === "color") {
-    P.frontPrint = ((PCF.printing_black_cost * pressSheets) * mk) + (PCF.printing_fullcolor_cost * pressSheets);
+    P.frontPrint = ((PCF.printing_black_cost + PCF.printing_fullcolor_cost) * pressSheets) * mk;
   } else {
     P.frontPrint = (PCF.printing_black_cost * pressSheets) * mk;
   }
   P.backPrint = 0;
   if (sides === 2) {
     if (c.backColor === "color") {
-      P.backPrint = (PCF.printing_black_cost * pressSheets) + (PCF.printing_fullcolor_cost * pressSheets);
+      P.backPrint = ((PCF.printing_black_cost + PCF.printing_fullcolor_cost) * pressSheets) * mk;
     } else {
-      P.backPrint = PCF.printing_black_cost * pressSheets;
+      P.backPrint = (PCF.printing_black_cost * pressSheets) * mk;
     }
   }
```

### 4. Removed baseCost surcharge (around lines 330-333)

The `$35` bindery-hour baseCost block was deleted entirely — the user asked to remove it because it created an awkward floor on small-quantity pricing:

```diff
-  // Minimum base cost
-  P.baseCost = (fold.val !== "flat" || qty <= 250) ? PCF.labor_bindery_hr : 0;
-
   // Artwork
```

All other labor rates, equipment speeds, surcharges, and formulas (cutting, folding, coating, round corner, etc.) are **unchanged** — the user specifically asked that those be preserved.

## Expected prices after the update

For the reference product (8.5×11 trifold brochure, 100lb Gloss Text, full color both sides):

| Qty | New PPS price | Vistaprint (most expensive competitor) | PPS vs Vistaprint |
|-----|---------------|----------------------------------------|-------------------|
| 25 | $49 | $46 | +7% |
| 50 | $73 | $72 | +1% |
| 100 | $114 | $110 | +3% |
| 250 | $212 | $190 | +12% |
| 500 | $339 | $310 | +9% |
| 1,000 | $528 | $520 | +1% |
| 2,500 | $1,110 | $1,050 | +6% |

PPS should sit **+1% to +12% above Vistaprint** at every tier — "slightly above everyone" as requested.

## Files in this repo that are part of this work

- **`data/calc-brochure.html`** — the complete updated file ready to copy to priorityprintservice.com
- **`data/calc-brochure-markup-update.patch`** — unified diff of the 4 changes (for reference or alternative manual apply)
- **`src/pps_tools/pps_calculator.py`** — a separate Python version of the calculator used for sweeps and competitor comparisons. Has its own set of PCF values that produce similar but not identical outputs (different formula constants). **Do not touch this** unless asked.
- **`pricing-comparison.html`** — a browser-based comparison tool that mirrors the Python calculator. **Do not touch this** unless asked.

## Context: why this was needed

The user is the owner of Priority Print Service (priorityprintservice.com). They compared their brochure calculator prices against six online competitors (Vistaprint, GotPrint, UPrinting, PrintPlace, PsPrint, Overnight Prints) and wanted their prices to land **slightly above the most expensive competitor (Vistaprint)** at every volume tier.

The previous session:
1. Identified that the live formula had an asymmetric print markup (only BW got markup)
2. Found the $35 baseCost was creating an artificial floor at small qty
3. Ran simulations across many markup parameters to find values that produce consistently "slightly above" pricing
4. Prepared the updated file but could not push it directly due to MCP repo allowlist restrictions
5. Asked the user for permission to add the target repo to the allowlist, which requires infrastructure-level access the user doesn't have
6. Committed the finished file here as a handoff

## Confirmation the file is correct

If you want to verify the file matches the expected content before uploading, run this check:

```bash
grep -E "backend_maximummarkup|const dL|printing_black_cost.*printing_fullcolor_cost|baseCost" data/calc-brochure.html
```

You should see:
- `backend_maximummarkup:15.2, backend_minimummarkup:3.5,`
- `const dL = 1.85 * Math.log(pressSheets) - 0.5;`
- Uniform print markup lines (both `P.frontPrint` and `P.backPrint` with `* mk`)
- **No** `P.baseCost = ...` line

If that all matches, the file is ready to upload.
