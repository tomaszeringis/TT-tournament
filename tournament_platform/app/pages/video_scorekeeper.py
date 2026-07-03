"""
Video Scorekeeper - AI-assisted video score suggestions with confirmation.

A human-in-the-loop score assistant that:
- Analyzes video input for table tennis matches
- Suggests point winners with confidence and evidence
- Requires explicit human confirmation before updating scores
"""

import streamlit as st
import tempfile
import os
from typing import Optional, List, Dict

from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament
from tournament_platform.app.utils import format_player_label, api_request, format_match_option
from tournament_platform.services.video_scorekeeper import (
    analyze_video_clip,
    suggest_point_winner,
    apply_confirmed_point,
    CalibrationConfig,
    VideoScoreSuggestion,
    SuggestedWinner,
)

# Import live camera component (gracefully handles missing dependencies)
try:
    from tournament_platform.app.pages.video_scorekeeper_live import render_live_camera
    LIVE_CAMERA_AVAILABLE = True
except ImportError:
    LIVE_CAMERA_AVAILABLE = False


# ============================================================================
# Session State Initialization
# ============================================================================

# Initialize MatchManager in session state
if 'match_manager' not in st.session_state:
    st.session_state.match_manager = MatchManager()

# Video scorekeeper state
if 'video_selected_tournament_id' not in st.session_state:
    st.session_state.video_selected_tournament_id = None
if 'video_selected_match_id' not in st.session_state:
    st.session_state.video_selected_match_id = None
if 'video_selected_player1_id' not in st.session_state:
    st.session_state.video_selected_player1_id = None
if 'video_selected_player1_name' not in st.session_state:
    st.session_state.video_selected_player1_name = None
if 'video_selected_player2_id' not in st.session_state:
    st.session_state.video_selected_player2_id = None
if 'video_selected_player2_name' not in st.session_state:
    st.session_state.video_selected_player2_name = None
if 'video_match_options' not in st.session_state:
    st.session_state.video_match_options = []
if 'video_suggestion' not in st.session_state:
    st.session_state.video_suggestion = None
if 'video_calibration' not in st.session_state:
    st.session_state.video_calibration = None
if 'opencv_available' not in st.session_state:
    st.session_state.opencv_available = False


# Shared match selector component
from tournament_platform.app.components.match_selector import (
    render_active_match_selector as _render_active_match_selector,
    render_selected_match_summary as _render_selected_match_summary,
    apply_selected_match_to_session as _apply_selected_match_to_session,
    clear_selected_match as _clear_selected_match,
)


def render_active_match_selector() -> None:
    _render_active_match_selector(prefix="video")


def apply_selected_match_to_session(match: Dict) -> None:
    _apply_selected_match_to_session(prefix="video", match=match)


def clear_selected_match() -> None:
    _clear_selected_match(prefix="video")


def render_selected_match_summary() -> None:
    _render_selected_match_summary(prefix="video")

def check_opencv_availability() -> bool:
    """Check if OpenCV is available."""
    try:
        import cv2
        return True
    except ImportError:
        return False


def render_calibration_ui() -> None:
    """Render calibration configuration UI."""
    st.subheader("📐 Table Calibration")
    st.caption("Configure table geometry for accurate point detection. Optional for basic use.")
    
    with st.expander("Calibration Settings", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            player_a_side = st.selectbox(
                "Player A Side",
                options=["top", "bottom"],
                index=0,
                key="calibration_player_a_side",
                help="Which side of the table is Player A on?"
            )
        
        with col2:
            player_b_side = st.selectbox(
                "Player B Side",
                options=["top", "bottom"],
                index=1,
                key="calibration_player_b_side",
                help="Which side of the table is Player B on?"
            )
        
        net_line_y = st.slider(
            "Net Line Y Position",
            min_value=0,
            max_value=480,
            value=240,
            key="calibration_net_line_y",
            help="Y-coordinate of the net line (default: middle of frame)"
        )
        
        if st.button("Save Calibration", key="save_calibration"):
            st.session_state.video_calibration = CalibrationConfig(
                player_a_side=player_a_side,
                player_b_side=player_b_side,
                net_line_y=float(net_line_y),
            )
            st.success("Calibration saved!")


def render_video_upload() -> None:
    """Render video upload UI."""
    st.subheader("📹 Video Analysis")
    st.caption("Upload a match/rally clip for AI point suggestion.")
    
    # Check OpenCV availability
    if not st.session_state.opencv_available:
        st.session_state.opencv_available = check_opencv_availability()
    
    if not st.session_state.opencv_available:
        st.warning("⚠️ OpenCV not installed. Video analysis is unavailable. Install with: `pip install opencv-python`")
        st.info("You can still use manual scoring below.")
    
    # Video file uploader
    uploaded_video = st.file_uploader(
        "Upload video clip",
        type=["mp4", "avi", "mov", "webm"],
        key="video_upload",
        help="Upload a short rally clip (max 30 seconds recommended)"
    )
    
    if uploaded_video is not None:
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(uploaded_video.read())
            temp_path = f.name
        
        try:
            # Show video preview
            st.video(temp_path)
            
            # Analyze button
            if st.button("🔍 Analyze Video", key="analyze_video_btn"):
                with st.spinner("Analyzing video..."):
                    # Phase 1: Placeholder - will be implemented in Phase 2
                    analysis = analyze_video_clip(temp_path, st.session_state.video_calibration)
                    suggestion = suggest_point_winner(analysis)
                    st.session_state.video_suggestion = suggestion
                    
                    if suggestion.needs_review:
                        st.warning("⚠️ Low confidence - please review the suggestion")
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def render_suggestion_ui() -> None:
    """Render the suggestion display UI."""
    st.subheader("💡 Point Suggestion")
    
    suggestion: Optional[VideoScoreSuggestion] = st.session_state.video_suggestion
    
    if suggestion is None:
        st.info("Upload a video and click 'Analyze Video' to get a point suggestion.")
        return
    
    # Display suggestion
    col1, col2 = st.columns([1, 2])
    
    with col1:
        if suggestion.suggested_winner == SuggestedWinner.PLAYER_A:
            st.success(f"### Point to Player A")
        elif suggestion.suggested_winner == SuggestedWinner.PLAYER_B:
            st.success(f"### Point to Player B")
        else:
            st.warning(f"### Unable to determine point winner")
        
        st.progress(suggestion.confidence)
        st.caption(f"Confidence: {suggestion.confidence:.1%}")
    
    with col2:
        st.markdown(f"**Reason:** {suggestion.reason}")
        
        if suggestion.detected_events:
            st.markdown("**Detected Events:**")
            for event in suggestion.detected_events[:5]:  # Show first 5
                st.caption(f"- {event.event_type} at {event.timestamp:.2f}s")
    
    if suggestion.needs_review:
        st.warning("⚠️ This suggestion needs review. Please verify before confirming.")


def render_score_controls() -> None:
    """Render score confirmation controls."""
    st.subheader("✅ Confirm or Override")
    
    suggestion: Optional[VideoScoreSuggestion] = st.session_state.video_suggestion
    
    if suggestion is None:
        return
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("✅ Confirm", key="confirm_suggestion", type="primary", use_container_width=True):
            try:
                apply_confirmed_point(
                    st.session_state.match_manager,
                    suggestion
                )
                st.session_state.video_suggestion = None
                st.success("Point confirmed! Score updated.")
                st.rerun()
            except Exception as e:
                st.error(f"Error confirming point: {e}")
    
    with col2:
        if st.button("❌ Reject", key="reject_suggestion", use_container_width=True):
            st.session_state.video_suggestion = None
            st.info("Suggestion rejected.")
            st.rerun()
    
    with col3:
        # Override dropdown
        override_winner = st.selectbox(
            "Override",
            options=["-- Select --", "Player A", "Player B"],
            key="override_winner",
            label_visibility="collapsed"
        )
        if override_winner != "-- Select --" and st.button("Override", key="override_btn"):
            try:
                apply_confirmed_point(
                    st.session_state.match_manager,
                    suggestion,
                    winner_override="player_a" if override_winner == "Player A" else "player_b"
                )
                st.session_state.video_suggestion = None
                st.success(f"Point overridden to {override_winner}!")
                st.rerun()
            except Exception as e:
                st.error(f"Error overriding point: {e}")


def render_current_score() -> None:
    """Render current score display."""
    st.subheader("📊 Current Score")
    
    state: MatchState = st.session_state.match_manager.state
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        st.markdown(f"### {state.player_a}")
        st.markdown(f"## {state.score_a}")
    
    with col2:
        st.markdown("### Set")
        st.markdown(f"## {state.current_set}")
    
    with col3:
        st.markdown(f"### {state.player_b}")
        st.markdown(f"## {state.score_b}")
    
    # Undo button
    if st.button("↩️ Undo Last Point", key="undo_point"):
        success, msg = st.session_state.match_manager.undo_last_point()
        if success:
            st.success(msg)
        else:
            st.warning(msg)
        st.rerun()


# ============================================================================
# Page UI
# ============================================================================

st.title("Video Scorekeeper")
st.caption("AI-assisted point suggestions with human confirmation. Upload a video to get started.")

# Active Tournament Match Selector
render_active_match_selector()
render_selected_match_summary()

st.divider()

# Calibration UI
render_calibration_ui()

st.divider()

# Video Upload
render_video_upload()

st.divider()

# Live Camera (Phase 4)
if LIVE_CAMERA_AVAILABLE:
    render_live_camera()
    st.divider()

# Suggestion Display
render_suggestion_ui()

# Score Controls
render_score_controls()

st.divider()

# Current Score
render_current_score()