import sqlite3
import json
import uuid
import re
from datetime import datetime

DB_PATH = "bookly.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- 1. Python Execution Functions ---

def lookup_order(order_id: str, email: str) -> str:
    """Verifies user identity and retrieves order details.

        Args:
            order_id: The order identifier (e.g., 'ORD-1001', '1001', or 'ORD1001').
            email: The customer's email address.
        """

    order_id = normalize_order_id(order_id)
    email = email.strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor()
    # Your SQL query here...

    # Query order with customer email verification gate
    query_order = """
    SELECT o.order_id, c.name, c.email, o.order_date, o.delivery_date, 
           o.estimated_delivery, o.carrier, o.tracking_number, 
           o.shipping_status, o.total_amount, o.order_status
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    WHERE LOWER(o.order_id) = LOWER(?) AND LOWER(c.email) = LOWER(?)
    """
    cursor.execute(query_order, (order_id.strip(), email.strip()))
    order_row = cursor.fetchone()

    if not order_row:
        conn.close()
        return json.dumps({
            "error": "Order not found or customer email does not match. Please verify your order ID and email."
        })

    # Retrieve associated items
    query_items = """
    SELECT oi.book_id, b.title, oi.quantity, oi.unit_price, oi.item_status
    FROM order_items oi
    JOIN books b ON oi.book_id = b.book_id
    WHERE oi.order_id = ?
    """
    cursor.execute(query_items, (order_id.strip(),))
    item_rows = cursor.fetchall()
    conn.close()

    items = [
        {
            "book_id": r["book_id"],
            "title": r["title"],
            "quantity": r["quantity"],
            "unit_price": r["unit_price"],
            "status": r["item_status"]
        }
        for r in item_rows
    ]

    return json.dumps({
        "order_id": order_row["order_id"],
        "customer_name": order_row["name"],
        "order_date": order_row["order_date"],
        "delivery_date": order_row["delivery_date"],
        "estimated_delivery": order_row["estimated_delivery"],
        "carrier": order_row["carrier"],
        "tracking_number": order_row["tracking_number"],
        "shipping_status": order_row["shipping_status"],
        "order_status": order_row["order_status"],
        "items": items
    })


def process_refund(order_id: str, email: str, book_id: str, reason: str = "Unwanted") -> str:
    order_id = normalize_order_id(order_id)
    email = email.strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor()
    # Your SQL query here...

    # 1. Identity & Order Gate
    cursor.execute("""
    SELECT o.order_id, o.customer_id, o.delivery_date, o.order_status, c.email
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    WHERE LOWER(o.order_id) = LOWER(?) AND LOWER(c.email) = LOWER(?)
    """, (order_id.strip(), email.strip()))
    order = cursor.fetchone()

    if not order:
        conn.close()
        return json.dumps({"status": "failed", "reason": "Order ID or customer email verification failed."})

    # 2. Check Item Existence & Current Return State
    cursor.execute("""
    SELECT oi.order_item_id, oi.unit_price, oi.item_status, b.title
    FROM order_items oi
    JOIN books b ON oi.book_id = b.book_id
    WHERE oi.order_id = ? AND oi.book_id = ?
    """, (order_id.strip(), book_id.strip()))
    item = cursor.fetchone()

    if not item:
        conn.close()
        return json.dumps({"status": "failed", "reason": f"Book ID '{book_id}' was not found in order '{order_id}'."})

    # Differentiate between in-progress return and finalized refund
    if item["item_status"] == "Return Initiated":
        # Fetch the active return details
        cursor.execute("""
        SELECT return_id, return_label_tracking 
        FROM returns 
        WHERE order_id = ? AND book_id = ? 
        ORDER BY created_at DESC LIMIT 1
        """, (order["order_id"], book_id.strip()))
        ret = cursor.fetchone()
        conn.close()
        return json.dumps({
            "status": "in_progress",
            "reason": (
                f"A return has already been initiated for '{item['title']}' (Return ID: {ret['return_id'] if ret else 'N/A'}). "
                "The refund is currently pending drop-off and carrier receipt."
            )
        })

    if item["item_status"] == "Refunded":
        conn.close()
        return json.dumps({"status": "failed", "reason": f"Item '{item['title']}' has already been returned and refunded."})

    # 3. 30-Day Policy Gate Check
    delivery_date_str = order["delivery_date"]
    if not delivery_date_str:
        conn.close()
        return json.dumps({"status": "failed", "reason": "Order has not been delivered yet. Cannot process return."})

    delivery_date = datetime.strptime(delivery_date_str, "%Y-%m-%d")
    days_since_delivery = (datetime.now() - delivery_date).days

    if days_since_delivery > 30:
        conn.close()
        return json.dumps({
            "status": "rejected",
            "reason": f"Return window expired. Delivered {days_since_delivery} days ago (policy limit is 30 days)."
        })

    # 4. Insert Return Record & Update Status to 'Return Initiated'
    return_id = f"RET-{uuid.uuid4().hex[:6].upper()}"
    return_tracking = f"RET-USPS-{uuid.uuid4().hex[:8].upper()}"
    today_str = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
    INSERT INTO returns (return_id, order_id, book_id, customer_id, return_reason, return_status, refund_amount, return_label_tracking, created_at)
    VALUES (?, ?, ?, ?, ?, 'Initiated', ?, ?, ?)
    """, (return_id, order["order_id"], book_id.strip(), order["customer_id"], reason, item["unit_price"], return_tracking, today_str))

    cursor.execute("UPDATE order_items SET item_status = 'Return Initiated' WHERE order_item_id = ?", (item["order_item_id"],))

    # Evaluate sibling items for parent order status
    cursor.execute("SELECT item_status FROM order_items WHERE order_id = ?", (order["order_id"],))
    all_statuses = [r["item_status"] for r in cursor.fetchall()]

    if all(s == "Return Initiated" for s in all_statuses):
        new_order_status = "Return Initiated"
    elif any(s in ("Return Initiated", "Refunded") for s in all_statuses):
        new_order_status = "Partially Return Initiated"
    else:
        new_order_status = order["order_status"]

    cursor.execute(
        "UPDATE orders SET order_status = ? WHERE order_id = ?",
        (new_order_status, order["order_id"])
    )

    conn.commit()
    conn.close()

    return json.dumps({
        "status": "success",
        "return_id": return_id,
        "book_title": item["title"],
        "pending_refund_amount": f"${item['unit_price']:.2f}",
        "return_tracking": return_tracking,
        "order_status": new_order_status,
        "instructions": (
            "1. Locate the prepaid return shipping sticker included in your original Bookly package. "
            "2. Affix the sticker over the original shipping label. "
            "3. Drop the package off at any USPS drop box or post office. "
            "Your refund will post automatically to your original payment method once scanned by the carrier."
        )
    })

def escalate_to_human(reason: str, summary: str, order_id: str = None) -> str:
    """Escalates complex issues, explicit human requests, or disputes to a live support agent."""
    ticket_id = f"TICKET-{uuid.uuid4().hex[:6].upper()}"

    return json.dumps({
        "status": "escalated",
        "ticket_id": ticket_id,
        "reason": reason,
        "summary": summary,
        "message": (
            f"I have routed your request to our senior support team (Ticket #{ticket_id}). "
            "A human representative will review our conversation and take over shortly."
        )
    })



def normalize_order_id(order_id: str) -> str:
    """
    Normalizes user-supplied order IDs:
    - '1003'     -> 'ORD-1003'
    - 'ord1003'  -> 'ORD-1003'
    - 'ord-1003' -> 'ORD-1003'
    - 'ORD 1003' -> 'ORD-1003'
    """
    cleaned = str(order_id).strip()

    # Extract numeric digits
    match = re.search(r'\d+', cleaned)
    if match:
        digits = match.group(0)
        return f"ORD-{digits}"

    return cleaned.upper()

# --- 2. Function Calling Tool Schemas ---

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "Look up tracking, delivery status, and items for an order. Requires BOTH order_id and email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID, e.g., 'ORD-1001'"},
                    "email": {"type": "string", "description": "The customer's email address"}
                },
                "required": ["order_id", "email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "process_refund",
            "description": "Process a return and refund for a specific item in an order. Requires order_id, email, and the book_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID, e.g., 'ORD-1001'"},
                    "email": {"type": "string", "description": "The customer's email address"},
                    "book_id": {"type": "string", "description": "The specific book identifier, e.g., 'BOOK-101'"},
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for return (e.g., 'Damaged', 'Unwanted', 'Wrong Item')"
                    }
                },
                "required": ["order_id", "email", "book_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escalates complex issues, explicit requests for a representative/human, or out-of-policy disputes to a human support agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Short category or reason for the transfer (e.g., 'Customer requested human agent', 'Damaged goods exchange')"
                    },
                    "summary": {
                        "type": "string",
                        "description": "A concise 1-2 sentence overview of the user's issue and what has been attempted so far."
                    },
                    "order_id": {
                        "type": "string",
                        "description": "The order ID if mentioned, otherwise leave null or empty."
                    }
                },
                "required": ["reason", "summary"]
            }
        }
    }
]

tool_mapping = {
    "lookup_order": lookup_order,
    "process_refund": process_refund,
    "escalate_to_human": escalate_to_human
}