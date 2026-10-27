"""Flask web app for the PPS Marketing Hub.

Pages:
    /             Dashboard — cross-platform KPIs, daily spend by channel, pacing
    /campaigns    Every campaign on every platform; pause / enable / change budget
    /publish      Write once, post to Facebook, Instagram, Pinterest, X and LinkedIn; schedule; calendar
    /studio       AI Studio — Claude writes platform-ready ad copy
    /insights     AI performance review with one-click fixes
    /automation   Rules that pause, scale or flag campaigns
    /budgets      Monthly budgets and pacing
    /utm          UTM link builder
    /connections  Connect platforms, pick accounts, demo mode
    /activity     Log of every change made through the hub

Every state-changing request needs the session's CSRF token, and an
optional password (MARKETING_APP_PASSWORD) protects the whole app.
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import math
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import Markup

from pps_tools.marketing import analytics as an
from pps_tools.marketing import rules as rules_mod
from pps_tools.marketing import store as st
from pps_tools.marketing.ai import AIError, ai_configured
from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.copywriter import FORMATS, GOALS, CopyBrief, Copywriter
from pps_tools.marketing.http import NotConnectedError, PlatformAPIError
from pps_tools.marketing.hub import HubError, MarketingHub
from pps_tools.marketing.insights import Analyst, apply_recommendation, build_snapshot
from pps_tools.marketing.models import ACTIVE, NETWORKS, PAUSED, network_for
from pps_tools.marketing.pacing import month_key, pacing_for
from pps_tools.marketing.publisher import (
    INSTAGRAM_MAX_HASHTAGS,
    PINTEREST_TITLE_LIMIT,
    TEXT_LIMITS,
    Scheduler,
    publish_post,
    resolve_targets,
    validate,
)
from pps_tools.marketing.store import Store
from pps_tools.marketing.utm import NETWORK_PRESETS, UTMError, build_url, google_ads_final_url_suffix

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent

NAV = [
    ("dashboard", "Dashboard", "grid"),
    ("campaigns", "Campaigns", "bars"),
    ("publish", "Publish", "send"),
    ("studio", "AI Studio", "sparkle"),
    ("insights", "Insights", "bulb"),
    ("automation", "Automation", "bolt"),
    ("budgets", "Budgets", "wallet"),
    ("utm", "UTM Builder", "link"),
    ("connections", "Connections", "plug"),
    ("activity", "Activity", "clock"),
]

CURRENCY_SYMBOLS = {"USD": "$", "CAD": "CA$", "AUD": "A$", "EUR": "€", "GBP": "£", "NZD": "NZ$", "MXN": "MX$"}


# -- formatting helpers (also registered as Jinja filters) ------------------------


def money(value: Optional[float], currency: str = "USD", cents: Optional[bool] = None) -> str:
    if value is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if cents is None:
        cents = abs(value) < 1000
    return f"{'-' if value < 0 else ''}{symbol}{abs(value):,.{2 if cents else 0}f}"


def compact(value: Optional[float], prefix: str = "") -> str:
    if value is None:
        return "—"
    v = abs(value)
    sign = "-" if value < 0 else ""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            num = v / div
            return f"{sign}{prefix}{num:.1f}{suffix}" if num < 100 else f"{sign}{prefix}{num:.0f}{suffix}"
    if prefix and v < 1000:
        return f"{sign}{prefix}{v:,.0f}" if v >= 100 else f"{sign}{prefix}{v:,.2f}"
    return f"{sign}{v:,.0f}" if v >= 100 or float(v).is_integer() else f"{sign}{v:,.1f}"


def num(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def pct(value: Optional[float], digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def ratio(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.2f}×"


def roas_text(totals) -> str:
    """ROAS, or a dash when the campaign tracks no revenue (lead gen, awareness)."""
    if not totals or not totals.conversion_value:
        return "—"
    return ratio(totals.roas)


def signed_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{'+' if value >= 0 else '−'}{abs(value) * 100:.0f}%"


def metric_text(metric: str, value: Optional[float], currency: str = "USD") -> str:
    if metric in ("spend", "conversion_value", "cpa", "cpc", "cpm"):
        return money(value, currency)
    if metric in ("ctr", "cvr"):
        return pct(value)
    if metric == "roas":
        return ratio(value)
    return num(value, 0 if metric != "conversions" or (value or 0) >= 100 else 1)


def objective_text(value: Optional[str]) -> str:
    """OUTCOME_SALES -> Sales, PERFORMANCE_MAX -> Performance Max."""
    if not value:
        return ""
    text = str(value).upper().removeprefix("OUTCOME_")
    if text == "PERFORMANCE_MAX":
        return "Performance Max"
    words = text.replace("_", " ").lower()
    return words[:1].upper() + words[1:]


def safe_next(target: Optional[str]) -> str:
    """Only follow same-site paths after login (never //host or /\\host tricks)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    parts = urlsplit(target)
    return target if not parts.scheme and not parts.netloc else "/"


def safe_url(url: Optional[str]) -> Optional[str]:
    """Links that came back from a platform are only rendered when they're plain https."""
    return url if isinstance(url, str) and url.startswith("https://") else None


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}"


def long_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def local_time(iso: Optional[str]) -> Markup:
    """A <time> element the browser rewrites into the viewer's local time."""
    if not iso:
        return Markup("")
    return Markup('<time datetime="{0}" data-local>{1} UTC</time>').format(iso, iso[:16].replace("T", " "))


# -- app factory -------------------------------------------------------------------


def create_app(
    settings: Optional[MarketingSettings] = None,
    hub: Optional[MarketingHub] = None,
    start_scheduler: bool = False,
    copywriter: Optional[Copywriter] = None,
    analyst: Optional[Analyst] = None,
) -> Flask:
    settings = settings or (hub.settings if hub else MarketingSettings.from_env())
    hub = hub or MarketingHub(Store(settings.db_path), settings)
    store = hub.store

    app = Flask(
        __name__,
        template_folder=str(HERE / "templates"),
        static_folder=str(HERE / "static"),
        static_url_path="/static",
    )
    app.secret_key = settings.secret_key or store.secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.base_url.startswith("https://"),
    )
    app.extensions["marketing_hub"] = hub

    copy_ai = copywriter or Copywriter(settings.brand_context, model=settings.claude_model)
    analyst_ai = analyst or Analyst(
        settings.brand_context, model=settings.claude_model, max_budget_change_pct=settings.max_budget_change_pct
    )

    if start_scheduler:
        scheduler = Scheduler(hub)
        scheduler.start()
        app.extensions["marketing_scheduler"] = scheduler

    for name, fn in {
        "money": money,
        "compact": compact,
        "num": num,
        "pct": pct,
        "ratio": ratio,
        "roas": roas_text,
        "signed_pct": signed_pct,
        "local_time": local_time,
        "safe_url": safe_url,
        "objective": objective_text,
        "short_date": short_date,
        "long_date": long_date,
    }.items():
        app.add_template_filter(fn, name)

    # -- helpers ---------------------------------------------------------------

    def csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def wants_json() -> bool:
        return request.path.startswith("/api/") or request.is_json

    def api_error(message: str, status: int = 400):
        return jsonify({"ok": False, "error": message}), status

    def period_from_args():
        return an.resolve_period(request.args.get("range"), request.args.get("start"), request.args.get("end"))

    def platform_labels() -> dict:
        return {k: p.name for k, p in hub.platforms.items()}

    @app.context_processor
    def inject():
        return {
            "nav": NAV,
            "csrf_token": csrf_token,
            "demo_active": hub.demo_active(),
            "networks": NETWORKS,
            "network_for": network_for,
            "platform_names": platform_labels(),
            "platform_short": {k: p.short_name or p.name for k, p in hub.platforms.items()},
            "ai_ready": ai_configured(),
            "app_password": bool(settings.app_password),
            "presets": an.PRESETS,
            "metric_text": metric_text,
        }

    @app.before_request
    def guard():
        if request.endpoint in ("static", "healthz"):
            return None
        if settings.app_password and not session.get("authed") and request.endpoint != "login":
            if wants_json():
                return api_error("Sign in first.", 401)
            return redirect(url_for("login", next=request.full_path))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(sent, expected):
                if wants_json():
                    return api_error("Your session expired — reload the page and try again.", 400)
                abort(400, "Your session expired — reload the page and try again.")
        return None

    @app.errorhandler(400)
    @app.errorhandler(404)
    def http_error(err):
        if wants_json():
            return api_error(getattr(err, "description", str(err)), err.code)
        return render_template("mk_error.html", error=err), err.code

    # -- auth -------------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not settings.app_password:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("password", ""), settings.app_password):
                session.clear()
                session["authed"] = True
                return redirect(safe_next(request.args.get("next")))
            flash("Wrong password.", "error")
        return render_template("mk_login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True})

    # -- dashboard ---------------------------------------------------------------

    def kpi(metric: str, cur: an.Totals, old: an.Totals, spark: list[float], currency: str) -> dict:
        value, before = cur.metric(metric), old.metric(metric)
        delta = an.change(value, before)
        return {
            "metric": metric,
            "label": an.METRIC_LABELS[metric],
            "value": value,
            "text": metric_text(metric, value, currency) if metric not in ("spend", "conversion_value") else compact(value, CURRENCY_SYMBOLS.get(currency, "$")),
            "delta": delta,
            "delta_text": signed_pct(delta),
            "tone": an.delta_tone(metric, delta),
            "previous_text": metric_text(metric, before, currency),
            "spark": spark,
        }

    @app.route("/")
    def dashboard():
        period = period_from_args()
        refresh = request.args.get("refresh") == "1"
        prev = period.previous()
        # The four lookups are independent; on a cold cache each is a round trip to every platform.
        with ThreadPoolExecutor(max_workers=4) as pool:
            current_job = pool.submit(hub.metrics, period.start, period.end, refresh)
            previous_job = pool.submit(hub.metrics, prev.start, prev.end, refresh)
            campaigns_job = pool.submit(hub.campaigns, refresh)
            pacing_job = pool.submit(pacing_for, hub)
            rows, errors = current_job.result()
            prev_rows, _ = previous_job.result()
            campaigns, campaign_errors = campaigns_job.result()
            pacing = pacing_job.result()
        currencies = an.currencies(rows)
        currency = currencies[0] if currencies else "USD"
        cur, old = an.totals(rows), an.totals(prev_rows)

        def series(metric: str) -> list[float]:
            return an.daily(rows, period.start, period.end, metric)["total"]

        kpis = [kpi(m, cur, old, series(m), currency) for m in ("spend", "conversion_value", "roas", "conversions", "cpa", "ctr")]
        days = an.days_between(period.start, period.end)
        by_net_daily = an.daily(rows, period.start, period.end, "spend", key=lambda r: r.network if r.network in NETWORKS else "other")
        chart = {
            "days": days,
            "currency": CURRENCY_SYMBOLS.get(currency, ""),
            "series": [
                {"key": k, "label": NETWORKS[k].label, "slot": NETWORKS[k].slot, "values": by_net_daily[k]}
                for k in NETWORKS
                if k in by_net_daily
            ],
            "conversions": series("conversions"),
        }
        networks = an.by_network(rows)
        top_spend = max((t.spend for _, t in networks), default=0) or 1

        errors.update(campaign_errors)
        by_key = {c.key: c for c in campaigns}
        by_campaign = an.by_campaign(rows)
        names = {r.campaign_key: r.campaign_name for r in rows}
        top = sorted(by_campaign.items(), key=lambda kv: -kv[1].spend)[:8]
        spark_spend = an.daily(rows, period.start, period.end, "spend", key=lambda r: r.campaign_key)
        top_campaigns = [
            {
                "key": key,
                "name": (by_key[key].name if key in by_key else names.get(key, key)),
                "platform": key.split(":", 1)[0],
                "status": by_key[key].status if key in by_key else None,
                "totals": t,
                "spark": spark_spend.get(key, []),
            }
            for key, t in top
        ]
        return render_template(
            "mk_dashboard.html",
            period=period,
            previous=prev,
            kpis=kpis,
            chart=chart,
            networks=[(k, t, t.spend / top_spend) for k, t in networks],
            totals=cur,
            currency=currency,
            currencies=currencies,
            errors=errors,
            top_campaigns=top_campaigns,
            pacing=pacing,
            connected=hub.sources(),
        )

    @app.route("/export.csv")
    def export_csv():
        period = period_from_args()
        rows, _ = hub.metrics(period.start, period.end)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["date", "platform", "network", "account_id", "campaign_id", "campaign", "impressions",
                         "clicks", "spend", "conversions", "conversion_value", "currency"])
        for r in sorted(rows, key=lambda r: (r.date, r.platform, r.campaign_name)):
            writer.writerow([r.date, r.platform, r.network, r.account_id, r.campaign_id, r.campaign_name,
                             r.impressions, r.clicks, f"{r.spend:.2f}", f"{r.conversions:.2f}",
                             f"{r.conversion_value:.2f}", r.currency])
        filename = f"ad-performance-{period.start}-to-{period.end}.csv"
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    # -- campaigns ---------------------------------------------------------------

    @app.route("/campaigns")
    def campaigns():
        period = period_from_args()
        refresh = request.args.get("refresh") == "1"
        found, errors = hub.campaigns(refresh=refresh)
        rows, metric_errors = hub.metrics(period.start, period.end, refresh=refresh)
        errors.update(metric_errors)
        by_campaign = an.by_campaign(rows)
        spark = an.daily(rows, period.start, period.end, "spend", key=lambda r: r.campaign_key)
        networks_by_campaign: dict[str, set] = {}
        for r in rows:
            networks_by_campaign.setdefault(r.campaign_key, set()).add(r.network)
        items = []
        for c in found:
            t = by_campaign.get(c.key, an.Totals())
            if c.status not in (ACTIVE, PAUSED) and not t.spend:
                continue
            items.append({
                "c": c,
                "t": t,
                "spark": spark.get(c.key, []),
                "networks": sorted(networks_by_campaign.get(c.key, set(hub.platform(c.platform).networks[:1])),
                                   key=lambda n: list(NETWORKS).index(n) if n in NETWORKS else 99),
            })
        items.sort(key=lambda i: (-i["t"].spend, i["c"].name.lower()))
        return render_template(
            "mk_campaigns.html",
            period=period,
            items=items,
            errors=errors,
            totals=an.totals(rows),
            max_change=settings.max_budget_change_pct,
        )

    @app.route("/api/campaigns/status", methods=["POST"])
    def api_campaign_status():
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status", "")).upper()
        try:
            c = hub.set_campaign_status(str(payload.get("key", "")), status)
        except (HubError, PlatformAPIError, NotConnectedError, ValueError) as exc:
            return api_error(getattr(exc, "message", None) or str(exc))
        return jsonify({"ok": True, "status": c.status, "message": f"{'Paused' if c.status == PAUSED else 'Enabled'} “{c.name}”."})

    @app.route("/api/campaigns/budget", methods=["POST"])
    def api_campaign_budget():
        payload = request.get_json(silent=True) or {}
        try:
            amount = float(payload.get("amount"))
            c = hub.set_campaign_budget(str(payload.get("key", "")), amount)
        except (TypeError, ValueError):
            return api_error("Enter the new daily budget as a number.")
        except (HubError, PlatformAPIError, NotConnectedError) as exc:
            return api_error(getattr(exc, "message", None) or str(exc))
        return jsonify({"ok": True, "daily_budget": c.daily_budget,
                        "text": money(c.daily_budget, c.currency, cents=True),
                        "message": f"Daily budget for “{c.name}” is now {money(c.daily_budget, c.currency, cents=True)}."})

    # -- publishing --------------------------------------------------------------

    def post_from_form(form) -> dict:
        overrides = {n: form.get(f"override_{n}", "").strip() for n in TEXT_LIMITS if form.get(f"override_{n}", "").strip()}
        return {
            "body": form.get("body", "").strip(),
            "link": form.get("link", "").strip() or None,
            "image_url": form.get("image_url", "").strip() or None,
            "title": form.get("title", "").strip() or None,
            "overrides": overrides,
            "utm_campaign": form.get("utm_campaign", "").strip() or None,
            "targets": form.getlist("targets"),
        }

    @app.route("/publish", methods=["GET", "POST"])
    def publish():
        targets = hub.targets()
        if request.method == "POST":
            post = post_from_form(request.form)
            mode = request.form.get("mode", "now")
            chosen = resolve_targets(hub, post["targets"])
            problems = validate(post, chosen) if mode != "draft" else []
            scheduled_at = None
            if mode == "schedule":
                try:
                    when = datetime.fromisoformat(request.form.get("scheduled_utc", "").replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    if when < datetime.now(timezone.utc) - timedelta(minutes=1):
                        problems.append("Pick a time in the future.")
                    scheduled_at = st.utc_iso(when)
                except ValueError:
                    problems.append("Pick a date and time to schedule the post.")
            if problems:
                for p in problems:
                    flash(p, "error")
                return render_template("mk_publish.html", **publish_context(targets, post))
            status = {"draft": st.DRAFT, "schedule": st.SCHEDULED}.get(mode, st.DRAFT)
            edit_id = request.form.get("post_id", type=int)
            if edit_id and (existing := store.get_post(edit_id)) and existing["status"] in (st.DRAFT, st.SCHEDULED):
                store.update_post(edit_id, body=post["body"], link=post["link"], image_url=post["image_url"],
                                  title=post["title"], targets=post["targets"], overrides=post["overrides"],
                                  utm_campaign=post["utm_campaign"], status=status, scheduled_at=scheduled_at)
                post_id = edit_id
            else:
                post_id = store.create_post(status=status, scheduled_at=scheduled_at, **post)
            if mode == "now":
                result = publish_post(hub, post_id)
                flash_publish_result(result)
            elif mode == "schedule":
                flash("Post scheduled. It goes out automatically while the hub is running "
                      "(or run `pps marketing publish-due` from cron).", "success")
            else:
                flash("Draft saved.", "success")
            return redirect(url_for("publish"))

        prefill = None
        edit_id = request.args.get("edit", type=int)
        if edit_id:
            prefill = store.get_post(edit_id)
            if not prefill or prefill["status"] not in (st.DRAFT, st.SCHEDULED):
                flash("Only drafts and scheduled posts can be edited.", "error")
                prefill = None
        return render_template("mk_publish.html", **publish_context(targets, prefill))

    def flash_publish_result(post: Optional[dict]) -> None:
        if post is None:
            flash("That post is already being published.", "info")
            return
        results = post["results"]
        ok = [r for r in results.values() if r.get("ok")]
        bad = [r for r in results.values() if not r.get("ok")]
        if ok and not bad:
            flash(f"Published to {len(ok)} destination{'s' if len(ok) != 1 else ''}.", "success")
        elif ok:
            flash(f"Published to {len(ok)}, failed on {len(bad)}: " + "; ".join(r.get("error", "") for r in bad), "error")
        else:
            flash("Publishing failed: " + "; ".join(r.get("error", "") for r in bad), "error")

    def publish_context(targets, post=None) -> dict:
        store.fail_stale_publishing()
        posts = store.list_posts(limit=300)
        target_names = {t.key: (t.network, t.name) for t in hub.targets(enabled_only=False)}
        calendar = [
            {
                "id": p["id"],
                "status": p["status"],
                "when": p["scheduled_at"] or p["published_at"] or p["created_at"],
                "text": p["body"][:80],
                "networks": sorted({target_names[k][0] for k in p["targets"] if k in target_names}),
            }
            for p in posts
            if p["status"] != st.DRAFT
        ]
        tab = request.args.get("tab", "queue")
        return {
            "targets": targets,
            "post": post,
            "queue": [p for p in posts if p["status"] in (st.SCHEDULED, st.DRAFT, st.PUBLISHING)],
            "history": [p for p in posts if p["status"] in (st.PUBLISHED, st.PARTIAL, st.FAILED)][:40],
            "calendar": calendar,
            "target_names": target_names,
            "limits": TEXT_LIMITS,
            "pinterest_title_limit": PINTEREST_TITLE_LIMIT,
            "instagram_max_hashtags": INSTAGRAM_MAX_HASHTAGS,
            "tab": tab if tab in ("queue", "calendar", "history") else "queue",
        }

    @app.route("/posts/<int:post_id>/publish", methods=["POST"])
    def post_publish_now(post_id: int):
        post = store.get_post(post_id)
        if not post:
            abort(404)
        retry = post["status"] in (st.PARTIAL, st.FAILED)
        if not retry:
            chosen = resolve_targets(hub, post["targets"])
            problems = validate(post, chosen)
            if problems:
                for p in problems:
                    flash(p, "error")
                return redirect(url_for("publish"))
        flash_publish_result(publish_post(hub, post_id, retry_failed=retry))
        return redirect(url_for("publish"))

    @app.route("/posts/<int:post_id>/delete", methods=["POST"])
    def post_delete(post_id: int):
        if store.delete_post(post_id):
            flash("Post removed.", "info")
        else:
            flash("Published posts stay in the history.", "error")
        return redirect(url_for("publish"))

    # -- AI studio -----------------------------------------------------------------

    @app.route("/studio")
    def studio():
        formats_json = {
            key: {
                "label": f.label,
                "network": f.network,
                "slot": network_for(f.network).slot,
                "fields": [
                    {"name": fs.name, "label": fs.label, "limit": fs.limit, "recommended": fs.recommended,
                     "items": list(fs.items) if fs.items else None, "counter": fs.counter}
                    for fs in f.fields
                ],
            }
            for key, f in FORMATS.items()
        }
        return render_template("mk_studio.html", formats=FORMATS, formats_json=formats_json, goals=GOALS,
                               library=store.list_copy(30), model=settings.claude_model)

    @app.route("/api/studio/generate", methods=["POST"])
    def api_studio_generate():
        payload = request.get_json(silent=True) or {}
        try:
            brief = CopyBrief(
                product=str(payload.get("product", "")),
                formats=[str(f) for f in payload.get("formats") or []],
                offer=str(payload.get("offer", "")),
                audience=str(payload.get("audience", "")),
                tone=str(payload.get("tone", "")),
                goal=str(payload.get("goal", "conversions")),
                landing_url=str(payload.get("landing_url", "")),
                keywords=str(payload.get("keywords", "")),
                notes=str(payload.get("notes", "")),
                variants=int(payload.get("variants") or 3),
            )
            result = copy_ai.generate(brief)
        except AIError as exc:
            return api_error(str(exc))
        except (TypeError, ValueError):
            return api_error("Some of the brief's fields weren't valid.")
        store.log("ai.copy", f"Generated ad copy for “{brief.product[:60]}”", detail={"formats": brief.formats})
        return jsonify({"ok": True, "result": result.to_dict(), "brief": brief.to_dict()})

    @app.route("/api/studio/save", methods=["POST"])
    def api_studio_save():
        payload = request.get_json(silent=True) or {}
        brief, result = payload.get("brief"), payload.get("result")
        if not isinstance(brief, dict) or not isinstance(result, dict):
            return api_error("Nothing to save.")
        title = str(payload.get("title") or brief.get("product") or "Ad copy")[:120]
        copy_id = store.save_copy(title, brief, result)
        return jsonify({"ok": True, "id": copy_id})

    @app.route("/studio/library/<int:copy_id>/delete", methods=["POST"])
    def studio_delete(copy_id: int):
        store.delete_copy(copy_id)
        flash("Removed from the library.", "info")
        return redirect(url_for("studio"))

    # -- insights ------------------------------------------------------------------

    def quick_checks(period: an.Period) -> list[dict]:
        """Rule-of-thumb findings that don't need AI."""
        rows, _ = hub.metrics(period.start, period.end)
        prev = period.previous()
        prev_rows, _ = hub.metrics(prev.start, prev.end)
        checks = []
        names = {r.campaign_key: r.campaign_name for r in rows}
        for key, t in sorted(an.by_campaign(rows).items(), key=lambda kv: -kv[1].spend):
            if t.spend >= 50 and t.conversions == 0:
                checks.append({"tone": "critical", "text": f"“{names[key]}” spent {money(t.spend)} with no conversions."})
        nets = [(k, t) for k, t in an.by_network(rows) if t.spend >= 50 and t.roas is not None]
        if len(nets) >= 2:
            best = max(nets, key=lambda kv: kv[1].roas)
            worst = min(nets, key=lambda kv: kv[1].roas)
            checks.append({"tone": "good", "text": f"{network_for(best[0]).label} returns the most per dollar: {ratio(best[1].roas)} ROAS."})
            if worst[0] != best[0]:
                checks.append({"tone": "warning", "text": f"{network_for(worst[0]).label} returns the least: {ratio(worst[1].roas)} ROAS."})
        prev_by = an.by_campaign(prev_rows)
        movers = []
        for key, t in an.by_campaign(rows).items():
            before = prev_by.get(key)
            if before and before.cpa and t.cpa and t.conversions >= 3:
                movers.append((an.change(t.cpa, before.cpa), key, t, before))
        movers.sort(key=lambda m: -(m[0] or 0))
        for change, key, t, before in movers[:2]:
            if change and change > 0.25:
                checks.append({"tone": "warning", "text": f"Cost per conversion on “{names[key]}” rose {signed_pct(change)} "
                               f"({money(before.cpa)} → {money(t.cpa)})."})
        return checks[:8]

    @app.route("/insights")
    def insights():
        period = period_from_args()
        return render_template("mk_insights.html", period=period, checks=quick_checks(period), model=settings.claude_model)

    @app.route("/api/insights", methods=["POST"])
    def api_insights():
        payload = request.get_json(silent=True) or {}
        period = an.resolve_period(payload.get("range"), payload.get("start"), payload.get("end"))
        try:
            snapshot = build_snapshot(hub, period)
            report = analyst_ai.analyze(snapshot, str(payload.get("question", "")))
        except AIError as exc:
            return api_error(str(exc))
        store.log("ai.insights", f"AI review of {period.label.lower()}", detail={"headline": report.get("headline")})
        return jsonify({"ok": True, "report": report, "platforms": platform_labels()})

    @app.route("/api/insights/apply", methods=["POST"])
    def api_insights_apply():
        rec = request.get_json(silent=True) or {}
        try:
            message = apply_recommendation(hub, rec)
        except (AIError, HubError, PlatformAPIError, NotConnectedError) as exc:
            return api_error(getattr(exc, "message", None) or str(exc))
        return jsonify({"ok": True, "message": message})

    # -- automation ----------------------------------------------------------------

    @app.route("/automation")
    def automation():
        edit = store.get_rule(request.args.get("edit", type=int) or -1)
        template = request.args.get("template", type=int)
        rule = edit or (dict(rules_mod.DEFAULT_RULE, **rules_mod.TEMPLATES[template]) if template is not None
                        and 0 <= template < len(rules_mod.TEMPLATES) else None)
        rules = store.list_rules()
        return render_template(
            "mk_automation.html",
            rules=[dict(r, description=rules_mod.describe(r)) for r in rules],
            rule=rule,
            templates=rules_mod.TEMPLATES,
            metrics=rules_mod.METRICS,
            operators=list(rules_mod.OPERATORS),
            actions=rules_mod.ACTIONS,
            lookbacks=rules_mod.LOOKBACKS,
            percent_metrics=rules_mod.PERCENT_METRICS,
            max_change=settings.max_budget_change_pct,
        )

    @app.route("/automation/rules", methods=["POST"])
    def automation_save():
        form = request.form.to_dict()
        form["enabled"] = "enabled" in request.form
        rule_id = request.form.get("rule_id", type=int)
        try:
            rule = rules_mod.clean_rule(form, list(hub.platforms), settings.max_budget_change_pct)
        except rules_mod.RuleError as exc:
            flash(str(exc), "error")
            return redirect(url_for("automation", edit=rule_id) if rule_id else url_for("automation"))
        store.save_rule(rule, rule_id)
        store.log("rule.save", f"{'Updated' if rule_id else 'Created'} rule “{rule['name']}”", detail=rule)
        flash("Rule saved. Preview it with a dry run before letting it act.", "success")
        return redirect(url_for("automation"))

    @app.route("/automation/rules/<int:rule_id>/toggle", methods=["POST"])
    def automation_toggle(rule_id: int):
        rule = store.get_rule(rule_id)
        if rule:
            store.set_rule_enabled(rule_id, not rule["enabled"])
        return redirect(url_for("automation"))

    @app.route("/automation/rules/<int:rule_id>/delete", methods=["POST"])
    def automation_delete(rule_id: int):
        rule = store.get_rule(rule_id)
        store.delete_rule(rule_id)
        if rule:
            store.log("rule.delete", f"Deleted rule “{rule['name']}”")
        flash("Rule deleted.", "info")
        return redirect(url_for("automation"))

    @app.route("/api/automation/run", methods=["POST"])
    def api_automation_run():
        payload = request.get_json(silent=True) or {}
        dry_run = bool(payload.get("dry_run", True))
        rule_id = payload.get("rule_id")
        rules = [store.get_rule(int(rule_id))] if rule_id else store.list_rules(enabled_only=True)
        rules = [r for r in rules if r]
        if not rules:
            return api_error("No enabled rules to run.")
        problems: dict = {}
        try:
            outcomes = rules_mod.evaluate(hub, rules, dry_run=dry_run, problems=problems)
        except (PlatformAPIError, NotConnectedError) as exc:
            return api_error(getattr(exc, "message", None) or str(exc))
        if not dry_run:
            store.log("rule.run", f"Ran {len(rules)} rule(s): {len(outcomes)} match(es)",
                      detail={"applied": sum(1 for o in outcomes if o.status in ("applied", "alerted")),
                              "skipped_accounts": problems})
        return jsonify({"ok": True, "dry_run": dry_run, "outcomes": [o.to_dict() for o in outcomes],
                        "platforms": platform_labels(), "problems": problems})

    # -- budgets ---------------------------------------------------------------------

    @app.route("/budgets", methods=["GET", "POST"])
    def budgets():
        month = request.values.get("month") or month_key(date.today())
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            month = month_key(date.today())
        keys = ["total", *hub.platforms]
        labels = platform_labels()
        labels["total"] = "All platforms"
        if request.method == "POST":
            bad = []
            for key in keys:
                raw = request.form.get(f"budget_{key}", "").replace(",", "").replace("$", "").strip()
                try:
                    amount = float(raw) if raw else None
                except ValueError:
                    amount = float("nan")
                if amount is not None and (not math.isfinite(amount) or amount < 0):
                    bad.append(labels.get(key, key))
                    continue
                store.set_budget(month, key, amount)
            if bad:
                flash(f"Not saved — enter a plain amount for: {', '.join(bad)}. The other budgets were saved.", "error")
            else:
                flash("Budgets saved.", "success")
            return redirect(url_for("budgets", month=month))
        current = month_key(date.today())
        return render_template(
            "mk_budgets.html",
            month=month,
            months=[current, month_key(date.today().replace(day=28) + timedelta(days=5))],
            budgets=store.get_budgets(month),
            keys=keys,
            labels=labels,
            pacing=pacing_for(hub) if month == current else [],
        )

    # -- UTM builder ---------------------------------------------------------------

    @app.route("/utm", methods=["GET", "POST"])
    def utm():
        if request.method == "POST":
            f = request.form
            try:
                url = build_url(f.get("url", ""), f.get("source", ""), f.get("medium", ""), f.get("campaign", ""),
                                f.get("term"), f.get("content"))
            except UTMError as exc:
                flash(str(exc), "error")
                return redirect(url_for("utm"))
            store.save_utm_link(url, f.get("label", "").strip() or None)
            flash("Link saved.", "success")
            return redirect(url_for("utm"))
        return render_template("mk_utm.html", links=store.list_utm_links(), presets=NETWORK_PRESETS,
                               final_url_suffix=google_ads_final_url_suffix())

    @app.route("/utm/<int:link_id>/delete", methods=["POST"])
    def utm_delete(link_id: int):
        store.delete_utm_link(link_id)
        return redirect(url_for("utm"))

    # -- connections ------------------------------------------------------------------

    @app.route("/connections")
    def connections():
        cards = []
        for key, p in hub.platforms.items():
            conn = store.get_connection(key)
            cards.append({
                "p": p,
                "connection": conn,
                "accounts": store.list_accounts(key) if conn else [],
                "targets": store.list_targets(key) if conn else [],
                "warning": p.token_warning() if conn else None,
                "env": [(v, bool(p.env(v))) for v in p.env_vars],
                "keys_available": getattr(p, "has_api_keys", False),
            })
        return render_template("mk_connections.html", cards=cards, demo_setting=hub.demo_setting(),
                               model=settings.claude_model, base_url=settings.base_url)

    @app.route("/connections/demo", methods=["POST"])
    def connections_demo():
        try:
            hub.set_demo_setting(request.form.get("mode", "auto"))
        except HubError as exc:
            flash(str(exc), "error")
        return redirect(url_for("connections"))

    @app.route("/oauth/<platform>/start")
    def oauth_start(platform: str):
        p = hub.platforms.get(platform) or abort(404)
        if p.missing_env():
            flash(f"Add {', '.join(p.missing_env())} to your .env file first.", "error")
            return redirect(url_for("connections"))
        return redirect(p.authorization_url())

    @app.route("/oauth/<platform>/callback")
    def oauth_callback(platform: str):
        p = hub.platforms.get(platform) or abort(404)
        try:
            p.connect(request.args)
        except (PlatformAPIError, NotConnectedError) as exc:
            store.log("connection.error", f"Connecting {p.name} failed: {getattr(exc, 'message', exc)}", platform, ok=False)
            flash(f"Couldn't connect {p.name}: {getattr(exc, 'message', exc)}", "error")
            return redirect(url_for("connections"))
        store.log("connection.add", f"Connected {p.name}", platform)
        accounts = store.list_accounts(platform)
        targets = store.list_targets(platform)
        flash(f"Connected {p.name}: {len(accounts)} ad account(s), {len(targets)} place(s) to publish.", "success")
        return redirect(url_for("connections"))

    @app.route("/connections/<platform>/keys", methods=["POST"])
    def connections_keys(platform: str):
        p = hub.platforms.get(platform) or abort(404)
        if not hasattr(p, "connect_with_keys"):
            abort(404)
        try:
            p.connect_with_keys()
        except (PlatformAPIError, NotConnectedError) as exc:
            flash(f"Couldn't connect {p.name}: {getattr(exc, 'message', exc)}", "error")
            return redirect(url_for("connections"))
        store.log("connection.add", f"Connected {p.name} with API keys", platform)
        flash(f"Connected {p.name}.", "success")
        return redirect(url_for("connections"))

    @app.route("/connections/<platform>/refresh", methods=["POST"])
    def connections_refresh(platform: str):
        p = hub.platforms.get(platform) or abort(404)
        try:
            p.refresh_discovery()
            flash(f"Refreshed {p.name} accounts.", "success")
        except (PlatformAPIError, NotConnectedError) as exc:
            flash(f"Couldn't refresh {p.name}: {getattr(exc, 'message', exc)}", "error")
        return redirect(url_for("connections"))

    @app.route("/connections/<platform>/disconnect", methods=["POST"])
    def connections_disconnect(platform: str):
        p = hub.platforms.get(platform) or abort(404)
        p.disconnect()
        store.log("connection.remove", f"Disconnected {p.name}", platform)
        flash(f"Disconnected {p.name}. Revoke the app's access on {p.name} too if you no longer use it.", "info")
        return redirect(url_for("connections"))

    @app.route("/connections/<platform>/accounts/toggle", methods=["POST"])
    def connections_account_toggle(platform: str):
        store.set_account_enabled(platform, request.form.get("account_id", ""), request.form.get("enabled") == "1")
        store.cache_clear(f"metrics:{platform}:")
        store.cache_clear(f"campaigns:{platform}:")
        return redirect(url_for("connections"))

    @app.route("/connections/<platform>/targets/toggle", methods=["POST"])
    def connections_target_toggle(platform: str):
        store.set_target_enabled(platform, request.form.get("network", ""), request.form.get("target_id", ""),
                                 request.form.get("enabled") == "1")
        return redirect(url_for("connections"))

    # -- activity ----------------------------------------------------------------------

    @app.route("/activity")
    def activity():
        page = max(request.args.get("page", 1, type=int), 1)
        items = store.list_activity(limit=51, offset=(page - 1) * 50)
        return render_template("mk_activity.html", items=items[:50], page=page, more=len(items) > 50)

    return app
