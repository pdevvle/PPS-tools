"""Attachments: receipts, contracts and PDFs stored next to the database."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import Attachment, AttachmentLink, User
from pps_tools.books.services.errors import ValidationError

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".txt", ".csv", ".xlsx", ".xls", ".docx",
           ".doc", ".ofx", ".qfx", ".qbo", ".eml", ".zip", ".tif", ".tiff"}
MAX_BYTES = 25 * 1024 * 1024


def _safe_name(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "file"
    return name[:180]


def store(s: Session, config, filename: str, data: bytes, content_type: Optional[str] = None,
          user: Optional[User] = None, receipt: bool = False) -> Attachment:
    filename = _safe_name(filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise ValidationError(f"Files of type {ext or '(none)'} can't be attached.")
    if len(data) > MAX_BYTES:
        raise ValidationError("Attachments are limited to 25 MB.")
    digest = hashlib.sha256(data).hexdigest()
    subdir = config.attachments_dir / digest[:2]
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"{digest}{ext}"
    if not path.exists():
        path.write_bytes(data)
    att = Attachment(filename=filename, size=len(data), sha256=digest,
                     content_type=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                     storage_path=str(path.relative_to(config.data_dir)),
                     uploaded_by_id=user.id if user else None, receipt_status="inbox" if receipt else None)
    s.add(att)
    s.flush()
    return att


def link(s: Session, att: Attachment, object_type: str, object_id: int, include_in_email: bool = False) -> None:
    exists = s.scalar(select(AttachmentLink.id).where(AttachmentLink.attachment_id == att.id,
                                                      AttachmentLink.object_type == object_type,
                                                      AttachmentLink.object_id == object_id))
    if not exists:
        s.add(AttachmentLink(attachment_id=att.id, object_type=object_type, object_id=object_id,
                             include_in_email=include_in_email))
        if att.receipt_status == "inbox":
            att.receipt_status = "used"
        s.flush()


def for_object(s: Session, object_type: str, object_id: int) -> list[Attachment]:
    return list(s.scalars(select(Attachment).join(AttachmentLink, AttachmentLink.attachment_id == Attachment.id)
                          .where(AttachmentLink.object_type == object_type, AttachmentLink.object_id == object_id)
                          .order_by(Attachment.created_at)))


def read(config, att: Attachment) -> bytes:
    path = (config.data_dir / att.storage_path).resolve()
    if config.data_dir.resolve() not in path.parents:
        raise ValidationError("Attachment path is outside the data directory.")
    return path.read_bytes()


def path_of(config, att: Attachment) -> Path:
    return (config.data_dir / att.storage_path).resolve()
