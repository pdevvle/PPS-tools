"""Build a static, read-only copy of the Marketing Hub in demo mode, for publishing as an artifact.

usage: python build_snapshot.py <out_dir>

The app runs in-process (Flask test client) with a throwaway database. It is
seeded with a month of realistic activity, then every page reachable by a
plain link is rendered and saved as a static file. Links are pointed at those
files; anything that would change data is answered with a clear read-only
message instead. Rule previews (dry runs) are read-only in the real app too,
so their answers are computed here and served as-is.
"""

import html
import json
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from pps_tools.marketing import rules as rules_mod
from pps_tools.marketing.app import create_app
from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.copywriter import FORMATS, CopyBrief, check_variant

OUT = Path(sys.argv[1])
STATIC = Path(rules_mod.__file__).parent / "static"
TODAY = date.today()
DEFAULT_PARAMS = {"range": "30d", "tab": "queue"}
DROP_PARAMS = {"refresh"}
NOT_PAGES = ("/oauth/", "/export.csv", "/login", "/logout", "/healthz", "/static/", "/api/")
MAX_PAGES = 120

# -- run the app in demo mode -------------------------------------------------------

tmp = Path(tempfile.mkdtemp())
settings = MarketingSettings(db_path=tmp / "marketing.db", demo="on", base_url="http://localhost:5050")
app = create_app(settings)
app.config["TESTING"] = True
hub = app.extensions["marketing_hub"]
client = app.test_client()
client.get("/")


def token() -> str:
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def post_form(url: str, data: dict) -> None:
    resp = client.post(url, data={**data, "csrf_token": token()})
    assert resp.status_code in (200, 302), (url, resp.status_code)


def post_json(url: str, payload: dict) -> dict:
    resp = client.post(url, data=json.dumps(payload), content_type="application/json", headers={"X-CSRF-Token": token()})
    assert resp.status_code == 200, (url, resp.status_code, resp.data[:300])
    return resp.get_json()


# -- seed a believable month ---------------------------------------------------------

post_form("/budgets", {
    "month": TODAY.strftime("%Y-%m"), "budget_total": "16000", "budget_google_ads": "6000", "budget_meta": "3600",
    "budget_linkedin": "2000", "budget_tiktok": "1400", "budget_microsoft_ads": "1400", "budget_pinterest": "1000",
    "budget_x": "600",
})

for i in (0, 2, 3):
    rule = dict(rules_mod.DEFAULT_RULE, **rules_mod.TEMPLATES[i])
    data = {k: str(v) for k, v in rule.items() if v is not None and k != "enabled"}
    post_form("/automation/rules", dict(data, enabled="on"))
assert len(hub.store.list_rules()) == 3

targets = {t.network: t.key for t in hub.targets()}
site = "https://priorityprintservice.com"
post_form("/publish", {
    "body": "Need business cards fast? Order online and pick them up the same day.",
    "link": f"{site}/business-cards", "title": "Same-day business cards", "utm_campaign": "same-day-cards",
    "targets": [targets["facebook"], targets["x"], targets["linkedin"]], "mode": "now",
})
for days, body, link, nets in (
    (2, "Wedding season is here. Invitations, programs and place cards, printed on premium stock.",
     f"{site}/wedding-invitations", ("facebook", "x")),
    (5, "Trade show coming up? Get banners, brochures and business cards in one order.", "", ("facebook", "linkedin")),
):
    when = datetime.now(timezone.utc).replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=days)
    post_form("/publish", {"body": body, "link": link, "utm_campaign": "", "targets": [targets[n] for n in nets],
                           "mode": "schedule", "scheduled_utc": when.isoformat()})
post_form("/publish", {"body": "Holiday cards: order early to beat the rush.", "targets": [targets["facebook"]], "mode": "draft"})
assert {p["status"] for p in hub.store.list_posts()} == {"published", "scheduled", "draft"}

for url, source, medium, campaign, content, label in (
    (f"{site}/business-cards", "google", "cpc", "fall-business-cards", "", "Google Ads: fall business cards"),
    (f"{site}/brochures", "bing", "cpc", "brochures-catalogs", "", "Microsoft Ads: brochures"),
    (f"{site}/stickers", "facebook", "paid_social", "custom-stickers", "reel-a", "Meta: sticker reels"),
):
    post_form("/utm", {"url": url, "source": source, "medium": medium, "campaign": campaign, "content": content,
                       "term": "", "label": label})

post_json("/api/campaigns/status", {"key": "meta:act_1029384756:120210000004", "status": "PAUSED"})
post_json("/api/campaigns/budget", {"key": "microsoft_ads:180436527:413052001", "amount": "24"})

# One saved set in the AI Studio library, so the library shows what a result looks like.
rsa = {
    "angle": "Speed and quality",
    "headlines": [
        "Business Cards Printed Fast", "Same-Day Business Cards", "Premium Business Cards",
        "Order Business Cards Online", "Upload Your Design in Minutes", "Thick, Premium Cardstock",
        "Matte, Gloss or Soft-Touch", "Your Local Print Shop", "Design Help Available",
        "Cards That Make an Impression", "Reorder in Two Clicks", "Order Today, Pick Up Today",
        "Priority Print Service", "Shop Business Cards Now", "Cards for Your Whole Team",
    ],
    "descriptions": [
        "Order business cards online and pick them up the same day. Premium stock, sharp color.",
        "Upload your design or start from a template. We check every file before it prints.",
        "Matte, gloss and soft-touch finishes on thick cardstock. Cards for your whole team.",
        "A local print shop with fast turnaround. Order online today and pick up in store.",
    ],
    "path1": "business-cards",
    "path2": "same-day",
}
feed = [
    {"angle": "Ready today", "primary_text": "Need business cards by this afternoon? Order online and pick them up the same day from our shop.",
     "headline": "Business cards, ready today", "description": "Order online, pick up in store"},
    {"angle": "Feel the quality", "primary_text": "First impressions start with the card you hand over. Thick premium stock in matte, gloss or soft-touch.",
     "headline": "Cards that feel premium", "description": "Upload your design in minutes"},
]
issues = {"google_rsa": [check_variant(FORMATS["google_rsa"], rsa)], "meta_feed": [check_variant(FORMATS["meta_feed"], v) for v in feed]}
assert not any(i for group in issues.values() for i in group), issues
brief = CopyBrief(product="Business cards", formats=["google_rsa", "meta_feed"], offer="Same-day pickup",
                  audience="Local small business owners", goal="conversions", landing_url=f"{site}/business-cards", variants=2)
post_json("/api/studio/save", {
    "title": "Business cards: same-day pickup",
    "brief": brief.to_dict(),
    "result": {"strategy": "Lead with speed for searchers who need cards now, and with quality on social, where people "
                           "scroll past plain offers. Test the same-day angle against the premium-stock angle first.",
               "formats": {"google_rsa": [rsa], "meta_feed": feed}, "issues": issues, "model": settings.claude_model,
               "repaired": False},
})

# Rule previews: read-only in the real app, so the copy can answer them.
dry_runs = {"all": post_json("/api/automation/run", {"dry_run": True, "rule_id": None})}
for rule in hub.store.list_rules():
    dry_runs[str(rule["id"])] = post_json("/api/automation/run", {"dry_run": True, "rule_id": rule["id"]})

# -- crawl ---------------------------------------------------------------------------------

# The seeding left its confirmation messages queued; they don't belong on the pages.
with client.session_transaction() as sess:
    sess.pop("_flashes", None)


def normalize(href: str):
    """'/campaigns?range=30d&refresh=1' -> '/campaigns'; None for anything that isn't a local page."""
    href = html.unescape(href)
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        return None
    params = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                    if k not in DROP_PARAMS and DEFAULT_PARAMS.get(k) != v)
    return parts.path + ("?" + urlencode(params) if params else "")


def filename(url: str) -> str:
    if url == "/":
        return "index.html"
    path, _, query = url.partition("?")
    name = path.strip("/").replace("/", "-") or "dashboard"
    for k, v in parse_qsl(query):
        name += f"-{v}" if k in ("range", "tab") else f"-{k}-{v}"
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") + ".html"


HREF = re.compile(r'href="([^"]*)"')
pages: dict[str, str] = {}
order: list[str] = []
queue = ["/"]
while queue and len(pages) < MAX_PAGES:
    url = queue.pop(0)
    if url in pages or url.startswith(NOT_PAGES):
        continue
    resp = client.get(url)
    if resp.status_code != 200 or not resp.mimetype.startswith("text/html"):
        print("skip", url, resp.status_code)
        continue
    text = resp.data.decode()
    pages[url] = text
    order.append(url)
    for href in HREF.findall(text):
        target = normalize(href)
        if target and target not in pages and not target.startswith(NOT_PAGES):
            queue.append(target)
print(f"{len(pages)} pages:", ", ".join(order))

# -- rewrite into static files ---------------------------------------------------------------

files = {url: filename(url) for url in pages}
stamp = f"{TODAY:%b} {TODAY.day}, {TODAY.year}"
banner = (f"<strong>Read-only demo.</strong> Sample data for Priority Print Service as of {stamp}. "
          "Buttons that change things, publish or ask Claude only work in the running hub. "
          '<a href="connections.html">How to connect your ad accounts</a>')


def rewrite_href(match: re.Match) -> str:
    raw = match.group(1)
    if raw.startswith("/static/"):
        return f'href="{raw[1:]}"'
    target = normalize(raw)
    if target is None:
        return match.group(0)
    fragment = urlsplit(html.unescape(raw)).fragment
    if target in files:
        return f'href="{files[target]}{"#" + fragment if fragment else ""}"'
    return f'href="#" data-off="{raw}"'


def convert(url: str, text: str) -> str:
    text = HREF.sub(rewrite_href, text)
    text = text.replace('src="/static/mk.js"', 'src="static/snapshot.js"></script>\n<script src="static/mk.js"')
    text = re.sub(r'\s*<meta name="csrf-token"[^>]*>', "", text)
    text = re.sub(r'(name="csrf_token" value=")[^"]*"', r'\1"', text)
    text = re.sub(r'window\.location = "(/[^"]*)"',
                  lambda m: f'window.location = "{files.get(normalize(m.group(1)), "index.html")}"', text)
    new_banner, count = re.subn(r"<strong>Demo mode:</strong>.*?</p>", banner + "</p>", text, flags=re.S)
    if count:
        text = new_banner
    else:
        text = text.replace('<main class="content" id="main">',
                            f'<main class="content" id="main">\n      <div class="banner warning"><p>{banner}</p></div>', 1)
    return text


def as_fragment(text: str) -> str:
    """The published page gets its doctype, head and body from the artifact host."""
    head = text.split("<head>", 1)[1].split("</head>", 1)[0]
    body = text.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    keep = [line.strip() for line in head.splitlines()
            if line.strip().startswith(("<link rel=\"stylesheet\"", "<script>"))]
    return "<title>PPS Marketing Hub</title>\n" + "\n".join(keep) + "\n" + body.strip() + "\n"


if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "static").mkdir(parents=True)
for url, text in pages.items():
    page = convert(url, text)
    (OUT / files[url]).write_text(as_fragment(page) if url == "/" else page)
for name in ("mk.css", "mk.js"):
    shutil.copy(STATIC / name, OUT / "static" / name)

page_map = {url: files[url] for url in pages}
snapshot_js = (Path(__file__).parent / "snapshot.js").read_text()
(OUT / "static" / "snapshot.js").write_text(
    snapshot_js.replace("/*PAGES*/{}", json.dumps(page_map)).replace("/*DRY_RUNS*/{}", json.dumps(dry_runs))
)
total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
print(f"wrote {len(list(OUT.rglob('*.html')))} pages, {total / 1024:.0f} KB total to {OUT}")
