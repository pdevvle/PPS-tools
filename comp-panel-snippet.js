/**
 * PPS Competitor Comparison Panel — paste into calc-preview-test.html
 *
 * HOW TO ADD:
 *
 * 1. Paste this entire block into calc-preview-test.html, ABOVE the
 *    Panel component definition.
 *
 * 2. Inside the Panel component, after the </details> closing tag
 *    (the "Line Items" section), add this one line:
 *
 *      <CompPanel total={total} qty={tQ} product="booklets" />
 *
 *    That's it. The comparison appears below the line items.
 *
 * To add to a brochure calculator later, use product="brochures"
 * or product="flyers" instead.
 */

// ── Competitor price data (update when you run new scrapes) ──────────
const COMP_DATA = {
  booklets: {
    spec: "8.5x11, 100lb gloss text, full color both sides, saddle-stitched",
    tiers: {
      25:   {gotprint:32, overnightprints:40, printplace:35, psprint:42, uprinting:38, vistaprint:46},
      50:   {gotprint:42, overnightprints:55, printplace:48, psprint:58, uprinting:50, vistaprint:72},
      100:  {gotprint:62, overnightprints:78, printplace:68, psprint:82, uprinting:72, vistaprint:110},
      250:  {gotprint:100, overnightprints:135, printplace:115, psprint:145, uprinting:125, vistaprint:190},
      500:  {gotprint:160, overnightprints:210, printplace:180, psprint:230, uprinting:195, vistaprint:310},
      1000: {gotprint:270, overnightprints:360, printplace:310, psprint:400, uprinting:340, vistaprint:520},
      2500: {gotprint:540, overnightprints:730, printplace:620, psprint:810, uprinting:690, vistaprint:1050},
    }
  },
  brochures: {
    spec: "8.5x11, 100lb gloss text, full color both sides, trifold",
    tiers: {
      25:   {gotprint:32, overnightprints:40, printplace:35, psprint:42, uprinting:38, vistaprint:46},
      50:   {gotprint:42, overnightprints:55, printplace:48, psprint:58, uprinting:50, vistaprint:72},
      100:  {gotprint:62, overnightprints:78, printplace:68, psprint:82, uprinting:72, vistaprint:110},
      250:  {gotprint:100, overnightprints:135, printplace:115, psprint:145, uprinting:125, vistaprint:190},
      500:  {gotprint:160, overnightprints:210, printplace:180, psprint:230, uprinting:195, vistaprint:310},
      1000: {gotprint:270, overnightprints:360, printplace:310, psprint:400, uprinting:340, vistaprint:520},
      2500: {gotprint:540, overnightprints:730, printplace:620, psprint:810, uprinting:690, vistaprint:1050},
    }
  },
  flyers: {
    spec: "8.5x11, 100lb gloss text, full color, single-sided",
    tiers: {
      100:  {gotprint:18, printplace:20, uprinting:19, vistaprint:24},
      250:  {gotprint:28, printplace:32, uprinting:30, vistaprint:40},
      500:  {gotprint:40, printplace:45, uprinting:42, vistaprint:60},
      1000: {gotprint:60, printplace:65, uprinting:62, vistaprint:90},
      5000: {gotprint:180, printplace:200, uprinting:190, vistaprint:250},
    }
  },
  business_cards: {
    spec: "3.5x2, 14pt cardstock, full color both sides",
    tiers: {
      50:   {moo:20, gotprint:8, overnightprints:15, printplace:10, psprint:18, uprinting:12, vistaprint:20},
      100:  {moo:30, gotprint:10, overnightprints:18, printplace:14, psprint:22, uprinting:16, vistaprint:15},
      250:  {moo:50, gotprint:15, overnightprints:28, printplace:22, psprint:35, uprinting:25, vistaprint:22},
      500:  {moo:85, gotprint:22, overnightprints:40, printplace:32, psprint:50, uprinting:36, vistaprint:30},
      1000: {moo:140, gotprint:30, overnightprints:55, printplace:45, psprint:70, uprinting:50, vistaprint:42},
      2500: {moo:300, gotprint:55, overnightprints:100, printplace:80, psprint:120, uprinting:90, vistaprint:75},
    }
  },
  postcards: {
    spec: "4x6, 14pt cardstock, full color both sides",
    tiers: {
      100:  {gotprint:22, printplace:25, vistaprint:30},
      250:  {gotprint:35, printplace:40, vistaprint:48},
      500:  {gotprint:50, printplace:58, vistaprint:72},
      1000: {gotprint:75, printplace:85, vistaprint:110},
    }
  },
};

// ── CompPanel React component ────────────────────────────────────────
function CompPanel({total, qty, product}) {
  if (!total || total <= 0 || !qty || qty <= 0) return null;
  const block = COMP_DATA[product];
  if (!block) return null;

  const tiers = block.tiers;
  const tierKeys = Object.keys(tiers).map(Number).sort((a,b) => a - b);

  // Match to closest quantity tier
  let matched = tierKeys[0];
  for (const t of tierKeys) { if (t <= qty) matched = t; }
  if (!tierKeys.includes(qty)) {
    // If exact qty not in tiers, find closest
    const exact = tierKeys.find(t => t === qty);
    if (exact) matched = exact;
  }

  const comps = tiers[matched];
  if (!comps || Object.keys(comps).length === 0) return null;

  // Build ranked list
  const all = [{name: "PPS (You)", price: total, isPPS: true}];
  Object.entries(comps).forEach(([name, price]) => {
    const display = name.charAt(0).toUpperCase() + name.slice(1).replace(/prints$/, "prints");
    all.push({name: display, price, isPPS: false});
  });
  all.sort((a, b) => a.price - b.price);

  const ppsRank = all.findIndex(a => a.isPPS) + 1;
  const maxPrice = Math.max(...all.map(a => a.price));

  // Colors
  const green = "#059669";
  const red = "#dc2626";
  const blue = "#2563eb";
  const amber = "#d97706";
  const light = "#9ca3af";

  let badge, badgeBg, badgeColor;
  if (ppsRank === 1) { badge = "Cheapest"; badgeBg = "#d1fae5"; badgeColor = "#065f46"; }
  else if (ppsRank === all.length) { badge = "#" + ppsRank + " of " + all.length; badgeBg = "#fee2e2"; badgeColor = "#991b1b"; }
  else { badge = "#" + ppsRank + " of " + all.length; badgeBg = "#fef3c7"; badgeColor = "#92400e"; }

  const qtyNote = matched !== qty
    ? "Competitor prices for " + matched.toLocaleString() + " qty (closest to " + qty.toLocaleString() + ")"
    : null;

  return React.createElement("div", {style: {borderTop: "1px solid #e5e7eb", padding: "14px 18px"}},
    // Header
    React.createElement("div", {style: {display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10}},
      React.createElement("div", {style: {fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: light}}, "Competitor Comparison"),
      React.createElement("span", {style: {fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, background: badgeBg, color: badgeColor}}, badge)
    ),
    // Bars
    ...all.map((a, i) => {
      const pct = (a.price / maxPrice * 100);
      const diff = ((a.price - total) / total * 100);
      let barColor, diffColor, diffText;
      if (a.isPPS) { barColor = blue; diffColor = blue; diffText = "you"; }
      else if (diff < 0) { barColor = red; diffColor = red; diffText = diff.toFixed(0) + "%"; }
      else { barColor = green; diffColor = green; diffText = "+" + diff.toFixed(0) + "%"; }

      return React.createElement("div", {key: i, style: {display: "flex", alignItems: "center", padding: "3px 0", gap: 6}},
        React.createElement("span", {style: {width: 18, fontSize: 10, fontWeight: 700, color: light, textAlign: "center"}}, i + 1),
        React.createElement("span", {style: {width: 90, fontSize: 11.5, fontWeight: a.isPPS ? 700 : 400, color: a.isPPS ? blue : "#555", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}, a.name),
        React.createElement("div", {style: {flex: 1, height: 6, background: "#f3f4f6", borderRadius: 3, overflow: "hidden"}},
          React.createElement("div", {style: {width: pct + "%", height: "100%", background: barColor, borderRadius: 3, transition: "width 0.3s"}})
        ),
        React.createElement("span", {style: {width: 55, fontSize: 11.5, fontWeight: 600, textAlign: "right", fontVariantNumeric: "tabular-nums"}}, "$" + a.price.toFixed(2)),
        React.createElement("span", {style: {width: 38, fontSize: 10, textAlign: "right", color: diffColor, fontWeight: 600}}, diffText)
      );
    }),
    // Footnote
    React.createElement("div", {style: {marginTop: 8, fontSize: 9.5, color: "#c0c0c0", lineHeight: 1.4}},
      qtyNote && React.createElement("div", null, qtyNote),
      "Baseline: " + block.spec
    )
  );
}
