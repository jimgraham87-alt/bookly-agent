import streamlit as st
from database import reset_db
from agent import SYSTEM_PROMPT, run_agent_turn, reset_agent

st.set_page_config(page_title="Bookly Support", page_icon="📚", layout="centered")

# Sidebar controls for interviewers
with st.sidebar:
    st.title("📚 Bookly Admin")
    st.markdown("Use these controls to reset mock data during testing.")
    if st.button("Reset Database & Session", use_container_width=True):
        reset_db()  # Re-seeds SQLite database
        reset_agent()  # Clears Gemini's internal LLM conversation memory
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        st.session_state.chat_history = []
        st.success("Database and chat session reset!")
        st.rerun()

st.title("Your Bookly Customer Support, Paige!")
st.caption("Ask about your order status, tracking, or item returns.")

# Initialize session state for messages
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Display conversation history in chat bubbles
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Customer Input Field
if user_prompt := st.chat_input("How can we help you today?"):
    # Render user message
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # Append to LLM context and get agent response
    st.session_state.messages.append({"role": "user", "content": user_prompt})

    with st.chat_message("assistant"):
        with st.spinner("Bookly is checking..."):
            reply = run_agent_turn(st.session_state.messages)
            st.markdown(reply)

    st.session_state.chat_history.append({"role": "assistant", "content": reply})

    # Optional: Display alert if transferred to human
    if "Ticket #" in reply or "ticket #" in reply.lower():
        st.warning("Session escalated: Transferred to human support queue.")