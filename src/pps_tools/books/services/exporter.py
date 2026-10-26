"""Getting your data out: every table as CSV in a ZIP, or a SQLite backup.

Secrets never leave: password and token hashes, link tokens, and the
Stripe and SMTP credentials stored in company preferences are dropped.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pps_tools.books.db import Base

SKIP_TABLES = {"api_tokens"}
SECRET_COLUMNS = {"password_hash", "token_hash", "closing_password_hash", "portal_token", "public_token"}
SECRET_PREFS = {"stripe_keys", "smtp", "qbo_import"}


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def export_zip(s: Session) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {"exported_at": datetime.now(timezone.utc).isoformat(), "tables": {},
                    "amounts": "Columns ending in _cents are whole cents (12345 = $123.45). Ledger entries are "
                               "debit-positive and each transaction's entries sum to zero."}
        for table in Base.metadata.sorted_tables:
            if table.name in SKIP_TABLES:
                continue
            cols = [c for c in table.columns if c.name not in SECRET_COLUMNS]
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow([c.name for c in cols])
            n = 0
            for row in s.execute(select(*cols)):
                values = list(row)
                if table.name == "company":
                    idx = [c.name for c in cols].index("prefs")
                    values[idx] = {k: v for k, v in (values[idx] or {}).items() if k not in SECRET_PREFS}
                w.writerow([_cell(v) for v in values])
                n += 1
            zf.writestr(f"{table.name}.csv", out.getvalue())
            manifest["tables"][table.name] = n
        zf.writestr("README.txt", "PPS Books export\n\n" + json.dumps(manifest, indent=2) + "\n")
    return buf.getvalue()


def sqlite_backup(engine: Engine) -> bytes:
    """A consistent copy of the SQLite database, taken with SQLite's online backup."""
    if engine.url.get_backend_name() != "sqlite":
        raise ValueError("Database backups from the app work with SQLite. Use your database's own backup tools.")
    path = engine.url.database
    if not path or path == ":memory:":
        raise ValueError("This database is in memory; there's nothing on disk to back up.")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "backup.sqlite"
        src = sqlite3.connect(path)
        dst = sqlite3.connect(target)
        try:
            with dst:
                src.backup(dst)
            # Drop secrets from the copy too.
            dst.execute("DELETE FROM api_tokens")
            row = dst.execute("SELECT prefs FROM company WHERE id = 1").fetchone()
            if row and row[0]:
                prefs = {k: v for k, v in json.loads(row[0]).items() if k not in SECRET_PREFS}
                dst.execute("UPDATE company SET prefs = ? WHERE id = 1", (json.dumps(prefs),))
            dst.commit()
            dst.execute("VACUUM")
        finally:
            src.close()
            dst.close()
        return target.read_bytes()
