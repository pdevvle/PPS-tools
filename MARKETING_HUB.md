# PPS Marketing Hub

One web app for all of Priority Print Service's online advertising and social posting:
**Google Ads, Microsoft Advertising (Bing), Facebook, Instagram, Pinterest, X (Twitter), LinkedIn and TikTok**.

- **Dashboard** shows spend, revenue, ROAS, conversions, cost per conversion and CTR across every platform. Each number is compared with the previous period. It also has a daily spend chart by channel, a channel breakdown and your top campaigns. You can export it all to CSV.
- **Campaigns** lists every campaign from every connected account in one sortable table. You can pause or re-enable a campaign and change its daily budget right in the table.
- **Publish** lets you write a post once and send it to Facebook Pages, Instagram, Pinterest boards, X and LinkedIn Company Pages. You can:
  - publish now, schedule it, or save a draft
  - change the text for each network
  - see live character counts (X's own counting rules included)
  - have links tagged with UTMs automatically
  - see everything on a content calendar
- **AI Studio** has Claude write ad copy for each platform in the right format and length:
  - Responsive search ads for Google and Microsoft Advertising (they share a format)
  - Meta feed ads
  - Instagram captions
  - Pins
  - X posts
  - LinkedIn sponsored content
  - TikTok scripts

  Each variant takes a different angle so you can A/B test. Anything over a platform limit is caught and sent back to Claude once to be rewritten.
- **Insights** runs quick checks on every visit. You can also ask Claude for a full review: what's working, what isn't, and what to change. When Claude suggests pausing a campaign or changing its budget, you can apply it with one click.
- **Automation** runs rules like "pause a campaign if its cost per conversion is over $60 for 7 days" or "raise the budget 15% when ROAS is above 4". Every rule has a dry-run preview, a minimum-spend guard and a cooldown.
- **Budgets** holds a monthly budget per platform and shows pacing: on track, under- or overspending, a projected month-end total, and what's left to spend per day.
- **UTM Builder** makes consistently tagged links. It includes a Google Ads Final URL suffix, a Microsoft Advertising auto-tagging tip and a list of your saved links.
- **Activity** logs every change made through the hub: by you, by a rule, or from an AI suggestion.

It runs on your computer like the QuickBooks categorizer. The data stays in one local file, `marketing.db`.

## Quick start

```bash
pip install -e .               # once
pps marketing serve            # then open http://localhost:5050
```

Until you connect a platform, the hub runs in **demo mode** with realistic sample data for Priority Print Service. That lets you try every feature first; pausing, budget changes and posts are simulated. Demo mode switches off by itself once the first real platform is connected. You can also change it on the Connections page.

## Connecting the platforms

1. Copy `.env.example` to `.env` (if you haven't already).
2. Fill in the keys for the platforms you use (see below).
3. Restart `pps marketing serve`.
4. Click **Connect** on the **Connections** page.

Each platform needs this redirect URI registered in its developer settings. The Connections page shows each one with a copy button:

```
http://localhost:5050/oauth/<platform>/callback
```

If you run the hub somewhere other than `localhost:5050`, set `MARKETING_BASE_URL` to match. Meta requires https everywhere except localhost.

After connecting, you can include or exclude individual ad accounts and publishing destinations (Pages, boards, profiles) on the Connections page.

### Google Ads (ads)
1. In [Google Cloud Console](https://console.cloud.google.com), enable the **Google Ads API** for a project.
2. On the project's Google Ads API page, apply for **Explorer** or **Basic** access. A new project can only reach test accounts.
   - Developer tokens were retired in September 2026. Your access level now comes from the Cloud project.
3. Create an **OAuth client ID** of type *Web application* and add the redirect URI.
4. Set `GOOGLE_ADS_CLIENT_ID` and `GOOGLE_ADS_CLIENT_SECRET`.
5. Optional: if you reach client accounts through a manager (MCC) account, set `GOOGLE_ADS_LOGIN_CUSTOMER_ID`. The hub also finds client accounts under any manager you sign in with.

While your OAuth consent screen is in *Testing*, Google refresh tokens expire after 7 days. Publish the consent screen to avoid reconnecting weekly.

### Meta: Facebook + Instagram (ads and posting)
1. At [developers.facebook.com/apps](https://developers.facebook.com/apps), create a **Business** app. Add **Facebook Login** and the **Marketing API**.
2. Add the redirect URI under Facebook Login → Settings.
3. Set `META_APP_ID` and `META_APP_SECRET`.
4. The hub asks for these permissions:
   - `ads_read` and `ads_management`
   - `pages_show_list`, `pages_read_engagement` and `pages_manage_posts`
   - `instagram_basic` and `instagram_content_publish`
   - `business_management`

   You (as an app admin) can use them right away. Using them with other people's accounts requires Meta's App Review.
5. Instagram publishing needs an Instagram **professional** account linked to your Facebook Page.
6. If you use *Facebook Login for Business*, create a configuration and set `META_LOGIN_CONFIG_ID`.

Instagram ad spend comes from the same Meta ad accounts. The hub splits it out using Meta's placement breakdown, so Facebook and Instagram show as separate channels.

### Pinterest (ads and Pins)
1. Create an app at [developers.pinterest.com/apps](https://developers.pinterest.com/apps) and add the redirect URI.
2. Set `PINTEREST_APP_ID` and `PINTEREST_APP_SECRET`.
3. New apps start on **Trial** access, where Pins you create are only visible to you. Request **Standard** access to publish publicly.

Pinterest only reports the last 90 days, so longer ranges are clipped.

### X / Twitter (posting and ads)
- **Posting:** in the X developer console, enable **OAuth 2.0** (Web App, confidential client) and add the redirect URI. Set `X_CLIENT_ID` and `X_CLIENT_SECRET`.
  - The X API is pay-per-use, so add credits first.
  - X bills every post, and posts that contain a link cost much more than plain ones. The composer reminds you when X is selected.
- **Ads reporting and control:** the X Ads API still requires OAuth 1.0a.
  1. Apply for Ads API access.
  2. Copy the app's API key and secret and your access token and secret into `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` and `X_ACCESS_TOKEN_SECRET`.
  3. With only these keys set, use **Connect with API keys** on the Connections page. They can also post.

### LinkedIn (ads and Company Page posts)
1. Create an app at [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) and link it to your Company Page.
2. Request the **Advertising API** and **Community Management API** products, and add the redirect URI.
3. Set `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`.

LinkedIn access lasts 60 days. Approved Marketing partners also get a refresh token; otherwise the Connections page reminds you to reconnect.

### TikTok for Business (ads)
1. Create an app on the [TikTok API for Business portal](https://business-api.tiktok.com/portal) with the ad account, ads management and reporting scopes.
2. Set its advertiser redirect URL.
3. Set `TIKTOK_APP_ID` and `TIKTOK_APP_SECRET`.

If your app page shows a different "Advertiser authorization URL", put its base in `TIKTOK_AUTH_URL`.

### Microsoft Advertising (ads)
1. Sign in to the [Microsoft Advertising Developer Portal](https://developers.ads.microsoft.com) with your Microsoft Advertising login and request a **developer token**.
2. In the [Azure portal](https://portal.azure.com), go to **Microsoft Entra ID → App registrations** and register a new app. Under *Supported account types*, pick **Accounts in any organizational directory and personal Microsoft accounts**.
3. Under **Authentication**, add a **Web** platform with the redirect URI. Under **Certificates & secrets**, create a client secret and copy its *Value* (not its ID).
4. Set `MICROSOFT_ADS_CLIENT_ID` (the app's *Application (client) ID*), `MICROSOFT_ADS_CLIENT_SECRET` and `MICROSOFT_ADS_DEVELOPER_TOKEN`.
5. Optional: if the app only accepts your organization's accounts, set `MICROSOFT_ADS_TENANT` to your tenant ID.

Things to know:
- Microsoft builds performance reports on request, so a new date range takes a few extra seconds to load.
- Numbers use each account's own time zone, like the Microsoft Advertising website.
- Microsoft's sign-in lasts up to 90 days without use. The hub renews it every time it syncs, so you only reconnect if the hub sits unused for about three months.
- Client secrets expire (the Azure portal shows when). Create a new one before then and update `.env`.

### Claude (AI Studio + Insights)
Set `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com). The model defaults to `claude-opus-5-5`; change it with `MARKETING_CLAUDE_MODEL`.

`MARKETING_BRAND_CONTEXT` describes the business to Claude. Claude only uses prices, discounts and turnaround times that appear there or in the brief.

## Scheduled posts and rules

While `pps marketing serve` is running, scheduled posts go out automatically; it checks once a minute. To publish them, and to run automation rules, when the app isn't open, use cron (macOS/Linux) or Task Scheduler (Windows):

```cron
*/5 * * * *  cd /path/to/PPS-tools && pps marketing publish-due
0 * * * *    cd /path/to/PPS-tools && pps marketing run-rules
```

Always preview a new rule with **Preview (dry run)** first. Rules only touch active campaigns. They never move a budget more than `MARKETING_MAX_BUDGET_CHANGE_PCT` (default 50%) in one step, and they wait out their cooldown before acting on the same campaign again.

## Command line

| Command | What it does |
|---|---|
| `pps marketing serve [--port 5050]` | Runs the web app |
| `pps marketing status` | Shows which platforms are configured and connected |
| `pps marketing report [--range 30d] [--format table\|csv\|json]` | Spend and results by channel |
| `pps marketing publish-due` | Sends scheduled posts that are due |
| `pps marketing run-rules [--dry-run]` | Evaluates automation rules |

## Good to know

- **Conversions** are each platform's own count, so attribution windows differ:
  - Google Ads: primary conversion actions.
  - Meta: purchases plus leads. Purchase action types are never double-counted.
  - Pinterest: total conversions.
  - X: purchases plus sign-ups.
  - LinkedIn: website conversions.
  - TikTok: the optimization event.
  - Microsoft Advertising: goals counted in its Conversions column.

  Compare each channel with its own history first.
- **Revenue and ROAS** need conversion values set up on each platform (pixel or tag purchase values). Lead-generation campaigns show "—" for ROAS.
- **Freshness:** numbers are cached for 15 minutes (`MARKETING_CACHE_MINUTES`). Use **Refresh** to fetch new ones. "Last N days" ends yesterday, like the platforms' own dashboards.
- **Images** for posts must be public `https://` URLs. Your website's media library works. Instagram needs JPEGs.
- **Currencies:** if your accounts use different currencies, totals add them up as-is and the dashboard warns you.

## Security

- `marketing.db` holds the platforms' access tokens. It's created readable only by your user and is ignored by git. Keep it private and back it up like a password file.
- The hub listens on `127.0.0.1` by default. If you open it to other machines, set `MARKETING_APP_PASSWORD` and put it behind HTTPS.
- Every form and button that changes something carries a CSRF token, so other websites can't trigger changes through your browser.
- Disconnecting a platform deletes its tokens from the hub. You can also revoke the app's access in that platform's settings.

## For developers

Everything lives in `src/pps_tools/marketing/`:

| File | Purpose |
|---|---|
| `platforms/*.py` | One connector per platform behind a common `Platform` interface (`base.py`). `demo.py` generates the sample data |
| `hub.py` | Combines connectors, caching, demo mode, error isolation and the activity log |
| `store.py` | SQLite persistence |
| `analytics.py`, `pacing.py` | Totals, breakdowns, period comparisons and budget pacing |
| `publisher.py` | Cross-posting, per-network checks and the scheduler |
| `rules.py` | Automation rules |
| `ai.py`, `copywriter.py`, `insights.py` | Claude features (structured outputs with server-side fallback) |
| `app.py`, `templates/`, `static/` | Flask UI; dependency-free SVG charts in `static/mk.js` |

Run the tests with `pytest tests/test_marketing`. They mock every platform API, so no credentials are needed.

API versions in use (October 2026): Google Ads v26, Meta Graph/Marketing API v26.0, Pinterest v5, X API v2 + Ads API v12, LinkedIn `202610`, TikTok Business API v1.3, Microsoft Advertising API v13 (REST). You can override the Google Ads, Meta, X Ads and LinkedIn versions in `.env`.

Possible next steps:
- TikTok organic posting. This needs TikTok's Content Posting API audit.
- Uploading images straight from your computer through the WordPress media library.
