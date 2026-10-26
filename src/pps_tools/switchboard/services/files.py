"""File storage for attachments: bytes on disk under <data_dir>/files, metadata in the
``attachments`` table. Every file belongs to one owner row (owner_type/owner_id);
uploads start unowned and are claimed when the message/comment/job they were attached
to is saved. Unclaimed uploads are deleted after a day.
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

from pps_tools.switchboard import config, db
from pps_tools.switchboard.util import now, iso, now_iso, token

MAX_FILENAME = 180

# owner_type -> fn(user, owner_id) -> bool. Modules register who may download files
# attached to their rows (e.g. inbox: only people who can see the conversation).
# Owner types without a checker are readable by any signed-in teammate.
ACCESS_CHECKS: dict = {}


def register_access(owner_type: str, fn) -> None:
    ACCESS_CHECKS[owner_type] = fn


def can_read(user: dict, att: dict) -> bool:
    if att["owner_type"] is None:
        return att["uploaded_by"] == user["id"]
    check = ACCESS_CHECKS.get(att["owner_type"])
    return True if check is None else bool(check(user, att["owner_id"]))


def _root() -> Path:
    return config.current().files_dir


def safe_filename(name: str | None) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    if not name or name in (".", ".."):
        name = "file"
    if len(name) > MAX_FILENAME:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: MAX_FILENAME - len(ext) - 1] + "." + ext) if dot else name[:MAX_FILENAME]
    return name


def save_bytes(
    data: bytes,
    filename: str,
    content_type: str | None = None,
    uploaded_by: int | None = None,
    owner_type: str | None = None,
    owner_id: int | None = None,
    content_id: str | None = None,
    is_inline: bool = False,
) -> dict:
    filename = safe_filename(filename)
    content_type = (content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream").split(";")[0].strip()
    tok = token(18)
    key = f"{tok[:2]}/{tok[2:4]}/{tok}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    row = {
        "token": tok,
        "filename": filename,
        "content_type": content_type,
        "size": len(data),
        "storage_key": key,
        "content_id": (content_id or "").strip("<>") or None,
        "is_inline": 1 if is_inline else 0,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "uploaded_by": uploaded_by,
        "created_at": now_iso(),
    }
    row["id"] = db.insert("attachments", row)
    return row


def save_upload(file_storage, uploaded_by: int | None, **kwargs) -> dict:
    return save_bytes(file_storage.read(), file_storage.filename, file_storage.mimetype, uploaded_by, **kwargs)


def store_blob(data: bytes, suffix: str = "") -> str:
    """Store raw bytes not tracked as an attachment (e.g. original MIME). Returns key."""
    tok = token(18)
    key = f"raw/{tok[:2]}/{tok}{suffix}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def read_blob(key: str) -> bytes | None:
    path = _root() / key
    return path.read_bytes() if path.is_file() else None


def path_for(att: dict) -> Path:
    return _root() / att["storage_key"]


def read_bytes(att: dict) -> bytes:
    return path_for(att).read_bytes()


def get(att_id: int) -> dict | None:
    return db.one("SELECT * FROM attachments WHERE id = ?", att_id)


def claim(ids: list[int] | None, owner_type: str, owner_id: int, user_id: int | None = None) -> list[dict]:
    """Attach previously uploaded, unowned files (uploaded by ``user_id``) to an owner.
    Files already owned by the same owner are kept as is."""
    ids = [int(i) for i in (ids or []) if str(i).isdigit()]
    if not ids:
        return []
    params = [owner_type, owner_id, *ids]
    where_user = ""
    if user_id is not None:
        where_user = " AND (uploaded_by = ? OR uploaded_by IS NULL)"
        params.append(user_id)
    db.execute(
        f"UPDATE attachments SET owner_type = ?, owner_id = ? WHERE id IN ({db.placeholders(ids)}) "
        f"AND owner_type IS NULL{where_user}",
        params,
    )
    return for_owner(owner_type, owner_id)


def move(from_type: str, from_id: int, to_type: str, to_id: int) -> None:
    db.execute(
        "UPDATE attachments SET owner_type = ?, owner_id = ? WHERE owner_type = ? AND owner_id = ?",
        to_type, to_id, from_type, from_id,
    )


def copy_to(att: dict, owner_type: str, owner_id: int, uploaded_by: int | None = None) -> dict:
    """Duplicate a file for another owner (e.g. forwarding a message's attachments)."""
    return save_bytes(read_bytes(att), att["filename"], att["content_type"], uploaded_by,
                      owner_type=owner_type, owner_id=owner_id,
                      content_id=att.get("content_id"), is_inline=bool(att.get("is_inline")))


def for_owner(owner_type: str, owner_id: int) -> list[dict]:
    return db.query(
        "SELECT * FROM attachments WHERE owner_type = ? AND owner_id = ? ORDER BY id", owner_type, owner_id
    )


def for_owners(owner_type: str, ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = db.query(
        f"SELECT * FROM attachments WHERE owner_type = ? AND owner_id IN ({db.placeholders(ids)}) ORDER BY id",
        [owner_type, *ids],
    )
    for r in rows:
        out.setdefault(r["owner_id"], []).append(r)
    return out


def delete(att: dict) -> None:
    try:
        path_for(att).unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass
    db.delete("attachments", att["id"])


def delete_for_owner(owner_type: str, owner_id: int) -> None:
    for att in for_owner(owner_type, owner_id):
        delete(att)


def cleanup_orphans(max_age_hours: int = 24) -> int:
    from datetime import timedelta

    cutoff = iso(now() - timedelta(hours=max_age_hours))
    rows = db.query("SELECT * FROM attachments WHERE owner_type IS NULL AND created_at < ?", cutoff)
    for r in rows:
        delete(r)
    return len(rows)


def is_image(att: dict) -> bool:
    return (att.get("content_type") or "").startswith("image/")


def url(att: dict) -> str:
    return f"/api/files/{att['id']}/{att['filename']}"


def public_url(att: dict, absolute: bool = False) -> str:
    path = f"/public/files/{att['token']}/{att['filename']}"
    return config.current().base_url + path if absolute else path


def serialize(att: dict) -> dict:
    return {
        "id": att["id"],
        "filename": att["filename"],
        "content_type": att["content_type"],
        "size": att["size"],
        "is_image": is_image(att),
        "is_inline": bool(att.get("is_inline")),
        "content_id": att.get("content_id"),
        "url": url(att),
    }
