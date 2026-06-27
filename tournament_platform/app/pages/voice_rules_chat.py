import os
import streamlit as st
import asyncio
import tempfile
import hashlib
from typing import Optional, Dict, Any, List

from tournament_platform.services.umpire_engine import UmpireEngine, UmpireConfig
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player

# Initialize UmpireEngine in session state
if 'umpire_engine' not in st.session_state:
    st.session_state.umpire_engine = UmpireEngine()

# Initialize chat history
if 'voice_rules_chat_history' not in st.session_state:
    st.session_state.voice_rules_chat_history = []

# Initialize match context
if 'current_match_context' not in st.session_state:
    st.session_state.current_match_context = None

# Initialize audio processing guard to prevent re-processing same audio on rerun
if 'last_audio_hash' not in st.session_state:
    st.session_state.last_audio_hash = None


def get_current_match_context() -> Optional[Dict[str, Any]]:
    """
    Get the current match context from the database.
    Returns the most recent active match or None.
    """
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
    except Exception as e:
        st.error(f"Error fetching match context: {e}")
    return None


def display_chat_history():
    """Display the chat history using st.chat_message."""
    for message in st.session_state.voice_rules_chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])


async def process_voice_query(audio_bytes: bytes, match_context: Optional[Dict[str, Any]] = None):
    """
    Process voice input and return the response with streaming TTS.
    
    Args:
        audio_bytes: Raw audio bytes from st.audio_input
        match_context: Optional match context for awareness
        
    Returns:
        Tuple of (transcript, response_text)
    """
    # Save audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name
    
    try:
        # Get transcript
        transcript = st.session_state.umpire_engine.transcribe_audio_file(temp_path)
        
        if not transcript:
            return None, "Sorry, I couldn't understand the audio."
        
        # Get response with streaming TTS
        response_buffer = ""
        async for chunk in st.session_state.umpire_engine.ask_rules_voice(
            temp_path, 
            match_context=match_context
        ):
            response_buffer += chunk
        
        return transcript, response_buffer
        
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


# Page UI
st.title("🎤 Voice Rules Chat")
st.caption("Ask questions about tournament rules using your voice. The AI will answer with both text and voice response.")

# Match context selector
st.subheader("Match Context (Optional)")
col1, col2 = st.columns([2, 1])

with col1:
    use_current_match = st.checkbox("Use current active match as context", value=True)
    if use_current_match:
        match_context = get_current_match_context()
        if match_context:
            st.info(f"Current match: **{match_context['player1']}** vs **{match_context['player2']}**")
            if match_context.get('score'):
                st.caption(f"Score: {match_context['score']}")
        else:
            st.info("No active match found. You can still ask general rules questions.")
            match_context = None
    else:
        match_context = None

with col2:
    if st.button("🔄 Refresh Match Context"):
        st.session_state.current_match_context = get_current_match_context()
        st.rerun()

# Display chat history
st.subheader("Chat History")
display_chat_history()

# Voice input section
st.subheader("Ask a Question")
audio_input = st.audio_input("Click to record your question about tournament rules")

if audio_input:
    # Read audio bytes and compute hash to detect new audio
    audio_bytes = audio_input.read()
    audio_input.seek(0)  # Reset file pointer for potential future use
    audio_hash = hashlib.sha256(audio_bytes).hexdigest() if audio_bytes else None
    
    # Only process if this is new audio (not already processed)
    if audio_hash and audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        with st.spinner("Processing your question..."):
            # Process the audio using manual event loop to avoid conflicts
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                transcript, response = loop.run_until_complete(
                    process_voice_query(audio_bytes, match_context)
                )
            finally:
                loop.close()
            
            if transcript:
                # Add to chat history
                st.session_state.voice_rules_chat_history.append({
                    "role": "user",
                    "content": transcript
                })
                
                st.session_state.voice_rules_chat_history.append({
                    "role": "assistant",
                    "content": response
                })
                
                # Rerun to display updated chat
                st.rerun()
else:
    # Reset hash when audio is cleared
    st.session_state.last_audio_hash = None

# Text input alternative
st.divider()
st.caption("Or type your question:")

text_input = st.text_input(
    "Type your rules question here:",
    key="text_rules_question",
    label_visibility="collapsed"
)

if st.button("Ask", key="text_rules_ask") and text_input:
    with st.spinner("Getting answer..."):
        try:
            # Get rules context
            rules_context = st.session_state.umpire_engine.rules_retriever.search_rules(text_input, n_results=3)
            
            # Build chat history for context
            chat_history = st.session_state.voice_rules_chat_history.copy()
            
            # Get response - properly consume async generator
            async def _collect_rules_response():
                response_buffer = ""
                async for chunk in st.session_state.umpire_engine._llm_process_rules_stream(
                    text_input,
                    rules_context,
                    chat_history
                ):
                    response_buffer += chunk
                return response_buffer
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                response_buffer = loop.run_until_complete(_collect_rules_response())
            finally:
                loop.close()
            
            # Add to chat history
            st.session_state.voice_rules_chat_history.append({
                "role": "user",
                "content": text_input
            })
            
            st.session_state.voice_rules_chat_history.append({
                "role": "assistant",
                "content": response_buffer
            })
            
            # Clear input
            st.session_state.text_rules_question = ""
            st.rerun()
            
        except Exception as e:
            st.error(f"Error processing question: {e}")

# Clear chat button
if st.session_state.voice_rules_chat_history:
    if st.button("🗑️ Clear Chat History"):
        st.session_state.voice_rules_chat_history = []
        st.rerun()