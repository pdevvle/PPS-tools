"""Products and services."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books import money
from pps_tools.books.models import (ITEM_TYPES, BundleComponent, Item, ItemCategory, TransactionLine, Vendor)
from pps_tools.books.services import audit
from pps_tools.books.services import inventory as inv_service
from pps_tools.books.services.accounts import ordered_accounts, system_account_id
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.web import core

bp = Blueprint("items", __name__)


@bp.route("/items")
@core.requires("sales.view")
def index():
    s = core.db()
    q = select(Item)
    show = request.args.get("show", "active")
    if show == "active":
        q = q.where(Item.active.is_(True))
    elif show == "inactive":
        q = q.where(Item.active.is_(False))
    itype = request.args.get("type")
    if itype in ITEM_TYPES:
        q = q.where(Item.type == itype)
    cat = request.args.get("category_id", type=int)
    if cat:
        q = q.where(Item.category_id == cat)
    needle = (request.args.get("q") or "").strip()
    if needle:
        like = f"%{needle}%"
        q = q.where((Item.name.ilike(like)) | (Item.sku.ilike(like)) | (Item.description.ilike(like)))
    rows = s.scalars(q.order_by(Item.name)).all()
    if request.args.get("stock") == "low":
        rows = [it for it in rows if it.low_stock]
    elif request.args.get("stock") == "out":
        rows = [it for it in rows if it.is_inventory and (it.qty_on_hand or 0) <= 0]
    low = sum(1 for it in s.scalars(select(Item).where(Item.type == "inventory", Item.active.is_(True))) if it.low_stock)
    out = s.scalar(select(func.count(Item.id)).where(Item.type == "inventory", Item.active.is_(True))) or 0
    categories = s.scalars(select(ItemCategory).order_by(ItemCategory.name)).all()
    return render_template("items/index.html", rows=rows, show=show, low=low, inventory_count=out, categories=categories,
                           types=ITEM_TYPES)


@bp.route("/items/new", methods=["GET", "POST"])
@core.requires("lists.edit")
def new():
    itype = request.args.get("type", "service")
    return _form(Item(type=itype if itype in ITEM_TYPES else "service", taxable=True, active=True))


@bp.route("/items/<int:item_id>", methods=["GET", "POST"])
@core.requires("sales.view")
def edit(item_id: int):
    it = core.db().get(Item, item_id) or abort(404)
    if request.method == "POST" and not core.can("lists.edit"):
        abort(403)
    return _form(it)


def _form(it: Item):
    s = core.db()
    if request.method == "POST":
        is_new = it.id is None
        try:
            name = core.f("name") or ""
            if not name:
                raise ValidationError("Enter a name.", "name")
            dup = s.scalar(select(Item.id).where(func.lower(Item.name) == name.lower(), Item.id != (it.id or 0)))
            if dup:
                raise ValidationError(f"Another product or service is named “{name}”.", "name")
            new_type = core.f("type") or it.type
            if not is_new and it.type != new_type:
                if it.type == "inventory" or new_type == "inventory":
                    used = s.scalar(select(TransactionLine.id).where(TransactionLine.item_id == it.id).limit(1))
                    if used and new_type == "inventory":
                        raise ValidationError("Items already used on transactions can't be turned into inventory; "
                                              "create a new inventory item instead.", "type")
                    if used and it.type == "inventory":
                        raise ValidationError("An inventory item with history can't change type.", "type")
            it.name = name
            it.type = new_type
            it.sku = core.f("sku") or None
            it.unit = core.f("unit") or None
            it.category_id = core.f_int("category_id")
            it.description = core.f("description") or None
            it.sales_price = money.to_decimal(core.f("sales_price"), None)
            it.income_account_id = core.f_int("income_account_id")
            it.taxable = core.f_bool("taxable")
            it.purchase_description = core.f("purchase_description") or None
            it.cost = money.to_decimal(core.f("cost"), None)
            it.expense_account_id = core.f_int("expense_account_id")
            it.preferred_vendor_id = core.f_int("preferred_vendor_id")
            it.active = core.f_bool("active") if not is_new else True
            if it.type == "inventory":
                it.asset_account_id = core.f_int("asset_account_id") or system_account_id(s, "inventory_asset")
                it.expense_account_id = it.expense_account_id or system_account_id(s, "cogs")
                it.income_account_id = it.income_account_id or system_account_id(s, "sales_income")
                it.reorder_point = money.to_decimal(core.f("reorder_point"), None)
            if it.type == "bundle":
                it.show_bundle_components = core.f_bool("show_bundle_components")
                comps = []
                for i, row in enumerate(core.indexed_rows("c")):
                    cid = int(row["item_id"]) if row.get("item_id", "").isdigit() else None
                    if not cid:
                        continue
                    if cid == it.id:
                        raise ValidationError("A bundle can't contain itself.")
                    comp = s.get(Item, cid)
                    if comp is None or comp.type == "bundle":
                        raise ValidationError("Bundles can only contain products and services, not other bundles.")
                    comps.append(BundleComponent(item_id=cid, qty=money.to_decimal(row.get("qty"), Decimal(1)) or Decimal(1),
                                                 position=i))
                it.components = comps
            if is_new:
                s.add(it)
            s.flush()
            if is_new and it.type == "inventory":
                qty = money.to_decimal(core.f("initial_qty"), None)
                if qty:
                    from pps_tools.books.services import transactions as tx

                    as_of = core.f("as_of") or core.today().isoformat()
                    # Starting stock comes in as an inventory adjustment against Opening Balance Equity.
                    it.cost = it.cost or Decimal(0)
                    tx.save(s, {"type": "inventory_adjustment", "date": as_of,
                                "account_id": system_account_id(s, "opening_balance_equity"),
                                "memo": f"Starting quantity for {it.name}",
                                "lines": [{"item_id": it.id, "qty": str(qty)}]}, user=core.current_user())
                    it.inventory_start_date = core.today()
            audit.record(s, core.current_user(), "create" if is_new else "update", "item", it.id, name=it.name,
                         summary=f"{'Added' if is_new else 'Updated'} {it.type_label.lower()} {it.name}")
            s.commit()
        except (BooksError, money.MoneyError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render(it), 422
        flash(f"{it.name} saved.", "success")
        return redirect(url_for("items.edit", item_id=it.id))
    return _render(it)


def _render(it: Item):
    s = core.db()
    accounts = ordered_accounts(s, active_only=True)
    history = []
    if it.id and it.type == "inventory":
        _, _, history = inv_service.history(s, it.id)
        history = list(reversed(history[-25:]))
    return render_template(
        "items/form.html", it=it, types=ITEM_TYPES, history=history,
        income_accounts=[a for a in accounts if a.type in ("income", "other_income")],
        expense_accounts=[a for a in accounts if a.type in ("cogs", "expense", "other_expense", "fixed_asset",
                                                            "other_current_asset")],
        asset_accounts=[a for a in accounts if a.type == "other_current_asset"],
        vendors=s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
        categories=s.scalars(select(ItemCategory).order_by(ItemCategory.name)).all(),
        component_items=s.scalars(select(Item).where(Item.active.is_(True), Item.type != "bundle")
                                  .order_by(Item.name)).all())


@bp.route("/items/categories", methods=["GET", "POST"])
@core.requires("lists.edit")
def categories():
    s = core.db()
    if request.method == "POST":
        name = core.f("name")
        if core.f("delete"):
            cat = s.get(ItemCategory, int(core.f("delete")))
            if cat is not None:
                for it in s.scalars(select(Item).where(Item.category_id == cat.id)):
                    it.category_id = None
                s.delete(cat)
                s.commit()
                flash("Category removed.", "success")
        elif name:
            s.add(ItemCategory(name=name, parent_id=core.f_int("parent_id")))
            s.commit()
            flash(f"Category {name} added.", "success")
        return redirect(url_for("items.categories"))
    cats = s.scalars(select(ItemCategory).order_by(ItemCategory.name)).all()
    counts = dict(s.execute(select(Item.category_id, func.count(Item.id)).group_by(Item.category_id)).all())
    return render_template("items/categories.html", cats=cats, counts=counts)


@bp.route("/items/reorder", methods=["POST"])
@core.requires("purchases.edit")
def reorder():
    """Draft purchase orders for low-stock items, one per preferred vendor."""
    s = core.db()
    from collections import defaultdict

    from pps_tools.books.services import transactions as tx

    by_vendor = defaultdict(list)
    for it in s.scalars(select(Item).where(Item.type == "inventory", Item.active.is_(True))):
        if it.low_stock and it.preferred_vendor_id:
            by_vendor[it.preferred_vendor_id].append(it)
    if not by_vendor:
        flash("No low-stock products have a preferred vendor to order from.", "info")
        return redirect(url_for("items.index", stock="low"))
    made = []
    for vid, items in by_vendor.items():
        lines = []
        for it in items:
            need = max((it.reorder_point or Decimal(0)) * 2 - (it.qty_on_hand or Decimal(0)), Decimal(1))
            lines.append({"item_id": it.id, "qty": str(need)})
        made.append(tx.save(s, {"type": "purchase_order", "vendor_id": vid, "lines": lines}, user=core.current_user()))
    s.commit()
    flash(f"Drafted {len(made)} purchase order{'s' if len(made) != 1 else ''}. Review and send them.", "success")
    return redirect(url_for("expenses.purchase_orders", status="open"))
