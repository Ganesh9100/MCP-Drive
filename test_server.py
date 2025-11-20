from mcp.server.fastmcp import FastMCP

import sqlite3

mcp=FastMCP("orders")


@mcp.tool()
async def get_orders_schema() -> str:
    """This tool provides the schema information of the orders database. Call this to understand how to query the database."""
    return """Schema Information (for LLM understanding)
Table: customers

customer_id (TEXT, Primary Key) — Unique identifier for each customer.

name (TEXT, Required) — Full name of the customer.

email (TEXT, Required) — Email address of the customer.

Table: orders

order_id (TEXT, Primary Key) — Unique identifier for each order.

customer_id (TEXT, Foreign Key → customers.customer_id) — Links the order to the customer who placed it.

created_at (TEXT, Required) — Timestamp when the order was created.

status (TEXT, Required) — Current order status (e.g., “pending”, “shipped”, “delivered”, “cancelled”).

eta (TEXT, Optional) — Estimated time of arrival or delivery.

total_amount (REAL, Optional) — Total value of the order in currency units.

Table: order_events

event_id (TEXT, Primary Key) — Unique identifier for each event.

order_id (TEXT, Foreign Key → orders.order_id) — The order associated with this event.

ts (TEXT, Required) — Timestamp of when the event occurred.

event_type (TEXT, Required) — Type of event (e.g., “created”, “updated”, “delivered”, “cancelled”).

note (TEXT, Optional) — Additional information or comments about the event.

Relationships

Each customer can have multiple orders (1-to-many relationship).

Each order can have multiple order_events (1-to-many relationship)."""

@mcp.tool()
async def get_order_status_from_db(customer_id: str) -> str:
    """Fetch the status of the order for the given customer_id from the database."""
    try:
        connection = sqlite3.connect("orders.db")
        cursor = connection.cursor()
        cursor.execute(
            "SELECT status FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT 1;",
            (customer_id,)
        )
        result = cursor.fetchone()
        connection.close()

        if result:
            return f"The latest order status for customer_id '{customer_id}' is: {result[0]}"
        else:
            return f"No orders found for customer_id '{customer_id}'."
    except sqlite3.Error as e:
        return f"Error fetching order status: {e}"

@mcp.tool()
async def cancel_order(customer_id: str, order_id: str) -> str:
    """Cancel an order if it is in the 'ORDERED' status."""
    try:
        connection = sqlite3.connect("orders.db")
        cursor = connection.cursor()

        # Check the current status of the order
        cursor.execute(
            "SELECT status FROM orders WHERE customer_id = ? AND order_id = ?;",
            (customer_id, order_id),
        )
        result = cursor.fetchone()

        if not result:
            connection.close()
            return f"No order found for customer_id '{customer_id}' and order_id '{order_id}'."

        current_status = result[0]

        # Only allow cancellation if the status is 'ORDERED'
        if current_status == "ORDERED":
            cursor.execute(
                "UPDATE orders SET status = 'CANCELLED' WHERE customer_id = ? AND order_id = ?;",
                (customer_id, order_id),
            )
            connection.commit()
            connection.close()
            return f"Order '{order_id}' for customer_id '{customer_id}' has been successfully cancelled."
        elif current_status in ["DISPATCHED", "CANCELLED", "DELIVERED", "IN_TRANSIT"]:
            connection.close()
            return f"Order '{order_id}' cannot be cancelled as it is in '{current_status}' status."
        else:
            connection.close()
            return f"Order '{order_id}' has an unknown status '{current_status}', and cannot be cancelled."

    except sqlite3.Error as e:
        return f"Error cancelling order: {e}"

if __name__=="__main__":
    mcp.run(transport="streamable-http")
