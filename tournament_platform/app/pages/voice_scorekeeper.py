"""
Voice-Activated Tournament Scorekeeper

A simple, privacy-focused scorekeeping system using:
- Streamlit's st.audio_input for voice capture
- faster-whisper for local transcription
- Keyword matching for intent parsing
- pyttsx3 for offline TTS feedback
- Game-by-game scoring workflow
"""

import streamlit as st
import asyncio
import tempfile
import hashlib
import os
import requests
import copy
import uuid
from typing import Any, Optional, Tuple, Dict, List

# Import the MatchManager and UmpireEngine
from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.services.umpire_engine import UmpireEngine, UmpireConfig
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament
from tournament_platform.app.utils import format_player_label, api_request
from tournament_platform.services.settings import KEEP_AUDIO_FILES
from tournament_platform.services.schemas import ActiveMatchResponse
# Import intent classifier for voice command classification
from tournament_platform.multimodal_ai.intent_classifier import IntentClassifier, IntentType, IntentResult
# Import coaching service for RAG-based feedback
from tournament_platform.services.coaching_service import CoachingService
# Import game-by-game scoring utilities
from tournament_platform.app.services.match_score import (
    parse_game_score,
    validate_game_score,
    summarize_match,
)
from tournament_platform.app.api_client import api_client
from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    SpokenScoreState,
)
from tournament_platform.app.components.spoken_commentary import speak_commentary


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

# Initialize IntentClassifier for voice command classification
if 'intent_classifier' not in st.session_state:
    st.session_state.intent_classifier = IntentClassifier(threshold=0.3)

# Initialize CoachingService for RAG-based feedback
if 'coaching_service' not in st.session_state:
    st.session_state.coaching_service = CoachingService()

# Initialize audio processing guard
if 'last_audio_hash' not in st.session_state:
    st.session_state.last_audio_hash = None

# Initialize feedback message
if 'last_feedback' not in st.session_state:
    st.session_state.last_feedback = None

# Real-time mode state
if 'realtime_mode' not in st.session_state:
    st.session_state.realtime_mode = False
if 'listening' not in st.session_state:
    st.session_state.listening = False
if 'audio_level' not in st.session_state:
    st.session_state.audio_level = 0.0

# Voice scorekeeper match selector state
if 'voice_selected_tournament_id' not in st.session_state:
    st.session_state.voice_selected_tournament_id = None
if 'voice_selected_match_id' not in st.session_state:
    st.session_state.voice_selected_match_id = None
if 'voice_selected_player1_id' not in st.session_state:
    st.session_state.voice_selected_player1_id = None
if 'voice_selected_player1_name' not in st.session_state:
    st.session_state.voice_selected_player1_name = None
if 'voice_selected_player2_id' not in st.session_state:
    st.session_state.voice_selected_player2_id = None
if 'voice_selected_player2_name' not in st.session_state:
    st.session_state.voice_selected_player2_name = None
if 'voice_match_options' not in st.session_state:
    st.session_state.voice_match_options = []
if 'voice_parsed_result' not in st.session_state:
    st.session_state.voice_parsed_result = None
if 'voice_score_input' not in st.session_state:
    st.session_state.voice_score_input = "0-0"

# ============================================================================
# Commentary Settings Initialization
# ============================================================================
if 'commentary_enabled' not in st.session_state:
    st.session_state.commentary_enabled = False
if 'commentary_style' not in st.session_state:
    st.session_state.commentary_style = CommentaryStyle.NEUTRAL.value
if 'commentary_verbosity' not in st.session_state:
    st.session_state.commentary_verbosity = CommentaryVerbosity.STANDARD.value
if 'commentary_voice' not in st.session_state:
    st.session_state.commentary_voice = "default"
if 'commentary_language' not in st.session_state:
    st.session_state.commentary_language = "en-US"
if 'commentary_muted' not in st.session_state:
    st.session_state.commentary_muted = False
if 'last_commentary_event_id' not in st.session_state:
    st.session_state.last_commentary_event_id = None
if 'pending_commentary' not in st.session_state:
    st.session_state.pending_commentary = None
if 'last_commentary_text' not in st.session_state:
    st.session_state.last_commentary_text = None


# ============================================================================
# Commentary Helpers
# ============================================================================

_commentary_service = CommentaryService()


def _get_commentary_settings() -> CommentarySettings:
    """Build CommentarySettings from current session state."""
    return CommentarySettings(
        enabled=st.session_state.get("commentary_enabled", False),
        style=CommentaryStyle(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
        verbosity=CommentaryVerbosity(st.session_state.get("commentary_verbosity", CommentaryVerbosity.STANDARD.value)),
        voice=st.session_state.get("commentary_voice", "default"),
        language=st.session_state.get("commentary_language", "en-US"),
        muted=st.session_state.get("commentary_muted", False),
    )


def _build_and_store_commentary(
    event_type: str,
    state: Any,
    previous_state: Optional[Any] = None,
) -> None:
    """
    Build a commentary line and store it in session_state.pending_commentary
    if it should be spoken (respects dedupe and settings).
    """
    event_id = str(uuid.uuid4())
    settings = _get_commentary_settings()

    spoken_state = SpokenScoreState.from_match_state(state)
    prev_spoken = SpokenScoreState.from_match_state(previous_state) if previous_state else None

    line = _commentary_service.build_score_commentary(
        event_type=event_type,
        state=spoken_state,
        settings=settings,
        event_id=event_id,
        previous_state=prev_spoken,
    )

    if _commentary_service.should_speak_commentary(
        last_event_id=st.session_state.get("last_commentary_event_id"),
        current_event_id=event_id,
        settings=settings,
    ):
        st.session_state.pending_commentary = line
        st.session_state.last_commentary_event_id = event_id
        st.session_state.last_commentary_text = line.text
    else:
        st.session_state.pending_commentary = None


def render_commentary_settings() -> None:
    """Render the commentary settings UI."""
    with st.expander("🔊 Spoken Commentary", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.commentary_enabled = st.toggle(
                "Enable commentary",
                value=st.session_state.commentary_enabled,
                help="Turn spoken commentary on or off.",
            )
            st.session_state.commentary_style = st.selectbox(
                "Voice style",
                options=[s.value for s in CommentaryStyle],
                index=[s.value for s in CommentaryStyle].index(st.session_state.commentary_style),
            )
        with col2:
            st.session_state.commentary_verbosity = st.selectbox(
                "Verbosity",
                options=[v.value for v in CommentaryVerbosity],
                index=[v.value for v in CommentaryVerbosity].index(st.session_state.commentary_verbosity),
            )
            st.session_state.commentary_voice = st.selectbox(
                "Voice",
                options=["default"],
                index=0,
            )

        col_mute, col_replay = st.columns(2)
        with col_mute:
            mute_label = "Unmute" if st.session_state.commentary_muted else "Mute"
            if st.button(mute_label, use_container_width=True):
                st.session_state.commentary_muted = not st.session_state.commentary_muted
                st.rerun()
        with col_replay:
            if st.button("🔊 Replay last", use_container_width=True):
                last_text = st.session_state.get("last_commentary_text")
                if last_text:
                    st.session_state.pending_commentary = CommentaryLine(
                        text=last_text,
                        event_type="replay",
                        priority=2,
                        should_speak=True,
                        dedupe_key=f"replay:{uuid.uuid4()}",
                        event_id=str(uuid.uuid4()),
                    )
                    st.rerun()


def render_pending_commentary() -> None:
    """Render the pending commentary line (speech + text preview) and clear it."""
    pending = st.session_state.get("pending_commentary")
    if not pending:
        return

    settings = _get_commentary_settings()
    if settings.enabled and not settings.muted and pending.should_speak:
        try:
            speak_commentary(
                text=pending.text,
                key=f"commentary_{pending.event_id}",
                voice=settings.voice,
                lang=settings.language,
            )
        except Exception as e:
            st.warning(f"Commentary unavailable: {e}")

    if pending.text:
        st.caption(f"🔊 {pending.text}")

    # Clear after rendering so it doesn't repeat on next rerun
    st.session_state.pending_commentary = None


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


def process_voice_command(audio_bytes: bytes) -> Tuple[str, str, IntentResult]:
    """
    Process voice input and return transcript, response, and intent classification.
    
    Args:
        audio_bytes: Raw audio bytes from st.audio_input
        
    Returns:
        Tuple of (transcript, response_text, intent_result)
    """
    # Save audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        temp_path = f.name
    
    try:
        # Transcribe using faster-whisper
        transcript = st.session_state.umpire_engine.transcribe_audio_file(temp_path)
        
        if not transcript:
            return "", "Sorry, I couldn't understand the audio.", IntentResult(
                intent_type=IntentType.UNKNOWN,
                confidence=0.0,
                raw_text=""
            )
        
        # Classify intent using IntentClassifier
        intent_result = st.session_state.intent_classifier.classify(transcript)
        
        # Process based on intent type
        if intent_result.intent_type == IntentType.SCORE_UPDATE:
            success, response = st.session_state.match_manager.update_score(transcript)
        elif intent_result.intent_type == IntentType.COACHING_QUERY:
            # Use CoachingService to generate RAG-based feedback
            stroke_type = intent_result.entities.get('stroke_type', 'general')
            try:
                feedback = st.session_state.coaching_service.generate_feedback(
                    session_id=0,  # No session ID for voice queries
                    transcript=transcript,
                    stroke_type=stroke_type
                )
                response = feedback.feedback_text
            except Exception as e:
                response = f"Coaching query received. Stroke type: {stroke_type}. (AI feedback unavailable: {e})"
        elif intent_result.intent_type == IntentType.SESSION_CONTROL:
            action = intent_result.entities.get('action', 'unknown')
            response = f"Session control: {action}"
        elif intent_result.intent_type == IntentType.PLAYER_INFO:
            response = f"Player info query: {intent_result.entities.get('player', 'unknown')}"
        else:
            # Default to score update for unknown intents (backward compatibility)
            success, response = st.session_state.match_manager.update_score(transcript)
        
        return transcript, response, intent_result
        
    finally:
        # Clean up temp file unless configured to keep for debugging
        if not KEEP_AUDIO_FILES and os.path.exists(temp_path):
            os.unlink(temp_path)


# ============================================================================
# Active Tournament Match Selector Helpers
# ============================================================================

@st.cache_data(ttl=60)
def fetch_active_tournaments() -> List[Dict]:
    """Return all tournaments as plain dicts for selectbox options."""
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).order_by(Tournament.name).all()
        return [
            {"id": t.id, "name": t.name, "type": t.tournament_type.value if t.tournament_type else None}
            for t in tournaments
        ]
    finally:
        db.close()


@st.cache_data(ttl=30)
def fetch_active_matches(tournament_id: int, statuses: Optional[List[str]] = None) -> List[Dict]:
    """Fetch scorable matches for a tournament via the API."""
    params = {"limit": 100}
    if statuses:
        params["statuses"] = ",".join(statuses)
    response = api_request(
        "get",
        f"/api/tournaments/{tournament_id}/matches/active",
        params=params,
        parse_json=True,
        error_context="fetching active matches",
    )
    if response and isinstance(response, dict):
        return response.get("matches", [])
    return []


def format_match_option(match: Dict) -> str:
    """Format a match dict into a human-readable label for the selector."""
    parts = []
    if match.get("round_number") is not None:
        parts.append(f"Round {match['round_number']}")
    if match.get("location"):
        parts.append(f"Table {match['location']}")
    p1 = match.get("player1_name") or "TBD"
    p2 = match.get("player2_name") or "TBD"
    parts.append(f"{p1} vs {p2}")
    status = match.get("status", "unknown")
    parts.append(status)
    if match.get("scheduled_time"):
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(match["scheduled_time"].replace("Z", "+00:00"))
            parts.append(dt.strftime("%H:%M"))
        except Exception:
            pass
    return " | ".join(parts)


def apply_selected_match_to_session(match: Dict) -> None:
    """Apply a selected match dict to session state."""
    st.session_state.voice_selected_match_id = match.get("match_id")
    st.session_state.voice_selected_player1_id = match.get("player1_id")
    st.session_state.voice_selected_player1_name = match.get("player1_name")
    st.session_state.voice_selected_player2_id = match.get("player2_id")
    st.session_state.voice_selected_player2_name = match.get("player2_name")
    # Also update the MatchManager state for live scoring
    if (st.session_state.match_manager.state.player_a_id != match.get("player1_id") or
        st.session_state.match_manager.state.player_b_id != match.get("player2_id")):
        st.session_state.match_manager.set_player_names(
            match.get("player1_name") or "Player A",
            match.get("player2_name") or "Player B",
            match.get("player1_id"),
            match.get("player2_id"),
        )


def clear_selected_match() -> None:
    """Clear the selected match from session state."""
    st.session_state.voice_selected_match_id = None
    st.session_state.voice_selected_player1_id = None
    st.session_state.voice_selected_player1_name = None
    st.session_state.voice_selected_player2_id = None
    st.session_state.voice_selected_player2_name = None
    st.session_state.voice_match_options = []
    st.session_state.voice_parsed_result = None
    st.session_state.voice_score_input = "0-0"


def render_active_match_selector() -> None:
    """Render the active tournament match selector UI."""
    st.subheader("🎯 Active Tournament Matches")
    st.caption("Select a match to prefill players and score the result.")

    tournaments = fetch_active_tournaments()
    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        return

    tournament_options = {t["name"]: t["id"] for t in tournaments}
    current_tournament_id = st.session_state.voice_selected_tournament_id

    # Find index for current selection
    selected_tournament_name = None
    for name, tid in tournament_options.items():
        if tid == current_tournament_id:
            selected_tournament_name = name
            break

    col_t, col_f, col_r = st.columns([2, 2, 1])
    with col_t:
        selected_tournament_name = st.selectbox(
            "Tournament",
            options=list(tournament_options.keys()),
            index=list(tournament_options.keys()).index(selected_tournament_name) if selected_tournament_name else 0,
            key="voice_tournament_select",
        )
    with col_f:
        status_filter = st.multiselect(
            "Status filter",
            options=["active", "pending"],
            default=["active", "pending"],
            key="voice_status_filter",
        )
    with col_r:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="voice_refresh_matches", use_container_width=True):
            fetch_active_matches.clear()
            fetch_active_tournaments.clear()
            st.rerun()

    tournament_id = tournament_options[selected_tournament_name]
    st.session_state.voice_selected_tournament_id = tournament_id

    matches = fetch_active_matches(tournament_id, statuses=status_filter)
    st.session_state.voice_match_options = matches

    if not matches:
        st.info("No active or pending matches found for this tournament.")
        return

    # Build options list, disabling incomplete matches
    match_labels = []
    match_disabled = []
    for m in matches:
        label = format_match_option(m)
        match_labels.append(label)
        match_disabled.append(m.get("incomplete", False))

    # Find current selection index
    current_match_id = st.session_state.voice_selected_match_id
    selected_index = 0
    for i, m in enumerate(matches):
        if m.get("match_id") == current_match_id:
            selected_index = i
            break

    selected_label = st.selectbox(
        "Select a match",
        options=match_labels,
        index=selected_index,
        key="voice_match_select",
        help="Incomplete matches (missing players) are disabled unless byes are supported.",
    )

    # Find the selected match dict
    selected_match = None
    for i, label in enumerate(match_labels):
        if label == selected_label:
            selected_match = matches[i]
            break

    if selected_match:
        if selected_match.get("incomplete"):
            st.warning("⚠️ This match is missing a player and cannot be scored yet.")
        else:
            apply_selected_match_to_session(selected_match)

    # Clear button
    if st.button("🗑️ Clear selected match", key="voice_clear_match"):
        clear_selected_match()
        st.rerun()


def render_selected_match_summary() -> None:
    """Render a compact summary of the currently selected match."""
    if not st.session_state.voice_selected_match_id:
        return
    p1 = st.session_state.voice_selected_player1_name or "TBD"
    p2 = st.session_state.voice_selected_player2_name or "TBD"
    st.info(f"**Selected Match:** {p1} vs {p2} (ID: {st.session_state.voice_selected_match_id})")


# ============================================================================
# Page UI
# ============================================================================

st.title("Voice Scorekeeper")
st.caption("Speak to update scores. The system uses local transcription - no data leaves your machine.")

# Commentary Settings
render_commentary_settings()

# Active Tournament Match Selector
render_active_match_selector()
render_selected_match_summary()

st.divider()

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

# If a match is selected, prefill players from the match
selected_match_p1_id = st.session_state.voice_selected_player1_id
selected_match_p2_id = st.session_state.voice_selected_player2_id
selected_match_p1_name = st.session_state.voice_selected_player1_name
selected_match_p2_name = st.session_state.voice_selected_player2_name

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
    # If a match is selected and player A is not yet set, prefill from match
    if selected_match_p1_id and not current_player_a_id:
        for i, (label, p) in enumerate(player_options.items()):
            if p['id'] == selected_match_p1_id:
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
    # If a match is selected and player B is not yet set, prefill from match
    if selected_match_p2_id and not current_player_b_id:
        for i, (label, p) in enumerate(player_options.items()):
            if p['id'] == selected_match_p2_id:
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
            prev_state = copy.deepcopy(st.session_state.match_manager.state)
            success, msg = st.session_state.match_manager._add_point("A")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            _build_and_store_commentary("point_a", st.session_state.match_manager.state, prev_state)
            st.rerun()
    with btn_col2:
        if st.button("➖", key="sub_point_a", use_container_width=True):
            # Quick undo for Player A
            if st.session_state.match_manager.state.match_history:
                last = st.session_state.match_manager.state.match_history[-1]
                if last.get("player") == "A":
                    prev_state = copy.deepcopy(st.session_state.match_manager.state)
                    st.session_state.match_manager.undo_last_point()
                    st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_a}"
                    st.toast(st.session_state.last_feedback, icon="↩️")
                    _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
            st.rerun()

with score_col2:
    st.markdown(f"### {st.session_state.match_manager.state.player_b}")
    st.markdown(f"<h1 style='text-align: center; color: #ff7f0e;'>{st.session_state.match_manager.state.score_b}</h1>",
                unsafe_allow_html=True)
    
    # Manual override buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("➕", key="add_point_b", use_container_width=True):
            prev_state = copy.deepcopy(st.session_state.match_manager.state)
            success, msg = st.session_state.match_manager._add_point("B")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            _build_and_store_commentary("point_b", st.session_state.match_manager.state, prev_state)
            st.rerun()
    with btn_col2:
        if st.button("➖", key="sub_point_b", use_container_width=True):
            # Quick undo for Player B
            if st.session_state.match_manager.state.match_history:
                last = st.session_state.match_manager.state.match_history[-1]
                if last.get("player") == "B":
                    prev_state = copy.deepcopy(st.session_state.match_manager.state)
                    st.session_state.match_manager.undo_last_point()
                    st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_b}"
                    st.toast(st.session_state.last_feedback, icon="↩️")
                    _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
            st.rerun()

# Undo button
st.divider()
if st.button("↩️ Undo Last Point", use_container_width=True):
    prev_state = copy.deepcopy(st.session_state.match_manager.state)
    success, msg = st.session_state.match_manager.undo_last_point()
    st.session_state.last_feedback = msg
    st.toast(msg, icon="↩️")
    _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
    st.rerun()

# Reset match button
if st.button("🔄 Reset Match", use_container_width=True):
    prev_state = copy.deepcopy(st.session_state.match_manager.state)
    success, msg = st.session_state.match_manager.reset_match()
    st.session_state.last_feedback = msg
    st.toast(msg, icon="🔄")
    _build_and_store_commentary("reset", st.session_state.match_manager.state, prev_state)
    st.rerun()

# ============================================================================
# Game-by-Game Scoring Section
# ============================================================================

# Initialize in-progress game scores in session state (keyed by match_id)
if 'in_progress_game_scores' not in st.session_state:
    st.session_state.in_progress_game_scores = {}

def get_in_progress_games(match_id: int) -> List[Tuple[int, int]]:
    """Get the list of in-progress game scores for a match."""
    return st.session_state.in_progress_game_scores.get(match_id, [])

def add_game_score(match_id: int, score1: int, score2: int) -> None:
    """Add a game score to the in-progress list for a match."""
    if match_id not in st.session_state.in_progress_game_scores:
        st.session_state.in_progress_game_scores[match_id] = []
    st.session_state.in_progress_game_scores[match_id].append((score1, score2))

def clear_in_progress_games(match_id: int) -> None:
    """Clear in-progress game scores for a match."""
    st.session_state.in_progress_game_scores.pop(match_id, None)

# Game-by-game scoring UI (only show if a match is selected)
if st.session_state.voice_selected_match_id:
    st.divider()
    st.subheader("🎮 Game-by-Game Scoring")
    st.caption("Enter each game score as it's completed. The system will track games and determine the match winner.")
    
    match_id = st.session_state.voice_selected_match_id
    p1_name = st.session_state.voice_selected_player1_name or "Player A"
    p2_name = st.session_state.voice_selected_player2_name or "Player B"
    
    # Display current game scores
    in_progress_games = get_in_progress_games(match_id)
    if in_progress_games:
        st.markdown("**Games played:**")
        for i, (s1, s2) in enumerate(in_progress_games, 1):
            winner = "P1" if s1 > s2 else "P2"
            st.markdown(f"  Game {i}: {s1}-{s2} ({winner} wins)")
        
        # Show match summary
        summary = summarize_match(in_progress_games)
        if summary["is_complete"]:
            winner_name = p1_name if summary["winner_side"] == 1 else p2_name
            st.success(f"🏆 Match complete! {winner_name} wins {summary['player1_games']}-{summary['player2_games']}")
    
    # Game entry form
    with st.form("game_score_form"):
        st.markdown("**Enter completed game score:**")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            game_score1 = st.number_input(
                f"{p1_name} score",
                min_value=0,
                max_value=21,
                value=11,
                key="game_score1_input"
            )
        with col_g2:
            game_score2 = st.number_input(
                f"{p2_name} score",
                min_value=0,
                max_value=21,
                value=0,
                key="game_score2_input"
            )
        
        add_game_btn = st.form_submit_button("➕ Add Game", use_container_width=True)
        
        if add_game_btn:
            # Validate the game score
            if not validate_game_score(game_score1, game_score2):
                st.error("❌ Invalid game score. Winner must have ≥11 points and a 2-point lead.")
            else:
                add_game_score(match_id, game_score1, game_score2)
                st.toast(f"Game added: {game_score1}-{game_score2}", icon="✅")
                st.rerun()
    
    # Clear games button
    if in_progress_games:
        if st.button("🗑️ Clear All Games", key="clear_games_btn", use_container_width=True):
            clear_in_progress_games(match_id)
            st.toast("All games cleared", icon="↩️")
            st.rerun()
    
    # Submit match result button (only if match is complete)
    if in_progress_games:
        summary = summarize_match(in_progress_games)
        if summary["is_complete"]:
            if st.button("📤 Submit Match Result", key="submit_match_btn", use_container_width=True, type="primary"):
                winner_name = p1_name if summary["winner_side"] == 1 else p2_name
                score_str = summary["score_string"]
                
                with st.status("Submitting match result...", expanded=False) as status:
                    response = api_client.report_match_legacy(match_id, score_str, winner_name)
                    if response is not None:
                        clear_in_progress_games(match_id)
                        clear_selected_match()
                        status.update(label="Match result submitted!", state="complete", expanded=False)
                        st.success(f"✅ Match result submitted! {winner_name} wins {score_str}")
                        st.rerun()
                    else:
                        status.update(label="Submission failed", state="error", expanded=False)
                        st.error("❌ Failed to submit match result. Check API connection.")

# ============================================================================
# Voice Input Section
# ============================================================================

st.divider()
st.subheader("🎤 Voice Input")

# Real-time mode controls
col_mode1, col_mode2 = st.columns(2)
with col_mode1:
    if st.button("🎙️ Push to Talk", key="push_to_talk_btn", use_container_width=True, type="primary"):
        st.session_state.listening = True
        st.session_state.realtime_mode = False
with col_mode2:
    if st.button("🔴 Continuous Mode", key="continuous_mode_btn", use_container_width=True):
        st.session_state.realtime_mode = True
        st.session_state.listening = True

# Audio level indicator (for continuous mode)
if st.session_state.realtime_mode:
    st.progress(st.session_state.get('audio_level', 0.0), text="Audio Level")
    st.caption("Listening continuously... Speak clearly into your microphone.")

# Privacy notice
st.info(
    "🔒 **Privacy:** Audio is processed locally using faster-whisper. "
    "Temporary audio files are deleted by default after transcription. "
    "You must confirm the parsed result before it is submitted."
)

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
            transcript, response, intent_result = process_voice_command(audio_bytes)
            
            if transcript:
                st.session_state.last_feedback = response
                st.toast(response, icon="✅")
                speak_text(response)
                
                # Display intent classification info
                if intent_result:
                    intent_color = {
                        IntentType.SCORE_UPDATE: "🔵",
                        IntentType.COACHING_QUERY: "🟢",
                        IntentType.SESSION_CONTROL: "🟡",
                        IntentType.PLAYER_INFO: "🟣",
                        IntentType.UNKNOWN: "⚪"
                    }.get(intent_result.intent_type, "⚪")
                    
                    st.caption(f"{intent_color} Intent: {intent_result.intent_type.value} (confidence: {intent_result.confidence:.2f})")
                    if intent_result.entities:
                        st.caption(f"Entities: {intent_result.entities}")
                
                # Display coaching feedback in a structured way
                if intent_result and intent_result.intent_type == IntentType.COACHING_QUERY:
                    st.divider()
                    st.subheader("💡 Coaching Feedback")
                    st.markdown(f"**{response}**")
                
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

# Show selected match context if available
selected_match_id = st.session_state.voice_selected_match_id
selected_match_p1 = st.session_state.voice_selected_player1_name
selected_match_p2 = st.session_state.voice_selected_player2_name

if selected_match_id and selected_match_p1 and selected_match_p2:
    st.info(f"**Scoring for selected match:** {selected_match_p1} vs {selected_match_p2} (Match ID: {selected_match_id})")
    st.caption("Players are prefilled from the selected match. You can still edit names or swap the winner before submitting.")

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
                # Cleanup temp file unless configured to keep for debugging
                if not KEEP_AUDIO_FILES and os.path.exists(audio_path):
                    os.remove(audio_path)
                elif KEEP_AUDIO_FILES and os.path.exists(audio_path):
                    st.caption(f"🔧 Debug: audio saved to `{audio_path}` (KEEP_AUDIO_FILES=true)")
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
                    parse_payload = {"text": st.session_state.report_transcript}
                    # Include match context if a match is selected
                    if selected_match_id:
                        parse_payload["match_id"] = selected_match_id
                        parse_payload["tournament_id"] = st.session_state.voice_selected_tournament_id
                    response = api_request(
                        "post",
                        "/api/match/parse",
                        json=parse_payload,
                        error_context="match result parsing"
                    )
                    if response:
                        st.session_state.report_parsed = response
                        st.session_state.report_status = response.get("status", "unknown")
                        # Check for name mismatch with selected match
                        if selected_match_p1 and selected_match_p2:
                            parsed_p1 = response.get("player1")
                            parsed_p2 = response.get("player2")
                            if parsed_p1 and parsed_p2:
                                if (parsed_p1.lower() != selected_match_p1.lower() or
                                    parsed_p2.lower() != selected_match_p2.lower()):
                                    st.warning(
                                        f"⚠️ Transcript names do not match the selected match. "
                                        f"Selected: {selected_match_p1} vs {selected_match_p2}. "
                                        f"Parsed: {parsed_p1} vs {parsed_p2}. Please review before submitting."
                                    )
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

    # Review card - show selected match context prominently
    with st.container(border=True):
        if selected_match_id:
            st.markdown(f"**Match ID:** {selected_match_id}")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            display_p1 = parsed.get('player1') or selected_match_p1 or 'Not detected'
            st.markdown(f"**Player 1:** {display_p1}")
        with col_p2:
            display_p2 = parsed.get('player2') or selected_match_p2 or 'Not detected'
            st.markdown(f"**Player 2:** {display_p2}")
        st.markdown(f"**Score:** {parsed.get('score') or 'Not detected'}")
        st.markdown(f"**Winner:** {parsed.get('winner') or 'Not detected'}")
        st.caption(f"Confidence: {parsed.get('confidence', 0):.0%}")

    # Step 3: Confirm and submit
    st.markdown("**Step 3: Confirm and Submit**")
    st.caption("Verify the details below and submit to record the match result.")

    with st.form("voice_match_report_form"):
        # Prefill from selected match or parsed result
        default_p1 = selected_match_p1 or parsed.get("player1") or ""
        default_p2 = selected_match_p2 or parsed.get("player2") or ""

        # Swap winner buttons (outside form logic, using session state)
        if selected_match_p1 and selected_match_p2:
            swap_col1, swap_col2, swap_col3 = st.columns([1, 1, 2])
            with swap_col1:
                if st.button("🔄 Swap → P1 Wins", key="swap_winner_p1", use_container_width=True):
                    st.session_state.voice_swap_winner = selected_match_p1
                    st.rerun()
            with swap_col2:
                if st.button("🔄 Swap → P2 Wins", key="swap_winner_p2", use_container_width=True):
                    st.session_state.voice_swap_winner = selected_match_p2
                    st.rerun()
            with swap_col3:
                if st.button("↩️ Reset Swap", key="reset_swap", use_container_width=True):
                    if "voice_swap_winner" in st.session_state:
                        del st.session_state.voice_swap_winner
                    st.rerun()

        # Determine winner from swap if set
        swap_winner = st.session_state.get("voice_swap_winner")

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            p1 = st.text_input("Player 1", value=default_p1)
        with col_p2:
            p2 = st.text_input("Player 2", value=default_p2)

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

        # Winner selection - prefer selected match players and swap
        if p1 and p2:
            winner_options = ["Select winner", p1, p2]
            winner_index = 0
            # Prioritize swap winner if set
            if swap_winner and swap_winner in winner_options:
                winner_index = winner_options.index(swap_winner)
            else:
                parsed_winner = parsed.get("winner")
                if parsed_winner in winner_options:
                    winner_index = winner_options.index(parsed_winner)
            winner = st.selectbox("Winner", winner_options, index=winner_index)
        else:
            winner = "Select winner"
            st.warning("Enter both player names to select a winner.")

        score = f"{s1}-{s2}"

        # Tournament selection - prefill from selected match tournament if available
        db = SessionLocal()
        try:
            tournaments = db.query(Tournament).all()
            tournament_options = {t.name: t.id for t in tournaments}
            default_tournament_idx = 0
            if st.session_state.voice_selected_tournament_id:
                for i, (name, tid) in enumerate(tournament_options.items()):
                    if tid == st.session_state.voice_selected_tournament_id:
                        default_tournament_idx = i + 1  # +1 for "None" option
                        break
            selected_tournament = st.selectbox(
                "Tournament (optional)",
                options=["None"] + list(tournament_options.keys()),
                index=default_tournament_idx,
            )
        finally:
            db.close()

        # Validation
        if p1 and p2 and winner != "Select winner":
            if winner != p1 and winner != p2:
                st.warning("⚠️ Winner must be one of the players")

        # Check if selected match is already completed
        match_completed = False
        if selected_match_id:
            db_check = SessionLocal()
            try:
                match_check = db_check.query(Match).filter(Match.id == selected_match_id).first()
                if match_check and match_check.status == MatchStatus.completed:
                    match_completed = True
            finally:
                db_check.close()

        if match_completed:
            st.error("❌ This match has already been completed. Please refresh the match list and select an active match.")
            submitted = st.form_submit_button("📤 Submit Result", use_container_width=True, disabled=True)
        else:
            submitted = st.form_submit_button("📤 Submit Result", use_container_width=True)

        if submitted:
            if not p1 or not p2:
                st.error("Please provide both player names")
            elif winner == "Select winner":
                st.error("Please select a winner")
            elif winner != p1 and winner != p2:
                st.error("Winner must be one of the players")
            elif match_completed:
                st.error("Cannot submit: match is already completed")
            else:
                try:
                    payload = {
                        "score": score,
                        "winner": winner,
                    }
                    # Include match_id when available (preferred)
                    if selected_match_id:
                        payload["match_id"] = selected_match_id
                    else:
                        # Fallback to player names for backward compatibility
                        payload["player1"] = p1
                        payload["player2"] = p2
                    # Include tournament_id if selected
                    tournament_id_val = tournament_options.get(selected_tournament) if selected_tournament != "None" else None
                    if tournament_id_val:
                        payload["tournament_id"] = tournament_id_val

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
                            # Clear selected match after successful submission
                            if selected_match_id:
                                clear_selected_match()
                            status.update(label="Result submitted!", state="complete", expanded=False)
                            st.success("✅ Match result submitted successfully!")
                            _build_and_store_commentary("match_submitted", st.session_state.match_manager.state)
                            st.rerun()
                except Exception as e:
                    st.error(f"Connection error: {e}")

# Display last feedback
if st.session_state.last_feedback:
    st.info(f"Last action: {st.session_state.last_feedback}")

# Render pending commentary (speech + text preview)
render_pending_commentary()

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