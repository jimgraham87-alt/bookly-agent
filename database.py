import sqlite3
from datetime import datetime, timedelta

DB_PATH = "bookly.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Customers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        address TEXT,
        date_of_birth TEXT,
        loyalty_points INTEGER DEFAULT 0,
        lifetime_spend REAL DEFAULT 0.0
    );
    """)

    # 2. Books Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS books (
        book_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        release_year INTEGER,
        genre TEXT,
        rating REAL,
        nyt_bestseller INTEGER,
        series_name TEXT,
        series_order INTEGER,
        price REAL NOT NULL
    );
    """)

    # 3. Orders Table (Updated with Shipping & Tracking Fields)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        order_date TEXT NOT NULL,
        delivery_date TEXT,
        estimated_delivery TEXT,
        carrier TEXT,
        tracking_number TEXT,
        shipping_status TEXT,          -- 'Processing', 'In Transit', 'Out for Delivery', 'Delivered'
        total_amount REAL NOT NULL,
        payment_method TEXT,
        order_status TEXT NOT NULL,    -- 'Active', 'Cancelled', 'Refunded'
        FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
    );
    """)

    # 4. Order Items Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        unit_price REAL NOT NULL,
        item_status TEXT NOT NULL,     -- 'Active', 'Delivered', 'Cancelled', 'Refunded'
        FOREIGN KEY (order_id) REFERENCES orders (order_id),
        FOREIGN KEY (book_id) REFERENCES books (book_id)
    );
    """)

    # 5. Returns Table
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS returns (
                return_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id TEXT NOT NULL,       -- shared by every item in the same return request
                order_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                return_reason TEXT,
                return_status TEXT NOT NULL,
                refund_amount REAL NOT NULL,
                return_label_tracking TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (order_id),
                FOREIGN KEY (book_id) REFERENCES books (book_id),
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            );
        """)

    # --- Seed Data ---

    # Seed Customers
    customers = [
        ("CUST-01", "Alex Rivera", "alex@example.com", "123 Main St, Springfield", "1990-05-12", 120, 145.00),
        ("CUST-02", "Sarah Chen", "sarah@example.com", "456 Oak Rd, Seattle", "1985-11-23", 50, 40.00),
        ("CUST-03", "Jordan Hayes", "jordan@example.com", "789 Pine Ave, Austin", "1994-03-30", 210, 230.50),
        ("CUST-04", "Taylor Kim", "taylor@example.com", "22 Birch Ln, Denver", "1998-07-19", 15, 50.00)
    ]
    cursor.executemany("INSERT OR IGNORE INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers)

    # Seed Books
    books = [
        ("BOOK-101", "The Pragmatic Programmer", "Andrew Hunt, David Thomas", 1999, "Technology", 4.8, 1, None, None, 45.00),
        ("BOOK-102", "How to build an AI chatbot in 4 hours for dummies", "Jesse Zhang", 2023, "Technology", 5, 1, None, None, 40.00),
        ("BOOK-103", "Designing Data-Intensive Applications", "Martin Kleppmann", 2017, "Technology", 4.9, 0, None, None, 50.00),
        ("BOOK-104", "Robopocalypse", "Daniel H. Wilson", 2011, "Sci-Fi", 4.9, 0, None, None, 50.00),
        ("BOOK-201", "Dune", "Frank Herbert", 1965, "Sci-Fi", 4.7, 1, "Dune Chronicles", 1, 25.00),
        ("BOOK-202", "Dune Messiah", "Frank Herbert", 1969, "Sci-Fi", 4.4, 0, "Dune Chronicles", 2, 22.00),
        ("BOOK-105", "Co-Intelligence", "Ethan Mollick", 2024, "Technology", 4.2, 0, "",0,27.0),
        ("BOOK-106", "Foundation", "Isaac Asimov", 1951, "Sci-Fi", 4.3, 0, "", 0, 7.0)

    ]
    cursor.executemany("INSERT OR IGNORE INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", books)

    # Dynamic Dates for realistic testing
    today = datetime.now()
    d_today = today.strftime("%Y-%m-%d")
    d_recent = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    d_yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    d_tomorrow = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    d_expired = (today - timedelta(days=45)).strftime("%Y-%m-%d")

    # Seed Orders
    orders = [
        ("ORD-1001", "CUST-01", d_recent, d_yesterday, d_yesterday, "FedEx", "FDX-99201", "Delivered", 45.00,
         "Credit Card", "Delivered"),
        ("ORD-1002", "CUST-02", d_expired, d_expired, d_expired, "USPS", "9400111202", "Delivered", 40.00, "PayPal",
         "Delivered"),
        ("ORD-1003", "CUST-03", d_yesterday, None, d_tomorrow, "UPS", "1Z999AA10123456784", "In Transit", 95.00,
         "Credit Card", "Active"),
        ("ORD-1004", "CUST-04", d_today, None, None, None, None, "Processing", 50.00, "Credit Card", "Active")
    ]
    cursor.executemany("INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", orders)

    # Seed Order Items
    items = [
        ("ORD-1001", "BOOK-101", 1, 45.00, "Delivered"),
        ("ORD-1002", "BOOK-102", 1, 40.00, "Delivered"),
        ("ORD-1003", "BOOK-101", 1, 45.00, "Active"),
        ("ORD-1003", "BOOK-103", 1, 50.00, "Active"),
        ("ORD-1004", "BOOK-104", 1, 50.00, "Active")
    ]
    cursor.executemany("INSERT OR IGNORE INTO order_items (order_id, book_id, quantity, unit_price, item_status) VALUES (?, ?, ?, ?, ?)", items)

    conn.commit()
    conn.close()
    print("Database initialized with tracking and shipping details successfully.")


def reset_db():
    """Drops all tables and re-seeds mock data to a clean initial state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DROP TABLE IF EXISTS returns;")
    cursor.execute("DROP TABLE IF EXISTS order_items;")
    cursor.execute("DROP TABLE IF EXISTS orders;")
    cursor.execute("DROP TABLE IF EXISTS books;")
    cursor.execute("DROP TABLE IF EXISTS customers;")
    conn.commit()
    conn.close()

    # Re-initialize tables and seed records
    init_db()


if __name__ == "__main__":
    init_db()