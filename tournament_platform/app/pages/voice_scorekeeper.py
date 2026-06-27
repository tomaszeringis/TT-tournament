"""
Voice-Activated Tournament Scorekeeper

A simple, privacy-focused scorekeeping system using:
- Streamlit's st.audio_input for voice capture
- faster-whisper for local transcription
- Keyword matching for intent parsing
- pyttsx3 for offline TTS feedback
"""

import streamlit as st
import asyncio
import tempfile
import hashlib
import os
from typing import Optional, Tuple, Dict, List

# Import the MatchManager and UmpireEngine
from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.services.umpire_engine import UmpireEngine, UmpireConfig
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player
from tournament_platform.app.utils import format_player_label


# ============================================================================
# Player Selection Helpers
# ============================================================================

@st.cache_data(ttl=30)
def get_all_players() -> List[Dict]:
    """Return all players as plain dicts for selectbox options."""
    db = SessionLocal()
    try:
        players = db.query(Player).order_by(Player.name).all()
        return [
            {"id": p.id, "name": p.name, "rating": p.rating}
            for p in players
        ]
    finally:
        db.close()


def find_player_by_name(players: List[Dict], name: str) -> Optional[Dict]:
    """Find a player by name (case-insensitive, partial match)."""
    name_lower = name.lower().strip()
    for player in players:
        if player["name"].lower() == name_lower:
            return player
    # Try partial match
    for player in players:
        if name_lower in player["name"].lower():
            return player
    return None


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
            p1 = db.query(Player).filter(Player.id == active_match.player1_id).first() if active_match.player1_id else None
            p2 = db.query(Player).filter(Player.id == active_match.player2_id).first() if active_match.player2_id else None
            context = {
                "player1": p1.name if p1 else "Unknown",
                "player2": p2.name if p2 else "Unknown",
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

# Player selection configuration
st.subheader("Player Selection")
st.caption("Select two different players for the match. The system will validate against the database.")

# Get all players from database
all_players = get_all_players()
player_options = {format_player_label(p['name'], p['rating']): p for p in all_players}
player_names = list(player_options.keys())

# Initialize session state for player selection
if 'selected_player_a' not in st.session_state:
    st.session_state.selected_player_a = None
if 'selected_player_b' not in st.session_state:
    st.session_state.selected_player_b = None

col1, col2 = st.columns(2)

with col1:
    # Get current player A name to find index
    current_player_a = st.session_state.match_manager.state.player_a
    current_player_a_id = st.session_state.match_manager.state.player_a_id
    
    # Find the index of the currently selected player
    player_a_index = 0
    if current_player_a_id and current_player_a_id in [p['id'] for p in all_players]:
        for i, (label, p) in enumerate(player_options.items()):
            if p['id'] == current_player_a_id:
                player_a_index = i
                break
    
    selected_player_a_label = st.selectbox(
        "Player A",
        options=["-- Select Player --"] + player_names,
        index=player_a_index + 1 if player_a_index > 0 else 0,
        key="player_a_select",
        help="Select the first player from the database"
    )
    
    if selected_player_a_label != "-- Select Player --":
        st.session_state.selected_player_a = player_options[selected_player_a_label]

with col2:
    # Get current player B name to find index
    current_player_b = st.session_state.match_manager.state.player_b
    current_player_b_id = st.session_state.match_manager.state.player_b_id
    
    # Find the index of the currently selected player
    player_b_index = 0
    if current_player_b_id and current_player_b_id in [p['id'] for p in all_players]:
        for i, (label, p) in enumerate(player_options.items()):
            if p['id'] == current_player_b_id:
                player_b_index = i
                break
    
    selected_player_b_label = st.selectbox(
        "Player B",
        options=["-- Select Player --"] + player_names,
        index=player_b_index + 1 if player_b_index > 0 else 0,
        key="player_b_select",
        help="Select the second player from the database"
    )
    
    if selected_player_b_label != "-- Select Player --":
        st.session_state.selected_player_b = player_options[selected_player_b_label]

# Validate and update player selection
if st.session_state.selected_player_a and st.session_state.selected_player_b:
    # Check for duplicate selection
    if st.session_state.selected_player_a['id'] == st.session_state.selected_player_b['id']:
        st.error("❌ Cannot select the same player for both sides. Please choose two different players.")
    else:
        # Update MatchManager with selected players
        if (st.session_state.match_manager.state.player_a_id != st.session_state.selected_player_a['id'] or
            st.session_state.match_manager.state.player_b_id != st.session_state.selected_player_b['id']):
            st.session_state.match_manager.set_player_names(
                st.session_state.selected_player_a['name'],
                st.session_state.selected_player_b['name'],
                st.session_state.selected_player_a['id'],
                st.session_state.selected_player_b['id']
            )
            st.rerun()
elif st.session_state.selected_player_a or st.session_state.selected_player_b:
    st.info("Select both players to start the match.")

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