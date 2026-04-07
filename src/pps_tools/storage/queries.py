"""Reusable query functions for pricing data."""

from __future__ import annotations

from pathlib import Path

from pps_tools.storage.database import get_connection, get_db_path
from pps_tools.storage.models import PricePoint, OwnPricing, TrendPoint


def get_latest_prices(
    product: str | None = None,
    competitor: str | None = None,
    db_path: Path | None = None,
) -> list[PricePoint]:
    """Get the most recent price points, optionally filtered."""
    path = db_path or get_db_path()

    query = """
        SELECT pp.*, c.name as competitor_name, p.name as product_name
        FROM price_points pp
        JOIN competitors c ON pp.competitor_id = c.id
        JOIN products p ON pp.product_id = p.id
        WHERE pp.scraped_at = (
            SELECT MAX(pp2.scraped_at)
            FROM price_points pp2
            WHERE pp2.competitor_id = pp.competitor_id
              AND pp2.product_id = pp.product_id
              AND pp2.quantity = pp.quantity
        )
    """
    params: list = []

    if product:
        query += " AND p.name = ?"
        params.append(product)
    if competitor:
        query += " AND c.name = ?"
        params.append(competitor)

    query += " ORDER BY p.name, pp.quantity, c.name"

    with get_connection(path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            PricePoint(
                id=row["id"],
                competitor=row["competitor_name"],
                product=row["product_name"],
                quantity=row["quantity"],
                total_price=row["total_price"],
                unit_price=row["unit_price"],
                paper_type=row["paper_type"],
                size=row["size"],
                color_mode=row["color_mode"],
                sides=row["sides"],
                turnaround_days=row["turnaround_days"],
                finish=row["finish"],
                currency=row["currency"],
                scraped_at=row["scraped_at"],
                raw_text=row["raw_text"],
                competitor_id=row["competitor_id"],
                product_id=row["product_id"],
            )
            for row in rows
        ]


def get_price_history(
    product: str,
    competitor: str | None = None,
    days: int = 90,
    db_path: Path | None = None,
) -> list[TrendPoint]:
    """Get historical price points for trend analysis."""
    path = db_path or get_db_path()

    query = """
        SELECT pp.quantity, pp.total_price, pp.scraped_at,
               c.name as competitor_name, p.name as product_name
        FROM price_points pp
        JOIN competitors c ON pp.competitor_id = c.id
        JOIN products p ON pp.product_id = p.id
        WHERE p.name = ?
          AND pp.scraped_at >= datetime('now', ? || ' days')
    """
    params: list = [product, f"-{days}"]

    if competitor:
        query += " AND c.name = ?"
        params.append(competitor)

    query += " ORDER BY pp.scraped_at, c.name, pp.quantity"

    with get_connection(path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            TrendPoint(
                date=row["scraped_at"],
                price=row["total_price"],
                quantity=row["quantity"],
                competitor=row["competitor_name"],
                product=row["product_name"],
            )
            for row in rows
        ]


def get_own_pricing(
    product: str | None = None,
    db_path: Path | None = None,
) -> list[OwnPricing]:
    """Get PPS's own pricing data."""
    path = db_path or get_db_path()

    query = """
        SELECT op.*, p.name as product_name
        FROM own_pricing op
        JOIN products p ON op.product_id = p.id
        WHERE op.effective_date = (
            SELECT MAX(op2.effective_date)
            FROM own_pricing op2
            WHERE op2.product_id = op.product_id
              AND op2.quantity = op.quantity
        )
    """
    params: list = []

    if product:
        query += " AND p.name = ?"
        params.append(product)

    query += " ORDER BY p.name, op.quantity"

    with get_connection(path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            OwnPricing(
                id=row["id"],
                product=row["product_name"],
                quantity=row["quantity"],
                total_price=row["total_price"],
                paper_type=row["paper_type"],
                size=row["size"],
                color_mode=row["color_mode"],
                sides=row["sides"],
                turnaround_days=row["turnaround_days"],
                finish=row["finish"],
                effective_date=row["effective_date"],
                product_id=row["product_id"],
            )
            for row in rows
        ]


def save_price_points(
    points: list[PricePoint],
    scrape_run_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    """Save scraped price points to the database. Returns count saved."""
    path = db_path or get_db_path()
    saved = 0

    with get_connection(path) as conn:
        for point in points:
            # Resolve competitor_id
            comp_row = conn.execute(
                "SELECT id FROM competitors WHERE name = ?", (point.competitor,)
            ).fetchone()
            if not comp_row:
                continue

            # Resolve product_id
            prod_row = conn.execute(
                "SELECT id FROM products WHERE name = ?", (point.product,)
            ).fetchone()
            if not prod_row:
                continue

            conn.execute(
                """INSERT INTO price_points
                   (competitor_id, product_id, quantity, unit_price, total_price,
                    paper_type, size, color_mode, sides, turnaround_days, finish,
                    currency, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comp_row["id"], prod_row["id"], point.quantity,
                    point.unit_price, point.total_price,
                    point.paper_type, point.size, point.color_mode,
                    point.sides, point.turnaround_days, point.finish,
                    point.currency, point.raw_text,
                ),
            )
            saved += 1

    return saved


def save_own_pricing(
    prices: list[OwnPricing],
    db_path: Path | None = None,
) -> int:
    """Save PPS's own pricing data. Returns count saved."""
    path = db_path or get_db_path()
    saved = 0

    with get_connection(path) as conn:
        for price in prices:
            prod_row = conn.execute(
                "SELECT id FROM products WHERE name = ?", (price.product,)
            ).fetchone()
            if not prod_row:
                continue

            conn.execute(
                """INSERT OR REPLACE INTO own_pricing
                   (product_id, quantity, total_price, paper_type, size,
                    color_mode, sides, turnaround_days, finish, effective_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, date('now')))""",
                (
                    prod_row["id"], price.quantity, price.total_price,
                    price.paper_type, price.size, price.color_mode,
                    price.sides, price.turnaround_days, price.finish,
                    price.effective_date,
                ),
            )
            saved += 1

    return saved


def get_all_price_points(
    product: str | None = None,
    competitor: str | None = None,
    since: str | None = None,
    db_path: Path | None = None,
) -> list[PricePoint]:
    """Get all price points (for export), optionally filtered."""
    path = db_path or get_db_path()

    query = """
        SELECT pp.*, c.name as competitor_name, p.name as product_name
        FROM price_points pp
        JOIN competitors c ON pp.competitor_id = c.id
        JOIN products p ON pp.product_id = p.id
        WHERE 1=1
    """
    params: list = []

    if product:
        query += " AND p.name = ?"
        params.append(product)
    if competitor:
        query += " AND c.name = ?"
        params.append(competitor)
    if since:
        query += " AND pp.scraped_at >= ?"
        params.append(since)

    query += " ORDER BY pp.scraped_at DESC, p.name, pp.quantity, c.name"

    with get_connection(path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            PricePoint(
                id=row["id"],
                competitor=row["competitor_name"],
                product=row["product_name"],
                quantity=row["quantity"],
                total_price=row["total_price"],
                unit_price=row["unit_price"],
                paper_type=row["paper_type"],
                size=row["size"],
                color_mode=row["color_mode"],
                sides=row["sides"],
                turnaround_days=row["turnaround_days"],
                finish=row["finish"],
                currency=row["currency"],
                scraped_at=row["scraped_at"],
                raw_text=row["raw_text"],
                competitor_id=row["competitor_id"],
                product_id=row["product_id"],
            )
            for row in rows
        ]
