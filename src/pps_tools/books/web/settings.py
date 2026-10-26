"""Company settings, users, email, payments, 1099 mapping, API tokens."""

from __future__ import annotations

import hashlib
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books import money
from pps_tools.books.models import (ROLES, Account, ApiToken, CustomFieldDef, EmailMessage, PaymentMethod, Terms,
                                    User)
from pps_tools.books.services import attachments as attach_service
from pps_tools.books.services import audit, numbering, prefs
from pps_tools.books.services import users as user_service
from pps_tools.books.services.accounts import ordered_accounts
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.web import core

bp = Blueprint("settings", __name__)


def _save_prefs(values: dict, summary: str) -> None:
    s = core.db()
    prefs.set_many(s, values)
    audit.record(s, core.current_user(), "settings", "company", 1, summary=summary)
    s.commit()
    flash("Settings saved.", "success")


@bp.route("/settings")
@core.requires("reports.view")
def index():
    return render_template("settings/index.html")


@bp.route("/settings/company", methods=["GET", "POST"])
@core.requires("settings.edit")
def company():
    s = core.db()
    c = core.company()
    if request.method == "POST":
        for field in ("name", "legal_name", "ein", "email", "phone", "website", "address_line1", "address_line2",
                      "city", "state", "postal_code", "country", "industry", "timezone"):
            if field in request.form:
                setattr(c, field, core.f(field) or None)
        if not c.name:
            c.name = "My Company"
        c.entity_type = core.f("entity_type") or c.entity_type
        logo = request.files.get("logo")
        if logo and logo.filename:
            try:
                att = attach_service.store(s, core.config(), logo.filename, logo.read(), logo.mimetype,
                                           core.current_user())
                c.logo_attachment_id = att.id
            except BooksError as exc:
                flash(str(exc), "error")
        if core.f_bool("remove_logo"):
            c.logo_attachment_id = None
        audit.record(s, core.current_user(), "settings", "company", 1, summary="Updated company profile")
        s.commit()
        flash("Company profile saved.", "success")
        return redirect(url_for("settings.company"))
    return render_template("settings/company.html", c=c)


SALES_BOOLS = ["show_shipping_fields", "show_discount_field", "discount_before_tax", "shipping_taxable",
               "show_service_date", "deposit_to_undeposited_funds", "auto_apply_credits", "auto_apply_payments",
               "invoice_show_logo", "invoice_show_payment_link", "reminders_enabled", "late_fees_enabled"]
SALES_TEXT = ["default_invoice_message", "default_estimate_message", "default_statement_message",
              "invoice_accent_color", "invoice_footer", "late_fee_type", "late_fee_value",
              "email_invoice_subject", "email_invoice_body", "email_estimate_subject", "email_estimate_body",
              "email_receipt_subject", "email_receipt_body", "email_statement_subject", "email_statement_body",
              "email_reminder_subject", "email_reminder_body"]


@bp.route("/settings/sales", methods=["GET", "POST"])
@core.requires("settings.edit")
def sales():
    s = core.db()
    if request.method == "POST":
        values = {k: core.f_bool(k) for k in SALES_BOOLS}
        values.update({k: request.form.get(k, "") for k in SALES_TEXT if k in request.form})
        values["default_terms_id"] = core.f_int("default_terms_id")
        values["late_fee_days"] = core.f_int("late_fee_days") or 30
        values["reminder_days"] = sorted({int(x) for x in (core.f("reminder_days") or "").replace(" ", "").split(",")
                                          if x.isdigit()})
        for key in ("invoice", "estimate", "sales_receipt", "credit_memo", "refund_receipt"):
            nxt = core.f_int(f"next_{key}")
            if nxt:
                numbering.set_next(s, key, nxt, prefix=core.f(f"prefix_{key}") or "")
        _save_prefs(values, "Updated sales settings")
        return redirect(url_for("settings.sales"))
    seqs = {k: numbering._seq(s, k) for k in ("invoice", "estimate", "sales_receipt", "credit_memo", "refund_receipt")}
    s.commit()
    return render_template("settings/sales.html", p=prefs.get_all(s), seqs=seqs,
                           terms=s.scalars(select(Terms).where(Terms.active.is_(True))).all())


@bp.route("/settings/expenses", methods=["GET", "POST"])
@core.requires("settings.edit")
def expenses():
    s = core.db()
    if request.method == "POST":
        values = {k: core.f_bool(k) for k in ("billable_expenses", "warn_duplicate_check_numbers",
                                             "warn_duplicate_bill_numbers")}
        values["default_bill_terms_id"] = core.f_int("default_bill_terms_id")
        values["default_markup_pct"] = core.f("default_markup_pct") or "0"
        values["email_po_subject"] = request.form.get("email_po_subject", "")
        values["email_po_body"] = request.form.get("email_po_body", "")
        values["check_offset_x"] = core.f("check_offset_x") or "0"
        values["check_offset_y"] = core.f("check_offset_y") or "0"
        if core.f_int("next_purchase_order"):
            numbering.set_next(s, "purchase_order", core.f_int("next_purchase_order"))
        _save_prefs(values, "Updated expense settings")
        return redirect(url_for("settings.expenses"))
    seq = numbering._seq(s, "purchase_order")
    s.commit()
    return render_template("settings/expenses.html", p=prefs.get_all(s), seq=seq,
                           terms=s.scalars(select(Terms).where(Terms.active.is_(True))).all())


@bp.route("/settings/advanced", methods=["GET", "POST"])
@core.requires("settings.edit")
def advanced():
    s = core.db()
    c = core.company()
    if request.method == "POST":
        c.fiscal_year_start_month = core.f_int("fiscal_year_start_month") or 1
        c.accounting_method = core.f("accounting_method") or "accrual"
        c.home_currency = (core.f("home_currency") or "USD").upper()[:3]
        values = {"track_classes": core.f("track_classes") or "off", "track_locations": core.f_bool("track_locations"),
                  "location_label": core.f("location_label") or "Location", "track_projects": core.f_bool("track_projects"),
                  "track_time": core.f_bool("track_time"), "track_inventory": core.f_bool("track_inventory"),
                  "allow_negative_inventory": core.f_bool("allow_negative_inventory"),
                  "time_billable_by_default": core.f_bool("time_billable_by_default"),
                  "ai_categorize": core.f_bool("ai_categorize"), "ai_receipts": core.f_bool("ai_receipts")}
        rates = []
        for row in core.indexed_rows("mr"):
            if row.get("date") and row.get("rate"):
                rates.append([row["date"], row["rate"]])
        if rates:
            values["mileage_rates"] = sorted(rates)
        thresholds = {}
        for row in core.indexed_rows("t1099"):
            if row.get("year", "").isdigit() and row.get("amount"):
                thresholds[row["year"]] = row["amount"]
        if thresholds:
            values["nec_threshold_by_year"] = thresholds
        _save_prefs(values, "Updated advanced settings")
        return redirect(url_for("settings.advanced"))
    return render_template("settings/advanced.html", c=c, p=prefs.get_all(s))


@bp.route("/settings/payments", methods=["GET", "POST"])
@core.requires("settings.edit")
def payments():
    s = core.db()
    from pps_tools.books.services import stripe_service

    if request.method == "POST":
        keys = dict(prefs.get(s, "stripe_keys") or {})
        for field in ("secret_key", "publishable_key", "webhook_secret"):
            value = core.f(field)
            if value and "•" not in value:
                if field == "secret_key" and not value.startswith(("sk_", "rk_")):
                    flash("The secret key starts with sk_ or rk_.", "error")
                    return redirect(url_for("settings.payments"))
                if field == "webhook_secret" and not value.startswith("whsec_"):
                    flash("The webhook signing secret starts with whsec_.", "error")
                    return redirect(url_for("settings.payments"))
                keys[field] = value
            if core.f_bool(f"clear_{field}"):
                keys.pop(field, None)
        values = {"stripe_keys": keys, "stripe_enabled": core.f_bool("stripe_enabled"),
                  "stripe_card": core.f_bool("stripe_card"), "stripe_ach": core.f_bool("stripe_ach"),
                  "stripe_allow_partial": core.f_bool("stripe_allow_partial"),
                  "stripe_save_cards": core.f_bool("stripe_save_cards"),
                  "stripe_payout_account_id": core.f_int("stripe_payout_account_id"),
                  "stripe_fee_account": core.f("stripe_fee_account") or "merchant_fees",
                  "stripe_statement_descriptor": core.f("stripe_statement_descriptor") or ""}
        _save_prefs(values, "Updated Stripe settings")
        return redirect(url_for("settings.payments"))
    st = stripe_service.settings(s, core.config())
    cfg = core.config()

    def mask(v):
        return f"{v[:8]}••••{v[-4:]}" if v else ""

    return render_template("settings/payments.html", p=prefs.get_all(s), st=st, mask=mask,
                           env={"secret_key": bool(cfg.stripe_secret_key), "webhook_secret": bool(cfg.stripe_webhook_secret),
                                "publishable_key": bool(cfg.stripe_publishable_key)},
                           banks=ordered_accounts(s, active_only=True, types=["bank"]),
                           expense_accounts=ordered_accounts(s, active_only=True, types=["expense", "other_expense", "cogs"]),
                           webhook_url=f"{(cfg.base_url or request.host_url).rstrip('/')}{url_for('stripe_hooks.webhook')}")


@bp.route("/settings/email", methods=["GET", "POST"])
@core.requires("settings.edit")
def email():
    s = core.db()
    from pps_tools.books.services import email as email_service

    if request.method == "POST":
        if core.f("action") == "test":
            try:
                email_service.send(s, core.config(), core.f("test_to") or core.current_user().email,
                                   "Test email from PPS Books", "If you can read this, email is working.")
                s.commit()
                flash("Test email sent (or logged to the outbox if SMTP isn't set).", "success")
            except BooksError as exc:
                s.commit()
                flash(str(exc), "error")
            return redirect(url_for("settings.email"))
        smtp = dict(prefs.get(s, "smtp") or {})
        for field in ("host", "port", "user", "sender"):
            smtp[field] = core.f(field) or None
        pw = request.form.get("password")
        if pw and "•" not in pw:
            smtp["password"] = pw
        smtp["tls"] = core.f_bool("tls")
        _save_prefs({"smtp": smtp}, "Updated email settings")
        return redirect(url_for("settings.email"))
    outbox = s.scalars(select(EmailMessage).order_by(EmailMessage.created_at.desc()).limit(50)).all()
    return render_template("settings/email.html", smtp=email_service.smtp_settings(s, core.config()),
                           env=bool(core.config().smtp_host), stored=prefs.get(s, "smtp") or {}, outbox=outbox)


@bp.route("/settings/email/<int:msg_id>")
@core.requires("settings.edit")
def email_view(msg_id: int):
    msg = core.db().get(EmailMessage, msg_id) or abort(404)
    return render_template("settings/email_view.html", msg=msg)


# -- users ------------------------------------------------------------------------------------


@bp.route("/settings/users", methods=["GET", "POST"])
@core.requires("users.manage")
def users():
    s = core.db()
    if request.method == "POST":
        try:
            temp = core.f("password") or secrets.token_urlsafe(9)
            u = user_service.create_user(s, core.f("email") or "", core.f("name") or "", temp, core.f("role") or "standard")
            audit.record(s, core.current_user(), "create", "user", u.id, name=u.name,
                         summary=f"Added user {u.email} as {u.role_label}")
            s.commit()
            flash(f"Added {u.email}. Their temporary password is {temp} — share it privately; they can change it "
                  "under Your profile.", "success")
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.users"))
    rows = s.scalars(select(User).order_by(User.name)).all()
    return render_template("settings/users.html", rows=rows, roles=ROLES, permissions=user_service.PERMISSIONS)


@bp.route("/settings/users/<int:uid>", methods=["POST"])
@core.requires("users.manage")
def user_update(uid: int):
    s = core.db()
    u = s.get(User, uid) or abort(404)
    action = core.f("action")
    try:
        if action == "role":
            role = core.f("role")
            if role not in ROLES:
                raise ValidationError("Unknown role.")
            if u.role == "admin" and role != "admin" and user_service.admin_count(s) <= 1:
                raise ValidationError("Keep at least one company admin.")
            u.role = role
        elif action == "deactivate":
            if u.id == core.current_user().id:
                raise ValidationError("You can't deactivate yourself.")
            if u.role == "admin" and user_service.admin_count(s) <= 1:
                raise ValidationError("Keep at least one company admin.")
            u.active = False
        elif action == "activate":
            u.active = True
        elif action == "reset":
            temp = secrets.token_urlsafe(9)
            user_service.set_password(u, temp)
            u.locked_until = None
            flash(f"New temporary password for {u.email}: {temp}", "info")
        audit.record(s, core.current_user(), "update", "user", u.id, name=u.name, summary=f"{action} user {u.email}")
        s.commit()
        if action != "reset":
            flash("User updated.", "success")
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
    return redirect(url_for("settings.users"))


@bp.route("/settings/profile", methods=["GET", "POST"])
def profile():
    s = core.db()
    u = core.current_user()
    if request.method == "POST":
        try:
            u.name = core.f("name") or u.name
            new_email = (core.f("email") or u.email).lower()
            if new_email != u.email:
                if s.scalar(select(User.id).where(func.lower(User.email) == new_email, User.id != u.id)):
                    raise ValidationError("Another user has that email.")
                u.email = new_email
            if request.form.get("new_password"):
                from werkzeug.security import check_password_hash

                if not check_password_hash(u.password_hash, request.form.get("current_password", "")):
                    raise ValidationError("Your current password isn't right.")
                if request.form.get("new_password") != request.form.get("new_password2"):
                    raise ValidationError("The new passwords don't match.")
                user_service.set_password(u, request.form["new_password"])
                s.commit()
                core.login(u)
            s.commit()
            flash("Profile saved.", "success")
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.profile"))
    return render_template("settings/profile.html", u=u)


# -- 1099 mapping, custom fields, API tokens -------------------------------------------------------


@bp.route("/settings/1099", methods=["GET", "POST"])
@core.requires("settings.edit")
def form_1099():
    s = core.db()
    from pps_tools.books.services.reports.other import BOXES_1099

    accounts = [a for a in ordered_accounts(s, active_only=True) if a.classification == "expense"]
    if request.method == "POST":
        for a in accounts:
            box = core.f(f"box_{a.id}")
            a.form_1099_box = box if box in BOXES_1099 else None
        audit.record(s, core.current_user(), "settings", "company", 1, summary="Updated 1099 account mapping")
        s.commit()
        flash("1099 mapping saved.", "success")
        return redirect(url_for("settings.form_1099"))
    return render_template("settings/form_1099.html", accounts=accounts, boxes=BOXES_1099)


@bp.route("/settings/custom-fields", methods=["GET", "POST"])
@core.requires("settings.edit")
def custom_fields():
    s = core.db()
    if request.method == "POST":
        if core.f("delete"):
            f = s.get(CustomFieldDef, int(core.f("delete")))
            if f is not None:
                f.active = False
        elif core.f("name"):
            applies = ",".join(request.form.getlist("applies_to")) or "invoice"
            s.add(CustomFieldDef(name=core.f("name"), applies_to=applies, print_on_form=core.f_bool("print_on_form"),
                                 position=(s.scalar(select(func.max(CustomFieldDef.position))) or 0) + 1))
        s.commit()
        flash("Custom fields updated.", "success")
        return redirect(url_for("settings.custom_fields"))
    rows = s.scalars(select(CustomFieldDef).where(CustomFieldDef.active.is_(True)).order_by(CustomFieldDef.position)).all()
    return render_template("settings/custom_fields.html", rows=rows)


@bp.route("/settings/api", methods=["GET", "POST"])
@core.requires("settings.edit")
def api_tokens():
    s = core.db()
    new_token = None
    if request.method == "POST":
        if core.f("revoke"):
            tok = s.get(ApiToken, int(core.f("revoke")))
            if tok is not None:
                tok.revoked = True
                s.commit()
                flash("Token revoked.", "success")
            return redirect(url_for("settings.api_tokens"))
        raw = "pbk_" + secrets.token_urlsafe(32)
        tok = ApiToken(user_id=core.current_user().id, name=core.f("name") or "API token",
                       token_hash=hashlib.sha256(raw.encode()).hexdigest(), prefix=raw[:10])
        s.add(tok)
        audit.record(s, core.current_user(), "create", "api_token", None, summary=f"Created API token {tok.name}")
        s.commit()
        new_token = raw
    rows = s.scalars(select(ApiToken).order_by(ApiToken.created_at.desc())).all()
    return render_template("settings/api.html", rows=rows, new_token=new_token)
