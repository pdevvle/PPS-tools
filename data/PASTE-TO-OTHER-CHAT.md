# Task: Push updated calc-brochure.html to priorityprintservice.com

A previous Claude session prepared an updated `calc-brochure.html` for the user's live brochure calculator but was blocked from pushing it by an MCP allowlist. Your job is to finish the upload.

## What the user wants

The live brochure calculator at `https://pdevvle.github.io/priorityprintservice.com/calc-brochure.html` should produce prices that are **slightly above every competitor at every quantity tier**. The previous session tuned the markup curve, fixed a formula asymmetry, and removed the $35 baseCost surcharge. The finished HTML file is sitting in a separate repo ready to be copied to priorityprintservice.com.

## Your job

Copy the finished file to `calc-brochure.html` at the root of `pdevvle/priorityprintservice.com`, branch `pps-pricing-config`, replacing whatever is there.

**Important:** Do not modify the file content. It's already complete — upload it byte-for-byte.

## Step-by-step instructions

**Step 1 — Fetch the finished file.** It's at this public URL (no auth needed):

```
https://raw.githubusercontent.com/pdevvle/PPS-tools/claude/analyze-competitor-pricing-MQ8QA/data/calc-brochure.html
```

Fetch it via `WebFetch` or a Bash `curl` call. The file is 169KB. You can also try `mcp__github__get_file_contents` with `owner=pdevvle, repo=PPS-tools, path=data/calc-brochure.html, ref=claude/analyze-competitor-pricing-MQ8QA` if you have access to that repo.

**Step 2 — Get the SHA of the current destination file.** Call `mcp__github__get_file_contents` with:

- `owner`: `pdevvle`
- `repo`: `priorityprintservice.com`
- `path`: `calc-brochure.html`
- `ref`: `pps-pricing-config`

Extract the `sha` field from the response.

**Step 3 — Upload the new content.** Call `mcp__github__create_or_update_file` with:

- `owner`: `pdevvle`
- `repo`: `priorityprintservice.com`
- `branch`: `pps-pricing-config`
- `path`: `calc-brochure.html`
- `content`: the full file content from Step 1
- `sha`: the SHA from Step 2
- `message`: `Reprice brochure calculator: slightly above all competitors at every tier`

**Step 4 — Confirm success to the user.** The live GitHub Pages site rebuilds automatically within a minute or two after the commit lands.

## If you get an allowlist error

If you see "Access denied: repository pdevvle/priorityprintservice.com is not configured for this session", tell the user:

> "I'm also blocked by the allowlist restriction. The finished file is at https://raw.githubusercontent.com/pdevvle/PPS-tools/claude/analyze-competitor-pricing-MQ8QA/data/calc-brochure.html. To unblock me, someone with access to the Claude Code session config needs to add `pdevvle/priorityprintservice.com` to the allowed repositories list. Or I can walk you through the GitHub web editor in about 3 minutes, no coding required."

## Verification (optional)

Before uploading, you can sanity-check the file content:

```bash
curl -s https://raw.githubusercontent.com/pdevvle/PPS-tools/claude/analyze-competitor-pricing-MQ8QA/data/calc-brochure.html | grep -E "backend_maximummarkup|const dL|P\.baseCost"
```

You should see:

- `backend_maximummarkup:15.2, backend_minimummarkup:3.5,`
- `const dL = 1.85 * Math.log(pressSheets) - 0.5;`
- **No** `P.baseCost = ...` line at all

## What changed vs. the current live file (for context only — do NOT re-apply manually, the file already has these)

**1. PCF values (line 51-52):**

```diff
-  backend_maximummarkup:9, backend_minimummarkup:1.5,
-  easydiscount_factor:0.05, easydiscount_max:1500,
+  backend_maximummarkup:15.2, backend_minimummarkup:3.5,
+  easydiscount_factor:0.05, easydiscount_max:0,
```

**2. Markup curve formula (line 255):**

```diff
-  const dL = 0.7 * Math.log(pressSheets) + 0.5412;
+  const dL = 1.85 * Math.log(pressSheets) - 0.5;
```

**3. Print markup applied uniformly (lines 266-279):** The old code only applied `mk` to the BW portion of `frontPrint` and not to `backPrint` at all. Now `mk` multiplies all printing costs:

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

**4. Removed baseCost surcharge (lines 330-333):** The `$35` bindery-hour baseCost block was deleted entirely — it was creating an awkward floor on small-quantity pricing:

```diff
-  // Minimum base cost
-  P.baseCost = (fold.val !== "flat" || qty <= 250) ? PCF.labor_bindery_hr : 0;
-
   // Artwork
```

The orphan `{l:"Base Cost",v:P.baseCost,g:"fee"}` reference in the display array at line 436 was also removed.

All other labor rates, equipment speeds, surcharges, and formulas (cutting, folding, coating, round corner, etc.) are **unchanged** — the user specifically asked that those be preserved.

## Expected prices after upload

For 8.5×11 trifold brochure, 100lb Gloss Text, full color both sides:

| Qty | New PPS price | Vistaprint (most expensive competitor) | PPS vs Vistaprint |
|-----|---------------|----------------------------------------|-------------------|
| 25 | $49 | $46 | +7% |
| 50 | $73 | $72 | +1% |
| 100 | $114 | $110 | +3% |
| 250 | $212 | $190 | +12% |
| 500 | $339 | $310 | +9% |
| 1,000 | $528 | $520 | +1% |
| 2,500 | $1,110 | $1,050 | +6% |

PPS should sit +1% to +12% above Vistaprint at every tier — "slightly above everyone" as requested.

## Why this exists

The user is the owner of Priority Print Service. They compared their brochure calculator prices against six online competitors (Vistaprint, GotPrint, UPrinting, PrintPlace, PsPrint, Overnight Prints) and wanted their prices to land slightly above the most expensive one at every volume tier. The previous Claude session did all the analysis and file preparation but was restricted to a different repo by its MCP allowlist, so it couldn't finish the upload. The user is not a developer and asked for the work to be handed off to another chat session that has the right repo access.
