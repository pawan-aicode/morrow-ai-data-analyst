import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sales.db"

customers = [
    ("Aarav Sharma", "Delhi"),
    ("Priya Verma", "Mumbai"),
    ("Rohan Singh", "Bengaluru"),
    ("Ananya Gupta", "Pune"),
    ("Kabir Mehta", "Hyderabad"),
    ("Isha Patel", "Ahmedabad"),
    ("Arjun Rao", "Chennai"),
    ("Meera Nair", "Kochi"),
    ("Vivaan Jain", "Jaipur"),
    ("Sana Khan", "Lucknow"),
    ("Dev Malhotra", "Delhi"),
    ("Aditi Das", "Kolkata"),
    ("Reyansh Kapoor", "Chandigarh"),
    ("Kiara Joshi", "Indore"),
    ("Ibrahim Ali", "Bhopal"),
    ("Myra Roy", "Mumbai"),
    ("Advik Sethi", "Noida"),
    ("Zoya Fernandes", "Goa"),
    ("Krish Bansal", "Gurugram"),
    ("Tara Iyer", "Coimbatore"),
]

products = [
    ("Laptop Pro", "Electronics", 75000),
    ("Wireless Mouse", "Accessories", 1200),
    ("Mechanical Keyboard", "Accessories", 4500),
python scripts/create_database.pyue: {revenue:,.2f}")id2)ROM order_items").fetch
Database created: /home/pawan/Projects/ai-data-analyst/data/sales.db
Customers: 20
Products: 10
Orders: 500
Order items: 1278
Completed-order revenue: 19,452,100.00
(.venv) pawan@pawan:~/Projects/ai-data-analyst$
python - <<'PY'
import sqlite3
from pathlib import Path

db = Path("data/sales.db")
assert db.exists(), "Database file was not created"

with sqlite3.connect(db) as conn:
    tables = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
    """).fetchall()

    print("Tables:", [row[0] for row in tables])

    print("\nTop 5 products by completed-order revenue:")

    rows = conn.execute("""
        SELECT
            p.product_name,
            SUM(oi.quantity * oi.unit_price) AS revenue
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE o.status = 'completed'
        GROUP BY p.product_id, p.product_name
        ORDER BY revenue DESC
        LIMIT 5
    """).fetchall()

    for name, revenue in rows:
        print(f"{name}: {revenue:,.2f}")

print("\nDatabase verification passed.")
