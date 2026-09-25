import os
import sqlite3
import json
import uuid
import re
import pdfplumber
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

    # Query order with customer email verification
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

def process_refund(order_id: str, email: str, book_ids: list[str], reason: str = "Unwanted") -> str:
    """Deterministic business logic gate for initiating a return. Covers ALL chosen
    items on the order under a single Return Authorization -- one return_id and one
    prepaid label for the whole parcel, matching how a real multi-item return ships.

        Args:
            order_id: The order identifier (e.g., 'ORD-1001', '1001', or 'ORD1001').
            email: The customer's email address, used to verify identity.
            book_ids: One or more book IDs from this order to return together.
            reason: Optional free-text reason for the return.
        """
    conn = get_db_connection()
    cursor = conn.cursor()

    order_id_clean = normalize_order_id(order_id)
    email_clean = email.strip().lower()

    cursor.execute("""
    SELECT o.order_id, o.customer_id, o.delivery_date, o.order_status, c.email
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    WHERE LOWER(o.order_id) = LOWER(?) AND LOWER(c.email) = LOWER(?)
    """, (order_id_clean, email_clean))
    order = cursor.fetchone()

    if not order:
        conn.close()
        return json.dumps({"status": "failed", "reason": "Order ID or customer email verification failed."})

    # 30-day window is evaluated once at the order level -- every item on one
    # order shares the same delivery date.
    delivery_date_str = order["delivery_date"]
    if delivery_date_str:
        delivery_date = datetime.strptime(delivery_date_str, "%Y-%m-%d")
        days_since_delivery = (datetime.now() - delivery_date).days
        if days_since_delivery > 30:
            conn.close()
            return json.dumps({
                "status": "rejected",
                "reason": f"Return window expired. Delivered {days_since_delivery} days ago (policy limit is 30 days)."
            })

    eligible_items = []
    already_in_progress = []
    already_refunded = []
    not_found = []

    for book_id in book_ids:
        cursor.execute("""
        SELECT oi.order_item_id, oi.unit_price, oi.item_status, b.title
        FROM order_items oi
        JOIN books b ON oi.book_id = b.book_id
        WHERE oi.order_id = ? AND oi.book_id = ?
        """, (order["order_id"], book_id.strip()))
        item = cursor.fetchone()

        if not item:
            not_found.append(book_id)
            continue
        if item["item_status"] == "Return Initiated":
            already_in_progress.append(item["title"])
            continue
        if item["item_status"] == "Refunded":
            already_refunded.append(item["title"])
            continue

        eligible_items.append({
            "order_item_id": item["order_item_id"],
            "book_id": book_id.strip(),
            "title": item["title"],
            "unit_price": item["unit_price"],
        })

    if not eligible_items:
        conn.close()
        return json.dumps({
            "status": "failed",
            "reason": "None of the requested items are eligible for a new return.",
            "already_in_progress": already_in_progress,
            "already_refunded": already_refunded,
            "not_found": not_found,
        })

    # One Return Authorization covers every eligible item from this call.
    return_id = f"RET-{uuid.uuid4().hex[:6].upper()}"
    return_tracking = f"RET-USPS-{uuid.uuid4().hex[:8].upper()}"
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_refund = 0.0

    for item in eligible_items:
        cursor.execute("""
        INSERT INTO returns (return_id, order_id, book_id, customer_id, return_reason, return_status, refund_amount, return_label_tracking, created_at)
        VALUES (?, ?, ?, ?, ?, 'Initiated', ?, ?, ?)
        """, (return_id, order["order_id"], item["book_id"], order["customer_id"], reason, item["unit_price"], return_tracking, today_str))
        cursor.execute("UPDATE order_items SET item_status = 'Return Initiated' WHERE order_item_id = ?", (item["order_item_id"],))
        total_refund += item["unit_price"]

    # Evaluate sibling items to dynamically set parent order_status
    cursor.execute("SELECT item_status FROM order_items WHERE order_id = ?", (order["order_id"],))
    all_statuses = [r["item_status"] for r in cursor.fetchall()]
    if all(s == "Return Initiated" for s in all_statuses):
        new_order_status = "Return Initiated"
    elif any(s in ("Return Initiated", "Refunded") for s in all_statuses):
        new_order_status = "Partially Return Initiated"
    else:
        new_order_status = order["order_status"]

    cursor.execute("UPDATE orders SET order_status = ? WHERE order_id = ?", (new_order_status, order["order_id"]))
    conn.commit()
    conn.close()

    return json.dumps({
        "status": "success",
        "return_id": return_id,
        "items": [{"title": i["title"], "refund_amount": f"${i['unit_price']:.2f}"} for i in eligible_items],
        "pending_refund_amount": f"${total_refund:.2f}",
        "return_tracking": return_tracking,
        "order_status": new_order_status,
        "skipped": {
            "already_in_progress": already_in_progress,
            "already_refunded": already_refunded,
            "not_found": not_found,
        },
        "instructions": (
            "1. Repack the returned book(s) together in the original packaging where possible. "
            "2. Affix the single prepaid return label (included in the parcel) over the original shipping label. "
            "3. Drop the package off at any USPS drop box or post office. "
            "Your refund will process as soon as Bookly confirms receipt of the return item/s."
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

def lookup_book(query: str) -> str:
    """Looks up a book in the Bookly catalog by title or book ID.

        Args:
            query: The book title (full or partial) or book ID (e.g., 'BOOK-101') the customer asked about.
        """
    q = query.strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT book_id, title, author, release_year, genre, rating, price, series_name, series_order
    FROM books WHERE LOWER(book_id) = LOWER(?)
    """, (q,))
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
        SELECT book_id, title, author, release_year, genre, rating, price, series_name, series_order
        FROM books WHERE LOWER(title) LIKE LOWER(?)
        """, (f"%{q}%",))
        row = cursor.fetchone()

    conn.close()

    if not row:
        return json.dumps({
            "found": False,
            "message": f"'{query}' is not in the Bookly catalog. You may still know this book from general knowledge, but never state a price or offer to add it to cart, since Bookly doesn't actually sell it."
        })

    return json.dumps({
        "found": True,
        "book_id": row["book_id"],
        "title": row["title"],
        "author": row["author"],
        "release_year": row["release_year"],
        "genre": row["genre"],
        "rating": row["rating"],
        "price": row["price"],
        "series_name": row["series_name"],
        "series_order": row["series_order"]
    })


def get_current_date() -> str:
    from datetime import date
    return date.today().isoformat()

def cancel_order(order_id: str, email: str) -> str:
    """Cancels an order that has not yet shipped and reverses the charge.

        Args:
            order_id: The order identifier (e.g., 'ORD-1001', '1001', or 'ORD1001').
            email: The customer's email address, used to verify identity.
        """
    order_id_clean = normalize_order_id(order_id)
    email_clean = email.strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT o.order_id, o.shipping_status, o.order_status
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    WHERE LOWER(o.order_id) = LOWER(?) AND LOWER(c.email) = LOWER(?)
    """, (order_id_clean, email_clean))
    order = cursor.fetchone()

    if not order:
        conn.close()
        return json.dumps({"status": "failed", "reason": "Order ID or customer email verification failed."})

    if order["shipping_status"] != "Processing":
        conn.close()
        return json.dumps({
            "status": "failed",
            "reason": f"Order '{order_id_clean}' has already shipped (status: {order['shipping_status']}) and can no longer be cancelled. It can still be returned once delivered."
        })

    cursor.execute(
        "UPDATE orders SET order_status = 'Cancelled by customer', shipping_status = 'Cancelled' WHERE order_id = ?",
        (order["order_id"],)
    )
    cursor.execute(
        "UPDATE order_items SET item_status = 'Cancelled' WHERE order_id = ?",
        (order["order_id"],)
    )
    conn.commit()
    conn.close()

    return json.dumps({
        "status": "success",
        "order_id": order["order_id"],
        "message": "Order cancelled before shipment. Payment will be reversed to the original payment method."
    })


# Shipping & store policy: grounded in sources/bookly_policies.pdf


POLICY_PDF_PATH = os.path.join("sources", "bookly_policies.pdf")

SHIPPING_ALIASES = {
    "United States": ["us", "usa", "u.s.", "u.s.a.", "united states", "united states of america", "america"],
    "Canada": ["canada", "ca"],
    "United Kingdom": ["uk", "u.k.", "united kingdom", "great britain", "britain", "england",
                       "scotland", "wales", "northern ireland"],
    "European Union": ["eu", "europe", "european union", "germany", "france", "spain", "italy",
                        "netherlands", "ireland", "belgium", "portugal", "austria", "sweden",
                        "denmark", "poland"],
    "Australia & New Zealand": ["australia", "new zealand", "au", "nz", "aus"]
}

POLICY_TOPIC_KEYWORDS = {
    "Resetting Your Password": ["password", "reset", "login", "log in", "forgot", "account access"],
    "Accepted Payment Methods": ["payment", "credit card", "paypal", "pay for", "way to pay", "how do you pay"],
    "Changing or Cancelling an Order": ["change order", "modify order", "edit order", "update address", "cancel"],
    "Returns & Refunds": ["return", "refund", "exchange"],
    "Support Hours": ["hours", "contact", "phone", "call", "support hours"]
}

_policy_doc_cache = None  # populated on first tool call, then reused for the process lifetime


def _load_policy_document():
    """Parses sources/bookly_policies.pdf once and caches the result: the shipping
    table's rows, and each general-policy section's body text, keyed by heading."""
    global _policy_doc_cache
    if _policy_doc_cache is not None:
        return _policy_doc_cache

    shipping_rows = []
    full_text = ""

    with pdfplumber.open(POLICY_PDF_PATH) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
            for table in page.extract_tables():
                if table and table[0] and table[0][0] == "Region":
                    shipping_rows.extend(table[1:])

    sections = {}
    headings = list(POLICY_TOPIC_KEYWORDS.keys())
    for i, heading in enumerate(headings):
        start = full_text.find(heading)
        if start == -1:
            continue
        start += len(heading)
        end = len(full_text)
        for other in headings[i + 1:]:
            pos = full_text.find(other, start)
            if pos != -1:
                end = min(end, pos)
        sections[heading] = full_text[start:end].strip().replace("\n", " ")

    _policy_doc_cache = {"shipping_rows": shipping_rows, "sections": sections}
    return _policy_doc_cache


def get_shipping_info(country: str) -> str:
    """Looks up shipping cost and delivery time for a destination country, read live
        from the shipping table in sources/bookly_policies.pdf.

        Args:
            country: The destination country or region the customer wants to ship to.
        """
    doc = _load_policy_document()
    q = country.strip().lower().rstrip(".")

    target_region = None
    for region, aliases in SHIPPING_ALIASES.items():
        if q in aliases:
            target_region = region
            break

    def row_to_dict(row, matched):
        return {
            "matched": matched,
            "region": row[0].replace("\n", " "),
            "standard_days": row[1].replace("\n", " "),
            "standard_cost": row[2],
            "express_days": row[3].replace("\n", " "),
            "express_cost": row[4],
            "free_standard_threshold": row[5]
        }

    if target_region:
        for row in doc["shipping_rows"]:
            if row[0] and row[0].replace("\n", " ") == target_region:
                return json.dumps(row_to_dict(row, True))

    for row in doc["shipping_rows"]:
        if row[0] and "Rest of World" in row[0]:
            result = row_to_dict(row, False)
            result["note"] = f"'{country}' isn't one of our standard shipping zones, so this is our Rest of World rate."
            return json.dumps(result)

    return json.dumps({"matched": False, "error": "Shipping information is temporarily unavailable."})


def get_store_policy(topic: str) -> str:
    """Looks up Bookly's policy on a general topic (password reset, payment methods,
        order changes/cancellation, returns overview, or support hours), read live from
        sources/bookly_policies.pdf.

        Args:
            topic: What the customer is asking about, in their own words (e.g. 'how do I reset my password').
        """
    doc = _load_policy_document()
    q = topic.strip().lower()

    for heading, keywords in POLICY_TOPIC_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            text = doc["sections"].get(heading)
            if text:
                return json.dumps({"matched": True, "topic": heading, "text": text})

    return json.dumps({"matched": False, "available_topics": list(doc["sections"].keys())})


def add_to_cart(book_id: str) -> str:
    """Adds a book from the catalog to the customer's cart.

        Args:
            book_id: The book identifier (e.g., 'BOOK-101').
        """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT book_id, title, price FROM books WHERE book_id = ?", (book_id.strip(),))
    book = cursor.fetchone()
    conn.close()

    if not book:
        return json.dumps({"status": "failed", "reason": f"Book ID '{book_id}' was not found in the catalog."})

    return json.dumps({
        "status": "success",
        "book_id": book["book_id"],
        "title": book["title"],
        "price": book["price"]
    })