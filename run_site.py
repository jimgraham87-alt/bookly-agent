import os
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from agent import SYSTEM_PROMPT, reset_agent, run_agent_turn
from database import reset_db

# Ensure images directory exists
IMAGE_DIR = "images"
os.makedirs(IMAGE_DIR, exist_ok=True)

# Fallback genre map in case 'genre' column is not in your books table yet
DEFAULT_GENRE_MAP = {
    "The Pragmatic Programmer": "Software Engineering",
    "How to build an AI chatbot in 4 hours for dummies": "Software Engineering",
    "Refactoring": "Software Engineering",
    "Designing Data-Intensive Applications": "Distributed Systems & Cloud",
    "Building Microservices": "Distributed Systems & Cloud",
}


def get_store_books_by_genre():
    """Fetches unique books from SQLite and groups them into up to 2 genres (max 4 books each)."""
    conn = sqlite3.connect("bookly.db", timeout=20.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check available columns in the books table
    cursor.execute("PRAGMA table_info(books)")
    columns = [row["name"] for row in cursor.fetchall()]
    has_genre = "genre" in columns

    if has_genre:
        cursor.execute("""
            SELECT DISTINCT book_id, title, price, author, release_year, genre
            FROM books 
            ORDER BY title ASC
        """)
    else:
        cursor.execute("""
            SELECT DISTINCT book_id, title, price, author, release_year
            FROM books 
            ORDER BY title ASC
        """)

    rows = cursor.fetchall()
    conn.close()

    # Group into genres
    catalog_by_genre = defaultdict(list)
    for idx, r in enumerate(rows):
        title = r["title"]
        if has_genre and r["genre"]:
            genre = r["genre"]
        else:
            genre = DEFAULT_GENRE_MAP.get(
                title, "Software Engineering" if idx % 2 == 0 else "Distributed Systems & Cloud"
            )

        catalog_by_genre[genre].append(dict(r))

    # Restrict to maximum 2 genres, up to 4 books per genre
    limited_catalog = {}
    for genre, books in list(catalog_by_genre.items())[:2]:
        limited_catalog[genre] = books[:4]

    return limited_catalog


def render_genre_rows():
    """Generates the HTML rows with cover image and the interactive Ask Paige overlay button."""
    catalog = get_store_books_by_genre()
    rows_html = ""

    for genre, books in catalog.items():
        cards_html = ""
        for b in books:
            book_id = b["book_id"]
            # Escape quotes in title for the JS function call
            safe_title = b["title"].replace("'", "\\'")
            cards_html += f"""
            <div class="product-card">
              <div class="book-cover">
                <img src="/images/{book_id}" 
                     alt="{b['title']}" 
                     class="book-cover-img"
                     onerror="this.parentElement.innerHTML='<div class=\\'book-fallback-cover\\'>📖</div>';">
                <button class="ai-info-badge" 
                        onclick="askPaigeAboutBook('{safe_title}')" 
                        title="Ask Paige about this book">
                  💬 Ask Paige
                </button>
              </div>
              <div class="book-title">{b['title']}</div>
              <div class="author">Author: {b['author']}</div>
              <div class="book-price">${float(b['price']):.2f}</div>
              <button class="btn-buy" onclick="incrementCart()">Add to Cart</button>
            </div>
            """

        rows_html += f"""
        <div class="genre-row">
          <h3 class="genre-title">{genre}</h3>
          <div class="product-grid">
            {cards_html}
          </div>
        </div>
        """
    return rows_html


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_db()
    reset_agent()
    yield


app = FastAPI(title="Bookly Storefront & Support Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


session_messages = [{"role": "system", "content": SYSTEM_PROMPT}]


@app.get("/images/{book_id}")
async def get_book_image(book_id: str):
    """Serves image file matching book_id with or without extensions (.png, .jpg, .jpeg, .webp)."""
    search_dirs = [IMAGE_DIR, "."]
    extensions = ["", ".png", ".jpg", ".jpeg", ".webp"]

    for d in search_dirs:
        for ext in extensions:
            candidate = os.path.join(d, f"{book_id}{ext}")
            if os.path.isfile(candidate):
                return FileResponse(candidate)

    raise HTTPException(status_code=404, detail="Image not found")


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    global session_messages
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty message")

    session_messages.append({"role": "user", "content": user_msg})
    reply = run_agent_turn(session_messages)
    is_escalated = "ticket #" in reply.lower()

    # Detect if agent confirmed adding a book to the cart
    is_cart_add = any(
        phrase in reply.lower()
        for phrase in [
            "added to your cart",
            "added it to your cart",
            "added to the cart",
            "have added",
        ]
    )

    return {"reply": reply, "escalated": is_escalated, "added_to_cart": is_cart_add}


@app.post("/api/reset")
async def reset_endpoint():
    global session_messages
    reset_db()
    reset_agent()
    session_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    return {"status": "success", "message": "Database and conversation session reset."}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" name="robots" content="noindex, nofollow" />
  <title>Bookly | Online Book Store</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {
      --primary: #026670;
      --primary-dark: #01434a;
      --accent: #ed9b40;
      --bg: #f8f9fa;
      --text: #2b2d42;
      --border: #e2e8f0;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding-bottom: 90px; }

    .top-bar { background: #013237; color: #fff; font-size: 13px; text-align: center; padding: 7px; font-weight: 500; }
    header { background: var(--primary); color: white; padding: 14px 40px; display: flex; align-items: center; justify-content: space-between; gap: 20px; }
    .brand { font-size: 26px; font-weight: 800; color: white; text-decoration: none; }
    .search-bar { flex: 1; max-width: 600px; display: flex; }
    .search-bar input { width: 100%; padding: 10px 14px; border: none; border-radius: 4px 0 0 4px; font-size: 14px; outline: none; }
    .search-bar button { background: var(--accent); border: none; padding: 10px 20px; border-radius: 0 4px 4px 0; color: white; font-weight: 700; cursor: pointer; }
    .header-links { font-size: 14px; display: flex; gap: 20px; font-weight: 500; align-items: center; }

    /* Dynamic Cart Badge */
    #cartHeader {
      background: rgba(255, 255, 255, 0.15);
      padding: 6px 14px;
      border-radius: 20px;
      font-weight: 700;
      transition: transform 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275), background 0.2s;
      cursor: pointer;
    }
    #cartHeader.cart-bump {
      transform: scale(1.15);
      background: var(--accent);
    }

    .nav-ribbon { background: white; border-bottom: 1px solid var(--border); padding: 10px 40px; display: flex; gap: 25px; font-size: 14px; font-weight: 600; }
    .nav-ribbon a { text-decoration: none; color: #4a5568; }
    .nav-ribbon a:hover { color: var(--primary); }

    .container { max-width: 1200px; margin: 25px auto; padding: 0 20px; }
    .hero-banner { background: linear-gradient(135deg, #026670, #9fedd7); color: #013237; border-radius: 8px; padding: 35px; margin-bottom: 30px; }
    .hero-banner h1 { font-size: 30px; margin-bottom: 8px; }

    .section-title { font-size: 22px; font-weight: 800; margin-bottom: 20px; border-bottom: 2.5px solid var(--primary); padding-bottom: 6px; display: inline-block; }

    /* Genre Row & Product Styling */
    .genre-row { margin-bottom: 36px; }
    .genre-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--primary-dark);
      margin-bottom: 14px;
      padding-bottom: 6px;
      border-bottom: 1.5px solid var(--border);
    }
    .product-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 20px; }
    .product-card { background: white; border: 1px solid var(--border); border-radius: 6px; padding: 16px; display: flex; flex-direction: column; justify-content: space-between; }
    .product-card:hover { box-shadow: 0 6px 14px rgba(0,0,0,0.06); }

    /* Cover Image Container */
    .book-cover {
      position: relative; /* Needed to anchor the badge overlay */
      height: 220px;
      background: #edf2f7;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      margin-bottom: 12px;
    }
    .book-cover-img {
      height: 100%;
      width: auto;
      max-width: 100%;
      object-fit: cover;
      box-shadow: 0 4px 8px rgba(0, 0, 0, 0.12);
      border-radius: 3px;
      transition: transform 0.2s ease;
    }
    .product-card:hover .book-cover-img {
      transform: scale(1.04);
    }
    .book-fallback-cover {
      font-size: 48px;
    }

    /* Ask Paige Floating Badge */
    .ai-info-badge {
      position: absolute;
      bottom: 8px;
      right: 8px;
      background: rgba(2, 102, 112, 0.92);
      color: white;
      border: 1px solid rgba(255, 255, 255, 0.4);
      backdrop-filter: blur(4px);
      padding: 5px 11px;
      border-radius: 16px;
      font-size: 11.5px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
      transition: all 0.2s ease;
      z-index: 5;
    }
    .ai-info-badge:hover {
      background: var(--accent);
      transform: scale(1.06);
    }

    .book-title { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
    .author { font-size: 12px; color: #718096; margin-bottom: 8px; }
    .book-price { font-size: 18px; font-weight: 800; color: #c53030; margin-bottom: 12px; }
    .btn-buy { background: var(--primary); color: white; border: none; padding: 9px; border-radius: 4px; font-weight: 600; cursor: pointer; }

/* Floating Chat Bubble */
    .chat-bubble-launcher {
      position: fixed;
      bottom: 25px;
      right: 25px;
      width: 65px;
      height: 65px;
      background: var(--primary);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 6px 18px rgba(0,0,0,0.25);
      cursor: pointer;
      z-index: 9999;
      overflow: hidden;
      border: 2px solid white;
      transition: transform 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }
    .chat-bubble-launcher:hover { 
      transform: scale(1.1); 
    }
    .chat-bubble-launcher img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    /* Chat Window */
    .chat-window {
      position: fixed;
      bottom: 95px;
      right: 25px;
      width: 380px;
      height: 520px;
      background: white;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
      display: none;
      flex-direction: column;
      overflow: hidden;
      z-index: 9999;
      border: 1px solid var(--border);
    }
    .chat-header {
      background: var(--primary);
      color: white;
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .chat-header h3 { font-size: 15px; font-weight: 600; }
    .chat-actions { display: flex; gap: 10px; }
    .chat-actions button { background: none; border: none; color: white; cursor: pointer; font-size: 16px; opacity: 0.85; }
    .chat-actions button:hover { opacity: 1; }

    .chat-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      background: #fbfbfb;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg { max-width: 82%; padding: 10px 14px; border-radius: 12px; font-size: 13.5px; line-height: 1.45; word-wrap: break-word; }
    .msg.bot { background: white; border: 1px solid var(--border); align-self: flex-start; border-bottom-left-radius: 2px; }
    .msg.user { background: var(--primary); color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
    .msg.escalated { border-left: 4px solid var(--accent); background: #fff8ee; }

    .chat-input-area {
      padding: 12px;
      background: white;
      border-top: 1px solid var(--border);
      display: flex;
      gap: 8px;
    }
    .chat-input-area input {
      flex: 1;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
      outline: none;
      font-size: 13.5px;
    }
    .chat-input-area button {
      background: var(--primary);
      color: white;
      border: none;
      padding: 0 16px;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
    }
    
    /* Test Case Suite Section */
    .tester-guide-section {
      margin-top: 50px;
      padding-top: 30px;
      border-top: 2px dashed var(--border);
    }
    .tester-header {
      margin-bottom: 22px;
    }
    .tester-header h2 {
      font-size: 22px;
      font-weight: 800;
      color: var(--primary-dark);
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .tester-header p {
      font-size: 14px;
      color: #555;
      margin-top: 4px;
    }
    .test-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 18px;
    }
    .test-card {
      background: white;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: 0 2px 6px rgba(0,0,0,0.03);
      transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .test-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 14px rgba(0,0,0,0.07);
    }
    .test-card-top {
      margin-bottom: 12px;
    }
    .test-badge {
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 12px;
      margin-bottom: 8px;
    }
    .badge-gate { background: #e3f2fd; color: #0d47a1; }
    .badge-lookup { background: #e8f5e9; color: #1b5e20; }
    .badge-action { background: #ede7f6; color: #4a148c; }
    .badge-policy { background: #ffebee; color: #b71c1c; }
    .badge-escalate { background: #fff3e0; color: #e65100; }
    .badge-sales { background: #e0f2f1; color: #004d40; }

    .test-title {
      font-size: 15px;
      font-weight: 700;
      color: #1a202c;
      margin-bottom: 6px;
    }
    .test-meta {
      font-size: 12.5px;
      color: #64748b;
      margin-bottom: 10px;
      line-height: 1.4;
    }
    .test-expected {
      font-size: 12.5px;
      background: #f8fafc;
      border-left: 3px solid var(--primary);
      padding: 8px 10px;
      border-radius: 0 4px 4px 0;
      margin-bottom: 14px;
      color: #334155;
    }
    .prompt-preview {
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 13px;
      font-family: monospace;
      color: #0f172a;
      margin-bottom: 12px;
      word-break: break-word;
    }
    .btn-test-run {
      background: var(--primary);
      color: white;
      border: none;
      padding: 9px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: background 0.15s ease;
      width: 100%;
    }
    .btn-test-run:hover {
      background: var(--primary-dark);
    }
    .msg.bot ul {
      margin: 8px 0 8px 18px;
      padding: 0;
    }
    .msg.bot li {
      margin-bottom: 4px;
    }
    
    .msg { 
      max-width: 82%; 
      padding: 10px 14px; 
      border-radius: 12px; 
      font-size: 13.5px; 
      line-height: 1.5; 
      word-wrap: break-word; 
      white-space: pre-wrap; /* Preserves paragraphs, indentation, and line breaks */
    }
  </style>
</head>
<body>

  <div class="top-bar">Fast & Tracked Delivery | 30-Day Easy Returns</div>

  <header>
    <a href="#" class="brand">📖 Bookly</a>
    <div class="search-bar">
      <input type="text" placeholder="Search title, author, or ISBN...">
      <button>Search</button>
    </div>
    <div class="header-links">
      <span>Track Order</span>
      <span>Sign In</span>
      <span id="cartHeader">Cart (<span id="cartCount">0</span>)</span>
    </div>
  </header>

  <nav class="nav-ribbon">
    <a href="#">Bestsellers</a>
    <a href="#">Fiction</a>
    <a href="#">Non-Fiction</a>
    <a href="#">Technology & Coding</a>
    <a href="#">Children's</a>
  </nav>

  <main class="container">
    <div class="hero-banner">
      <div>
        <h1>Spring Reading Sale</h1>
        <p>Explore software engineering classics and distributed systems titles.</p>
      </div>
    </div>

    <h2 class="section-title">Top Titles in these genres!</h2>
    <div class="genre-catalog-container">
      <!-- DYNAMIC_GENRE_ROWS -->
    </div>
    <!-- TEST CASE SUITE FOR EVALUATORS -->
    <section class="tester-guide-section">
      <div class="tester-header">
        <h2>🧪 Test Scenarios</h2>
        <p>Click <strong>"Run Test 💬"</strong> on any card to launch Paige and automatically execute the scenario.</p>
      </div>

      <div class="test-grid">
        <!-- Test 1 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-gate">Identity Verification</span>
            <div class="test-title">1. Multi-Turn Information Gathering</div>
            <div class="test-meta"><strong>Context:</strong> User requests order tracking without providing credentials.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Paige refuses to execute tools and prompts for both Order ID and customer email.</div>
          </div>
          <div>
            <div class="prompt-preview">"Hi, where is my order?"</div>
            <button class="btn-test-run" onclick="runTestCase('Hi, where is my order?')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 2 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-lookup">Order Tracking</span>
            <div class="test-title">2. Single-Item Order Lookup</div>
            <div class="test-meta"><strong>Context:</strong> ORD-1001 • alex@example.com (The Pragmatic Programmer).</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Normalizes order ID ("1001" &rarr; "ORD-1001"), calls lookup_order, and confirms delivery status.</div>
          </div>
          <div>
            <div class="prompt-preview">"Where is order 1001? Email is alex@example.com"</div>
            <button class="btn-test-run" onclick="runTestCase('Where is order 1001? Email is alex@example.com')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 3 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-gate">Ambiguity Clarification</span>
            <div class="test-title">3. Multi-Item Return Ambiguity</div>
            <div class="test-meta"><strong>Context:</strong> ORD-1003 • jordan@example.com (Contains 2 books).</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Stops before processing. Inquires which specific title the customer wants to return.</div>
          </div>
          <div>
            <div class="prompt-preview">"I want to return a book for order 1003, email is jordan@example.com"</div>
            <button class="btn-test-run" onclick="runTestCase('I want to return a book for order 1003, email is jordan@example.com')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 4 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-action">Action Execution</span>
            <div class="test-title">4. Disambiguation Resolution & Return</div>
            <div class="test-meta"><strong>Context:</strong> Resolves multi-item ambiguity from Test #3.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Invokes process_refund, marks status as initiated, and provides drop-off instructions.</div>
          </div>
          <div>
            <div class="prompt-preview">"I want to return The Pragmatic Programmer"</div>
            <button class="btn-test-run" onclick="runTestCase('I want to return The Pragmatic Programmer')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 5 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-policy">Policy Enforcement</span>
            <div class="test-title">5. 30-Day Return Limit Gate</div>
            <div class="test-meta"><strong>Context:</strong> ORD-1002 • sarah@example.com (Delivered July 1, 2026; &gt;30 days).</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Checks delivery date against 30-day policy and politely declines the refund request.</div>
          </div>
          <div>
            <div class="prompt-preview">"Can I return How to build an AI chatbot in 4 hours for dummies from order 1002? Email is sarah@example.com"</div>
            <button class="btn-test-run" onclick="runTestCase('Can I return How to build an AI chatbot in 4 hours for dummies from order 1002? Email is sarah@example.com')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 6 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-escalate">Human Escalation Gate</span>
            <div class="test-title">6. Escalation Deflection & Handoff</div>
            <div class="test-meta"><strong>Context:</strong> Cold-open request for a human manager without prior inquiry.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Paige deflects initial demand, lists her capabilities, and asks for the issue. If the user repeats their demand or displays negative sentiment, she invokes escalate_to_human and creates a ticket.</div>
          </div>
          <div>
            <div class="prompt-preview">"I demand to speak to a human manager right now."</div>
            <button class="btn-test-run" onclick="runTestCase('I demand to speak to a human manager right now.')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 7 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-sales">Catalog Q&A + Cart</span>
            <div class="test-title">7. Catalog Recommendation & Cart Add</div>
            <div class="test-meta"><strong>Context:</strong> Customer inquires about a store title.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Paige provides a 2-sentence summary, prompts to buy, and clicking 'Yes' bumps the Cart counter.</div>
          </div>
          <div>
            <div class="prompt-preview">"Can you tell me more about Designing Data-Intensive Applications?"</div>
            <button class="btn-test-run" onclick="runTestCase('Can you tell me more about Designing Data-Intensive Applications?')">Run Test 💬</button>
          </div>
        </div>
      </div>
    </section>
  </main>

<!-- Floating Launcher -->
  <div class="chat-bubble-launcher" id="chatLauncher" title="Chat with Paige!">
    <img src="/images/paige.png" alt="Paige Support" onerror="this.src='/images/paige';">
  </div>

  <!-- Pop-up Floating Chat Window -->
  <div class="chat-window" id="chatWindow">
    <div class="chat-header">
      <div>
        <h3>Bookly Support</h3>
        <span style="font-size: 11px; opacity: 0.85;">Online • Automated Returns</span>
      </div>
      <div class="chat-actions">
        <button id="resetBtn" title="Reset Session & Database">🔄</button>
        <button id="closeChatBtn" title="Close">✕</button>
      </div>
    </div>
    <div class="chat-messages" id="chatMessages">
      <div class="msg bot">Hello! I'm Paige, Bookly's virtual assistant.<br>I can help you with your order, shipping, returns or any questions you might have about our catalogue!<br>What can I do for you today?</div>
    </div>
    <div class="chat-input-area">
      <input type="text" id="userInput" placeholder="Ask about an order, return, or book..." autocomplete="off">
      <button id="sendBtn">Send</button>
    </div>
  </div>

  <script>
    const launcher = document.getElementById('chatLauncher');
    const chatWindow = document.getElementById('chatWindow');
    const closeBtn = document.getElementById('closeChatBtn');
    const resetBtn = document.getElementById('resetBtn');
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const cartCountEl = document.getElementById('cartCount');
    const cartHeader = document.getElementById('cartHeader');

    let currentCartCount = 0;
    
    // Automatically opens the widget and executes the test case prompt
    function runTestCase(promptText) {
      chatWindow.style.display = 'flex';
      sendMessage(promptText);
    }
    
    function formatMessage(text) {
      // Convert Markdown bold **text** to <strong>text</strong>
      let formatted = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
      // Convert bullet lines "- " into bullet symbols "• "
      formatted = formatted.replace(/^\\s*-\\s+/gm, '• ');
      return formatted;
    }

    function appendMsg(text, role) {
      const div = document.createElement('div');
      div.className = `msg ${role}`;
      if (role === 'bot') {
        div.innerHTML = formatMessage(text);
      } else {
        div.innerText = text;
      }
      chatMessages.appendChild(div);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return div;
    }

    function incrementCart() {
      currentCartCount += 1;
      cartCountEl.innerText = currentCartCount;
      cartHeader.classList.add('cart-bump');
      setTimeout(() => cartHeader.classList.remove('cart-bump'), 300);
    }

    launcher.addEventListener('click', () => {
      const isVisible = chatWindow.style.display === 'flex';
      chatWindow.style.display = isVisible ? 'none' : 'flex';
      if (!isVisible) userInput.focus();
    });

    closeBtn.addEventListener('click', () => { chatWindow.style.display = 'none'; });

    async function sendMessage(customText = null) {
      const text = customText !== null ? customText.trim() : userInput.value.trim();
      if (!text) return;

      appendMsg(text, 'user');
      if (customText === null) userInput.value = '';

      const loadingMsg = appendMsg('Checking details...', 'bot');

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        const data = await res.json();
        loadingMsg.remove();

        const botMsg = appendMsg(data.reply, 'bot');
        if (data.escalated) botMsg.classList.add('escalated');

        // Check if item was confirmed added to cart
        if (data.added_to_cart || /(added (it |the book )?to your cart|have added)/i.test(data.reply)) {
          incrementCart();
        }
      } catch (err) {
        loadingMsg.innerText = 'Unable to reach support. Please try again.';
      }
    }

    // Opens chat and queries Paige about the clicked book
    function askPaigeAboutBook(bookTitle) {
      chatWindow.style.display = 'flex';
      sendMessage(`Can you tell me more about "${bookTitle}"?`);
    }

    resetBtn.addEventListener('click', async () => {
      if (confirm('Reset mock database and conversation context to baseline?')) {
        await fetch('/api/reset', { method: 'POST' });
        chatMessages.innerHTML = '<div class="msg bot">Hello! I\\'m Paige, Bookly\\'s virtual assistant.<br>I can help you with your order, shipping, returns or any questions you might have about our catalogue!<br>What can I do for you today?</div>';
        currentCartCount = 0;
        cartCountEl.innerText = '0';
      }
    });

    sendBtn.addEventListener('click', () => sendMessage());
    userInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_store():
    genre_html = render_genre_rows()
    return HTML_TEMPLATE.replace("<!-- DYNAMIC_GENRE_ROWS -->", genre_html)


if __name__ == "__main__":
    # Runs when you click Play in PyCharm or type: python run_site.py
    uvicorn.run("run_site:app", host="127.0.0.1", port=8000, reload=True)