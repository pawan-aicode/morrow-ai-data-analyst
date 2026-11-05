import json
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sales.db"
API_URL = "http://localhost:11434/api/chat"

MODELS = [
    "qwen3.5:4b-q4_K_M",
    "qwen3.5:4b-q4_K_M",
]

PROMPT = """
Generate one SQLite SELECT query.

Question: Show the top 5 products by revenue from completed orders.

Schema:
products(product_id, product_name, category, unit_price)
orders(order_id, customer_id, order_date, status)
order_items(order_item_id, order_id, product_id, quantity, unit_price)

Revenue = SUM(order_items.quantity * order_items.unit_price).
Only completed orders count.
Join order_items to orders on order_id.
Join order_items to products on product_id.
Group by product_id and product_name.
Sort by revenue descending and return 5 rows.

Return only SQL. No explanations or Markdown.
"""

EXPECTED_SQL = """
SELECT p.product_id, p.product_name,
       SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.status = 'completed'
GROUP BY p.product_id, p.product_name
ORDER BY revenue DESC
LIMIT 5
"""

def get_sql(model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode())
    elapsed = time.perf_counter() - start
    sql = data.get("message", {}).get("content", "").strip()
    return sql, elapsed

def execute_read_only(sql):
    # Open the existing database without allowing writes.
    uri = f"{DB_PATH.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        # Require exactly one read-only SELECT statement.
        statements = [part.strip() for part in sql.split(";") if part.strip()]
        if len(statements) != 1:
            raise ValueError("Expected exactly one SQL statement")
        statement = statements[0]
        if not statement.lower().startswith("select"):
            raise ValueError("Only SELECT queries are allowed")
        return conn.execute(statement).fetchall()

with sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True) as conn:
    expected = conn.execute(EXPECTED_SQL).fetchall()

print("Expected top-five results:")
for row in expected:
    print(row)

for model in MODELS:
    print("\n" + "=" * 65)
    print("MODEL:", model)

    try:
        sql, elapsed = get_sql(model)
        print(f"Response time: {elapsed:.2f} seconds")
        print("Generated SQL:\n", sql)

        actual = execute_read_only(sql)
        passed = actual == expected

        print("Rows returned:", len(actual))
        print("Exact result match:", "PASS" if passed else "FAIL")

        if not passed:
            print("Actual results:")
            for row in actual:
                print(row)

    except Exception as exc:
        print("TEST FAILED:", repr(exc))
