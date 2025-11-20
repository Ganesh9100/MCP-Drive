"""
create_orders_db.py
--------------------
Creates a local SQLite database named 'orders.db' with dummy telecom
order data — 3 customers, 3 orders each, and order event timelines.

Run:
    python create_orders_db.py
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
import random
import os

DB_PATH = "orders.db"

# Remove existing DB if you want a fresh dataset
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# Connect to SQLite
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Create schema
cur.executescript("""
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL
);

CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    eta TEXT,
    total_amount REAL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_events (
    event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY(order_id) REFERENCES orders(order_id)
);
""")

# Dummy customers
customers = [
    {"customer_id": f"cust_{i}", "name": f"Customer {i}", "email": f"customer{i}@example.com"}
    for i in range(1, 4)
]
cur.executemany("INSERT INTO customers VALUES (:customer_id, :name, :email)", customers)

# Dummy orders and events
statuses = ["ORDERED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]
now = datetime.now()
orders, events = [], []

for c in customers:
    for j in range(1, 4):
        order_id = f"{c['customer_id']}-ord-{j}"
        created_at = (now - timedelta(days=random.randint(1, 10))).isoformat()
        status = random.choice(statuses)
        eta = None if status in ("DELIVERED", "CANCELLED") else (now + timedelta(days=random.randint(1, 7))).isoformat()
        total_amount = round(random.uniform(199.0, 4999.0), 2)

        orders.append({
            "order_id": order_id,
            "customer_id": c["customer_id"],
            "created_at": created_at,
            "status": status,
            "eta": eta,
            "total_amount": total_amount,
        })

        # Build event timeline
        timeline = [("ORDER_PLACED", "Order placed by customer"), ("PAYMENT_CONFIRMED", "Payment received")]
        if status in ("DISPATCHED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"):
            timeline.append(("DISPATCHED", "Order dispatched"))
        if status in ("IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"):
            timeline.append(("IN_TRANSIT", "Package in transit"))
        if status == "DELIVERED":
            timeline.append(("DELIVERED", "Delivered to customer"))

        ts = datetime.fromisoformat(created_at)
        for etype, note in timeline:
            ts += timedelta(hours=random.randint(4, 24))
            events.append({
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "ts": ts.isoformat(),
                "event_type": etype,
                "note": note,
            })

# Insert data
cur.executemany(
    "INSERT INTO orders VALUES (:order_id, :customer_id, :created_at, :status, :eta, :total_amount)",
    orders
)
cur.executemany(
    "INSERT INTO order_events VALUES (:event_id, :order_id, :ts, :event_type, :note)",
    events
)
conn.commit()

# Show summary
print(f"Database '{DB_PATH}' created successfully!\n")
print("Sample customers:")
for row in cur.execute("SELECT * FROM customers LIMIT 3"):
    print(row)

print("\nSample orders:")
for row in cur.execute("SELECT order_id, customer_id, status, eta FROM orders LIMIT 5"):
    print(row)

print("\nSample events:")
for row in cur.execute("SELECT order_id, event_type, ts FROM order_events LIMIT 5"):
    print(row)

conn.close()
