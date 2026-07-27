"""
Phase 2/4: Side-effect drain fragment for deferred commentary/TTS/DB operations.
This fragment runs independently to process queued side effects without blocking score updates.
"""

import time
import logging
from typing import Optional

import streamlit as st

from tournament_platform.services.settings import VOICE_LOW_LATENCY_EXPERIMENTAL, VOICE_DEBUG_EVENTS
from tournament_platform.app.services.latency_trace import record_latency, latency_stats
from tournament_platform.app.services.side_effects import SideEffectQueue


def _drain_side_effects_fragment() -> None:
    """
    Streamlit fragment that drains and processes queued side effects.
    
    In low-latency mode, called periodically via st.fragment(run_every=0.5) to process
    commentary, TTS, and DB snapshots without blocking the main scoring path.
    """
    if not VOICE_LOW_LATENCY_EXPERIMENTAL:
        return
    
    # Get the side-effect queue from session state
    if "side_effect_queue" not in st.session_state:
        st.session_state.side_effect_queue = SideEffectQueue()
    
    queue: SideEffectQueue = st.session_state.side_effect_queue
    events = queue.drain()
    
    if not events:
        return
    
    for event in events:
        _process_side_effect_event(event)


def _process_side_effect_event(event) -> None:
    """Process a single side effect event (commentary, TTS, DB).
    
    Uses the actual session state match_manager for live processing,
    falling back gracefully if not available.
    """
    # Import inside the function to avoid circular imports at module load
    from tournament_platform.app.pages.voice_scorekeeper import (
        persist_live_match_snapshot,
        _build_and_store_commentary,
    )
    
    # Get current match manager from session state
    mm = st.session_state.get("match_manager")
    if mm is None:
        return
    
    # Process based on action type
    if event.action_type in ("point_a", "point_b"):
        # Deferred commentary
        if event.commentary_settings.get("enabled"):
            _build_and_store_commentary(
                f"point_{event.action_type[-1].lower()}",
                mm.state,
                None,  # previous_state not stored in Phase 2
            )
    
    # DB snapshot (minimal, already done in callback but this is for async path)
    match_id = event.match_id
    if match_id:
        try:
            persist_live_match_snapshot(match_id, mm.engine)
        except Exception as e:
            if VOICE_DEBUG_EVENTS:
                st.warning(f"DB snapshot failed: {e}")


def render_latency_diagnostics() -> None:
    """Render latency diagnostics in a collapsible expander."""
    if not VOICE_DEBUG_EVENTS:
        return
    
    with st.expander("⏱️ Latency Diagnostics", expanded=False):
        stats = latency_stats()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Events recorded", stats["count"])
        with col2:
            st.metric("p50 latency", f"{stats['p50_ms']:.1f} ms")
        with col3:
            st.metric("p95 latency", f"{stats['p95_ms']:.1f} ms")
        
        stats_max = latency_stats(stage="score_apply")
        if stats_max["count"] > 0:
            st.caption(f"Score apply max: {stats_max['max_ms']:.1f} ms")
        
        if st.session_state.get("side_effect_queue"):
            q: SideEffectQueue = st.session_state["side_effect_queue"]
            st.caption(f"Pending side effects: {q.pending_count}")


# Initialize the side-effect queue in session state
def init_side_effect_queue() -> None:
    """Initialize side-effect queue in session state if not present."""
    if "side_effect_queue" not in st.session_state:
        st.session_state.side_effect_queue = SideEffectQueue()
    if "voice_session_epoch" not in st.session_state:
        st.session_state.voice_session_epoch = "1"