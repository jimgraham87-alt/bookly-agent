# 📚 Bookly AI Support Agent

A customer support AI agent for **Bookly**, a fictional online bookstore, built for the
Decagon Solutions Engineering take-home. It handles order tracking, returns/refunds,
multi-item disambiguation, catalog inquiries, shipping/policy questions, and human
escalation, backed by a real SQLite database and a live policy document — all through
Gemini's native function calling, with no orchestration framework.

Two interfaces share the same agent: a **FastAPI storefront** with an embedded chat
widget, and a **terminal CLI** for quick, low-friction testing.

---

## 🏗️ Architecture & Design Philosophy

The core belief behind this build: **conversational reasoning and transactional business
logic should be strictly separated.** The LLM decides *when* to act and *what to say*; it
never decides *whether an action is allowed* or *what a policy actually says* — both are
grounded in real data every time, not memory or inference.

1. **Deterministic business gates.** Identity verification, the 30-day return window,
   delivery-status checks, and duplicate-return prevention are all hardcoded in `tools.py`,
   not left to the model's judgment. The model can request an action; the database decides
   whether it's actually allowed to happen.
2. **Native function calling, not a schema layer.** `agent.py` passes plain Python
   functions directly into Gemini's `tools=` config. The SDK builds tool declarations from
   each function's docstring and type hints and dispatches calls automatically — there's
   no hand-maintained JSON schema or framework (e.g. LangChain) between the model and the
   code that runs.
3. **Two interfaces, one agent.** `run_site.py` (FastAPI) serves a storefront page with
   a floating chat widget and a built-in test-scenario panel; `main.py` is a terminal CLI
   with the same `agent.py` underneath, useful for fast iteration without a browser.
4. **State lifecycle.** Returns mirror real reverse logistics:
   `Delivered → Return Initiated → Carrier Scan → Refunded`. The agent's
   `process_refund` tool only ever gets the flow to "Return Initiated" — the actual refund
   is modeled as releasing once the carrier scans the returned parcel, not the moment the
   agent responds.
5. **Policy answers are grounded in a live document, not duplicated in code.**
   Shipping rates and general store policies (password reset, payment methods, order
   changes, returns overview, support hours) live in `sources/bookly_policies.pdf` —
   the same kind of source-of-truth document a real support platform would ingest.
   `get_shipping_info` and `get_store_policy` parse that PDF at runtime with
   `pdfplumber`; nothing about *what the policy says* is hardcoded in Python. Update the
   PDF, and the agent's answers update with it — no code change or redeploy needed. The
   only things kept in code are interpretation logic that isn't policy content at all:
   which country names map to which shipping region, and which customer phrasing maps to
   which section heading.

---

## 📂 Project Structure

```text
bookly-agent/
├── run_site.py             # FastAPI app: storefront page + chat widget + /api/chat, /api/reset
├── main.py                 # Terminal CLI, with a lightweight prompt-injection heuristic
├── agent.py                # Gemini session orchestration + the AOP system prompt
├── tools.py                # Deterministic tool functions the model can call
├── database.py              # SQLite schema + seed data, with a reset-to-baseline utility
├── build_policy_pdf.py       # Regenerates sources/bookly_policies.pdf (rerun after editing it)
├── sources/
│   └── bookly_policies.pdf     # Shipping rates + general policies — read live by tools.py
├── images/                        # Book cover images served by run_site.py's /images route
├── requirements.txt                # Python dependencies
├── .env                              # GEMINI_API_KEY (git-ignored)
└── .gitignore                         # Keeps credentials and the local SQLite file out of git
```

---

## 🧰 Tools

| Tool | Grounded in | Requires identity verification |
|---|---|---|
| `lookup_order` | SQLite | Yes |
| `process_refund` | SQLite | Yes |
| `cancel_order` | SQLite | Yes |
| `escalate_to_human` | — | No |
| `lookup_book` | SQLite | No |
| `add_to_cart` | SQLite | No |
| `get_shipping_info` | `sources/bookly_policies.pdf` | No |
| `get_store_policy` | `sources/bookly_policies.pdf` | No |
| `get_current_date` | System clock | No |

---

## ▶️ Running it

```bash
pip install -r requirements.txt
```

Create a `.env` file with:
```
GEMINI_API_KEY=your_key_here
```

**Storefront (recommended for demo):**
```bash
python run_site.py
```
Opens on `http://127.0.0.1:8000`. Click the chat bubble in the bottom-right corner to talk
to Paige, click any book's "Ask Paige" button for a catalog inquiry, or use the built-in
**Test Scenarios** panel to run any of the 10 pre-built scenarios with one click.

**CLI (fastest for quick testing):**
```bash
python main.py
```
Resets the database on launch, then drops you into a terminal chat loop. Type `exit` to quit.

**Editing store policies:**
```bash
python build_policy_pdf.py
```
Edit `sources/bookly_policies.pdf` directly (or, for structured shipping rates, edit the
source Platypus content in `build_policy_pdf.py` and rerun it) — the agent reads the PDF
live, so no other code changes are needed for a policy update to take effect.

---

## 🧪 Test data

The database seeds three orders on every reset:

| Order | Customer | State | Good for testing |
|---|---|---|---|
| `ORD-1001` | alex@example.com | Delivered yesterday | Return within the 30-day window |
| `ORD-1002` | sarah@example.com | Delivered 45 days ago | Return window expired |
| `ORD-1003` | jordan@example.com | In transit, 2 items | Multi-item disambiguation + not-yet-delivered return flow |

The storefront's **Test Scenarios** panel covers all of the above plus identity
verification, escalation, catalog Q&A + cart, shipping (both a missing-destination
clarifying question and a resolved regional lookup), and a general policy question.

---

## What I'd do differently with more time

- Replace the string-matching used to detect "was this escalated / added to cart" in
  `run_site.py` (checking the reply text for phrases like `"ticket #"`) with a structured
  signal from `run_agent_turn` about which tools actually executed that turn.
- Upgrade `get_store_policy`'s keyword matching to embedding-based semantic search over
  the same PDF, so a question with the right intent but no keyword overlap (e.g. "I'm
  locked out of my account") still resolves correctly.
- Add a seeded order in a `Processing` (pre-shipment) state — none of the current seed
  data exercises the `cancel_order` path.
- Split the system prompt into a smaller router + task-specific sub-prompts as the number
  of policies grows, rather than one large prompt handling every gate.
