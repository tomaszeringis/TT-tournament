"""
AI Assistant - Unified chat interface for tournament questions.

Combines the Tournament Assistant and Rules Q&A into a single page with tabs.
- Tournament Assistant: General tournament questions using the AI facade
- Rules Q&A: Rules questions using the /api/rules/ask endpoint
"""

import streamlit as st
import requests
from typing import Optional
import uuid

from tournament_platform.config import settings
from tournament_platform.services.settings import ENABLE_RULES_ASSISTANT
from tournament_platform.app.utils import api_request
from tournament_platform.services.ai_facade import answer_rules_question, AIAnswer
from tournament_platform.app.components.ai_status import render_ai_status_badge, render_ai_status_expander
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
# Tournament Assistant history
if "ai_assistant_messages" not in st.session_state:
    st.session_state.ai_assistant_messages = []

if "ai_feedback" not in st.session_state:
    st.session_state.ai_feedback = {}

# Rules Q&A history
if "ai_rules_messages" not in st.session_state:
    st.session_state.ai_rules_messages = []

if "ai_rules_last_answer" not in st.session_state:
    st.session_state.ai_rules_last_answer = None

# ---------------------------------------------------------------------------
# Example questions for Rules Q&A
# ---------------------------------------------------------------------------
EXAMPLE_QUESTIONS = [
    "What happens on a tie?",
    "How are round-robin standings calculated?",
    "What should I do if a player withdraws?",
    "Can I edit a submitted score?",
]

# ---------------------------------------------------------------------------
# Helper: get current match context
# ---------------------------------------------------------------------------
def get_current_match_context() -> Optional[dict]:
    """Get the current match context from the database."""
    try:
        db = SessionLocal()
        active_match = db.query(Match).filter(
            Match.status == MatchStatus.active
        ).order_by(Match.scheduled_time.desc()).first()

        if active_match:
            p1 = db.query(Player).filter(Player.id == active_match.player1_id).first() if active_match.player1_id else None
            p2 = db.query(Player).filter(Player.id == active_match.player2_id).first() if active_match.player2_id else None
            context = {
                "player1": p1.name if p1 else "Unknown",
                "player2": p2.name if p2 else "Unknown",
                "tournament": active_match.tournament.name if active_match.tournament else None,
                "score": active_match.score,
                "match_id": active_match.id
            }
            db.close()
            return context
        db.close()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------
st.title("🤖 AI Assistant")
st.caption("Ask tournament, rules, ranking, schedule, and operations questions.")

# Show AI status
render_ai_status_badge()

# ---------------------------------------------------------------------------
# Combined sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("💡 Assistant Capabilities")
    st.markdown("""
    - Answer rules questions using RAG
    - Explain tournament standings
    - Help with match reporting
    - Summarize tournament status

    **Note:** This assistant provides information only.
    No database changes are made from chat responses.
    """)

    st.divider()
    st.subheader("💡 Quick Questions")
    st.markdown("Tap an example to ask:")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, key=f"example_{hash(q)}", use_container_width=True):
            st.session_state.ai_rules_pending_question = q
            st.rerun()

    st.divider()
    if st.session_state.ai_assistant_messages:
        if st.button("🗑️ Clear Tournament Chat", use_container_width=True):
            st.session_state.ai_assistant_messages = []
            st.session_state.ai_feedback = {}
            st.rerun()

    if st.session_state.ai_rules_messages:
        if st.button("🗑️ Clear Rules Chat", use_container_width=True):
            st.session_state.ai_rules_messages = []
            st.session_state.ai_rules_last_answer = None
            st.rerun()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tabs = st.tabs(["Tournament Assistant", "Rules Q&A"])

# ===========================================================================
# TAB 1: Tournament Assistant
# ===========================================================================
with tabs[0]:
    # Display chat history using st.chat_message
    for i, message in enumerate(st.session_state.ai_assistant_messages):
        with st.chat_message(message["role"]):
            st.write(message["content"])

            # Show sources for assistant messages
            if message["role"] == "assistant" and message.get("source_details"):
                with st.expander("📚 Sources used", expanded=False):
                    for source in message["source_details"]:
                        st.markdown(f"**Source:** {source.get('id', 'Unknown')}")
                        if source.get('metadata'):
                            meta = source['metadata']
                            if meta.get('source'):
                                st.caption(f"Document: {meta.get('source')}")
                            if meta.get('page'):
                                st.caption(f"Page: {meta.get('page')}")
                        st.markdown(f"**Relevance:** {source.get('distance', 'N/A')}")
                        st.markdown("---")

            # Show feedback buttons for assistant messages
            if message["role"] == "assistant" and message.get("msg_id"):
                msg_id = message["msg_id"]
                if msg_id not in st.session_state.ai_feedback:
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("👍 Helpful", key=f"helpful_{msg_id}"):
                            st.session_state.ai_feedback[msg_id] = "helpful"
                            st.rerun()
                    with col2:
                        if st.button("👎 Not helpful", key=f"not_helpful_{msg_id}"):
                            st.session_state.ai_feedback[msg_id] = "not_helpful"
                            st.rerun()
                else:
                    feedback = st.session_state.ai_feedback[msg_id]
                    st.caption(f"Feedback: {'👍 Helpful' if feedback == 'helpful' else '👎 Not helpful'}")

    # Chat input using st.chat_input
    prompt = st.chat_input("Ask a question about tournaments, rules, or standings...")

    if prompt:
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)

        # Add to chat history
        st.session_state.ai_assistant_messages.append({
            "role": "user",
            "content": prompt
        })

        # Get AI response with status indicator
        with st.chat_message("assistant"):
            with st.status("Thinking...", expanded=False) as status:
                try:
                    # Use the facade for a clean interface
                    ai_answer: AIAnswer = answer_rules_question(prompt)
                    response = ai_answer.answer
                    status.update(label="Answer ready", state="complete", expanded=False)
                except Exception as e:
                    response = "Sorry, I couldn't process your question. Please ensure Ollama is running and the model is available."
                    ai_answer = AIAnswer(answer=response, sources=[], source_details=[], confidence=None, grounded=False)
                    status.update(label="Error occurred", state="error", expanded=False)

            st.write(response)

            # Show sources if available
            if ai_answer.source_details:
                with st.expander("📚 Sources used", expanded=False):
                    for source in ai_answer.source_details:
                        st.markdown(f"**Source:** {source.get('id', 'Unknown')}")
                        if source.get('metadata'):
                            meta = source['metadata']
                            if meta.get('source'):
                                st.caption(f"Document: {meta.get('source')}")
                            if meta.get('page'):
                                st.caption(f"Page: {meta.get('page')}")
                        st.markdown(f"**Relevance:** {source.get('distance', 'N/A')}")
                        st.markdown("---")

            # Show confidence indicator
            if not ai_answer.grounded:
                st.warning("⚠️ No relevant rules found in the knowledge base. This answer is not grounded in official rules.")

        # Add to chat history with source details
        msg_id = str(uuid.uuid4())
        st.session_state.ai_assistant_messages.append({
            "role": "assistant",
            "content": response,
            "source_details": ai_answer.source_details,
            "msg_id": msg_id
        })

# ===========================================================================
# TAB 2: Rules Q&A
# ===========================================================================
with tabs[1]:
    if not ENABLE_RULES_ASSISTANT:
        st.warning(
            "🚫 The Rules Q&A is currently disabled in settings. "
            "Set `ENABLE_RULES_ASSISTANT=True` in your `.env` file to enable it."
        )
        st.stop()

    # Display chat history
    for msg in st.session_state.ai_rules_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant" and msg.get("question"):
                st.caption(f"**Question:** {msg['question']}")

    # Chat input
    pending = st.session_state.pop("ai_rules_pending_question", None)
    prompt = st.chat_input("Ask a question about tournament rules...") or pending

    if prompt:
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)

        st.session_state.ai_rules_messages.append({
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
                if st.button("📋 Copy answer", key=f"copy_{len(st.session_state.ai_rules_messages)}"):
                    st.toast("Answer copied to clipboard!", icon="📋")
                    # Store for potential clipboard interaction
                    st.session_state.ai_rules_last_answer = answer
            with col_reuse:
                if st.button("📢 Use as announcement", key=f"reuse_{len(st.session_state.ai_rules_messages)}"):
                    st.session_state.ai_rules_last_answer = answer
                    st.toast("Answer saved for announcement use.", icon="📢")

        # Save to history
        st.session_state.ai_rules_messages.append({
            "role": "assistant",
            "content": answer,
            "question": prompt,
        })

    # -----------------------------------------------------------------------
    # Last answer reuse area
    # -----------------------------------------------------------------------
    if st.session_state.ai_rules_last_answer:
        st.divider()
        st.subheader("📢 Announcement Text")
        st.text_area(
            "Copy or edit the answer below for use in announcements:",
            value=st.session_state.ai_rules_last_answer,
            key="announcement_text",
            height=120,
        )
        if st.button("📋 Copy to clipboard", key="copy_announcement"):
            st.toast("Announcement text ready!", icon="📋")

# ---------------------------------------------------------------------------
# Detailed status expander (outside tabs, at page bottom)
# ---------------------------------------------------------------------------
st.divider()
render_ai_status_expander()
