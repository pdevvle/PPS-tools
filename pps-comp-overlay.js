/**
 * PPS Competitor Comparison Overlay
 *
 * Drop-in script for priorityprintservice.com product pages.
 * Activated by typing a secret code into the Set 1 job name field.
 * Shows competitor pricing for the same configuration.
 *
 * Installation: Add via theme custom JS, a snippet plugin (e.g. WPCode),
 * or enqueue in pps-calculators.php.
 *
 * Usage: Type the activation code into the "Job Name / PO#" field.
 * The comparison panel appears below the price. Clear the field to hide it.
 */
(function () {
  'use strict';

  // ── CONFIG ──────────────────────────────────────────────────────────────
  // Change this to whatever secret code you want. Leave empty to disable.
  const ACTIVATION_CODE = '';

  // ── COMPETITOR PRICE DATA ──────────────────────────────────────────────
  // Keyed by product slug → quantity → {competitor: price}
  // Update this when you run new scrapes.
  const COMP = {
    brochures: {
      25:   {gotprint:32, overnightprints:40, printplace:35, psprint:42, uprinting:38, vistaprint:46},
      50:   {gotprint:42, overnightprints:55, printplace:48, psprint:58, uprinting:50, vistaprint:72},
      100:  {gotprint:62, overnightprints:78, printplace:68, psprint:82, uprinting:72, vistaprint:110},
      250:  {gotprint:100, overnightprints:135, printplace:115, psprint:145, uprinting:125, vistaprint:190},
      500:  {gotprint:160, overnightprints:210, printplace:180, psprint:230, uprinting:195, vistaprint:310},
      1000: {gotprint:270, overnightprints:360, printplace:310, psprint:400, uprinting:340, vistaprint:520},
      2500: {gotprint:540, overnightprints:730, printplace:620, psprint:810, uprinting:690, vistaprint:1050},
    },
    booklets: {
      25:   {gotprint:32, overnightprints:40, printplace:35, psprint:42, uprinting:38, vistaprint:46},
      50:   {gotprint:42, overnightprints:55, printplace:48, psprint:58, uprinting:50, vistaprint:72},
      100:  {gotprint:62, overnightprints:78, printplace:68, psprint:82, uprinting:72, vistaprint:110},
      250:  {gotprint:100, overnightprints:135, printplace:115, psprint:145, uprinting:125, vistaprint:190},
      500:  {gotprint:160, overnightprints:210, printplace:180, psprint:230, uprinting:195, vistaprint:310},
      1000: {gotprint:270, overnightprints:360, printplace:310, psprint:400, uprinting:340, vistaprint:520},
      2500: {gotprint:540, overnightprints:730, printplace:620, psprint:810, uprinting:690, vistaprint:1050},
    },
    flyers: {
      100:  {gotprint:18, printplace:20, uprinting:19, vistaprint:24},
      250:  {gotprint:28, printplace:32, uprinting:30, vistaprint:40},
      500:  {gotprint:40, printplace:45, uprinting:42, vistaprint:60},
      1000: {gotprint:60, printplace:65, uprinting:62, vistaprint:90},
      5000: {gotprint:180, printplace:200, uprinting:190, vistaprint:250},
    },
    business_cards: {
      50:   {moo:20, gotprint:8, overnightprints:15, printplace:10, psprint:18, uprinting:12, vistaprint:20},
      100:  {moo:30, gotprint:10, overnightprints:18, printplace:14, psprint:22, uprinting:16, vistaprint:15},
      250:  {moo:50, gotprint:15, overnightprints:28, printplace:22, psprint:35, uprinting:25, vistaprint:22},
      500:  {moo:85, gotprint:22, overnightprints:40, printplace:32, psprint:50, uprinting:36, vistaprint:30},
      1000: {moo:140, gotprint:30, overnightprints:55, printplace:45, psprint:70, uprinting:50, vistaprint:42},
      2500: {moo:300, gotprint:55, overnightprints:100, printplace:80, psprint:120, uprinting:90, vistaprint:75},
    },
    postcards: {
      100:  {gotprint:22, printplace:25, vistaprint:30},
      250:  {gotprint:35, printplace:40, vistaprint:48},
      500:  {gotprint:50, printplace:58, vistaprint:72},
      1000: {gotprint:75, printplace:85, vistaprint:110},
    },
  };

  // ── PRODUCT DETECTION ──────────────────────────────────────────────────
  // Maps URL slugs to COMP keys
  const SLUG_MAP = {
    'brochures-flat-printing': 'brochures',
    'brochures': 'brochures',
    'booklets': 'booklets',
    'saddle-stitch-booklets': 'booklets',
    'saddlestitch-booklets': 'booklets',
    'flyers': 'flyers',
    'flat-printing': 'flyers',
    'business-cards': 'business_cards',
    'postcards': 'postcards',
    'post-cards': 'postcards',
  };

  function detectProduct() {
    const path = window.location.pathname.replace(/\/$/, '');
    const slug = path.split('/').pop();
    return SLUG_MAP[slug] || null;
  }

  // ── QUANTITY MATCHING ──────────────────────────────────────────────────
  // Find the closest quantity tier (exact match or nearest lower)
  function matchQuantity(qty, available) {
    const tiers = Object.keys(available).map(Number).sort((a, b) => a - b);
    // Exact match first
    if (tiers.includes(qty)) return qty;
    // Nearest lower tier
    const lower = tiers.filter(t => t <= qty);
    if (lower.length) return lower[lower.length - 1];
    // Nearest higher if no lower
    return tiers[0] || null;
  }

  // ── DOM HELPERS ────────────────────────────────────────────────────────

  function findCalcRoot() {
    return document.getElementById('pps-calculator-wrap') ||
           document.getElementById('pps-calculator-root');
  }

  // Find the job name input (first text input whose placeholder or
  // preceding label mentions "job name" or "PO")
  function findJobNameInput() {
    const root = findCalcRoot();
    if (!root) return null;
    const inputs = root.querySelectorAll('input[type="text"], input:not([type])');
    for (const inp of inputs) {
      const ph = (inp.placeholder || '').toLowerCase();
      const lbl = (inp.getAttribute('aria-label') || '').toLowerCase();
      // Check preceding label or sibling text
      const parent = inp.closest('label, div, span');
      const parentText = parent ? parent.textContent.toLowerCase() : '';
      if (ph.includes('job name') || ph.includes('po#') || ph.includes('po #') ||
          lbl.includes('job name') ||
          parentText.includes('job name') || parentText.includes('po#')) {
        return inp;
      }
    }
    // Fallback: first text input in "Set 1" area
    for (const inp of inputs) {
      const parentText = (inp.closest('div')?.textContent || '').toLowerCase();
      if (parentText.includes('set 1') && !parentText.includes('set 2')) {
        return inp;
      }
    }
    return inputs[0] || null;
  }

  // Read the current quantity from the calculator
  function readQuantity() {
    const root = findCalcRoot();
    if (!root) return null;
    // Look for number inputs
    const numInputs = root.querySelectorAll('input[type="number"]');
    for (const inp of numInputs) {
      const parent = inp.closest('label, div');
      const text = parent ? parent.textContent.toLowerCase() : '';
      if (text.includes('quantity') || text.includes('qty')) {
        const val = parseInt(inp.value, 10);
        if (val > 0) return val;
      }
    }
    // Fallback: first number input with a reasonable value
    for (const inp of numInputs) {
      const val = parseInt(inp.value, 10);
      if (val > 0 && val < 100000) return val;
    }
    return null;
  }

  // Read the current PPS total price from the calculator
  function readPPSTotal() {
    const root = findCalcRoot();
    if (!root) return null;
    // Look for elements showing a dollar amount that looks like a total
    // The calc typically shows "Grand Total" or just a large dollar figure
    const allText = root.querySelectorAll('*');
    let bestPrice = null;
    for (const el of allText) {
      if (el.children.length > 0) continue; // leaf nodes only
      const text = el.textContent.trim();
      const match = text.match(/^\$\s?([\d,]+\.?\d{0,2})$/);
      if (match) {
        const price = parseFloat(match[1].replace(/,/g, ''));
        // The grand total is typically the largest dollar amount on the page
        if (price > 0 && (bestPrice === null || price > bestPrice)) {
          // Check if this is near a "total" label
          const parentText = (el.closest('div')?.textContent || '').toLowerCase();
          if (parentText.includes('total') || parentText.includes('grand')) {
            bestPrice = price;
          }
        }
      }
    }
    // If we didn't find one near "total", take the largest
    if (bestPrice === null) {
      for (const el of allText) {
        if (el.children.length > 0) continue;
        const match = el.textContent.trim().match(/^\$\s?([\d,]+\.?\d{0,2})$/);
        if (match) {
          const price = parseFloat(match[1].replace(/,/g, ''));
          if (price > 10 && (bestPrice === null || price > bestPrice)) {
            bestPrice = price;
          }
        }
      }
    }
    return bestPrice;
  }

  // ── COMPARISON PANEL ───────────────────────────────────────────────────

  let panel = null;

  function createPanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'pps-comp-overlay';
    panel.innerHTML = '<div class="pps-comp-inner"></div>';

    const style = document.createElement('style');
    style.textContent = `
      #pps-comp-overlay {
        margin: 16px 0;
        border: 2px solid #2563eb;
        border-radius: 10px;
        background: #f0f5ff;
        padding: 16px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 13px;
        display: none;
      }
      #pps-comp-overlay .pps-comp-header {
        font-size: 14px;
        font-weight: 700;
        color: #1e40af;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      #pps-comp-overlay .pps-comp-header span {
        font-size: 11px;
        font-weight: 400;
        color: #6b7280;
      }
      #pps-comp-overlay table {
        width: 100%;
        border-collapse: collapse;
        background: #fff;
        border-radius: 6px;
        overflow: hidden;
      }
      #pps-comp-overlay th {
        text-align: left;
        padding: 6px 10px;
        background: #e0e7ff;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        color: #4338ca;
        white-space: nowrap;
      }
      #pps-comp-overlay td {
        padding: 6px 10px;
        border-bottom: 1px solid #f0f0f0;
        white-space: nowrap;
      }
      #pps-comp-overlay .comp-price { text-align: right; font-variant-numeric: tabular-nums; }
      #pps-comp-overlay .comp-pps { font-weight: 700; color: #2563eb; background: #eff6ff; }
      #pps-comp-overlay .comp-cheaper { color: #dc2626; }
      #pps-comp-overlay .comp-more { color: #059669; }
      #pps-comp-overlay .comp-diff { font-size: 11px; margin-left: 4px; }
      #pps-comp-overlay .comp-position {
        margin-top: 10px;
        padding: 8px 12px;
        border-radius: 6px;
        font-weight: 600;
        text-align: center;
        font-size: 13px;
      }
      #pps-comp-overlay .pos-winning { background: #d1fae5; color: #065f46; }
      #pps-comp-overlay .pos-losing { background: #fee2e2; color: #991b1b; }
      #pps-comp-overlay .pos-mid { background: #fef3c7; color: #92400e; }
      #pps-comp-overlay .comp-note {
        margin-top: 8px;
        font-size: 11px;
        color: #9ca3af;
        text-align: center;
      }
    `;
    document.head.appendChild(style);

    // Insert after the calculator
    const root = findCalcRoot();
    if (root) {
      root.parentNode.insertBefore(panel, root.nextSibling);
    } else {
      document.body.appendChild(panel);
    }
    return panel;
  }

  function updatePanel() {
    const product = detectProduct();
    if (!product || !COMP[product]) {
      hidePanel();
      return;
    }

    const ppsTotal = readPPSTotal();
    const qty = readQuantity();
    if (!ppsTotal || !qty) return;

    const compData = COMP[product];
    const matchedQty = matchQuantity(qty, compData);
    if (!matchedQty) return;

    const competitors = compData[matchedQty];
    if (!competitors || Object.keys(competitors).length === 0) return;

    const p = createPanel();
    const inner = p.querySelector('.pps-comp-inner');

    // Build ranking
    const all = { PPS: ppsTotal, ...competitors };
    const ranked = Object.entries(all).sort((a, b) => a[1] - b[1]);
    const ppsRank = ranked.findIndex(([n]) => n === 'PPS') + 1;
    const total = ranked.length;

    // Build table rows
    let rows = '';
    for (const [name, price] of ranked) {
      const isPPS = name === 'PPS';
      const diff = ((price - ppsTotal) / ppsTotal * 100);
      let diffStr = '';
      let cls = '';

      if (isPPS) {
        cls = 'comp-pps';
      } else if (diff < 0) {
        cls = 'comp-cheaper';
        diffStr = `<span class="comp-diff">(${diff.toFixed(0)}%)</span>`;
      } else if (diff > 0) {
        cls = 'comp-more';
        diffStr = `<span class="comp-diff">(+${diff.toFixed(0)}%)</span>`;
      }

      const displayName = isPPS ? 'PPS (You)' : name.charAt(0).toUpperCase() + name.slice(1);
      rows += `<tr class="${cls}">
        <td>${displayName}</td>
        <td class="comp-price">$${price.toFixed(2)} ${diffStr}</td>
      </tr>`;
    }

    // Position summary
    let posClass, posText;
    if (ppsRank === 1) {
      posClass = 'pos-winning';
      posText = `You're the cheapest! #1 of ${total}`;
    } else if (ppsRank === total) {
      posClass = 'pos-losing';
      posText = `Most expensive — #${ppsRank} of ${total}`;
    } else {
      posClass = 'pos-mid';
      posText = `#${ppsRank} of ${total} — ${ppsRank - 1} competitor(s) cheaper`;
    }

    const qtyNote = matchedQty !== qty
      ? `Showing competitor prices for ${matchedQty.toLocaleString()} (closest to ${qty.toLocaleString()})`
      : `Quantity: ${qty.toLocaleString()}`;

    inner.innerHTML = `
      <div class="pps-comp-header">
        Competitor Comparison
        <span>${qtyNote}</span>
      </div>
      <table>
        <thead><tr><th>Company</th><th class="comp-price">Total Price</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="comp-position ${posClass}">${posText}</div>
      <div class="comp-note">Competitor prices are for standard specs at this quantity tier. Your actual config may differ.</div>
    `;

    p.style.display = 'block';
  }

  function hidePanel() {
    if (panel) panel.style.display = 'none';
  }

  // ── ACTIVATION LOGIC ───────────────────────────────────────────────────

  let activated = false;

  function checkActivation(inputValue) {
    if (!ACTIVATION_CODE) {
      // No code set — feature disabled until configured
      return false;
    }
    return inputValue.trim().toLowerCase() === ACTIVATION_CODE.toLowerCase();
  }

  function startWatching() {
    if (activated) return;
    activated = true;
    updatePanel();

    // Watch for calculator changes (quantity, options, etc.)
    const root = findCalcRoot();
    if (root) {
      const observer = new MutationObserver(() => {
        if (activated) updatePanel();
      });
      observer.observe(root, { childList: true, subtree: true, characterData: true });
    }
  }

  function stopWatching() {
    activated = false;
    hidePanel();
  }

  // ── INIT ───────────────────────────────────────────────────────────────

  function init() {
    // Only run on product pages with a calculator
    if (!findCalcRoot()) return;
    if (!detectProduct()) return;

    // If no activation code is set, don't do anything
    if (!ACTIVATION_CODE) return;

    // Poll for the job name input (React may not have rendered yet)
    let attempts = 0;
    const poll = setInterval(() => {
      attempts++;
      const jobInput = findJobNameInput();
      if (jobInput) {
        clearInterval(poll);
        // Watch for the activation code
        jobInput.addEventListener('input', function () {
          if (checkActivation(this.value)) {
            startWatching();
          } else {
            stopWatching();
          }
        });
        // Also check on blur in case React batches updates
        jobInput.addEventListener('change', function () {
          if (checkActivation(this.value)) {
            startWatching();
          } else {
            stopWatching();
          }
        });
      }
      if (attempts > 50) clearInterval(poll); // give up after ~10s
    }, 200);
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
