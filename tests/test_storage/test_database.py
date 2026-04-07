"""Tests for database module."""

from pps_tools.storage.database import init_db, get_connection, get_db_stats, prune_old_records


def test_init_db(tmp_path):
    """Test database initialization creates tables and seeds data."""
    db_path = tmp_path / "test.db"
    result = init_db(db_path)
    assert result == db_path
    assert db_path.exists()

    with get_connection(db_path) as conn:
        # Check tables exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "competitors" in table_names
        assert "products" in table_names
        assert "price_points" in table_names
        assert "own_pricing" in table_names

        # Check competitors were seeded
        count = conn.execute("SELECT COUNT(*) as cnt FROM competitors").fetchone()
        assert count["cnt"] > 0

        # Check products were seeded
        count = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()
        assert count["cnt"] > 0

        # Check pricing URLs were seeded
        count = conn.execute("SELECT COUNT(*) as cnt FROM pricing_urls").fetchone()
        assert count["cnt"] > 0


def test_init_db_idempotent(tmp_path):
    """Test that init_db can be called multiple times safely."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_db(db_path)  # Should not raise

    with get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM competitors").fetchone()
        assert count["cnt"] > 0


def test_get_db_stats(tmp_db):
    """Test database statistics."""
    stats = get_db_stats(tmp_db)
    assert "competitors" in stats
    assert "products" in stats
    assert "price_points" in stats
    assert stats["competitors"] > 0
    assert stats["products"] > 0


def test_prune_old_records(tmp_db):
    """Test pruning old records."""
    # Insert a price point
    with get_connection(tmp_db) as conn:
        conn.execute(
            """INSERT INTO price_points
               (competitor_id, product_id, quantity, total_price, scraped_at)
               VALUES (1, 1, 100, 29.99, datetime('now', '-100 days'))"""
        )
        conn.execute(
            """INSERT INTO price_points
               (competitor_id, product_id, quantity, total_price, scraped_at)
               VALUES (1, 1, 100, 29.99, datetime('now'))"""
        )

    deleted = prune_old_records(30, tmp_db)
    assert deleted == 1

    with get_connection(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM price_points").fetchone()
        assert count["cnt"] == 1
