"""SQLite persistence for the Marketing Hub.

One small database file holds everything the hub needs between runs:
platform connections (OAuth tokens), the ad accounts and publish targets
found on each platform, scheduled posts, automation rules, monthly
budgets, saved UTM links and ad copy, an activity log of every change
made through the hub, and a short-lived cache of fetched metrics.

A new sqlite3 connection is opened per operation, so the store is safe to
share between Flask request threads and the background post scheduler.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from pps_tools.marketing.models import AdAccount, PublishTarget

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    platform     TEXT PRIMARY KEY,
    credentials  TEXT NOT NULL,
    profile      TEXT NOT NULL DEFAULT '{}',
    connected_at TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_accounts (
    platform   TEXT NOT NULL,
    account_id TEXT NOT NULL,
    data       TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (platform, account_id)
);

CREATE TABLE IF NOT EXISTS publish_targets (
    platform  TEXT NOT NULL,
    network   TEXT NOT NULL,
    target_id TEXT NOT NULL,
    data      TEXT NOT NULL,
    secret    TEXT,
    enabled   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (platform, network, target_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state      TEXT PRIMARY KEY,
    platform   TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY,
    body         TEXT NOT NULL,
    link         TEXT,
    image_url    TEXT,
    title        TEXT,
    targets      TEXT NOT NULL,
    overrides    TEXT NOT NULL DEFAULT '{}',
    utm_campaign TEXT,
    status       TEXT NOT NULL,
    scheduled_at TEXT,
    published_at TEXT,
    results      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_due ON posts(status, scheduled_at);

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY,
    data       TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS rule_fires (
    rule_id      INTEGER NOT NULL,
    campaign_key TEXT NOT NULL,
    fired_at     REAL NOT NULL,
    PRIMARY KEY (rule_id, campaign_key)
);

CREATE TABLE IF NOT EXISTS activity (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    platform TEXT,
    summary  TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT '{}',
    ok       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS budgets (
    month    TEXT NOT NULL,
    platform TEXT NOT NULL,
    amount   REAL NOT NULL,
    PRIMARY KEY (month, platform)
);

CREATE TABLE IF NOT EXISTS utm_links (
    id         INTEGER PRIMARY KEY,
    label      TEXT,
    url        TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copy_library (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    brief      TEXT NOT NULL,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""

# Post lifecycle.
DRAFT = "draft"
SCHEDULED = "scheduled"
PUBLISHING = "publishing"
PUBLISHED = "published"
PARTIAL = "partial"
FAILED = "failed"

OAUTH_STATE_TTL = 15 * 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).astimezone(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # The file holds OAuth tokens: create it private to this user (SQLite gives
        # its -wal / -shm side files the same permissions).
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQL)

    # -- settings -----------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def delete_setting(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def secret_key(self) -> str:
        """A Flask session key that survives restarts (generated once, then reused)."""
        key = self.get_setting("flask_secret_key")
        if not key:
            key = secrets.token_hex(32)
            self.set_setting("flask_secret_key", key)
        return key

    # -- connections --------------------------------------------------------

    def save_connection(self, platform: str, credentials: dict, profile: Optional[dict] = None) -> None:
        now = utc_iso()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO connections(platform, credentials, profile, connected_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(platform) DO UPDATE SET "
                "credentials = excluded.credentials, profile = excluded.profile, "
                "updated_at = excluded.updated_at",
                (platform, json.dumps(credentials), json.dumps(profile or {}), now, now),
            )

    def update_credentials(self, platform: str, credentials: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE connections SET credentials = ?, updated_at = ? WHERE platform = ?",
                (json.dumps(credentials), utc_iso(), platform),
            )

    def get_connection(self, platform: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM connections WHERE platform = ?", (platform,)).fetchone()
        if not row:
            return None
        return {
            "platform": row["platform"],
            "credentials": json.loads(row["credentials"]),
            "profile": json.loads(row["profile"]),
            "connected_at": row["connected_at"],
            "updated_at": row["updated_at"],
        }

    def connected_platforms(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT platform FROM connections ORDER BY platform").fetchall()
        return [r["platform"] for r in rows]

    def delete_connection(self, platform: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM connections WHERE platform = ?", (platform,))
            conn.execute("DELETE FROM ad_accounts WHERE platform = ?", (platform,))
            conn.execute("DELETE FROM publish_targets WHERE platform = ?", (platform,))
            conn.execute("DELETE FROM cache WHERE key LIKE ?", (f"%:{platform}:%",))

    # -- ad accounts ----------------------------------------------------------

    def replace_accounts(self, platform: str, accounts: list[AdAccount]) -> None:
        """Store freshly discovered accounts, keeping the user's on/off choices."""
        with self._conn() as conn:
            previous = {
                r["account_id"]: bool(r["enabled"])
                for r in conn.execute(
                    "SELECT account_id, enabled FROM ad_accounts WHERE platform = ?", (platform,)
                )
            }
            conn.execute("DELETE FROM ad_accounts WHERE platform = ?", (platform,))
            for acct in accounts:
                enabled = previous.get(acct.account_id, acct.enabled)
                conn.execute(
                    "INSERT INTO ad_accounts(platform, account_id, data, enabled) VALUES(?, ?, ?, ?)",
                    (platform, acct.account_id, json.dumps(acct.to_dict()), int(enabled)),
                )

    def list_accounts(self, platform: Optional[str] = None, enabled_only: bool = False) -> list[AdAccount]:
        sql = "SELECT data, enabled FROM ad_accounts"
        clauses, args = [], []
        if platform:
            clauses.append("platform = ?")
            args.append(platform)
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY platform, account_id"
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        accounts = []
        for r in rows:
            acct = AdAccount.from_dict(json.loads(r["data"]))
            acct.enabled = bool(r["enabled"])
            accounts.append(acct)
        return accounts

    def set_account_enabled(self, platform: str, account_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE ad_accounts SET enabled = ? WHERE platform = ? AND account_id = ?",
                (int(enabled), platform, account_id),
            )

    # -- publish targets ------------------------------------------------------

    def replace_targets(self, platform: str, targets: list[tuple[PublishTarget, Optional[dict]]]) -> None:
        """Store discovered targets with any per-target secret (e.g. a Page token)."""
        with self._conn() as conn:
            previous = {
                (r["network"], r["target_id"]): bool(r["enabled"])
                for r in conn.execute(
                    "SELECT network, target_id, enabled FROM publish_targets WHERE platform = ?",
                    (platform,),
                )
            }
            conn.execute("DELETE FROM publish_targets WHERE platform = ?", (platform,))
            for target, secret in targets:
                enabled = previous.get((target.network, target.target_id), target.enabled)
                conn.execute(
                    "INSERT INTO publish_targets(platform, network, target_id, data, secret, enabled) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        platform,
                        target.network,
                        target.target_id,
                        json.dumps(target.to_dict()),
                        json.dumps(secret) if secret else None,
                        int(enabled),
                    ),
                )

    def list_targets(self, platform: Optional[str] = None, enabled_only: bool = False) -> list[PublishTarget]:
        sql = "SELECT data, enabled FROM publish_targets"
        clauses, args = [], []
        if platform:
            clauses.append("platform = ?")
            args.append(platform)
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY platform, network, target_id"
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        targets = []
        for r in rows:
            t = PublishTarget.from_dict(json.loads(r["data"]))
            t.enabled = bool(r["enabled"])
            targets.append(t)
        return targets

    def target_secret(self, platform: str, network: str, target_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT secret FROM publish_targets WHERE platform = ? AND network = ? AND target_id = ?",
                (platform, network, target_id),
            ).fetchone()
        return json.loads(row["secret"]) if row and row["secret"] else None

    def set_target_enabled(self, platform: str, network: str, target_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE publish_targets SET enabled = ? WHERE platform = ? AND network = ? AND target_id = ?",
                (int(enabled), platform, network, target_id),
            )

    # -- OAuth state (CSRF protection + PKCE verifiers for the redirect dance) ----

    def create_oauth_state(self, platform: str, data: Optional[dict] = None) -> str:
        state = secrets.token_urlsafe(24)
        now = time.time()
        with self._conn() as conn:
            conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (now - OAUTH_STATE_TTL,))
            conn.execute(
                "INSERT INTO oauth_states(state, platform, data, created_at) VALUES(?, ?, ?, ?)",
                (state, platform, json.dumps(data or {}), now),
            )
        return state

    def pop_oauth_state(self, state: str, platform: str) -> Optional[dict]:
        """Return the state's data once; None if unknown, expired or for another platform."""
        if not state:
            return None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if not row or row["platform"] != platform:
            return None
        if row["created_at"] < time.time() - OAUTH_STATE_TTL:
            return None
        return json.loads(row["data"])

    # -- posts ----------------------------------------------------------------

    def create_post(
        self,
        body: str,
        targets: list[str],
        link: Optional[str] = None,
        image_url: Optional[str] = None,
        title: Optional[str] = None,
        overrides: Optional[dict] = None,
        utm_campaign: Optional[str] = None,
        status: str = DRAFT,
        scheduled_at: Optional[str] = None,
    ) -> int:
        now = utc_iso()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO posts(body, link, image_url, title, targets, overrides, utm_campaign, "
                "status, scheduled_at, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    body,
                    link,
                    image_url,
                    title,
                    json.dumps(targets),
                    json.dumps(overrides or {}),
                    utm_campaign,
                    status,
                    scheduled_at,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def _post_row(self, row: sqlite3.Row) -> dict:
        post = dict(row)
        post["targets"] = json.loads(post["targets"])
        post["overrides"] = json.loads(post["overrides"] or "{}")
        post["results"] = json.loads(post["results"] or "{}")
        return post

    def get_post(self, post_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return self._post_row(row) if row else None

    def list_posts(self, statuses: Optional[list[str]] = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM posts"
        args: list = []
        if statuses:
            sql += " WHERE status IN (%s)" % ",".join("?" * len(statuses))
            args.extend(statuses)
        sql += " ORDER BY COALESCE(scheduled_at, published_at, created_at) DESC LIMIT ?"
        args.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._post_row(r) for r in rows]

    def update_post(self, post_id: int, **fields: Any) -> None:
        if not fields:
            return
        for key in ("targets", "overrides", "results"):
            if key in fields and not isinstance(fields[key], str):
                fields[key] = json.dumps(fields[key])
        fields["updated_at"] = utc_iso()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE posts SET {assignments} WHERE id = ?", (*fields.values(), post_id))

    def claim_post(self, post_id: int, from_statuses: tuple[str, ...] = (SCHEDULED, DRAFT)) -> bool:
        """Atomically move a post to 'publishing' so it can never be sent twice."""
        marks = ",".join("?" * len(from_statuses))
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE posts SET status = ?, updated_at = ? WHERE id = ? AND status IN ({marks})",
                (PUBLISHING, utc_iso(), post_id, *from_statuses),
            )
            return cur.rowcount == 1

    def fail_stale_publishing(self, older_than_minutes: int = 15) -> int:
        """Release posts left in 'publishing' by a crash or restart so they can be retried.

        Destinations without a recorded result are marked as interrupted (they may
        or may not have received the post, hence the warning).
        """
        cutoff = utc_iso(datetime.fromtimestamp(time.time() - older_than_minutes * 60, timezone.utc))
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, targets, results FROM posts WHERE status = ? AND updated_at < ?", (PUBLISHING, cutoff)
            ).fetchall()
            for row in rows:
                results = json.loads(row["results"] or "{}")
                for key in json.loads(row["targets"]):
                    results.setdefault(key, {
                        "ok": False,
                        "error": "Publishing was interrupted. Check this network for the post before retrying.",
                    })
                status = PARTIAL if any(r.get("ok") for r in results.values()) else FAILED
                conn.execute(
                    "UPDATE posts SET status = ?, results = ?, updated_at = ? WHERE id = ?",
                    (status, json.dumps(results), utc_iso(), row["id"]),
                )
        return len(rows)

    def due_post_ids(self, now: Optional[datetime] = None) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM posts WHERE status = ? AND scheduled_at <= ? ORDER BY scheduled_at",
                (SCHEDULED, utc_iso(now)),
            ).fetchall()
        return [r["id"] for r in rows]

    def delete_post(self, post_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM posts WHERE id = ? AND status IN (?, ?, ?)",
                (post_id, DRAFT, SCHEDULED, FAILED),
            )
            return cur.rowcount == 1

    # -- rules ----------------------------------------------------------------

    def save_rule(self, data: dict, rule_id: Optional[int] = None) -> int:
        payload = {k: v for k, v in data.items() if k not in ("id", "created_at", "last_run_at")}
        enabled = int(bool(payload.get("enabled", True)))
        with self._conn() as conn:
            if rule_id is None:
                cur = conn.execute(
                    "INSERT INTO rules(data, enabled, created_at) VALUES(?, ?, ?)",
                    (json.dumps(payload), enabled, utc_iso()),
                )
                return int(cur.lastrowid)
            conn.execute(
                "UPDATE rules SET data = ?, enabled = ? WHERE id = ?",
                (json.dumps(payload), enabled, rule_id),
            )
            return rule_id

    def _rule_row(self, row: sqlite3.Row) -> dict:
        rule = json.loads(row["data"])
        rule.update(
            id=row["id"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_run_at=row["last_run_at"],
        )
        return rule

    def list_rules(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._rule_row(r) for r in rows]

    def get_rule(self, rule_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        return self._rule_row(row) if row else None

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        rule = self.get_rule(rule_id)
        if rule:
            rule["enabled"] = enabled
            self.save_rule(rule, rule_id)

    def delete_rule(self, rule_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            conn.execute("DELETE FROM rule_fires WHERE rule_id = ?", (rule_id,))

    def mark_rule_run(self, rule_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE rules SET last_run_at = ? WHERE id = ?", (utc_iso(), rule_id))

    def last_rule_fire(self, rule_id: int, campaign_key: str) -> Optional[float]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fired_at FROM rule_fires WHERE rule_id = ? AND campaign_key = ?",
                (rule_id, campaign_key),
            ).fetchone()
        return row["fired_at"] if row else None

    def record_rule_fire(self, rule_id: int, campaign_key: str, at: Optional[float] = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO rule_fires(rule_id, campaign_key, fired_at) VALUES(?, ?, ?) "
                "ON CONFLICT(rule_id, campaign_key) DO UPDATE SET fired_at = excluded.fired_at",
                (rule_id, campaign_key, at if at is not None else time.time()),
            )

    # -- activity log ----------------------------------------------------------

    def log(
        self,
        kind: str,
        summary: str,
        platform: Optional[str] = None,
        detail: Optional[dict] = None,
        ok: bool = True,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO activity(at, kind, platform, summary, detail, ok) VALUES(?, ?, ?, ?, ?, ?)",
                (utc_iso(), kind, platform, summary, json.dumps(detail or {}, default=str), int(ok)),
            )

    def list_activity(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["detail"] = json.loads(item["detail"] or "{}")
            item["ok"] = bool(item["ok"])
            out.append(item)
        return out

    # -- budgets ---------------------------------------------------------------

    def set_budget(self, month: str, platform: str, amount: Optional[float]) -> None:
        with self._conn() as conn:
            if amount is None or amount <= 0:
                conn.execute("DELETE FROM budgets WHERE month = ? AND platform = ?", (month, platform))
            else:
                conn.execute(
                    "INSERT INTO budgets(month, platform, amount) VALUES(?, ?, ?) "
                    "ON CONFLICT(month, platform) DO UPDATE SET amount = excluded.amount",
                    (month, platform, float(amount)),
                )

    def get_budgets(self, month: str) -> dict[str, float]:
        with self._conn() as conn:
            rows = conn.execute("SELECT platform, amount FROM budgets WHERE month = ?", (month,)).fetchall()
        return {r["platform"]: r["amount"] for r in rows}

    # -- UTM links ---------------------------------------------------------------

    def save_utm_link(self, url: str, label: Optional[str] = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO utm_links(label, url, created_at) VALUES(?, ?, ?)", (label, url, utc_iso())
            )
            return int(cur.lastrowid)

    def list_utm_links(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM utm_links ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete_utm_link(self, link_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM utm_links WHERE id = ?", (link_id,))

    # -- saved ad copy -----------------------------------------------------------

    def save_copy(self, title: str, brief: dict, result: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO copy_library(title, brief, result, created_at) VALUES(?, ?, ?, ?)",
                (title, json.dumps(brief), json.dumps(result), utc_iso()),
            )
            return int(cur.lastrowid)

    def list_copy(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM copy_library ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["brief"] = json.loads(item["brief"])
            item["result"] = json.loads(item["result"])
            out.append(item)
        return out

    def delete_copy(self, copy_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM copy_library WHERE id = ?", (copy_id,))

    # -- cache -------------------------------------------------------------------

    def cache_get(self, key: str, max_age_seconds: float) -> Optional[Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT payload, fetched_at FROM cache WHERE key = ?", (key,)).fetchone()
        if not row or row["fetched_at"] < time.time() - max_age_seconds:
            return None
        return json.loads(row["payload"])

    def cache_set(self, key: str, payload: Any) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO cache(key, payload, fetched_at) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
                (key, json.dumps(payload), time.time()),
            )

    def cache_clear(self, prefix: str = "") -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))
