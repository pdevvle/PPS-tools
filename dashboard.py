#!/usr/bin/env python3
"""PPS Competitor Pricing Dashboard — double-click to open in your browser.

No terminal needed. Just run this file and your browser opens automatically.
Click buttons to scrape competitor prices and export for your calculator.
"""

import json
import os
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

# Ensure pps_tools is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

PORT = 8787
HOST = "127.0.0.1"


def get_db_status():
    """Get current database status and latest prices."""
    try:
        from pps_tools.storage.database import get_connection
        with get_connection() as conn:
            # Last scrape time
            row = conn.execute(
                "SELECT MAX(finished_at) as last FROM scrape_runs WHERE status = 'success'"
            ).fetchone()
            last_scrape = row["last"] if row and row["last"] else "Never"

            # Price counts per product
            products = conn.execute("""
                SELECT p.name, p.display_name, COUNT(DISTINCT pp.quantity) as tiers,
                       COUNT(DISTINCT c.name) as competitors,
                       MAX(pp.scraped_at) as last_updated
                FROM price_points pp
                JOIN products p ON pp.product_id = p.id
                JOIN competitors c ON pp.competitor_id = c.id
                WHERE pp.scraped_at = (
                    SELECT MAX(pp2.scraped_at)
                    FROM price_points pp2
                    WHERE pp2.competitor_id = pp.competitor_id
                      AND pp2.product_id = pp.product_id
                      AND pp2.quantity = pp.quantity
                )
                GROUP BY p.name
                ORDER BY p.display_name
            """).fetchall()

            product_list = [dict(r) for r in products]

            # Total records
            total = conn.execute("SELECT COUNT(*) as c FROM price_points").fetchone()["c"]

            return {
                "ok": True,
                "last_scrape": last_scrape,
                "products": product_list,
                "total_records": total,
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_price_table(product):
    """Get competitor prices for a specific product as a table."""
    try:
        from pps_tools.storage.queries import get_latest_prices
        points = get_latest_prices(product=product)

        # Group: qty -> {competitor: price}
        table = {}
        competitors = set()
        for p in points:
            table.setdefault(p.quantity, {})[p.competitor] = p.total_price
            competitors.add(p.competitor)

        return {
            "ok": True,
            "product": product,
            "competitors": sorted(competitors),
            "tiers": {qty: prices for qty, prices in sorted(table.items())},
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_scrape():
    """Run the scraper across all competitors."""
    try:
        from pps_tools.scraping.fetcher import Fetcher
        from pps_tools.scraping.parsers import get_parser_for_url
        from pps_tools.storage.database import get_connection
        from pps_tools.storage.queries import save_price_points

        fetcher = Fetcher()
        results = []

        with get_connection() as conn:
            rows = conn.execute("""
                SELECT pu.url, pu.id as url_id, pu.is_dynamic,
                       c.name as competitor_name, c.id as competitor_id,
                       p.name as product_name, p.id as product_id
                FROM pricing_urls pu
                JOIN competitors c ON pu.competitor_id = c.id
                JOIN products p ON pu.product_id = p.id
                WHERE pu.is_active = 1
                ORDER BY c.name, p.name
            """).fetchall()

        total_points = 0
        for row in rows:
            if row["is_dynamic"]:
                results.append({
                    "competitor": row["competitor_name"],
                    "product": row["product_name"],
                    "status": "skipped",
                    "reason": "Requires JavaScript",
                    "points": 0,
                })
                continue

            try:
                result = fetcher.fetch(row["url"])
                if not result.success:
                    results.append({
                        "competitor": row["competitor_name"],
                        "product": row["product_name"],
                        "status": "failed",
                        "reason": result.error or "Unknown error",
                        "points": 0,
                    })
                    continue

                parser = get_parser_for_url(row["url"], result.html)
                if not parser:
                    results.append({
                        "competitor": row["competitor_name"],
                        "product": row["product_name"],
                        "status": "failed",
                        "reason": "No parser found",
                        "points": 0,
                    })
                    continue

                points = parser.parse(row["url"], result.html, row["product_name"])
                saved = save_price_points(points) if points else 0
                total_points += saved

                results.append({
                    "competitor": row["competitor_name"],
                    "product": row["product_name"],
                    "status": "success" if saved > 0 else "empty",
                    "points": saved,
                })

                # Update last_checked
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE pricing_urls SET last_checked = datetime('now') WHERE id = ?",
                        (row["url_id"],),
                    )
            except Exception as e:
                results.append({
                    "competitor": row["competitor_name"],
                    "product": row["product_name"],
                    "status": "error",
                    "reason": str(e),
                    "points": 0,
                })

        return {"ok": True, "results": results, "total_points": total_points}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def export_js():
    """Export competitor prices as JavaScript snippet."""
    try:
        from pps_tools.commands.export_comp_js import build_comp_data, render_js
        from pps_tools.storage.queries import get_latest_prices
        from pps_tools.utils.config import get_products

        points = get_latest_prices()
        if not points:
            return {"ok": False, "error": "No pricing data in database. Run a scrape first."}

        products_config = get_products()
        comp_data = build_comp_data(points, products_config)
        js_output = render_js(comp_data)

        # Also save to file
        out_path = Path(__file__).resolve().parent / "data" / "comp-data.js"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(js_output)

        return {"ok": True, "js": js_output, "saved_to": str(out_path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── HTML UI ───────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PPS Competitor Pricing</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #333; }
  .header { background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%); color: #fff; padding: 20px 30px; }
  .header h1 { font-size: 20px; font-weight: 700; }
  .header p { font-size: 12px; opacity: 0.7; margin-top: 4px; }
  .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
  .card { background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px; overflow: hidden; }
  .card-header { padding: 14px 20px; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
  .card-header h2 { font-size: 14px; font-weight: 600; color: #555; }
  .card-body { padding: 16px 20px; }
  .btn { border: none; padding: 8px 18px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
  .btn-blue { background: #2563eb; color: #fff; }
  .btn-blue:hover { background: #1d4ed8; }
  .btn-green { background: #059669; color: #fff; }
  .btn-green:hover { background: #047857; }
  .btn-outline { background: #fff; color: #555; border: 1px solid #ddd; }
  .btn-outline:hover { background: #f9fafb; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .status-bar { display: flex; gap: 24px; flex-wrap: wrap; }
  .stat { text-align: center; }
  .stat-val { font-size: 24px; font-weight: 700; color: #2563eb; }
  .stat-label { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.3px; }
  .product-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
  .product-tile { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; cursor: pointer; transition: all 0.15s; }
  .product-tile:hover { border-color: #2563eb; background: #eff6ff; }
  .product-tile.active { border-color: #2563eb; background: #dbeafe; }
  .product-tile h3 { font-size: 13px; font-weight: 600; }
  .product-tile .meta { font-size: 11px; color: #888; margin-top: 2px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 8px 10px; border-bottom: 2px solid #e5e5e5; font-size: 11px; text-transform: uppercase; color: #888; }
  td { padding: 7px 10px; border-bottom: 1px solid #f0f0f0; font-variant-numeric: tabular-nums; }
  tr:hover { background: #f8fafc; }
  .price-cell { text-align: right; }
  .log { font-family: monospace; font-size: 12px; background: #1e1e1e; color: #d4d4d4; padding: 14px; border-radius: 6px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; }
  .log .ok { color: #4ec9b0; }
  .log .err { color: #f14c4c; }
  .log .skip { color: #888; }
  .log .info { color: #569cd6; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite; margin-right: 6px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .js-box { background: #1e1e1e; color: #d4d4d4; font-family: monospace; font-size: 11px; padding: 14px; border-radius: 6px; max-height: 400px; overflow: auto; white-space: pre; margin-top: 10px; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #059669; color: #fff; padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; opacity: 0; transition: opacity 0.3s; z-index: 999; }
  .toast.show { opacity: 1; }
  .empty-msg { color: #aaa; text-align: center; padding: 30px; font-size: 13px; }
</style>
</head>
<body>

<div class="header">
  <h1>PPS Competitor Pricing Dashboard</h1>
  <p>Scrape, view, and export competitor prices for your calculators</p>
</div>

<div class="container">

  <!-- Status -->
  <div class="card">
    <div class="card-header">
      <h2>Database Status</h2>
      <div>
        <button class="btn btn-blue" onclick="runScrape()" id="scrapeBtn">Refresh All Prices</button>
        <button class="btn btn-green" onclick="runExport()" id="exportBtn" style="margin-left:6px;">Export for Calculator</button>
      </div>
    </div>
    <div class="card-body">
      <div class="status-bar" id="statusBar">
        <div class="stat"><div class="stat-val" id="statTotal">—</div><div class="stat-label">Price Points</div></div>
        <div class="stat"><div class="stat-val" id="statProducts">—</div><div class="stat-label">Products</div></div>
        <div class="stat"><div class="stat-val" id="statLast">—</div><div class="stat-label">Last Scrape</div></div>
      </div>
    </div>
  </div>

  <!-- Products -->
  <div class="card">
    <div class="card-header"><h2>Products</h2></div>
    <div class="card-body">
      <div class="product-grid" id="productGrid">
        <div class="empty-msg">Loading...</div>
      </div>
    </div>
  </div>

  <!-- Price Table -->
  <div class="card" id="priceCard" style="display:none">
    <div class="card-header">
      <h2 id="priceTitle">Prices</h2>
    </div>
    <div class="card-body">
      <div id="priceTable"></div>
    </div>
  </div>

  <!-- Scrape Log -->
  <div class="card" id="logCard" style="display:none">
    <div class="card-header">
      <h2>Scrape Log</h2>
      <button class="btn btn-outline" onclick="document.getElementById('logCard').style.display='none'">Close</button>
    </div>
    <div class="card-body">
      <div class="log" id="scrapeLog"></div>
    </div>
  </div>

  <!-- Export Output -->
  <div class="card" id="exportCard" style="display:none">
    <div class="card-header">
      <h2>Exported JavaScript</h2>
      <div>
        <button class="btn btn-outline" onclick="copyJS()">Copy to Clipboard</button>
        <button class="btn btn-outline" onclick="document.getElementById('exportCard').style.display='none'" style="margin-left:6px;">Close</button>
      </div>
    </div>
    <div class="card-body">
      <p style="font-size:12px;color:#888;margin-bottom:6px;">Paste this into your calculator HTML file, replacing the old COMP_DATA block:</p>
      <div class="js-box" id="jsOutput"></div>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const API = '';

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

async function api(endpoint, params = {}) {
  const qs = new URLSearchParams(params).toString();
  const url = endpoint + (qs ? '?' + qs : '');
  const resp = await fetch(url);
  return resp.json();
}

async function loadStatus() {
  const data = await api('/api/status');
  if (!data.ok) return;
  document.getElementById('statTotal').textContent = data.total_records.toLocaleString();
  document.getElementById('statProducts').textContent = data.products.length;
  document.getElementById('statLast').textContent = data.last_scrape === 'Never' ? 'Never' : new Date(data.last_scrape).toLocaleDateString();

  const grid = document.getElementById('productGrid');
  if (data.products.length === 0) {
    grid.innerHTML = '<div class="empty-msg">No pricing data yet. Click "Refresh All Prices" to scrape competitor sites.</div>';
    return;
  }
  grid.innerHTML = data.products.map(p => `
    <div class="product-tile" onclick="loadPrices('${p.name}', this)" data-product="${p.name}">
      <h3>${p.display_name}</h3>
      <div class="meta">${p.competitors} competitors, ${p.tiers} qty tiers</div>
    </div>
  `).join('');
}

async function loadPrices(product, tile) {
  // Highlight active tile
  document.querySelectorAll('.product-tile').forEach(t => t.classList.remove('active'));
  if (tile) tile.classList.add('active');

  const data = await api('/api/prices', {product});
  if (!data.ok) return;

  const card = document.getElementById('priceCard');
  card.style.display = 'block';
  document.getElementById('priceTitle').textContent = product.replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase()) + ' — Competitor Prices';

  if (data.competitors.length === 0) {
    document.getElementById('priceTable').innerHTML = '<div class="empty-msg">No competitor data for this product.</div>';
    return;
  }

  let html = '<table><thead><tr><th>Qty</th>';
  data.competitors.forEach(c => {
    html += '<th class="price-cell">' + c.charAt(0).toUpperCase() + c.slice(1) + '</th>';
  });
  html += '</tr></thead><tbody>';

  for (const [qty, prices] of Object.entries(data.tiers)) {
    html += '<tr><td><strong>' + Number(qty).toLocaleString() + '</strong></td>';
    data.competitors.forEach(c => {
      const p = prices[c];
      html += '<td class="price-cell">' + (p != null ? '$' + p.toFixed(2) : '<span style="color:#ccc">—</span>') + '</td>';
    });
    html += '</tr>';
  }
  html += '</tbody></table>';

  document.getElementById('priceTable').innerHTML = html;
  card.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

async function runScrape() {
  const btn = document.getElementById('scrapeBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Scraping...';

  const logCard = document.getElementById('logCard');
  const log = document.getElementById('scrapeLog');
  logCard.style.display = 'block';
  log.innerHTML = '<span class="info">Starting scrape of all competitor sites...</span>\\n';

  try {
    const data = await api('/api/scrape');
    if (!data.ok) {
      log.innerHTML += '<span class="err">Error: ' + data.error + '</span>\\n';
      return;
    }

    for (const r of data.results) {
      if (r.status === 'success') {
        log.innerHTML += '<span class="ok">OK</span>  ' + r.competitor.padEnd(18) + r.product.padEnd(18) + r.points + ' prices\\n';
      } else if (r.status === 'skipped') {
        log.innerHTML += '<span class="skip">SKIP</span> ' + r.competitor.padEnd(18) + r.product.padEnd(18) + (r.reason || '') + '\\n';
      } else {
        log.innerHTML += '<span class="err">FAIL</span> ' + r.competitor.padEnd(18) + r.product.padEnd(18) + (r.reason || '') + '\\n';
      }
    }

    log.innerHTML += '\\n<span class="info">Done! ' + data.total_points + ' total price points saved.</span>\\n';
    showToast('Scrape complete — ' + data.total_points + ' prices saved');
    await loadStatus();
  } catch (e) {
    log.innerHTML += '<span class="err">Network error: ' + e.message + '</span>\\n';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Refresh All Prices';
  }
}

async function runExport() {
  const btn = document.getElementById('exportBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Exporting...';

  try {
    const data = await api('/api/export');
    if (!data.ok) {
      alert('Export failed: ' + data.error);
      return;
    }

    document.getElementById('exportCard').style.display = 'block';
    document.getElementById('jsOutput').textContent = data.js;
    showToast('Exported! Also saved to ' + data.saved_to);
    document.getElementById('exportCard').scrollIntoView({behavior: 'smooth'});
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Export for Calculator';
  }
}

function copyJS() {
  const text = document.getElementById('jsOutput').textContent;
  navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard!'));
}

// Load on start
loadStatus();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress console output

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        params = {}
        if "?" in self.path:
            params = {k: v[0] for k, v in parse_qs(self.path.split("?")[1]).items()}

        if path == "/":
            self._html(HTML_PAGE)
        elif path == "/api/status":
            self._json(get_db_status())
        elif path == "/api/prices":
            self._json(get_price_table(params.get("product", "")))
        elif path == "/api/scrape":
            self._json(run_scrape())
        elif path == "/api/export":
            self._json(export_js())
        else:
            self.send_error(404)


def main():
    server = HTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"

    print(f"PPS Competitor Pricing Dashboard")
    print(f"Opening {url} in your browser...")
    print(f"Close this window to stop.\n")

    # Open browser after a short delay
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
