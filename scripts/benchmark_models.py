import json
import time
import urllib.request

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

Rules:
- Revenue = SUM(order_items.quantity * order_items.unit_price).
- Only include orders where status = 'completed'.
- Join order_items to orders on order_id.
- Join order_items to products on product_id.
- Group by product_id and product_name.
- Sort by revenue descending.
- Return only 5 rows.

Return only SQL, without explanations or Markdown.
"""

for model in MODELS:
    print("\n" + "=" * 60)
    print("MODEL:", model)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
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

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))

        elapsed = time.perf_counter() - start
        message = result.get("message", {})

        print(f"Elapsed: {elapsed:.2f} seconds")
        print("SQL/model response:")
        print(message.get("content", "").strip())

        thinking = message.get("thinking", "")
        if thinking:
            print("Separate thinking output: present")

        print("Prompt tokens:", result.get("prompt_eval_count"))
        print("Generated tokens:", result.get("eval_count"))
        print("Generation time (seconds):",
              round(result.get("eval_duration", 0) / 1e9, 2))

    except Exception as exc:
        print("Request failed:", repr(exc))
