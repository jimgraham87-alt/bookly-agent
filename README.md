# 📚 Bookly AI Support Agent

An enterprise-grade customer support AI agent for **Bookly**, an e-commerce bookstore. Built using native function calling with Google's Gemini SDK, SQLite, and Streamlit, this system handles order tracking, reverse-logistics returns, multi-item disambiguation, and human escalation with deterministic business logic gates.

---

## 🏗️ Architecture & Design Philosophy

Rather than relying purely on LLM reasoning for critical business operations, this project strictly decouples conversational interface from transactional business rules:

1. **Deterministic Business Gates**: Critical business policies (e.g., identity verification, 30-day return windows, delivered-status validation, duplicate prevention) are hardcoded in pure Python database functions. The LLM cannot hallucinate or bypass state transitions.
2. **Native Tool Calling**: Uses Gemini's native structured tool invocation (`tools_schema`) rather than fragile string parsing or heavy orchestration frameworks (e.g., LangChain).
3. **Dual Interface**: Fully testable via a modern **Streamlit Web UI** or a secure **Terminal CLI**.
4. **State Lifecycle**: Accurately mirrors real-world reverse logistics:
   $$\text{Delivered} \longrightarrow \mathbf{\text{Return Initiated}} \longrightarrow \text{Carrier Scan / Receipt} \longrightarrow \mathbf{\text{Refunded}}$$

---

## 📂 Project Structure

```text
bookly-agent/
├── app.py              # Streamlit Web Application (Chat UI + Admin Controls)
├── main.py             # CLI Interface with prompt-injection defense & session loops
├── agent.py            # Gemini client orchestration, AOP System Prompt, and session manager
├── tools.py            # Deterministic execution functions and JSON schemas
├── database.py         # SQLite schema initialization and seed data reset utilities
├── requirements.txt    # Project dependencies
├── .env                # API keys and local environment variables (Git-ignored)
└── .gitignore          # Prevents credentials and local SQLite caches from leaking