import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH = Path("data/sales.db").resolve()
API_URL = "http://localhost:11434/api/chat"
MODELS = ["qwen3.5:4b-q4_K_M", "qwen3.5:4b-q4_K_M"]

SCHEMA = """
SQLite database schema:
customers(customer_id, name, city)
products(product_id, product_name, category, unit_price)
orders(order_id, customer_id, order_date, status)
order_items(order_item_id, order_id, product_id, quantity, unit_price)

Relationships:
orders.customer_id = customers.customer_id
order_items.order_id = orders.order_id
order_items.product_id = products.product_id

Completed-order revenue = SUM(order_items.quantity * order_items.unit_price).
Dates are stored as YYYY-MM-DD text.
Use SQLite syntax, not MySQL syntax.
Return one SQL query only. Do not modify data.
"""

TESTS = [
    {
        "name": "October vs September 2026 revenue",
        "question": "For completed orders, calculate revenue for October 2026 and September 2026. Return month and revenue, with the newer month first.",
        "expected": """
            SELECT SUBSTR(o.order_date, 1, 7) AS month,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.status = 'completed'
              AND SUBSTR(o.order_date, 1, 7) IN ('2026-10', '2026-09')
            GROUP BY SUBSTR(o.order_date, 1, 7)
            ORDER BY month DESC
        """
    },
    {
        "name": "Top 10 customers by spending",
        "question": "Find the top 10 customers by total spending on completed orders. Return customer_id, customer name, and total_spending, highest first.",
        "expected": """
            SELECT c.customer_id, c.name,
                   SUM(oi.quantity * oi.unit_price) AS total_spending
            FROM customers c
            JOIN orders o ON o.customer_id = c.customer_id
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.status = 'completed'
            GROUP BY c.customer_id, c.name
            ORDER BY total_spending DESC, c.customer_id ASC
            LIMIT 10
        """
    },
    {
        "name": "Cancellation rate",
        "question": "Calculate the cancellation rate as a percentage of all orders. Return total_orders, cancelled_orders, and cancellation_rate_pct. Round the percentage to two decimal places.",
        "expected": """
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)
                       AS cancelled_orders,
                   ROUND(
                       100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)
                       / NULLIF(COUNT(*), 0), 2
                   ) AS cancellation_rate_pct
            FROM orders
        """
    },
    {
        "name": "Products never ordered",
        "question": "Find products that have never appeared in order_items, including products that have never been ordered at all. Return product_id and product_name in product_id order.",
        "expected": """
            SELECT p.product_id, p.product_name
            FROM products p
            WHERE NOT EXISTS (
                SELECT 1
                FROM order_items oi
                WHERE oi.product_id = p.product_id
            )
            ORDER BY p.product_id
        """
    },
    {
        "name": "Top customer per city",
        "question": "Find the highest-spending customer in each city using completed-order revenue. Return city, customer_id, customer name, and revenue. If customers tie, include all tied customers. Sort by city, then customer_id.",
        "expected": """
            WITH customer_revenue AS (
                SELECT c.city, c.customer_id, c.name,
                       SUM(oi.quantity * oi.unit_price) AS revenue
                FROM customers c
                JOIN orders o ON o.customer_id = c.customer_id
                JOIN order_items oi ON oi.order_id = o.order_id
                WHERE o.status = 'completed'
                GROUP BY c.city, c.customer_id, c.name
            ),
            ranked AS (
                SELECT city, customer_id, name, revenue,
                       RANK() OVER (
                           PARTITION BY city ORDER BY revenue DESC
                       ) AS city_rank
                FROM customer_revenue
            )
            SELECT city, customer_id, name, revenue
            FROM ranked
            WHERE city_rank = 1
            ORDER BY city, customer_id
        """
    },
]

def normalize(rows):
    normalized = []
    for row in rows:
        values = []
        for value in row:
            if isinstance(value, float):
                value = round(value, 2)
            values.append(value)
        normalized.append(tuple(values))
    return normalized

def run_readonly(sql):
    # Allow only a single read-only SELECT/WITH statement.
    cleaned = sql.strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.I):
        raise ValueError("Rejected: query must start with SELECT or WITH.")
    if ";" in cleaned:
        raise ValueError("Rejected: multiple statements are not allowed.")

    uri = DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: 1, 2_000_000)
        cursor = conn.execute(cleaned)
        rows = cursor.fetchmany(501)
        if len(rows) > 500:
            raise ValueError("Query returned more than 500 rows.")
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
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read().decode())
    elapsed = time.perf_counter() - start

    content = data["message"]["content"].strip()
    content = re.sub(r"```(?:sql)?", "", content, flags=re.I).replace("```", "")
    match = re.search(r"\b(SELECT|WITH)\b", content, re.I)
    if not match:
        raise ValueError("No SQL found in response: " + content[:200])
    return content[match.start():].strip(), elapsed

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    results = []
    print("HARD SQL BENCHMARK")
    print(f"Database: {DB_PATH}")
    print("")

    for test in TESTS:
        print("=" * 72)
        print("TEST:", test["name"])
        expected = run_readonly(test["expected"])
        print("Reference rows:", len(expected))

        for model in MODELS:
            print(f"\nModel: {model}")
            try:
                sql, elapsed = ask_model(model, test["question"])
                actual = run_readonly(sql)
                passed = actual == expected
                status = "PASS" if passed else "FAIL"
                print(f"Time: {elapsed:.2f}s | Result: {status}")
                if not passed:
                    print("Expected (first 5):", expected[:5])
                    print("Actual   (first 5):", actual[:5])
                print("SQL:")
                print(sql)
                results.append((model, passed, elapsed))
            except Exception as exc:
                print(f"Result: ERROR | {type(exc).__name__}: {exc}")
                results.append((model, False, None))

    print("\n" + "=" * 72)
    print("SUMMARY")
    for model in MODELS:
        model_results = [r for r in results if r[0] == model]
        passed = sum(r[1] for r in model_results)
        times = [r[2] for r in model_results if r[2] is not None]
        avg = sum(times) / len(times) if times else None
        print(f"{model}: {passed}/{len(model_results)} passed")
        print(f"  Mean response time for successful API calls: "
              f"{avg:.2f}s" if avg is not None else "  No successful API timings")

    print("\nFinished. Database opened read-only.")

if __name__ == "__main__":
    main()
