"""Attachment downloads, uploads to customers/vendors/items, and unlinking."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from sqlalchemy import select

from pps_tools.books.models import Attachment, AttachmentLink, Customer, Item, Transaction, Vendor
from pps_tools.books.services import attachments as attach_service
from pps_tools.books.services import audit
from pps_tools.books.services import users as user_service
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.web import core

bp = Blueprint("attachments", __name__)

# Shown in the browser; everything else downloads.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"}
OBJECT_PERMS = {"customer": "sales.view", "vendor": "purchases.view", "item": "sales.view",
                "employee": "time.view", "account": "accounting.view", "reconciliation": "reconcile"}
OBJECT_MODELS = {"customer": Customer, "vendor": Vendor, "item": Item}


def _can_see(att: Attachment) -> bool:
    user = core.current_user()
    if core.company() is not None and core.company().logo_attachment_id == att.id:
        return True
    if not att.links:
        # Unfiled receipts and uploads: whoever can work the bank feed, or who uploaded it.
        return core.can("banking.view") or att.uploaded_by_id == (user.id if user else None)
    for link in att.links:
        if link.object_type == "transaction":
            txn = core.db().get(Transaction, link.object_id)
            if txn is not None and user_service.can_view_type(user, txn.type):
                return True
        elif core.can(OBJECT_PERMS.get(link.object_type, "accounting.view")):
            return True
    return False


@bp.route("/attachments/<int:att_id>")
def download(att_id: int):
    att = core.db().get(Attachment, att_id) or abort(404)
    if not _can_see(att):
        abort(403)
    path = attach_service.path_of(core.config(), att)
    if core.config().data_dir.resolve() not in path.parents or not path.exists():
        abort(404)
    inline = request.args.get("inline") == "1" and att.content_type in INLINE_TYPES
    resp = send_file(path, mimetype=att.content_type if inline else "application/octet-stream",
                     as_attachment=not inline, download_name=att.filename, max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return resp


@bp.route("/attachments/upload", methods=["POST"])
def upload():
    s = core.db()
    object_type = core.f("object_type") or ""
    object_id = core.f_int("object_id")
    back = core.safe_next(request.referrer or url_for("dashboard.home"))
    if object_type == "transaction":
        txn = s.get(Transaction, object_id) if object_id else None
        if txn is None:
            abort(404)
        if not user_service.can_edit_type(core.current_user(), txn.type):
            abort(403)
    elif object_type in OBJECT_MODELS:
        if not object_id or s.get(OBJECT_MODELS[object_type], object_id) is None:
            abort(404)
        if not core.can("lists.edit"):
            abort(403)
    else:
        abort(400)
    files = [fs for fs in request.files.getlist("files") if fs and fs.filename]
    if not files:
        flash("Choose a file to attach.", "error")
        return redirect(back)
    try:
        for fs in files:
            att = attach_service.store(s, core.config(), fs.filename, fs.read(), fs.mimetype, core.current_user())
            attach_service.link(s, att, object_type, object_id, include_in_email=core.f_bool("include_in_email"))
            audit.record(s, core.current_user(), "update", object_type, object_id,
                         summary=f"Attached {att.filename}")
        s.commit()
    except ValidationError as exc:
        s.rollback()
        flash(str(exc), "error")
        return redirect(back)
    flash(f"Attached {len(files)} file{'s' if len(files) != 1 else ''}.", "success")
    return redirect(back)


@bp.route("/attachments/<int:att_id>/unlink", methods=["POST"])
def unlink(att_id: int):
    s = core.db()
    att = s.get(Attachment, att_id) or abort(404)
    object_type = core.f("object_type") or ""
    object_id = core.f_int("object_id")
    link = s.scalar(select(AttachmentLink).where(AttachmentLink.attachment_id == att.id,
                                                 AttachmentLink.object_type == object_type,
                                                 AttachmentLink.object_id == object_id))
    if link is None:
        abort(404)
    if object_type == "transaction":
        txn = s.get(Transaction, object_id)
        if txn is None or not user_service.can_edit_type(core.current_user(), txn.type):
            abort(403)
    elif not core.can("lists.edit"):
        abort(403)
    s.delete(link)
    s.flush()
    s.expire(att, ["links"])
    if not att.links and att.receipt_status is None and core.company().logo_attachment_id != att.id:
        # Nothing else uses it: drop the record (the file is content-addressed and may be shared).
        s.delete(att)
    audit.record(s, core.current_user(), "update", object_type, object_id, summary=f"Removed attachment {att.filename}")
    s.commit()
    flash(f"Removed {att.filename}.", "success")
    return redirect(core.safe_next(request.referrer or url_for("dashboard.home")))


@bp.route("/attachments/<int:att_id>/email", methods=["POST"])
def toggle_email(att_id: int):
    """Whether a transaction's attachment goes along when the form is emailed."""
    s = core.db()
    link = s.scalar(select(AttachmentLink).where(AttachmentLink.attachment_id == att_id,
                                                 AttachmentLink.object_type == "transaction",
                                                 AttachmentLink.object_id == core.f_int("object_id")))
    if link is None:
        abort(404)
    txn = s.get(Transaction, link.object_id)
    if txn is None or not user_service.can_edit_type(core.current_user(), txn.type):
        abort(403)
    link.include_in_email = not link.include_in_email
    s.commit()
    return redirect(core.safe_next(request.referrer or url_for("txn.go", txn_id=txn.id)))
