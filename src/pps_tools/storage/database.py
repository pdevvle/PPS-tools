"""SQLite database management for PPS-Tools."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from pps_tools.utils.config import get_settings, get_competitors, get_products

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS competitors (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    base_url     TEXT NOT NULL,
    is_active    INTEGER DEFAULT 1,
    is_dynamic   INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    category     TEXT
);

CREATE TABLE IF NOT EXISTS pricing_urls (
    id               INTEGER PRIMARY KEY,
    competitor_id    INTEGER REFERENCES competitors(id),
    product_id       INTEGER REFERENCES products(id),
    url              TEXT NOT NULL,
    discovery_method TEXT DEFAULT 'config',
    is_dynamic       INTEGER DEFAULT 0,
    last_checked     TEXT,
    is_active        INTEGER DEFAULT 1,
    UNIQUE(competitor_id, product_id, url)
);

CREATE TABLE IF NOT EXISTS price_points (
    id              INTEGER PRIMARY KEY,
    competitor_id   INTEGER REFERENCES competitors(id),
    product_id      INTEGER REFERENCES products(id),
    pricing_url_id  INTEGER REFERENCES pricing_urls(id),
    quantity        INTEGER NOT NULL,
    unit_price      REAL,
    total_price     REAL NOT NULL,
    paper_type      TEXT,
    size            TEXT,
    color_mode      TEXT,
    sides           TEXT,
    turnaround_days INTEGER,
    finish          TEXT,
    currency        TEXT DEFAULT 'USD',
    scraped_at      TEXT DEFAULT (datetime('now')),
    raw_text        TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_points_lookup
    ON price_points(competitor_id, product_id, quantity, scraped_at);

CREATE TABLE IF NOT EXISTS own_pricing (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id),
    quantity        INTEGER NOT NULL,
    total_price     REAL NOT NULL,
    paper_type      TEXT,
    size            TEXT,
    color_mode      TEXT,
    sides           TEXT,
    turnaround_days INTEGER,
    finish          TEXT,
    effective_date  TEXT DEFAULT (date('now')),
    UNIQUE(product_id, quantity, paper_type, size, color_mode, sides,
           turnaround_days, finish, effective_date)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY,
    started_at     TEXT DEFAULT (datetime('now')),
    finished_at    TEXT,
    competitor_id  INTEGER REFERENCES competitors(id),
    product_id     INTEGER REFERENCES products(id),
    url            TEXT,
    status         TEXT,
    records_found  INTEGER DEFAULT 0,
    error_message  TEXT
);
"""


def get_db_path() -> Path:
    settings = get_settings()
    return Path(settings.get("storage", {}).get("database_path", "pps_pricing.db"))


@contextmanager
def get_connection(db_path: Path | None = None):
    """Context manager returning a SQLite connection."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    """Create database schema and seed reference data from config."""
    path = db_path or get_db_path()

    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)

        # Set schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )

        # Seed competitors from config
        competitors = get_competitors()
        for name, info in competitors.items():
            conn.execute(
                """INSERT OR IGNORE INTO competitors (name, display_name, base_url, is_dynamic)
                   VALUES (?, ?, ?, ?)""",
                (name, info["display_name"], info["base_url"], int(info.get("is_dynamic", False))),
            )

        # Seed products from config
        products = get_products()
        for name, info in products.items():
            conn.execute(
                """INSERT OR IGNORE INTO products (name, display_name, category)
                   VALUES (?, ?, ?)""",
                (name, info["display_name"], info.get("category", "")),
            )

        # Seed pricing URLs from config
        for comp_name, comp_info in competitors.items():
            comp_row = conn.execute(
                "SELECT id FROM competitors WHERE name = ?", (comp_name,)
            ).fetchone()
            if not comp_row:
                continue
            comp_id = comp_row["id"]

            for product_name, url in comp_info.get("pricing_urls", {}).items():
                prod_row = conn.execute(
                    "SELECT id FROM products WHERE name = ?", (product_name,)
                ).fetchone()
                if not prod_row:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO pricing_urls
                       (competitor_id, product_id, url, discovery_method, is_dynamic)
                       VALUES (?, ?, ?, 'config', ?)""",
                    (comp_id, prod_row["id"], url, int(comp_info.get("is_dynamic", False))),
                )

    return path


def get_db_stats(db_path: Path | None = None) -> dict:
    """Return record counts and latest scrape dates."""
    path = db_path or get_db_path()
    stats = {}

    with get_connection(path) as conn:
        for table in ["competitors", "products", "pricing_urls", "price_points",
                       "own_pricing", "scrape_runs"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            stats[table] = row["cnt"]

        row = conn.execute(
            "SELECT MAX(scraped_at) as latest FROM price_points"
        ).fetchone()
        stats["latest_scrape"] = row["latest"]

        row = conn.execute(
            "SELECT MIN(scraped_at) as earliest FROM price_points"
        ).fetchone()
        stats["earliest_scrape"] = row["earliest"]

    return stats


def prune_old_records(days: int, db_path: Path | None = None) -> int:
    """Remove price_points older than given days. Returns count deleted."""
    path = db_path or get_db_path()

    with get_connection(path) as conn:
        cursor = conn.execute(
            """DELETE FROM price_points
               WHERE scraped_at < datetime('now', ? || ' days')""",
            (f"-{days}",),
        )
        return cursor.rowcount
