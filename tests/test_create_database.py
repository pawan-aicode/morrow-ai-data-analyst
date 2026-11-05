import sqlite3

from scripts.create_database import create_database


def test_create_database_builds_valid_synthetic_schema(tmp_path):
    db_path = tmp_path / "nested" / "sales.db"

    create_database(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("customers", "products", "orders", "order_items")
        }
        status_counts = dict(
            connection.execute(
                "SELECT status, COUNT(*) FROM orders GROUP BY status"
            )
        )
        orphaned_items = connection.execute(
            """
            SELECT COUNT(*)
            FROM order_items oi
            LEFT JOIN orders o ON o.order_id = oi.order_id
            LEFT JOIN products p ON p.product_id = oi.product_id
            WHERE o.order_id IS NULL OR p.product_id IS NULL
            """
        ).fetchone()[0]
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert {"customers", "products", "orders", "order_items"} <= tables
    assert counts == {
        "customers": 20,
        "products": 10,
        "orders": 500,
        "order_items": 927,
    }
    assert status_counts == {
        "cancelled": 102,
        "completed": 235,
        "processing": 85,
        "shipped": 78,
    }
    assert orphaned_items == 0
    assert foreign_key_errors == []


def test_create_database_is_safe_to_rerun(tmp_path):
    db_path = tmp_path / "sales.db"

    create_database(db_path)
    create_database(db_path)

    with sqlite3.connect(db_path) as connection:
        counts = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("customers", "products", "orders", "order_items")
        ]

    assert counts == [20, 10, 500, 927]
