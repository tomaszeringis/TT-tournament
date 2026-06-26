"""
Voice-Activated Tournament Scorekeeper

A simple, privacy-focused scorekeeping system using:
- Streamlit's st.audio_input for voice capture
- faster-whisper for local transcription
- Keyword matching for intent parsing
- pyttsx3 for offline TTS feedback
"""

import streamlit as st
import sys
import os
import asyncio
import tempfile
import hashlib
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import the MatchManager and UmpireEngine
from services.match_manager import MatchManager, MatchState
from services.umpire_engine import UmpireEngine, UmpireConfig
from models import SessionLocal, Match, MatchStatus

# ============================================================================
# TTS Engine (Offline, using pyttsx3)
# ============================================================================

def speak_text(text: str) -> None:
    """
    Speak text using pyttsx3 (offline TTS).
    Non-blocking implementation for Streamlit.
    """
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        st.warning(f"TTS unavailable: {e}")


# ============================================================================
# Session State Initialization
# ============================================================================

# Initialize MatchManager in session state
if 'match_manager' not in st.session_state:
    st.session_state.match_manager = MatchManager()

# Initialize UmpireEngine for transcription
if 'umpire_engine' not in st.session_state:
    st.session_state.umpire_engine = UmpireEngine()

# Initialize audio processing guard
if 'last_audio_hash' not in st.session_state:
    st.session_state.last_audio_hash = None

# Initialize feedback message
if 'last_feedback' not in st.session_state:
    st.session_state.last_feedback = None


# ============================================================================
# Helper Functions
# ============================================================================

def get_current_match_context() -> Optional[dict]:
    """Get the current match context from the database."""
    try:
        db = SessionLocal()
        active_match = db.query(Match).filter(
            Match.status == MatchStatus.active
        ).order_by(Match.scheduled_time.desc()).first()
        
        if active_match:
            context = {
                "player1": active_match.player1,
                "player2": active_match.player2,
                "match_id": active_match.id
            }
            db.close()
            return context
        db.close()
    except Exception as e:
        st.error(f"Error fetching match context: {e}")
    return None


def process_voice_command(audio_bytes: bytes) -> Tuple[str, str]:
    """
    Process voice input and return transcript and response.
    
    Args:
        audio_bytes: Raw audio bytes from st.audio_input
        
    Returns:
        Tuple of (transcript, response_text)
    """
    # Save audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name
    
    try:
        # Transcribe using faster-whisper
        transcript = st.session_state.umpire_engine.transcribe_audio_file(temp_path)
        
        if not transcript:
            return "", "Sorry, I couldn't understand the audio."
        
        # Process the transcript with MatchManager
        success, response = st.session_state.match_manager.update_score(transcript)
        
        return transcript, response
        
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


# ============================================================================
# Page UI
# ============================================================================

st.title("🎤 Voice Scorekeeper")
st.caption("Speak to update scores. The system uses local transcription - no data leaves your machine.")

# Player name configuration
st.subheader("Player Names")
col1, col2 = st.columns(2)

with col1:
    player_a_name = st.text_input(
        "Player A Name",
        value=st.session_state.match_manager.state.player_a,
        key="player_a_name_input"
    )

with col2:
    player_b_name = st.text_input(
        "Player B Name",
        value=st.session_state.match_manager.state.player_b,
        key="player_b_name_input"
    )

# Update player names if changed
if (player_a_name != st.session_state.match_manager.state.player_a or 
    player_b_name != st.session_state.match_manager.state.player_b):
    st.session_state.match_manager.set_player_names(player_a_name, player_b_name)
    st.rerun()

# Current score display
st.divider()
st.subheader("Current Score")

# Large, prominent score display
score_col1, score_col2 = st.columns(2)

with score_col1:
    st.markdown(f"### {st.session_state.match_manager.state.player_a}")
    st.markdown(f"<h1 style='text-align: center; color: #1f77b4;'>{st.session_state.match_manager.state.score_a}</h1>", 
                unsafe_allow_html=True)
    
    # Manual override buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("➕", key="add_point_a", use_container_width=True):
            success, msg = st.session_state.match_manager._add_point("A")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            speak_text(msg)
            st.rerun()
    with btn_col2:
        if st.button("➖", key="sub_point_a", use_container_width=True):
            # Quick undo for Player A
            if st.session_state.match_manager.state.match_history:
                last = st.session_state.match_manager.state.match_history[-1]
                if last.get("player") == "A":
                    st.session_state.match_manager.undo_last_point()
                    st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_a}"
                    st.toast(st.session_state.last_feedback, icon="↩️")
                    speak_text(st.session_state.last_feedback)
            st.rerun()

with score_col2:
    st.markdown(f"### {st.session_state.match_manager.state.player_b}")
    st.markdown(f"<h1 style='text-align: center; color: #ff7f0e;'>{st.session_state.match_manager.state.score_b}</h1>", 
                unsafe_allow_html=True)
    
    # Manual override buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("➕", key="add_point_b", use_container_width=True):
            success, msg = st.session_state.match_manager._add_point("B")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            speak_text(msg)
            st.rerun()
    with btn_col2:
        if st.button("➖", key="sub_point_b", use_container_width=True):
            # Quick undo for Player B
            if st.session_state.match_manager.state.match_history:
                last = st.session_state.match_manager.state.match_history[-1]
                if last.get("player") == "B":
                    st.session_state.match_manager.undo_last_point()
                    st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_b}"
                    st.toast(st.session_state.last_feedback, icon="↩️")
                    speak_text(st.session_state.last_feedback)
            st.rerun()

# Undo button
st.divider()
if st.button("↩️ Undo Last Point", use_container_width=True):
    success, msg = st.session_state.match_manager.undo_last_point()
    st.session_state.last_feedback = msg
    st.toast(msg, icon="↩️")
    speak_text(msg)
    st.rerun()

# Reset match button
if st.button("🔄 Reset Match", use_container_width=True):
    success, msg = st.session_state.match_manager.reset_match()
    st.session_state.last_feedback = msg
    st.toast(msg, icon="🔄")
    speak_text(msg)
    st.rerun()

# Voice input section
st.divider()
st.subheader("Voice Input")

audio_input = st.audio_input("Click to record your score command")

if audio_input:
    # Read audio bytes and compute hash to detect new audio
    audio_bytes = audio_input.read()
    audio_input.seek(0)  # Reset file pointer
    audio_hash = hashlib.sha256(audio_bytes).hexdigest() if audio_bytes else None
    
    # Only process if this is new audio
    if audio_hash and audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        
        with st.spinner("Processing voice command..."):
            # Process the audio
            transcript, response = process_voice_command(audio_bytes)
            
            if transcript:
                st.session_state.last_feedback = response
                st.toast(response, icon="✅")
                speak_text(response)
                st.rerun()
else:
    # Reset hash when audio is cleared
    st.session_state.last_audio_hash = None

# Display last feedback
if st.session_state.last_feedback:
    st.info(f"Last action: {st.session_state.last_feedback}")

# Instructions
st.divider()
st.subheader("Voice Commands")
st.markdown("""
**Supported commands:**
- "Point to [Player Name]" - Add a point
- "Player A scored" / "Player B scored" - Add a point
- "Undo last point" - Remove the last point
- "What's the score?" - Hear the current score

**Tips:**
- Speak clearly and at a normal pace
- The system works best in a quiet environment
- Use the +/− buttons for quick manual corrections
""")