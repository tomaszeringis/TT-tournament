"""
Phase 2 helper: Manual scoring with optional side-effect deferring.
This provides the infrastructure for low-latency mode without breaking existing behavior.
"""

import time
import copy
import logging
from typing import Optional, Tuple, Any, Dict

from tournament_platform.services.settings import (
    VOICE_LOW_LATENCY_EXPERIMENTAL,
    VOICE_LATENCY_TRACE,
)
from tournament_platform.app.services.latency_trace import record_latency
from tournament_platform.app.services.side_effects import SideEffectQueue

logger = logging.getLogger(__name__)


def _apply_manual_score_with_tracing(
    mm,
    player: str,
    match_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Apply manual score change with optional latency tracing and side-effect queuing.
    
    In normal mode: behaves like the current inline handlers (score + commentary + TTS + DB).
    In low-latency mode: score mutation only, side effects queued for fragment drain.
    
    Returns (success, message).
    """
    trace_id = str(time.time_ns())
    action = f"manual_point_{player}"
    
    started_ns = time.perf_counter_ns()
    
    # 1. Capture state before
    state_before = {
        "score_a": mm.state.score_a,
        "score_b": mm.state.score_b,
        "games_won_a": mm.state.sets_a,
        "games_won_b": mm.state.sets_b,
    }
    
    # 2. Apply score
    success, msg = mm._add_point(player)
    
    # 3. Record latency
    if VOICE_LATENCY_TRACE:
        record_latency(
            trace_id=trace_id,
            action_id=action,
            match_id=match_id,
            source="manual",
            stage="score_apply",
            started_ns=started_ns,
            finished_ns=time.perf_counter_ns(),
            success=success,
        )
    
    return success, msg


def _get_side_effect_queue():
    """Get or create the side-effect queue in session state."""
    import streamlit as st
    if "side_effect_queue" not in st.session_state:
        st.session_state.side_effect_queue = SideEffectQueue()
    return st.session_state.side_effect_queue


def _queue_side_effect(
    source: str,
    action_type: str,
    state_before: Dict,
    state_after: Dict,
    match_id: Optional[int] = None,
    match_epoch: Optional[str] = None,
) -> None:
    """
    Queue a side effect for deferred processing.
    Called in low-latency mode to defer commentary/TTS/DB.
    """
    if not VOICE_LOW_LATENCY_EXPERIMENTAL:
        return
    
    import streamlit as st
    from tournament_platform.services.settings import CommentarySettings
    
    q = _get_side_effect_queue()
    settings = CommentarySettings(
        enabled=st.session_state.get("commentary_enabled", False),
        style=st.session_state.get("commentary_style", "neutral"),
        verbosity=st.session_state.get("commentary_verbosity", "standard"),
        voice=st.session_state.get("commentary_voice", "default"),
        language=st.session_state.get("commentary_language", "en"),
        muted=st.session_state.get("commentary_muted", False),
        mode=st.session_state.get("commentary_mode", "every_point"),
        intensity=st.session_state.get("commentary_intensity", "medium"),
        speak_generated=st.session_state.get("commentary_speak_generated", True),
        ollama_rewrite_enabled=st.session_state.get("commentary_ollama_rewrite_enabled", False),
        ollama_model=st.session_state.get("commentary_ollama_model", ""),
        ollama_timeout=st.session_state.get("commentary_ollama_timeout", 2.0),
        voice_profile_id=st.session_state.get("commentary_voice_profile", "browser_default"),
        rate=st.session_state.get("commentary_rate", 1.0),
        pitch=st.session_state.get("commentary_pitch", 1.0),
        volume=st.session_state.get("commentary_volume", 1.0),
    )
    
    q.enqueue(
        source=source,
        action_type=action_type,
        state_before=state_before,
        state_after=state_after,
        match_id=match_id,
        match_epoch=match_epoch or st.session_state.get("voice_session_epoch", "1"),
        commentary_settings={
            "enabled": settings.enabled,
            "style": settings.style.value if hasattr(settings.style, 'value') else settings.style,
            "language": settings.language,
            "mode": settings.mode.value if hasattr(settings.mode, 'value') else settings.mode,
        },
    )