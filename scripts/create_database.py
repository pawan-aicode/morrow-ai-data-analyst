import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sales.db"
RANDOM_SEED = 42

CUSTOMERS = [
    ("Customer 001", "Delhi"),
    ("Customer 002", "Mumbai"),
    ("Customer 003", "Bengaluru"),
    ("Customer 004", "Pune"),
    ("Customer 005", "Hyderabad"),
    ("Customer 006", "Ahmedabad"),
    ("Customer 007", "Chennai"),
    ("Customer 008", "Kochi"),
    ("Customer 009", "Jaipur"),
    ("Customer 010", "Lucknow"),
    ("Customer 011", "Delhi"),
    ("Customer 012", "Kolkata"),
    ("Customer 013", "Chandigarh"),
    ("Customer 014", "Indore"),
    ("Customer 015", "Bhopal"),
    ("Customer 016", "Mumbai"),
    ("Customer 017", "Noida"),
    ("Customer 018", "Goa"),
    ("Customer 019", "Gurugram"),
    ("Customer 020", "Coimbatore"),
]

PRODUCTS = [
    ("Laptop Pro", "Electronics", 75000.0),
    ("Wireless Mouse", "Accessories", 1200.0),
    ("Mechanical Keyboard", "Accessories", 4500.0),
    ("Monitor 27 inch", "Electronics", 22000.0),
    ("USB-C Hub", "Accessories", 2800.0),
    ("Office Chair", "Furniture", 12500.0),
    ("Standing Desk", "Furniture", 28000.0),
    ("Webcam HD", "Electronics", 5500.0),
    ("Headphones", "Electronics", 8500.0),
    ("Laptop Stand", "Accessories", 1800.0),
]

STATUS_COUNTS = {
    "cancelled": 102,
    "completed": 235,
    "processing": 85,
    "shipped": 78,
}

# Completed-order quantities keep the demo's benchmark output deterministic.
COMPLETED_PRODUCT_TARGETS = {
    1: (50, 119),
    7: (45, 115),
    4: (45, 141),
    6: (35, 120),
    9: (30, 87),
    2: (20, 40),
    3: (10, 20),
}


def _create_schema(connection):
    connection.executescript(
        """
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL
        );

        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit_price REAL NOT NULL CHECK (unit_price >= 0)
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('completed', 'shipped', 'processing', 'cancelled')
            ),
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );

        CREATE INDEX idx_orders_date ON orders(order_date);
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_order_items_order ON order_items(order_id);
        CREATE INDEX idx_order_items_product ON order_items(product_id);
        """
    )


def _quantities(total_units, order_count, rng):
    quantities = [total_units // order_count] * order_count
    for index in rng.sample(range(order_count), total_units % order_count):
        quantities[index] += 1
    return quantities


def _completed_items(order_ids, rng):
    assignments = []
    available_orders = list(order_ids)
    rng.shuffle(available_orders)

    for product_id, (order_count, total_units) in COMPLETED_PRODUCT_TARGETS.items():
        selected = available_orders[:order_count]
        available_orders = available_orders[order_count:]
        quantities = _quantities(total_units, order_count, rng)
        assignments.extend(
            (order_id, product_id, quantity)
            for order_id, quantity in zip(selected, quantities)
        )

    return assignments, available_orders


def create_database(db_path=DB_PATH):
    """Create a deterministic synthetic sales database at ``db_path``."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED)

    statuses = [
        status
        for status, count in STATUS_COUNTS.items()
        for _ in range(count)
    ]
    rng.shuffle(statuses)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO customers(customer_id, name, city) VALUES (?, ?, ?)",
            ((index, name, city) for index, (name, city) in enumerate(CUSTOMERS, 1)),
        )
        connection.executemany(
            """
            INSERT INTO products(product_id, product_name, category, unit_price)
            VALUES (?, ?, ?, ?)
            """,
            (
                (index, name, category, price)
                for index, (name, category, price) in enumerate(PRODUCTS, 1)
            ),
        )

        start_date = date(2025, 1, 1)
        orders = [
            (
                order_id,
                rng.randint(1, len(CUSTOMERS)),
                (start_date + timedelta(days=rng.randint(0, 663))).isoformat(),
                status,
            )
            for order_id, status in enumerate(statuses, 1)
        ]
        connection.executemany(
            """
            INSERT INTO orders(order_id, customer_id, order_date, status)
            VALUES (?, ?, ?, ?)
            """,
            orders,
        )

        completed_ids = [
            order_id for order_id, _, _, status in orders if status == "completed"
        ]
        items, remaining_completed_ids = _completed_items(completed_ids, rng)

        for order_id in remaining_completed_ids:
            product_id = rng.choice((2, 3))
            items.append((order_id, product_id, rng.randint(1, 2)))

        for order_id, _, _, status in orders:
            if status == "completed":
                continue
            for _ in range(rng.randint(1, 4)):
                items.append((order_id, rng.randint(1, len(PRODUCTS)), rng.randint(1, 3)))

        connection.executemany(
            """
            INSERT INTO order_items(order_id, product_id, quantity, unit_price)
            SELECT ?, ?, ?, unit_price
            FROM products
            WHERE product_id = ?
            """,
            [(order_id, product_id, quantity, product_id) for order_id, product_id, quantity in items],
        )
        connection.commit()

    print(f"Database created: {db_path}")
    print(f"Customers: {len(CUSTOMERS)}")
    print(f"Products: {len(PRODUCTS)}")
    print(f"Orders: {len(orders)}")
    print(f"Order items: {len(items)}")


if __name__ == "__main__":
    create_database()
