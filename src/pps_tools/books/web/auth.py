"""Sign in, sign out, and first-run company setup."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from pps_tools.books.services import audit
from pps_tools.books.services import setup as setup_service
from pps_tools.books.services import users as user_service
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.web import core

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    s = core.db()
    if not setup_service.is_set_up(s):
        return redirect(url_for("auth.setup"))
    if request.method == "POST":
        user = user_service.authenticate(s, core.f("email"), request.form.get("password", ""))
        if user is None:
            s.commit()  # keep the failed-login counter
            flash("That email and password don't match.", "error")
            return render_template("auth/login.html", email=core.f("email")), 401
        audit.record(s, user, "login", "user", user.id, summary=f"{user.name} signed in", ip=core.client_ip())
        s.commit()
        core.login(user)
        return redirect(core.safe_next(url_for("dashboard.home")))
    return render_template("auth/login.html", email="")


@bp.route("/logout", methods=["POST"])
def logout():
    core.logout()
    flash("You're signed out.", "info")
    return redirect(url_for("auth.login"))


INDUSTRY_CHOICES = [("print_shop", "Commercial printing / print shop"), ("general", "Other small business")]
ENTITY_CHOICES = [("sole_prop", "Sole proprietor (Schedule C)"), ("llc", "LLC"),
                  ("partnership", "Partnership (Form 1065)"), ("s_corp", "S corporation (Form 1120-S)"),
                  ("c_corp", "C corporation (Form 1120)"), ("nonprofit", "Nonprofit (Form 990)")]


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    s = core.db()
    if setup_service.is_set_up(s):
        return redirect(url_for("auth.login"))
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        try:
            if request.form.get("password") != request.form.get("password2"):
                raise ValidationError("The two passwords don't match.", "password2")
            setup_service.create_company(
                s, core.f("company_name", ""), core.f("email", ""), core.f("name", ""),
                request.form.get("password", ""), industry=core.f("industry", "general"),
                entity_type=core.f("entity_type", "llc"),
                fiscal_year_start_month=core.f_int("fiscal_year_start_month") or 1,
                accounting_method=core.f("accounting_method", "accrual"), state=core.f("state"),
                account_numbers=core.f_bool("account_numbers"))
            user = user_service.authenticate(s, core.f("email", ""), request.form.get("password", ""))
            s.commit()
            if user:
                core.login(user)
            flash("Your company is ready. Start by connecting Stripe or adding your bank balances.", "success")
            return redirect(url_for("dashboard.home"))
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
    return render_template("auth/setup.html", form=form, industries=INDUSTRY_CHOICES, entities=ENTITY_CHOICES)
