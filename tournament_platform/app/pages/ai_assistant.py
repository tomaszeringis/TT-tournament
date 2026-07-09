"""
AI Assistant - Unified chat interface for tournament questions.

Combines the Tournament Assistant and Rules Q&A into a single page with tabs.
- Tournament Assistant: General tournament questions using the AI facade
- Rules Q&A: Rules questions using the /api/rules/ask endpoint (with voice input option)
"""

import streamlit as st

st.set_page_config(page_title="AI Assistant - TT Platform", layout="wide")
import requests
from typing import Optional
import uuid
import asyncio

from tournament_platform.config import settings
from tournament_platform.services.settings import ENABLE_RULES_ASSISTANT
from tournament_platform.app.utils import api_request, get_current_match_context
from tournament_platform.services.ai_facade import answer_rules_question, AIAnswer
from tournament_platform.app.components.ai_status import render_ai_status_badge, render_ai_status_expander
from tournament_platform.app.components.ai_chat import (
    render_chat_history,
    render_chat_input,
    render_ai_status_indicator,
    render_voice_input,
    render_answer_actions,
    render_announcement_text_area,
)
from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player

# Apply design system styles
apply_global_styles()

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

# Voice input state
if "voice_rules_audio_hash" not in st.session_state:
    st.session_state.voice_rules_audio_hash = None

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
# Page UI
# ---------------------------------------------------------------------------
st.title("AI Assistant")
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
    def on_feedback(msg_id: str, feedback: str):
        st.session_state.ai_feedback[msg_id] = feedback
        st.rerun()

    render_chat_history(st.session_state.ai_assistant_messages, on_feedback)

    prompt = render_chat_input("Ask a question about tournaments, rules, or standings...")

    if prompt:
        # Add to chat history
        st.session_state.ai_assistant_messages.append({
            "role": "user",
            "content": prompt
        })

        # Get AI response with status indicator
        with st.chat_message("assistant"):
            with st.status("Thinking...", expanded=False) as status:
                try:
                    ai_answer: AIAnswer = answer_rules_question(prompt)
                    response = ai_answer.answer
                    status.update(label="Answer ready", state="complete", expanded=False)
                except Exception as e:
                    response = "Sorry, I couldn't process your question. Please ensure Ollama is running and the model is available."
                    ai_answer = AIAnswer(answer=response, sources=[], source_details=[], confidence=None, grounded=False)
                    status.update(label="Error occurred", state="error", expanded=False)

            st.write(response)

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

            render_ai_status_indicator(ai_answer.grounded, ai_answer.confidence)

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

    for msg in st.session_state.ai_rules_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant" and msg.get("question"):
                st.caption(f"**Question:** {msg['question']}")

    def on_transcript(transcript: str):
        st.session_state.ai_rules_pending_question = transcript
        st.rerun()

    render_voice_input(on_transcript, key="rules_voice_input")

    pending = st.session_state.pop("ai_rules_pending_question", None)
    prompt = st.chat_input("Ask a question about tournament rules...") or pending

    if prompt:
        st.session_state.ai_rules_messages.append({
            "role": "user",
            "content": prompt,
        })

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

            def on_copy():
                st.session_state.ai_rules_last_answer = answer

            def on_reuse():
                st.session_state.ai_rules_last_answer = answer

            render_answer_actions(answer, on_copy, on_reuse)

        st.session_state.ai_rules_messages.append({
            "role": "assistant",
            "content": answer,
            "question": prompt,
        })

    if st.session_state.ai_rules_last_answer:
        st.divider()
        render_announcement_text_area(st.session_state.ai_rules_last_answer)

# ---------------------------------------------------------------------------
# Detailed status expander (outside tabs, at page bottom)
# ---------------------------------------------------------------------------
st.divider()
render_ai_status_expander()
