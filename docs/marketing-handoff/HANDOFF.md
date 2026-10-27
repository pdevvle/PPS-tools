# PPS Marketing Hub: handoff

Written October 27, 2026, for whoever picks up the Marketing Hub next. It covers what exists, what was in progress when this was written, and what is left.

## Contents of this folder

| File | What it is |
|---|---|
| `HANDOFF.md` | This document |
| `ui-sketch.jpg` | The owner's hand-drawn sketch of the new navigation (photographed sideways; rotate 90° clockwise to read it) |
| `marketing-ui-wip.patch` | The unfinished navigation work, not yet committed (see [Work in progress](#work-in-progress-navigation-from-the-sketch)). It applies cleanly to commit `1bf1167` |
| `scripts/build_snapshot.py`, `scripts/snapshot.js` | Builds the read-only demo copy that is published as a claude.ai artifact |
| `scripts/check_snapshot.js` | A Playwright pass over that demo copy |
| `scripts/shoot.js`, `scripts/e2e.js` | A screenshot helper, and the click-through test of the live app in demo mode. `e2e.js` targets the old navigation |

## Where things live

- **Repository and branch:** `pdevvle/PPS-tools`, branch `claude/quickbooks-book-categorizer-Q85ha`.
- **Pull request:** [pdevvle/PPS-tools#1](https://github.com/pdevvle/PPS-tools/pull/1), a draft whose base is `claude/analyze-competitor-pricing-MQ8QA`.
- **The branch is shared.** Other sessions push to it as well: the Nightfall Protocol game (`games/`), Switchboard (`src/pps_tools/switchboard/`, `docs/switchboard.md`) and the QuickBooks categorizer. PPS Books moved to its own branch, `claude/pps-books`, with its own pull request, [pdevvle/PPS-tools#6](https://github.com/pdevvle/PPS-tools/pull/6).
  - Fetch before you commit, and fast-forward or merge. Don't rebase pushed history.
- **The PR description is shared too.** Only edit its **"Also on this branch: PPS Marketing Hub"** section and the testing subsection under it.
- **Code:** `src/pps_tools/marketing/`. The user guide is `MARKETING_HUB.md`, the environment variables are in `.env.example`, and the tests are in `tests/test_marketing/`.

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pps marketing serve                      # http://localhost:5050, demo data until a platform is connected
python -m pytest -q tests/test_marketing # 163 tests, about 20 s; every platform API is mocked
python -m pytest -q                      # full suite: 526 passed at the Microsoft Advertising commit
```

## What is done (committed and pushed)

### The Marketing Hub
This is a Flask app run by `pps marketing serve`, which keeps its data in a local SQLite file (`marketing.db`). It covers **Google Ads, Microsoft Advertising, Meta (Facebook + Instagram), Pinterest, X, LinkedIn and TikTok**.

- **Dashboard:** KPIs compared with the previous period, daily spend by channel, conversions, a channel table, top campaigns, budget pacing and CSV export.
- **Campaigns:** one table of every campaign, with pause, enable and daily-budget edits. Shared, lifetime, ad-set and experiment budgets are left alone.
- **Publish:** write once, post to Facebook Pages, Instagram, Pinterest, X and LinkedIn. It has per-network text, X's character counting, automatic UTM tags, scheduling, a queue, history and a calendar.
- **AI Studio and Insights:** Claude (`claude-opus-5-5`, structured outputs, server-side fallback). Studio writes ad copy and checks it against each platform's limits. Insights writes a performance review whose pause and budget suggestions can be applied with one click.
- **Automation:** rules with dry runs, minimum-spend guards, cooldowns and a budget-change cap (`MARKETING_MAX_BUDGET_CHANGE_PCT`).
- **Also:** monthly budgets with pacing, a UTM builder, connections with per-platform setup steps, an activity log, and a CLI (`status`, `report`, `publish-due`, `run-rules`).
- **Safety:** CSRF on every change, an optional password (`MARKETING_APP_PASSWORD`), and tokens in a private SQLite file.
- **Demo mode:** realistic sample data generated from `platforms/demo.py`. It is the same every time and simulates pauses and budget changes.

**How it's built**
- **`hub.py`** combines the connectors. It fetches each account in parallel, keeps one account's errors from affecting the others, caches results in SQLite and switches in the demo stand-ins.
- **`platforms/*.py`:** one connector per platform behind `platforms/base.py`.
- **`models.py`** defines the normalized shapes and `NETWORKS`. Each network keeps one chart color everywhere, with slots 1 to 8; Microsoft is 8, the last free slot.
- **`analytics.py`, `pacing.py`, `rules.py` and `publisher.py`** hold the business logic. `publisher.py` includes the scheduler.
- **`ai.py`, `copywriter.py` and `insights.py`** are the Claude features.
- **`app.py`, `templates/` and `static/`** are the UI. The charts are dependency-free SVG, drawn by `static/mk.js`.

**API versions in use**

| Platform | Version and notes |
|---|---|
| Google Ads | v26. No developer token; uses `login-customer-id` for manager (MCC) accounts |
| Meta Graph | v26.0 |
| Pinterest | v5 |
| X | API v2 for posting, Ads API v12 with OAuth 1.0a for ads |
| LinkedIn | `202610`, with Rest.li encoding |
| TikTok | v1.3 |
| Microsoft Advertising | REST v13 |

### Microsoft Advertising (commit `3076455`)
This is `platforms/microsoft_ads.py`.

- **Sign-in:** Microsoft identity platform OAuth with PKCE and `prompt=select_account`. Every call also needs a developer token. The environment variables are `MICROSOFT_ADS_CLIENT_ID`, `MICROSOFT_ADS_CLIENT_SECRET`, `MICROSOFT_ADS_DEVELOPER_TOKEN` and optionally `MICROSOFT_ADS_TENANT`.
- **Accounts:** found with GetUser, then SearchAccounts. Campaign and reporting calls send the `CustomerId` and `CustomerAccountId` headers.
- **Campaigns:**
  - Read with `QueryByAccountId` for Search, Shopping, Audience and Performance Max.
  - Updated with PUT. Partial errors raise an error rather than being ignored.
  - Shared, lifetime and experiment budgets are protected from edits.
- **Reports:** an asynchronous report, run as submit, then poll, then download a zipped CSV.
  - It uses the `ConversionsQualified` column; `Conversions` is deprecated.
  - It runs in the account's own time zone. Four zone names are spelled differently in the report list and are translated.
  - The end date is clamped to "today" in UTC−12, because Microsoft rejects future dates.
- **Elsewhere in the hub:** demo data, red (slot 8) in charts, a `bing`/`cpc` UTM preset and an auto-tagging tip on the UTM page. The AI Studio responsive search ad format is labeled for both Google and Microsoft.

### Read-only demo at a URL
- **Link:** https://claude.ai/artifact/X3GT9hFqe56M5hRBv7MD2z. It's private to the owner until they share it.
- **What it is:** a static copy of the app in demo mode, with 38 pages and the stylesheet and scripts as of October 26. It shows the old navigation.
- **How it's built:** `scripts/build_snapshot.py` runs the app in-process with a throwaway database and fills it with a month of activity. It then crawls every page reachable by a link and points those links at the saved files. Finally it writes `static/snapshot.js`, which:
  - answers form posts and `fetch` calls with a "read-only" toast
  - serves rule dry runs computed while building
  - maps the app's links to the saved pages
- **Artifact rules that matter here:**
  - The main page (`index.html`) is a fragment, with no doctype, head or body; the artifact host wraps it.
  - The other pages are full documents.
  - Downloads, `confirm()` and posting forms don't work inside an artifact, which is why the shim exists.
- **To rebuild:** `python docs/marketing-handoff/scripts/build_snapshot.py <out_dir>`. Then check it with `scripts/check_snapshot.js`, serving a copy of `<out_dir>` in which `index.html` is wrapped in a doctype, head and body.
- **To republish to the same URL from a new session:** run the Artifact tool's `read` on the URL first. Then publish with `url` set, `file_path=<out_dir>/index.html`, `root=<out_dir>`, and every other file in `files`.
- **After the new navigation lands, expect about 210 pages.** That's 7 services × 6 date ranges plus 21 campaigns × 6. Raise `MAX_PAGES` in the builder, and stay under the 255-files-per-publish limit.

## Work in progress: navigation from the sketch

### What the owner asked for
The request was: *"review ui changes. Note that this will eventually be a tab within another service not being built by you (see toolbar placement). Just leave the inbox feature tbd"*. The sketch is `ui-sketch.jpg`; some of the handwriting is hard to read.

- **Toolbar (host app, not ours):** a vertical rail of round icons, reading Inbox, Schedule, Marketing, Social posts, then two hard-to-read labels, probably Accounting and Inventory. The Marketing Hub becomes the **Marketing** tab.
  - The host is most likely **Switchboard**, another session's app in this repo. It is a shared team inbox with staffing and jobs, and it has a 64px dark rail and 236px module sidebars.
  - See `src/pps_tools/switchboard/static/js/views/app.js` (`.rail`) and `static/css/base.css` (`--rail-w`, `--sidebar-w`). Don't change Switchboard; it belongs to another session.
- **View 1:** a list headed **All services**, then Google Ads, Meta, X.com and **+ Add New**.
- **View 2:** clicking a service opens a column with **Leads**, **Stats** and **Link to dashboard**. Leads opens the **inbox (from the other repo), filtered to leads**, drawn as contact cards such as "John Smith". Per the request, the inbox is **TBD**.
- **Margin note:** "each view compresses sidebars but doesn't entirely hide them, making each visible."
- **Revision note:** "View 1 should be closer to your dashboard view, but should be organized **Dashboard > Services > Campaigns > View 2**."

### How it was interpreted (decisions so far)
- **Four levels.**
  1. **All services**: the current dashboard.
  2. **One service**: a service dashboard, plus a campaigns column.
  3. **One campaign** (the sketch's View 2): Stats, Leads (placeholder) and a link to the platform's own dashboard.
  4. Each step down compresses the columns above it instead of hiding them.
- **Services column.** It holds All services, then only the *connected* services (all seven in demo mode), then **+ Add new**, which leads to Connections.
  - Publish, AI Studio, Insights, Automation, Budgets, UTM Builder, Activity and Connections move to a **Tools** group at the bottom of that column.
  - The all-campaigns table stays at `/campaigns`, linked from the dashboard.
- **"Link to dashboard" = the platform's own ads dashboard** ("Open Google Ads ↗"), not the hub's dashboard.
  - Deep-link URL formats are undocumented for most platforms, so links go to each platform's dashboard home.
  - Meta links to its account (`?act=<id>`) and LinkedIn to the account overview (`/campaignmanager/accounts/<id>/overview`).
- **Leads** is a "To be decided" placeholder with grey skeleton rows. Nothing about leads is invented. It can say how many conversions the platform counted for the campaign.
- **No host rail is built.** The layout just has to work inside a container with a 64px rail on its left.
- **The hub's own colors and type stay** (no restyle to Switchboard's palette). Column widths follow Switchboard's: 236px expanded.
- **The date range carries through the drill-down.** `?range=` or `?start=&end=` is kept on every navigation link. The default range (30 days) is left out of URLs.

### Already written (in `marketing-ui-wip.patch`, not committed)
Apply it with `git apply docs/marketing-handoff/marketing-ui-wip.patch`, or `git apply --3way` if those files have moved on.

**Warning:** with only the patch applied, every page fails to render until `mk_base.html` is rewritten. The context processor now provides `nav` as a dict, but `mk_base.html` still loops over it as a list of tuples (`{% for endpoint, label, ic in nav %}`). Don't commit the patch on its own.

The patch contains:

- **`app.py`**
  - Module docstring updated with the new routes.
  - `NAV` replaced by `TOOLS`, with new `PLATFORM_BADGES` and `KPI_METRICS`.
  - New helpers inside `create_app`:
    - `platform_slot`: a service's color is the color of its first network
    - `service_for_network`: maps networks to services, with "other" going to meta
    - `range_args`
    - `service_entry`
    - `nav_campaigns`: active campaigns first, by spend
    - `build_nav(level, platform, campaigns, rows, campaign_key)`: returns `level`, `range`, `services` (with spend when rows are given), `total_spend`, `service`, `campaigns` and `campaign_key`
    - `service_or_404`
    - `period_data`: this period, the previous period and campaigns, fetched in parallel
    - `kpi_tiles`, `spend_chart` and `campaign_items`, factored out of the dashboard and campaigns routes
    - `errors_for(errors, service, account=None)`
  - The context processor now provides `nav=build_nav()`, `tools` and `platform_slots`. Views pass their own `nav=` explicitly, which overrides it.
  - New routes:
    - `GET /services/<platform>`: endpoint `service`, renders `mk_service.html`
    - `GET /services/<platform>/campaigns/<account_id>/<campaign_id>`: endpoint `campaign`, renders `mk_campaign.html`. It returns 404 when the campaign has neither a campaign record nor any rows; a removed campaign that still has spend still shows its stats.
  - The dashboard now also passes `service_for_network`, `live_services` and `nav`. Each top campaign gains `account_id` and `campaign_id`.
  - `/export.csv` accepts `?platform=` and puts it in the file name.
  - `/campaigns` uses `campaign_items` and passes `nav`.
- **`platforms/base.py`:** `console_name`, `console_home` and `console_url(account=None)`.
  - Every connector sets the first two.
  - Meta and LinkedIn override `console_url`.
  - `DemoPlatform` copies the attributes and delegates to the real connector, through `self.real`.
- **`templates/mk_macros.html`**
  - New `plus` and `inbox` icons.
  - `platform()` uses `platform_slots` instead of a hard-coded map.
  - New `badge(service)` (initials on a tint of the service's color, using the class `tint-<slot>`) and `kpi_tiles(kpis)` macros, the latter lifted from the dashboard.
  - `period_filters(..., path={})` handles routes with path parameters. The form action and links use `url_for(endpoint, **path)`; `extra` stays as query parameters.

The template variables the two new routes pass:
- **`mk_service.html`:** `period`, `source`, `kpis`, `chart`, `items`, `totals`, `currency`, `currencies`, `errors`, `accounts` (a list of `(AdAccount, console_url)`), `console_url`, `max_change` and `nav`.
- **`mk_campaign.html`:** `period`, `source`, `c` (a Campaign, or None if removed), `key`, `name`, `account`, `kpis`, `chart`, `networks` (a per-network breakdown, only when there is more than one network, e.g. Meta), `totals`, `currency`, `errors`, `console_url`, `max_change` and `nav`.

### Still to do
1. **`templates/mk_base.html`: the new shell.** Keep the `<head>`, theme toggle, skip link, banners and flashes.
   - **Services column:** `<nav class="col col-services">`, with `is-compact` added when `nav.level > 1`. It contains:
     - a header reading "Marketing", plus the Demo pill
     - "All services", linking to `dashboard` with `**nav.range`, showing `nav.total_spend` when it isn't None
     - one item per `nav.services`: `badge(s)`, the short name and the period spend, linking to `service` with `**nav.range`
     - "+ Add new", linking to `connections`
     - a "Tools" group listing `tools`, plus the sign-out form when `app_password` is set
   - **Campaigns column:** `<nav class="col col-campaigns">`, only when `nav.service`; `is-compact` when `nav.level > 2`. It has a header (badge and service name), an "Overview" item linking to `service`, then the "Campaigns" items: a status dot (`.dot.good` when active), the name, the spend, and a link to `campaign`.
   - **Highlighting:** mark the current page with `aria-current="page"` and the current service, while a campaign is open, with `aria-current="location"`. Style on `[aria-current]`.
   - **Main area:** breadcrumbs above the `h1`. On level 2 they read "All services"; on level 3, "All services / {service}".
2. **`static/mk.css`: layout.** Remove the old `.sidebar`, `.brand` and `.nav` rules.
   - `.shell` becomes flex. `.col` is sticky and full height with `overflow-y: auto`; it is 236px wide, and the campaigns column 284px.
   - Compact services: 64px wide, badges only. Names are hidden the screen-reader way (the `.sr-only` technique), not `display: none`. Tools show as icons only. Use `title` attributes for tooltips.
   - Compact campaigns: about 208px wide, one-line names, no spend.
   - `.badge`: a 28px rounded square. Its background is `color-mix(in srgb, var(--tint) 20%, var(--surface))`, with `.tint-N { --tint: var(--series-N) }`. Declare a `var(--surface-3)` fallback first, and keep the text in `--ink` so it reads in both themes.
   - Campaign view: `.view` is a two-column grid, with a vertical sub-nav of 184px beside the content. Below 1200px the sub-nav becomes a row of tabs.
   - At 900px and below, the columns turn into horizontal, scrollable strips above the content, with tools after a divider. Keep at least a 16px side gutter, and keep the page body from scrolling sideways at 390px.
3. **`templates/mk_service.html`:**
   - Header actions: "Export CSV", using `platform=` with `**nav.range`, and "Open {console_name} ↗", which opens in a new tab with `rel="noopener"`.
   - Content: `period_filters(period, "service", path={"platform": source.key})`, then the errors, `kpi_tiles`, the spend-by-channel chart (`MK.charts.stacked`), the conversions chart (`MK.charts.line`), the campaigns table and an accounts card. Each account in the card gets its own console link.
4. **`templates/mk_campaign.html`:**
   - Header: the campaign name, its status, objective, account and budget, with Pause/Enable and an Edit control for the budget.
   - `.view-nav` links: **Stats** (`#stats`), **Leads** (`#leads`) with a "To be decided" pill, and **Open {console_name} ↗**.
   - Stats panel: date filters (`path` set to platform, account_id and campaign_id), `kpi_tiles`, the charts and the network breakdown.
   - Leads panel: the placeholder card and skeleton rows.
   - Panels toggle with `[data-view]` and `[data-view-panel]`, keyed on `location.hash`. Without JavaScript both panels show.
5. **Shared campaigns table.** Move the table from `mk_campaigns.html` into a macro shared by the all-campaigns and service pages. Campaign names should link to the campaign view, keeping `**nav.range`.
   - Move the inline pause and budget JavaScript into `mk.js` as `MK.campaignControls(root)`.
   - It should read the URLs and the change cap from `data-status-url`, `data-budget-url` and `data-max-change`.
   - Use `closest("[data-key]")` and a `data-label` for the confirm text, so the same code also drives the controls in the campaign view header.
6. **`mk.js` additions.**
   - The view tabs.
   - Scrolling the current item in each column into view. Use `getBoundingClientRect` differences, not `scrollIntoView`, which would also scroll the page.
7. **`mk_dashboard.html`.**
   - Use the `kpi_tiles` macro.
   - In the channel table, link each row to its service through `service_for_network`, but only for services in `live_services`.
   - Link each top campaign to its campaign view.
8. **Tests (`tests/test_marketing/test_app.py` and others).**
   - Add the service and campaign pages to `PAGES`, e.g. `/services/google_ads` and `/services/google_ads/campaigns/4825519306/20481`.
   - Check:
     - the compression classes at each level
     - that only connected services are listed outside demo mode
     - 404s for an unknown service and an unknown campaign
     - that the range is kept in navigation links
     - the console URLs (Meta `act`, LinkedIn overview, the demo delegation)
     - `/export.csv?platform=`
     - that the Leads placeholder is there
   - Update `e2e.js` for the new navigation.
9. **Check in a browser** at 1440px and 390px, in light and dark, with screenshots. Then update `MARKETING_HUB.md`, adding a short section on navigation and an "embedding as a tab" note.
10. **Rebuild the demo and republish it to the same URL, then commit, push and update the PR section.**

### Questions to put to the owner
- With **Schedule** and **Social posts** as their own tabs in the host rail, should Publish (posting, scheduling and the calendar) leave the Marketing tab? For now it sits under Tools.
- Is "Link to dashboard" right as the platform's own ads dashboard?
- **Leads:** how will an inbox lead be matched to a campaign? Options include the UTM or form source, click IDs (`gclid`, `msclkid`, `fbclid`) and lead-form IDs. And which inbox API will provide them: Switchboard's, or another repository's?
- Should the hub hide its own theme toggle and demo pill when embedded, and run under a URL prefix such as `/marketing`? `url_for` handles a prefix if the app is mounted with `DispatcherMiddleware`. A few links built in JavaScript use paths starting with `/`; check those.
