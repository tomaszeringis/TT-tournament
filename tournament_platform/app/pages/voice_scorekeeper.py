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
import requests
from typing import Optional, Tuple, Dict, List

# Import the MatchManager and UmpireEngine
from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.services.umpire_engine import UmpireEngine, UmpireConfig
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament
from tournament_platform.app.utils import format_player_label, api_request


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

# ============================================================================
# Match Reporting UI
# ============================================================================

st.divider()
st.subheader("📤 Report Match Result")

# Initialize session state for match reporting
if 'report_transcript' not in st.session_state:
    st.session_state.report_transcript = ""
if 'report_parsed' not in st.session_state:
    st.session_state.report_parsed = None
if 'report_status' not in st.session_state:
    st.session_state.report_status = None

# Step 1: Input transcript
st.markdown("**Step 1: Enter or record match result**")
col_report_input, col_report_text = st.columns([1, 2])

with col_report_input:
    if st.button("🎙️ Record Result", key="record_result_btn", use_container_width=True):
        st.session_state.report_transcript = ""
        st.session_state.report_parsed = None
        st.session_state.report_status = None
        with st.status("Recording...", expanded=True) as status:
            try:
                audio_path = asyncio.run(record_audio())
                status.update(label="Recording complete", state="complete", expanded=False)
                with st.status("Transcribing...", expanded=True) as trans_status:
                    reporter = get_speech_reporter()
                    transcript = reporter.transcribe_audio(audio_path)
                    st.session_state.report_transcript = transcript
                    trans_status.update(label="Transcription complete", state="complete", expanded=False)
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception as e:
                st.session_state.report_status = f"Error: {e}"
                status.update(label="Error occurred", state="error", expanded=True)

with col_report_text:
    report_text = st.text_area(
        "Or type match result (e.g., 'Alice beat Bob 3-1')",
        value=st.session_state.report_transcript,
        key="report_text_input",
        height=80,
        help="Describe the match result in natural language"
    )

    if st.button("🔍 Parse Result", key="parse_result_btn", use_container_width=True):
        if report_text.strip():
            st.session_state.report_transcript = report_text.strip()
            st.session_state.report_parsed = None
            st.session_state.report_status = None
            with st.spinner("Parsing match result..."):
                try:
                    response = api_request(
                        "post",
                        "/api/match/parse",
                        json={"text": st.session_state.report_transcript},
                        error_context="match result parsing"
                    )
                    if response:
                        st.session_state.report_parsed = response
                        st.session_state.report_status = response.get("status", "unknown")
                except Exception as e:
                    st.session_state.report_status = f"Error: {e}"
        else:
            st.warning("Please enter a match result first.")

# Step 2: Review parsed result
if st.session_state.report_parsed:
    st.divider()
    st.markdown("**Step 2: Review Parsed Result**")
    parsed = st.session_state.report_parsed

    # Status badge
    status_color = {
        "success": "🟢",
        "needs_review": "🟡",
        "error": "🔴"
    }.get(st.session_state.report_status, "⚪")
    st.markdown(f"**Status:** {status_color} {st.session_state.report_status}")

    # Show warnings if any
    if parsed.get("warnings"):
        for warning in parsed["warnings"]:
            st.warning(f"⚠️ {warning}")

    # Review card
    with st.container(border=True):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(f"**Player 1:** {parsed.get('player1') or 'Not detected'}")
        with col_p2:
            st.markdown(f"**Player 2:** {parsed.get('player2') or 'Not detected'}")
        st.markdown(f"**Score:** {parsed.get('score') or 'Not detected'}")
        st.markdown(f"**Winner:** {parsed.get('winner') or 'Not detected'}")
        st.caption(f"Confidence: {parsed.get('confidence', 0):.0%}")

    # Step 3: Confirm and submit
    st.markdown("**Step 3: Confirm and Submit**")
    st.caption("Verify the details below and submit to record the match result.")

    with st.form("voice_match_report_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            p1 = st.text_input("Player 1", value=parsed.get("player1") or "")
        with col_p2:
            p2 = st.text_input("Player 2", value=parsed.get("player2") or "")

        # Parse score for number inputs
        score_val = parsed.get("score") or "0-0"
        try:
            s1_str, s2_str = score_val.split("-")
            s1 = int(s1_str)
            s2 = int(s2_str)
        except Exception:
            s1, s2 = 0, 0

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            s1 = st.number_input("Player 1 Score", min_value=0, max_value=10, value=s1)
        with col_s2:
            s2 = st.number_input("Player 2 Score", min_value=0, max_value=10, value=s2)

        # Winner selection
        winner_options = ["Select winner", p1, p2] if p1 and p2 else ["Select Players First"]
        winner_index = 0
        if parsed.get("winner") in winner_options:
            winner_index = winner_options.index(parsed["winner"])
        winner = st.selectbox("Winner", winner_options, index=winner_index)

        score = f"{s1}-{s2}"

        # Tournament selection
        db = SessionLocal()
        try:
            tournaments = db.query(Tournament).all()
            tournament_options = {t.name: t.id for t in tournaments}
            selected_tournament = st.selectbox(
                "Tournament (optional)",
                options=["None"] + list(tournament_options.keys())
            )
        finally:
            db.close()

        # Validation
        if p1 and p2 and winner != "Select winner":
            if winner != p1 and winner != p2:
                st.warning("⚠️ Winner must be one of the players")

        submitted = st.form_submit_button("📤 Submit Result", use_container_width=True)

        if submitted:
            if not p1 or not p2:
                st.error("Please provide both player names")
            elif winner == "Select winner":
                st.error("Please select a winner")
            elif winner != p1 and winner != p2:
                st.error("Winner must be one of the players")
            else:
                try:
                    payload = {
                        "player1": p1,
                        "player2": p2,
                        "score": score,
                        "winner": winner,
                        "tournament_id": tournament_options.get(selected_tournament) if selected_tournament != "None" else None
                    }
                    with st.status("Submitting result...", expanded=False) as status:
                        response = api_request(
                            "post",
                            "/api/report",
                            json=payload,
                            error_context="match result submission"
                        )
                        if response is not None:
                            st.session_state.report_transcript = ""
                            st.session_state.report_parsed = None
                            st.session_state.report_status = None
                            status.update(label="Result submitted!", state="complete", expanded=False)
                            st.success("✅ Match result submitted successfully!")
                            st.rerun()
                except Exception as e:
                    st.error(f"Connection error: {e}")

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
- "Alice beat Bob 3-1" - Report a match result

**Tips:**
- Speak clearly and at a normal pace
- The system works best in a quiet environment
- Use the +/− buttons for quick manual corrections
""")