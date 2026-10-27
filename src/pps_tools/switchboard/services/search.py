"""Full-text index (SQLite FTS5) shared by every module.

Rows are keyed by (kind, ref_id); parent_id groups them (a message's conversation, a
chat message's room). Index on write, unindex on delete; queries go through
``match_expr`` so user input can never produce an FTS syntax error.
"""

from __future__ import annotations

import re

from pps_tools.switchboard import db
from pps_tools.switchboard.util import html_to_text

MAX_BODY = 20000


def index(kind: str, ref_id: int, title: str | None, body: str | None, parent_id: int | None = None,
          body_is_html: bool = False) -> None:
    text = html_to_text(body) if body_is_html else (body or "")
    db.execute("DELETE FROM search_index WHERE kind = ? AND ref_id = ?", kind, ref_id)
    db.execute(
        "INSERT INTO search_index (title, body, kind, ref_id, parent_id) VALUES (?, ?, ?, ?, ?)",
        title or "", text[:MAX_BODY], kind, ref_id, parent_id,
    )


def unindex(kind: str, ref_id: int) -> None:
    db.execute("DELETE FROM search_index WHERE kind = ? AND ref_id = ?", kind, ref_id)


def unindex_parent(kinds: list[str], parent_id: int) -> None:
    db.execute(
        f"DELETE FROM search_index WHERE parent_id = ? AND kind IN ({db.placeholders(kinds)})",
        [parent_id, *kinds],
    )


_TOKEN_RE = re.compile(r"[\w@.+'-]+", re.UNICODE)


def match_expr(text: str | None) -> str | None:
    """User text -> FTS5 expression: every word must appear; the last word may be a
    prefix (search-as-you-type). Returns None when there is nothing to search."""
    words = [w.strip(".'-") for w in _TOKEN_RE.findall(text or "")]
    words = [w for w in words if w]
    if not words:
        return None
    parts = ['"' + w.replace('"', '""') + '"' for w in words]
    parts[-1] += "*"
    return " ".join(parts)


def search(kinds: list[str], text: str, limit: int = 200) -> list[dict]:
    """[{kind, ref_id, parent_id}] best matches first."""
    expr = match_expr(text)
    if not expr:
        return []
    return db.query(
        f"SELECT kind, ref_id, parent_id FROM search_index WHERE search_index MATCH ? "
        f"AND kind IN ({db.placeholders(kinds)}) ORDER BY rank LIMIT ?",
        [expr, *kinds, limit],
    )


def parent_ids(kinds: list[str], text: str, limit: int = 1000) -> list[int]:
    seen, out = set(), []
    for row in search(kinds, text, limit):
        pid = row["parent_id"] if row["parent_id"] is not None else row["ref_id"]
        if pid not in seen:
            seen.add(pid)
            out.append(int(pid))
    return out
