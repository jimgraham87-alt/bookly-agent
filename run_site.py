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

from fastapi.staticfiles import StaticFiles

# Ensure images directory exists
IMAGE_DIR = "images"
os.makedirs(IMAGE_DIR, exist_ok=True)

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
app.mount("/static", StaticFiles(directory="static"), name="static")

import re

BOOK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

@app.get("/images/{book_id}")
async def get_book_image(book_id: str):
    """Serves image file matching book_id with or without extensions (.png, .jpg, .jpeg, .webp)."""
    if not BOOK_ID_PATTERN.match(book_id):
        raise HTTPException(status_code=404, detail="Image not found")

    extensions = ["", ".png", ".jpg", ".jpeg", ".webp"]
    for ext in extensions:
        candidate = os.path.join(IMAGE_DIR, f"{book_id}{ext}")
        if os.path.isfile(candidate):
            return FileResponse(candidate)

    raise HTTPException(status_code=404, detail="Image not found")


class ChatRequest(BaseModel):
    message: str
    session_id: str  # Isolated per tab/device


# Session store for message arrays: session_id -> list of message dicts
session_histories: dict[str, list] = {}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    user_msg = req.message.strip()
    session_id = req.session_id.strip()

    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty message")

    if session_id not in session_histories:
        session_histories[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    session_histories[session_id].append({"role": "user", "content": user_msg})

    # Run turn with isolated session
    reply = run_agent_turn(session_histories[session_id], session_id=session_id)

    is_escalated = "ticket #" in reply.lower()
    return {"reply": reply, "escalated": is_escalated}


class ResetRequest(BaseModel):
    session_id: str = None


@app.post("/api/reset")
async def reset_endpoint(req: ResetRequest = None):
    sid = req.session_id if req else None
    reset_db()
    reset_agent(sid)
    if sid and sid in session_histories:
        session_histories.pop(sid, None)
    elif not sid:
        session_histories.clear()
    return {"status": "success", "message": "State reset successfully."}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" name="robots" content="noindex, nofollow" />
  <title>Bookly | Online Book Store</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css">
</head>
<body>

  <div class="top-bar">Fast & Tracked Delivery | 30-Day Easy Returns</div>

  <header>
    <a href="#" class="brand"><img src="/images/logo"> Bookly</a>
    <div class="search-bar">
      <input type="text" placeholder="Search title, author, or ISBN...">
      <button>Search</button>
    </div>
    <div class="header-links">
      <span><a href="#" onclick="runTestCase('Hi, I would like to check the status of my order.'); return false;">Track an Order</a></span>
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
        <h1>Reading Sale on now</h1>
        <p>Explore a range of exciting titles!</p>
      </div>
    </div>

    <h2 class="section-title">Top Titles in these genres!</h2>
    <div class="genre-catalog-container">
      <!-- DYNAMIC_GENRE_ROWS -->
    </div>
    <!-- TEST CASE SUITE FOR EVALUATORS -->
    <hr class="section-divider">
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
            <div class="test-expected"><strong>Expected Behavior:</strong> If a continuation from test 3: Invokes process_refund, marks status as initiated, and provides drop-off instructions.<br>If an isolated test, request order information for verification before proceeding.</div>
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
            <div class="test-meta"><strong>Context:</strong> Customer inquires about a store title.<br><strong>Note:</strong> Have allowed for quering books outside of the database catalogue for demonstration purposes</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Paige provides a 2-sentence summary, prompts to buy, and clicking 'Yes' adds the item to the cart.</div>
          </div>
          <div>
            <div class="prompt-preview">"Can you tell me more about Designing Data-Intensive Applications?"</div>
            <button class="btn-test-run" onclick="runTestCase('Can you tell me more about Designing Data-Intensive Applications?')">Run Test 💬</button>
          </div>
        </div>
        <!-- Test 8 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-info">Clarifying Question</span>
            <div class="test-title">8. Shipping Inquiry — Missing Destination</div>
            <div class="test-meta"><strong>Context:</strong> Customer asks about shipping without naming a destination.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Paige does not guess a country or call get_shipping_info. She asks which country the customer is shipping to first.</div>
          </div>
          <div>
            <div class="prompt-preview">"How long does shipping take?"</div>
            <button class="btn-test-run" onclick="runTestCase('How long does shipping take?')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 9 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-info">Regional Shipping Rates</span>
            <div class="test-title">9. Shipping Cost & Time by Region</div>
            <div class="test-meta"><strong>Context:</strong> Destination is provided in the same message.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Calls get_shipping_info("Germany"), matches it to the European Union rate, and presents both standard and express cost/time.</div>
          </div>
          <div>
            <div class="prompt-preview">"How much would it cost to ship to Germany, and how long would it take?"</div>
            <button class="btn-test-run" onclick="runTestCase('How much would it cost to ship to Germany, and how long would it take?')">Run Test 💬</button>
          </div>
        </div>

        <!-- Test 10 -->
        <div class="test-card">
          <div class="test-card-top">
            <span class="test-badge badge-info">General Policy Lookup</span>
            <div class="test-title">10. Password Reset Help</div>
            <div class="test-meta"><strong>Context:</strong> General account question, unrelated to a specific order.</div>
            <div class="test-expected"><strong>Expected Behavior:</strong> Calls get_store_policy rather than answering from memory, and relays the actual reset steps and link expiry.</div>
          </div>
          <div>
            <div class="prompt-preview">"I forgot my password, how do I get back into my account?"</div>
            <button class="btn-test-run" onclick="runTestCase('I forgot my password, how do I get back into my account?')">Run Test 💬</button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="footer-grid">
      <div class="footer-brand">
        <h3>📚 Bookly</h3>
        <p>Your online bookstore for fiction, non-fiction, and everything in between — with support that actually knows your order.</p>
      </div>
      <div class="footer-col">
        <h4>Shop</h4>
        <a href="#">Browse Catalog</a>
        <a href="#">New Releases</a>
        <a href="#">Bestsellers</a>
      </div>
      <div class="footer-col">
        <h4>Support</h4>
        <a href="#" onclick="runTestCase('Hi, I would like to check the status of my order.'); return false;">Track an Order</a>
        <a href="#" onclick="runTestCase('Tell me about your returns policy'); return false;">Track an Order</a>
        <a href="#" onclick="runTestCase('Hi, I would like to ask about shipping'); return false;">Track an Order</a>
        <a href="#">Contact Us</a>
      </div>
      <div class="footer-col">
        <h4>Company</h4>
        <a href="#">About</a>
        <a href="#">Careers</a>
        <a href="#">Blog</a>
      </div>
    </div>
    <div class="footer-bottom">
      <span>&copy; 2026 Bookly, Inc. All rights reserved.</span>
      <div>
        <a href="#">Privacy Policy</a>
        <a href="#">Terms of Service</a>
      </div>
    </div>
  </footer>

<!-- Floating Launcher -->
  <div class="chat-bubble-launcher" id="chatLauncher" title="Chat with Paige!">
    <img src="/images/paige.png" alt="Paige Support" onerror="this.src='/images/paige';">
  </div>

  <!-- Pop-up Floating Chat Window -->
  <div class="chat-window" id="chatWindow">
    <div class="chat-header">
      <div>
        <h3>Bookly Support Agent, Paige!</h3>
        <span style="font-size: 11px; opacity: 0.85;">Automated returns, orders and information!</span>
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
    
// 1. Generate an isolated session ID per page load/tab
    const currentSessionId = 'sess_' + Math.random().toString(36).substring(2, 15);

    // 2. Updated sendMessage supporting both customText ("Ask Paige" / quick tests) and session_id
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
          body: JSON.stringify({ 
            message: text,
            session_id: currentSessionId   // Isolated session
          })
        });
        const data = await res.json();
        loadingMsg.remove();

        const botMsg = appendMsg(data.reply, 'bot');
        if (data.escalated) botMsg.classList.add('escalated');

        // Preserve cart incrementation
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