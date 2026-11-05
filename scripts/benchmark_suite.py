import json
import re
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path

DB_PATH = Path("data/sales.db").resolve()
API_URL = "http://localhost:11434/api/chat"
MODELS = ["qwen3.5:4b-q4_K_M", "qwen3.5:4b-q4_K_M"]

SCHEMA = """
Tables:
customers(customer_id, name, city)
products(product_id, product_name, category, unit_price)
orders(order_id, customer_id, order_date, status)
order_items(order_item_id, order_id, product_id, quantity, unit_price)

Relationships:
orders.customer_id = customers.customer_id
order_items.order_id = orders.order_id
order_items.product_id = products.product_id

Revenue means SUM(order_items.quantity * order_items.unit_price).
Only include completed orders when the question says completed orders.
Return SQL only. Use SQLite syntax. Do not modify the database.
"""

TESTS = [
    {
        "name": "Top 5 products by revenue",
        "question": "Find the top 5 products by revenue from completed orders. Return product_id, product_name, and revenue, highest revenue first.",
        "expected": """
            SELECT p.product_id, p.product_name,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE o.status = 'completed'
            GROUP BY p.product_id, p.product_name
            ORDER BY revenue DESC
            LIMIT 5
        """
    },
    {
        "name": "Monthly revenue in 2026",
        "question": "For completed orders in 2026, calculate revenue for each month. Return month as YYYY-MM and revenue, highest revenue first.",
        "expected": """
            SELECT SUBSTR(o.order_date, 1, 7) AS month,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.status = 'completed'
              AND SUBSTR(o.order_date, 1, 4) = '2026'
            GROUP BY SUBSTR(o.order_date, 1, 7)
            ORDER BY revenue DESC
        """
    },
    {
        "name": "Revenue by customer city",
        "question": "Calculate total revenue from completed orders for each customer city. Return city and revenue, highest revenue first.",
        "expected": """
            SELECT c.city, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM customers c
            JOIN orders o ON o.customer_id = c.customer_id
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.status = 'completed'
            GROUP BY c.city
            ORDER BY revenue DESC
        """
    },
    {
        "name": "Order count by status",
        "question": "Count orders for each status. Return status and order_count, highest count first, and break ties by status alphabetically.",
        "expected": """
            SELECT status, COUNT(*) AS order_count
            FROM orders
            GROUP BY status
            ORDER BY order_count DESC, status ASC
        """
    },
    {
        "name": "Top categories by quantity sold",
        "question": "Find product categories with the highest total quantity sold in completed orders. Return category and quantity_sold, highest quantity first.",
        "expected": """
            SELECT p.category, SUM(oi.quantity) AS quantity_sold
            FROM products p
            JOIN order_items oi ON oi.product_id = p.product_id
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.status = 'completed'
            GROUP BY p.category
            ORDER BY quantity_sold DESC, p.category ASC
        """
    },
]

def normalize(rows):
    result = []
    for row in rows:
        values = []
        for value in row:
            if isinstance(value, float):
                value = round(value, 2)
            values.append(value)
        result.append(tuple(values))
    return result

def run_readonly(sql):
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.I):
        raise ValueError("Rejected: SQL must start with SELECT or WITH.")
    if ";" in sql.rstrip().rstrip(";"):
        raise ValueError("Rejected: multiple SQL statements are not allowed.")

    uri = DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: 1, 2000000)
        cursor = conn.execute(sql.rstrip().rstrip(";"))
        rows = cursor.fetchmany(501)
        if len(rows) > 500:
            raise ValueError("Rejected: query returned more than 500 rows.")
        return normalize(rows)

def ask_model(model, question):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SCHEMA},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read().decode("utf-8"))
    elapsed = time.perf_counter() - start
    content = data["message"]["content"].strip()
    content = re.sub(r"```(?:sql)?", "", content, flags=re.I).replace("```", "")
    match = re.search(r"\b(SELECT|WITH)\b", content, re.I)
    if not match:
        raise ValueError("No SQL found in model response: " + content[:200])
    sql = content[match.start():].strip()
    return sql, elapsed

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    print("AI DATA ANALYST — MODEL BENCHMARK")
    print(f"Database: {DB_PATH}")
    print("Each test compares generated-query results with trusted-query results.")
    print("")

    for test in TESTS:
        print("=" * 72)
        print(f"TEST: {test['name']}")
        expected = run_readonly(test["expected"])
        print(f"Reference result rows: {len(expected)}")

        for model in MODELS:
            print(f"\nModel: {model}")
            try:
                sql, elapsed = ask_model(model, test["question"])
                actual = run_readonly(sql)
                passed = actual == expected
                print(f"Time: {elapsed:.2f}s")
                print(f"Result rows: {len(actual)}")
                print("Result match:", "PASS" if passed else "FAIL")
                if not passed:
                    print("Expected (first 5):", expected[:5])
                    print("Actual   (first 5):", actual[:5])
                print("Generated SQL:")
                print(sql)
            except Exception as exc:
                print("Result match: ERROR")
                print(f"Details: {type(exc).__name__}: {exc}")

    print("\nBenchmark finished. No database changes were permitted.")

if __name__ == "__main__":
    main()
