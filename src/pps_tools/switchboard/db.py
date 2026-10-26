"""SQLite access layer.

One connection per thread (sqlite3 connections must not be shared between threads).
Connections run in autocommit mode; anything that must be atomic goes through
``transaction()``, which takes SQLite's write lock up front (``BEGIN IMMEDIATE``) so
concurrent writers queue on the busy timeout instead of failing on lock upgrade.
Nested ``transaction()`` blocks become savepoints.

Rows come back as plain dicts. Helpers take parameters either positionally
(``one("... WHERE id = ?", 5)``) or as a single dict/list/tuple.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from pps_tools.switchboard.util import now_iso

logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"

_local = threading.local()
_db_path: Path | None = None


def configure(path: Path | str) -> None:
    """Point this process at a database file (call before any query)."""
    global _db_path
    close()
    _db_path = Path(path)


def path() -> Path:
    if _db_path is None:
        raise RuntimeError("db.configure() has not been called")
    return _db_path


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == _db_path:
        return conn
    if conn is not None:
        close()
    conn = sqlite3.connect(str(path()), isolation_level=None, timeout=30, check_same_thread=False)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    _local.conn = conn
    _local.path = _db_path
    _local.depth = 0
    _local.after = []
    return conn


def close() -> None:
    """Close this thread's connection (Flask teardown, worker shutdown)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None
            _local.depth = 0
            _local.after = []


def in_transaction() -> bool:
    return getattr(_local, "depth", 0) > 0


@contextmanager
def transaction():
    conn = connection()
    depth = _local.depth
    if depth == 0:
        conn.execute("BEGIN IMMEDIATE")
        _local.after = []
    else:
        conn.execute(f"SAVEPOINT sp{depth}")
    _local.depth = depth + 1
    try:
        yield conn
    except BaseException:
        _local.depth = depth
        if depth == 0:
            conn.execute("ROLLBACK")
            _local.after = []
        else:
            conn.execute(f"ROLLBACK TO sp{depth}")
            conn.execute(f"RELEASE sp{depth}")
        raise
    _local.depth = depth
    if depth == 0:
        conn.execute("COMMIT")
        callbacks, _local.after = _local.after, []
        for fn in callbacks:
            try:
                fn()
            except Exception:  # pragma: no cover - callbacks must not break the request
                logger.exception("after_commit callback failed")
    else:
        conn.execute(f"RELEASE sp{depth}")


def after_commit(fn: Callable[[], Any]) -> None:
    """Run ``fn`` once the outermost transaction commits (immediately if none is open).
    Used for realtime events and webhooks so nobody hears about uncommitted rows."""
    if in_transaction():
        _local.after.append(fn)
    else:
        fn()


def _params(args: tuple) -> Any:
    if len(args) == 1 and isinstance(args[0], (dict, list, tuple)):
        return args[0]
    return args


def execute(sql: str, *args) -> sqlite3.Cursor:
    return connection().execute(sql, _params(args))


def query(sql: str, *args) -> list[dict]:
    return connection().execute(sql, _params(args)).fetchall()


def one(sql: str, *args) -> dict | None:
    return connection().execute(sql, _params(args)).fetchone()


def scalar(sql: str, *args) -> Any:
    row = connection().execute(sql, _params(args)).fetchone()
    if row is None:
        return None
    return next(iter(row.values()))


def column(sql: str, *args) -> list:
    return [next(iter(r.values())) for r in connection().execute(sql, _params(args)).fetchall()]


def insert(table: str, values: dict) -> int:
    cols = list(values)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    return connection().execute(sql, [values[c] for c in cols]).lastrowid


def update(table: str, row_id: Any, values: dict, key: str = "id") -> int:
    if not values:
        return 0
    cols = list(values)
    sql = f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE {key} = ?"
    return connection().execute(sql, [values[c] for c in cols] + [row_id]).rowcount


def delete(table: str, row_id: Any, key: str = "id") -> int:
    return connection().execute(f"DELETE FROM {table} WHERE {key} = ?", (row_id,)).rowcount


def placeholders(items: Iterable) -> str:
    return ", ".join("?" for _ in items) or "NULL"


def jdump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def jload(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


# -- migrations ---------------------------------------------------------------------


def migrate() -> list[str]:
    """Apply schema/*.sql files that haven't run yet, in name order. Returns the
    names applied. Files are append-only once released: change the schema by adding
    a new numbered file."""
    conn = connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for file in sorted(SCHEMA_DIR.glob("*.sql")):
        if file.name in done:
            continue
        sql = file.read_text(encoding="utf-8")
        # executescript() commits any open transaction itself, so wrap explicitly.
        try:
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT INTO schema_migrations (name, applied_at) VALUES ('{file.name}', '{now_iso()}');\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(file.name)
        logger.info("Applied migration %s", file.name)
    return applied
