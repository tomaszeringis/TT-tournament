"""
AI Chat Components

Reusable components for AI-powered chat interfaces.
"""

import streamlit as st
from typing import List, Dict, Any, Optional, Callable
import uuid


def render_chat_message(message: Dict[str, Any], on_feedback: Optional[Callable[[str, str], None]] = None) -> None:
    """Render a single chat message with optional sources and feedback."""
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
        if message["role"] == "assistant" and message.get("msg_id") and on_feedback:
            msg_id = message["msg_id"]
            if msg_id not in st.session_state.get("ai_feedback", {}):
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("👍 Helpful", key=f"helpful_{msg_id}"):
                        on_feedback(msg_id, "helpful")
                with col2:
                    if st.button("👎 Not helpful", key=f"not_helpful_{msg_id}"):
                        on_feedback(msg_id, "not_helpful")
            else:
                feedback = st.session_state["ai_feedback"][msg_id]
                st.caption(f"Feedback: {'👍 Helpful' if feedback == 'helpful' else '👎 Not helpful'}")


def render_chat_history(
    messages: List[Dict[str, Any]],
    on_feedback: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Render the full chat history."""
    for message in messages:
        render_chat_message(message, on_feedback)


def render_chat_input(
    placeholder: str = "Ask a question...",
    key: str = "chat_input",
) -> Optional[str]:
    """Render chat input and return the prompt if submitted."""
    return st.chat_input(placeholder, key=key)


def render_ai_status_indicator(
    is_gounded: bool = True,
    confidence: Optional[float] = None,
) -> None:
    """Render AI status indicator."""
    if not is_gounded:
        st.warning("⚠️ No relevant rules found in the knowledge base. This answer is not grounded in official rules.")
    if confidence is not None:
        st.caption(f"Confidence: {confidence:.0%}")


def render_voice_input(
    on_transcript: Callable[[str], None],
    key: str = "voice_input",
) -> None:
    """Render voice input component."""
    st.caption("Or ask with your voice:")

    # Initialize UmpireEngine for voice transcription
    if 'umpire_engine' not in st.session_state:
        try:
            from tournament_platform.services.umpire_engine import UmpireEngine
            st.session_state.umpire_engine = UmpireEngine()
        except Exception:
            st.session_state.umpire_engine = None

    audio_input = st.audio_input("Click to record your question", key=key)

    if audio_input is not None:
        audio_bytes = audio_input.read()
        audio_input.seek(0)
        audio_hash = hash(audio_bytes) if audio_bytes else None

        if audio_hash and audio_hash != st.session_state.get("voice_audio_hash"):
            st.session_state.voice_audio_hash = audio_hash
            with st.spinner("Processing voice question..."):
                if st.session_state.umpire_engine:
                    try:
                        import tempfile
                        import os
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                            f.write(audio_bytes)
                            temp_path = f.name

                        try:
                            transcript = st.session_state.umpire_engine.transcribe_audio_file(temp_path)
                        finally:
                            if os.path.exists(temp_path):
                                os.unlink(temp_path)

                        if transcript:
                            on_transcript(transcript)
                        else:
                            st.warning("Could not understand the audio. Please try again.")
                    except Exception as e:
                        st.error(f"Voice processing error: {e}")
                else:
                    st.warning("Voice recognition is not available. Please type your question.")
    else:
        st.session_state.voice_audio_hash = None


def render_answer_actions(
    answer: str,
    on_copy: Optional[Callable[[], None]] = None,
    on_reuse: Optional[Callable[[], None]] = None,
) -> None:
    """Render copy and reuse actions for an answer."""
    col_copy, col_reuse = st.columns(2)
    with col_copy:
        if st.button("📋 Copy answer", key=f"copy_{uuid.uuid4()}"):
            if on_copy:
                on_copy()
            st.toast("Answer copied to clipboard!", icon="📋")
    with col_reuse:
        if st.button("📢 Use as announcement", key=f"reuse_{uuid.uuid4()}"):
            if on_reuse:
                on_reuse()
            st.toast("Answer saved for announcement use.", icon="📢")


def render_announcement_text_area(
    value: str,
    key: str = "announcement_text",
) -> None:
    """Render announcement text area for reuse."""
    st.subheader("📢 Announcement Text")
    st.text_area(
        "Copy or edit the answer below for use in announcements:",
        value=value,
        key=key,
        height=120,
    )
    if st.button("📋 Copy to clipboard", key="copy_announcement"):
        st.toast("Announcement text ready!", icon="📋")