"""
Tournament Rules Assistant

A dedicated chat interface for asking questions about tournament rules.
Uses the RAG-backed /api/rules/ask endpoint.
"""

import streamlit as st
import requests
from typing import Optional

from tournament_platform.config import settings
from tournament_platform.services.settings import ENABLE_RULES_ASSISTANT
from tournament_platform.app.utils import api_request

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
if "rules_chat_history" not in st.session_state:
    st.session_state.rules_chat_history = []

if "rules_last_answer" not in st.session_state:
    st.session_state.rules_last_answer = None

# ---------------------------------------------------------------------------
# Example questions
# ---------------------------------------------------------------------------
EXAMPLE_QUESTIONS = [
    "What happens on a tie?",
    "How are round-robin standings calculated?",
    "What should I do if a player withdraws?",
    "Can I edit a submitted score?",
]

# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------
st.title("📖 Tournament Rules Assistant")
st.caption(
    "Answers are based on the local tournament rules knowledge base. "
    "No database changes are made from chat responses."
)

if not ENABLE_RULES_ASSISTANT:
    st.warning(
        "🚫 The Rules Assistant is currently disabled in settings. "
        "Set `ENABLE_RULES_ASSISTANT=True` in your `.env` file to enable it."
    )
    st.stop()

# Show AI status
try:
    from tournament_platform.app.components.ai_status import render_ai_status_badge
    render_ai_status_badge()
except Exception:
    pass

# Sidebar helpers
with st.sidebar:
    st.subheader("💡 Quick Questions")
    st.markdown("Tap an example to ask:")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, key=f"example_{hash(q)}", use_container_width=True):
            st.session_state.rules_pending_question = q
            st.rerun()

    st.divider()
    if st.session_state.rules_chat_history:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.rules_chat_history = []
            st.session_state.rules_last_answer = None
            st.rerun()

# ---------------------------------------------------------------------------
# Chat history display
# ---------------------------------------------------------------------------
for msg in st.session_state.rules_chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg["role"] == "assistant" and msg.get("question"):
            st.caption(f"**Question:** {msg['question']}")

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
pending = st.session_state.pop("rules_pending_question", None)
prompt = st.chat_input("Ask a question about tournament rules...") or pending

if prompt:
    # Display user message
    with st.chat_message("user"):
        st.write(prompt)

    st.session_state.rules_chat_history.append({
        "role": "user",
        "content": prompt,
    })

    # Get AI response
    with st.chat_message("assistant"):
        with st.status("Thinking...", expanded=False) as status:
            try:
                response_data = api_request(
                    "post",
                    "/api/rules/ask",
                    json={"question": prompt},
                    parse_json=True,
                    timeout=30.0,
                    error_context="rules question",
                )

                if response_data is None:
                    answer = "Sorry, I couldn't reach the rules service. Please check that the API server is running."
                    status.update(label="Service unavailable", state="error", expanded=False)
                else:
                    answer = response_data.get("answer", "No answer returned.")
                    status.update(label="Answer ready", state="complete", expanded=False)

            except requests.exceptions.ConnectionError:
                answer = (
                    "❌ Cannot connect to the API server. "
                    "Make sure `python tournament_platform/api/server.py` is running."
                )
                status.update(label="Connection error", state="error", expanded=False)
            except Exception as e:
                answer = f"Sorry, I couldn't process your question: {e}"
                status.update(label="Error occurred", state="error", expanded=False)

        st.write(answer)
        st.caption(f"**Question:** {prompt}")

        # Copy / reuse actions
        col_copy, col_reuse = st.columns(2)
        with col_copy:
            if st.button("📋 Copy answer", key=f"copy_{len(st.session_state.rules_chat_history)}"):
                st.toast("Answer copied to clipboard!", icon="📋")
                # Store for potential clipboard interaction
                st.session_state.rules_last_answer = answer
        with col_reuse:
            if st.button("📢 Use as announcement", key=f"reuse_{len(st.session_state.rules_chat_history)}"):
                st.session_state.rules_last_answer = answer
                st.toast("Answer saved for announcement use.", icon="📢")

    # Save to history
    st.session_state.rules_chat_history.append({
        "role": "assistant",
        "content": answer,
        "question": prompt,
    })

# ---------------------------------------------------------------------------
# Last answer reuse area
# ---------------------------------------------------------------------------
if st.session_state.rules_last_answer:
    st.divider()
    st.subheader("📢 Announcement Text")
    st.text_area(
        "Copy or edit the answer below for use in announcements:",
        value=st.session_state.rules_last_answer,
        key="announcement_text",
        height=120,
    )
    if st.button("📋 Copy to clipboard", key="copy_announcement"):
        st.toast("Announcement text ready!", icon="📋")
