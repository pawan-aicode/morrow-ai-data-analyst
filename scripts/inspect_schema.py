import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.db"

with sqlite3.connect(DB_PATH) as conn:
    tables = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    print("DATABASE SCHEMA")
    print("=" * 50)

    for (table,) in tables:
        print(f"\nTable: {table}")

        columns = conn.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()

        for column in columns:
            _, name, data_type, not_null, default, primary_key = column
            details = f"{name} ({data_type})"

            if primary_key:
                details += " PRIMARY KEY"
            if not_null:
                details += " NOT NULL"

            print("  -", details)

        foreign_keys = conn.execute(
            f'PRAGMA foreign_key_list("{table}")'
        ).fetchall()

        for fk in foreign_keys:
            print(f"  - FOREIGN KEY: {fk[3]} -> {fk[2]}.{fk[4]}")
