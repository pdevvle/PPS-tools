"""Sidebar integrations shown next to a conversation.

kinds:
  iframe       — any web app, given a URL template such as
                 https://crm.example.com/lookup?email={{contact.email}}
                 Variables: contact.email, contact.name, contact.phone, contact.address,
                 contact.organization, conversation.id, conversation.subject.
  woocommerce  — recent orders for the contact's email from a WooCommerce store, via the
                 store's REST API (consumer key + secret; read-only keys are enough).

Secrets (the WooCommerce key and secret) never leave the server; responses carry a
masked hint instead, and saving the masked value keeps the stored one.
"""

from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote, urlparse

import requests

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.util import now_iso

KINDS = ("iframe", "woocommerce")
SECRET_FIELDS = {"woocommerce": ("consumer_key", "consumer_secret")}
MASK = "••••••••"
CACHE_SECONDS = 300
WOO_TIMEOUT = 8
VARIABLES = ("contact.email", "contact.name", "contact.phone", "contact.address", "contact.organization",
             "conversation.id", "conversation.subject")

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


class IntegrationError(Exception):
    pass


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return MASK + value[-4:] if len(value) > 8 else MASK


def get(integration_id: int) -> dict | None:
    return db.one("SELECT * FROM integrations WHERE id = ?", integration_id)


def serialize(row: dict, admin: bool = False) -> dict:
    config = db.jload(row["config_json"], {}) or {}
    public: dict = {}
    if row["kind"] == "iframe":
        public = {"url": config.get("url"), "height": config.get("height") or 320}
    elif row["kind"] == "woocommerce":
        public = {"store_url": config.get("store_url")}
        if admin:
            for field in SECRET_FIELDS["woocommerce"]:
                public[field] = _mask(config.get(field))
    return {
        "id": row["id"], "kind": row["kind"], "name": row["name"], "config": public,
        "is_active": bool(row["is_active"]), "position": row["position"], "created_at": row["created_at"],
    }


def _clean_store_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IntegrationError("Enter the store's address, like https://shop.example.com")
    return url


def clean_config(kind: str, data: dict, existing: dict | None = None) -> dict:
    """Validate a config from the settings form; masked secrets keep their stored value."""
    existing = existing or {}
    if kind == "iframe":
        url = (data.get("url") or "").strip()
        if not url.lower().startswith("https://"):
            raise IntegrationError("The app's URL must start with https://")
        unknown = [v for v in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", url) if v not in VARIABLES]
        if unknown:
            raise IntegrationError(f"Unknown variable: {{{{{unknown[0]}}}}}")
        try:
            height = int(data.get("height") or 320)
        except (TypeError, ValueError):
            height = 320
        return {"url": url, "height": max(120, min(height, 1200))}
    if kind == "woocommerce":
        out = {"store_url": _clean_store_url(data.get("store_url"))}
        for field in SECRET_FIELDS["woocommerce"]:
            value = (data.get(field) or "").strip()
            if not value or value.startswith(MASK):
                value = existing.get(field) or ""
            if not value:
                raise IntegrationError("Add the WooCommerce consumer key and secret")
            out[field] = value
        return out
    raise IntegrationError(f"Unknown integration kind '{kind}'")


# -- context for a conversation -------------------------------------------------------


def _context_values(conv: dict) -> dict:
    contact = contacts_svc.get(conv.get("contact_id")) or {}
    org = db.one("SELECT name, address FROM organizations WHERE id = ?", contact.get("organization_id")) \
        if contact.get("organization_id") else None
    return {
        "contact.email": contact.get("email") or "",
        "contact.name": contact.get("name") or "",
        "contact.phone": contact.get("phone") or "",
        "contact.address": contact.get("address") or (org or {}).get("address") or "",
        "contact.organization": (org or {}).get("name") or "",
        "conversation.id": str(conv["id"]),
        "conversation.subject": conv.get("subject") or "",
    }


def render_url(template: str, values: dict) -> str:
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: quote(values.get(m.group(1), ""), safe=""), template)


def _woo_orders(config: dict, email: str) -> list[dict]:
    store = config["store_url"]
    try:
        resp = requests.get(
            f"{store}/wp-json/wc/v3/orders",
            params={"search": email, "per_page": 5, "orderby": "date", "order": "desc"},
            auth=(config["consumer_key"], config["consumer_secret"]),
            timeout=WOO_TIMEOUT,
        )
    except requests.Timeout:
        raise IntegrationError("The store took too long to answer.")
    except requests.RequestException:
        raise IntegrationError("Couldn't reach the store.")
    if resp.status_code in (401, 403):
        raise IntegrationError("WooCommerce rejected the API keys. Check them in Settings → Sidebar apps.")
    if resp.status_code == 404:
        raise IntegrationError("No WooCommerce API at that address. Check the store URL.")
    if resp.status_code >= 400:
        raise IntegrationError(f"The store returned an error (HTTP {resp.status_code}).")
    try:
        orders = resp.json()
    except ValueError:
        raise IntegrationError("The store sent something that isn't WooCommerce data.")
    if not isinstance(orders, list):
        raise IntegrationError("The store sent something that isn't WooCommerce data.")
    out = []
    for o in orders:
        billing = (o.get("billing") or {}).get("email") or ""
        if billing and billing.strip().lower() != email.lower():
            continue  # 'search' matches substrings; keep only this customer's orders
        out.append({
            "id": o.get("id"),
            "number": str(o.get("number") or o.get("id")),
            "status": o.get("status"),
            "total": o.get("total"),
            "currency": o.get("currency") or "USD",
            "date": (o.get("date_created_gmt") + "Z") if o.get("date_created_gmt") else o.get("date_created"),
            "items": [{"name": li.get("name"), "quantity": li.get("quantity")} for li in o.get("line_items") or []],
            "url": f"{store}/wp-admin/post.php?post={o.get('id')}&action=edit",
        })
    return out


def context(row: dict, conv: dict) -> dict:
    """What the sidebar panel shows for this conversation."""
    config = db.jload(row["config_json"], {}) or {}
    values = _context_values(conv)
    if row["kind"] == "iframe":
        template = config.get("url") or ""
        missing = [v for v in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", template) if not values.get(v)]
        if missing:
            what = missing[0].split(".", 1)[1].replace("_", " ")
            return {"kind": "iframe", "url": None, "message": f"Needs the {what} for this {missing[0].split('.')[0]}."}
        url = render_url(template, values)
        if not url.lower().startswith("https://"):
            return {"kind": "iframe", "url": None, "message": "This app's URL isn't https, so it can't be shown."}
        return {"kind": "iframe", "url": url, "height": config.get("height") or 320}
    if row["kind"] == "woocommerce":
        email = values["contact.email"]
        if not email:
            return {"kind": "woocommerce", "orders": [], "message": "No email address for this contact."}
        key = (row["id"], email.lower(), row["config_json"])
        with _cache_lock:
            hit = _cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        try:
            result = {"kind": "woocommerce", "orders": _woo_orders(config, email), "store_url": config.get("store_url"),
                      "fetched_at": now_iso()}
        except IntegrationError as exc:
            return {"kind": "woocommerce", "orders": [], "message": str(exc)}
        with _cache_lock:
            _cache[key] = (time.monotonic() + CACHE_SECONDS, result)
        return result
    return {"kind": row["kind"], "message": "Unsupported integration"}


def test(kind: str, config: dict) -> dict:
    """Settings 'Test' button: check credentials without a conversation."""
    if kind == "woocommerce":
        try:
            resp = requests.get(f"{config['store_url']}/wp-json/wc/v3/orders", params={"per_page": 1},
                                auth=(config["consumer_key"], config["consumer_secret"]), timeout=WOO_TIMEOUT)
        except requests.RequestException:
            return {"ok": False, "message": "Couldn't reach the store."}
        if resp.status_code in (401, 403):
            return {"ok": False, "message": "WooCommerce rejected the API keys."}
        if resp.status_code == 404:
            return {"ok": False, "message": "No WooCommerce API at that address."}
        if resp.status_code >= 400:
            return {"ok": False, "message": f"The store returned HTTP {resp.status_code}."}
        return {"ok": True, "message": "Connected to WooCommerce."}
    return {"ok": True, "message": "Looks good."}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
