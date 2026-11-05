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
SQLite schema:
customers(customer_id, name, city)
products(product_id, product_name, category, unit_price)
orders(order_id, customer_id, order_date, status)
order_items(order_item_id, order_id, product_id, quantity, unit_price)

Join keys:
orders.customer_id = customers.customer_id
order_items.order_id = orders.order_id
order_items.product_id = products.product_id

Completed-order revenue = SUM(quantity * unit_price).
Dates are stored as YYYY-MM-DD text.
Use SQLite syntax only. Return one SQL query and no explanation.
"""

TESTS = [
    {
        "name": "September and October revenue",
        "question": (
            "For completed orders in September and October 2026, return "
            "month in exactly YYYY-MM format and revenue. Sort month "
            "descending. Use SQLite date/string functions."
        ),
        "expected": """
            SELECT SUBSTR(o.order_date, 1, 7) AS month,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.status = 'completed'
              AND SUBSTR(o.order_date, 1, 7) IN ('2026-09', '2026-10')
            GROUP BY SUBSTR(o.order_date, 1, 7)
            ORDER BY month DESC
        """,
        "format_check": "month_yyyy_mm",
    },
    {
        "name": "Top 10 customers by completed spending",
        "question": (
            "Return the top 10 customers by revenue from completed orders. "
            "Columns: customer_id, name, total_spending. Sort by spending "
            "descending, breaking ties by customer_id ascending."
        ),
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
        """,
        "format_check": None,
    },
    {
        "name": "Cancellation percentage",
        "question": (
            "Calculate the cancellation rate across all orders. Return "
            "total_orders, cancelled_orders, cancellation_rate_pct. "
            "Round the percentage to two decimal places."
        ),
        "expected": """
            SELECT COUNT(*) AS total_orders,
                   SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)
                       AS cancelled_orders,
                   ROUND(
                     100.0 * SUM(
                       CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END
                     ) / NULLIF(COUNT(*), 0), 2
                   ) AS cancellation_rate_pct
            FROM orders
        """,
        "format_check": None,
    },
    {
        "name": "Products never referenced by order items",
        "question": (
            "Find products that have never appeared in order_items. "
            "Return product_id and product_name in product_id ascending order. "
            "Do not confuse this with products that have no completed sales."
        ),
        "expected": """
            SELECT p.product_id, p.product_name
            FROM products p
            WHERE NOT EXISTS (
                SELECT 1 FROM order_items oi
                WHERE oi.product_id = p.product_id
            )
            ORDER BY p.product_id
        """,
        "format_check": None,
    },
    {
        "name": "Top two customers in each city",
        "question": (
            "For every city, find the two highest-revenue customers based "
            "only on completed orders. Return city, customer_id, name, "
            "revenue and rank_in_city. Use RANK() so ties at rank 2 are "
            "included. Sort by city, rank_in_city, then customer_id. "
            "Use SQLite-compatible SQL; do not use QUALIFY."
        ),
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
                       ) AS rank_in_city
                FROM customer_revenue
            )
            SELECT city, customer_id, name, revenue, rank_in_city
            FROM ranked
            WHERE rank_in_city <= 2
            ORDER BY city, rank_in_city, customer_id
        """,
        "format_check": None,
    },
]

def normalize(rows):
    output = []
    for row in rows:
        values = []
        for value in row:
            if isinstance(value, float):
                value = round(value, 2)
            values.append(value)
        output.append(tuple(values))
    return output

def execute_readonly(sql):
    cleaned = sql.strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.I):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed.")

    uri = DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: 1, 2_000_000)
        cursor = conn.execute(cleaned)
        rows = cursor.fetchmany(501)
        if len(rows) > 500:
            raise ValueError("Result exceeds 500 rows.")
        columns = [d[0].lower() for d in cursor.description or []]
        return columns, normalize(rows)

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

    raw = data["message"]["content"].strip()
    cleaned = re.sub(r"```(?:sql)?", "", raw, flags=re.I).replace("```", "")
    match = re.search(r"\b(SELECT|WITH)\b", cleaned, re.I)
    if not match:
        raise ValueError("No SQL found in model response.")
    return cleaned[match.start():].strip(), elapsed

def check_format(test, columns, rows):
    check = test["format_check"]
    if check == "month_yyyy_mm":
        if "month" not in columns:
            return False, "Missing column named month"
        index = columns.index("month")
        bad = [
            row[index] for row in rows
            if not isinstance(row[index], str)
            or not re.fullmatch(r"\d{4}-\d{2}", row[index])
        ]
        if bad:
            return False, f"Month values must use YYYY-MM; got {bad}"
    return True, "OK"

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    summary = []
    print("BENCHMARK V2 — EXECUTION / CORRECTNESS / FORMAT")
    print("Database:", DB_PATH)

    for test in TESTS:
        print("\n" + "=" * 72)
        print("TEST:", test["name"])
        expected_columns, expected_rows = execute_readonly(test["expected"])
        print("Reference rows:", len(expected_rows))

        for model in MODELS:
            print(f"\nModel: {model}")
            elapsed = None
            try:
                sql, elapsed = ask_model(model, test["question"])
                columns, rows = execute_readonly(sql)
                correct = rows == expected_rows
                format_ok, format_note = check_format(test, columns, rows)

                print("Execution: PASS")
                print("Result correctness:", "PASS" if correct else "FAIL")
                print("Format:", "PASS" if format_ok else "FAIL", "-", format_note)
                print(f"Response time: {elapsed:.2f}s")

                if not correct:
                    print("Expected columns:", expected_columns)
                    print("Actual columns:  ", columns)
                    print("Expected rows (first 5):", expected_rows[:5])
                    print("Actual rows   (first 5):", rows[:5])

                print("Generated SQL:\n" + sql)
                summary.append({
                    "model": model, "execution": True,
                    "correct": correct, "format": format_ok,
                    "time": elapsed,
                })
            except Exception as exc:
                print(f"Execution: FAIL — {type(exc).__name__}: {exc}")
                summary.append({
                    "model": model, "execution": False,
                    "correct": False, "format": False,
                    "time": elapsed,
                })

    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    for model in MODELS:
        entries = [r for r in summary if r["model"] == model]
        execution = sum(r["execution"] for r in entries)
        correct = sum(r["correct"] for r in entries)
        formatted = sum(r["format"] for r in entries)
        times = [r["time"] for r in entries if r["time"] is not None]
        avg = sum(times) / len(times) if times else 0
        print(f"\n{model}")
        print(f"  Executed: {execution}/{len(entries)}")
        print(f"  Correct results: {correct}/{len(entries)}")
        print(f"  Format checks passed: {formatted}/{len(entries)}")
        print(f"  Mean API response time: {avg:.2f}s (successful API calls only)")

    print("\nBenchmark complete. Database was opened read-only.")

if __name__ == "__main__":
    main()
