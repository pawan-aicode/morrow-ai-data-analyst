import json
import sqlite3
import time
import urllib.request

MODEL = "qwen3.5:4b-q4_K_M"
API_URL = "http://localhost:11434/api/chat"

# Isolated in-memory test database — your real DB is untouched.
conn = sqlite3.connect(":memory:")
conn.executescript("""
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT,
    city TEXT
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    status TEXT
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    quantity INTEGER,
    unit_price REAL
);

INSERT INTO customers VALUES
(1, 'Asha', 'Delhi'),
(2, 'Bala', 'Delhi'),
(3, 'Charu', 'Delhi'),
(4, 'Dev', 'Delhi'),
(5, 'Esha', 'Mumbai'),
(6, 'Farhan', 'Mumbai'),
(7, 'Gita', 'Mumbai');

INSERT INTO orders VALUES
(101, 1, 'completed'),
(102, 2, 'completed'),
(103, 3, 'completed'),
(104, 4, 'completed'),
(105, 5, 'completed'),
(106, 6, 'completed'),
(107, 7, 'cancelled');

INSERT INTO order_items VALUES
(1, 101, 10, 100),  -- Asha: 1000
(2, 102, 5, 100),   -- Bala: 500
(3, 103, 5, 100),   -- Charu: 500 (tie at rank 2)
(4, 104, 2, 100),   -- Dev: 200
(5, 105, 8, 100),   -- Esha: 800
(6, 106, 4, 100),   -- Farhan: 400
(7, 107, 99, 100);  -- Gita: cancelled; must be excluded
""")


question = """
For each city, rank customers by their total revenue from completed
orders, highest first. Return city, customer_id, name, revenue,
rank_in_city.

Requirements:
- Use RANK() OVER (PARTITION BY city ORDER BY revenue DESC).
- Include all customers tied at rank 2.
- Exclude customers ranked 3 or lower.
- SQLite does not allow window functions in WHERE or HAVING.
- Calculate revenue in a CTE named customer_revenue.
- Calculate rank_in_city in a second CTE named ranked.
- In the final SELECT, filter with WHERE rank_in_city <= 2.
- Exclude cancelled orders.
- Use SQLite-compatible SQL only.
- Return only SQL, without Markdown or explanation.
"""
schema = """
SQLite schema:
customers(customer_id, name, city)
orders(order_id, customer_id, status)
order_items(order_item_id, order_id, quantity, unit_price)
Revenue = SUM(quantity * unit_price).
Join orders to customers by customer_id and order_items by order_id.
"""

payload = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": schema},
        {"role": "user", "content": question},
    ],
    "stream": False,
    "think": False,
    "options": {"temperature": 0, "num_predict": 400},
}

request = urllib.request.Request(
    API_URL,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

print("Testing:", MODEL)
start = time.perf_counter()

with urllib.request.urlopen(request, timeout=180) as response:
    result = json.loads(response.read().decode())

elapsed = time.perf_counter() - start
sql = result["message"]["content"].strip()
sql = sql.replace("```sql", "").replace("```", "").strip()

print(f"\nResponse time: {elapsed:.2f}s")
print("\nGenerated SQL:\n", sql)

try:
    rows = conn.execute(sql).fetchall()

    expected = [
        ("Delhi", 1, "Asha", 1000.0, 1),
        ("Delhi", 2, "Bala", 500.0, 2),
        ("Delhi", 3, "Charu", 500.0, 2),
        ("Mumbai", 5, "Esha", 800.0, 1),
        ("Mumbai", 6, "Farhan", 400.0, 2),
    ]

    # Normalize numeric values for stable comparison.
    normalized = [
        (city, cid, name, round(revenue, 2), rank)
        for city, cid, name, revenue, rank in rows
    ]

    print("\nExpected rows:", len(expected))
    print("Actual rows:", len(normalized))
    print("Exact correctness:", "PASS" if normalized == expected else "FAIL")

    if normalized != expected:
        print("\nExpected:", expected)
        print("Actual:  ", normalized)

except sqlite3.Error as exc:
    print("\nSQL execution: FAIL —", exc)

conn.close()
