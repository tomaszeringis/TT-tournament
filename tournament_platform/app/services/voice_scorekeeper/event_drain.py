"""Voice Event Orchestration (Phase 5)"""

from __future__ import annotations

import copy, logging, time
from typing import Any, Dict, Optional

import streamlit as st

from tournament_platform.services.settings import VOICE_ENABLE_CONFIRMATION

logger = logging.getLogger(__name__)

_VOICE_RERUN_KEY = "_voice_needs_rerun"
_VOICE_RERUN_REASON_KEY = "_voice_rerun_reason"

# === _on_quick_voice_mode_changed (739-752) ===
def _on_quick_voice_mode_changed(old_mode: str, new_mode: str) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import _increment_voice_session_epoch
    if old_mode == "quick" and new_mode != "quick":
        st.session_state.quick_voice_point_trail = []
        st.session_state.quick_voice_current_streak = 0
        st.session_state.quick_voice_max_streak_a = 0
        st.session_state.quick_voice_max_streak_b = 0
        st.session_state.quick_voice_biggest_lead = {"player": None, "margin": 0}
        st.session_state.quick_voice_last_player = None
        st.session_state.quick_voice_last_ts = 0.0
        st.session_state.quick_voice_last_phrase = ""
        st.session_state.quick_voice_last_status = "idle"
        _increment_voice_session_epoch()




# === _apply_quick_voice_point (753-774) ===
def _apply_quick_voice_point(player: str, transcript: str) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import (
        play_cue,
        _maybe_speak_tts,
        _build_and_store_commentary,
        finalize_current_audio_rally,
        _append_audio_commentary_line,
        _request_voice_rerun,
    )
    mm = st.session_state.match_manager
    prev_state = copy.deepcopy(mm.state)
    success, msg = mm._add_point(player)
    if success:
        st.session_state.quick_voice_last_player = player
        st.session_state.quick_voice_last_ts = time.time() * 1000.0
        st.session_state.quick_voice_last_phrase = transcript
        st.session_state.quick_voice_last_status = "accepted"
        st.session_state.last_feedback = msg
        st.toast(msg, icon="✅")
        play_cue("point")
        _maybe_speak_tts(msg, "increment")
        _build_and_store_commentary("point_a" if player == "A" else "point_b", mm.state, prev_state)
        if st.session_state.get("tt_sounds_enabled"):
            audio_summary = finalize_current_audio_rally(reason="point_scored")
            st.session_state["_pending_audio_summary_for_commentary"] = audio_summary
            if audio_summary and audio_summary.confidence >= 0.55:
                _append_audio_commentary_line(audio_summary)
        _request_voice_rerun("quick_voice_accepted")




# === _process_quick_voice_event (775-802) ===
def _process_quick_voice_event(transcript: str) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import QuickVoiceScoringEngine
    if st.session_state.get("quick_voice_mode") != "quick":
        return

    mm = st.session_state.match_manager
    engine = QuickVoiceScoringEngine()
    result = engine.process(
        transcript=transcript,
        current_score_a=mm.state.score_a,
        current_score_b=mm.state.score_b,
        current_game_index=len(mm.engine.round_scores),
    )

    if result["action"] == "accept":
        _apply_quick_voice_point(result["player"], transcript)
    elif result["action"] == "ignore":
        st.session_state.quick_voice_last_player = result.get("player")
        st.session_state.quick_voice_last_phrase = transcript
        st.session_state.quick_voice_last_status = result.get("reason", "duplicate_ignored")
    else:
        st.session_state.quick_voice_last_phrase = transcript
        st.session_state.quick_voice_last_status = "rejected"


# ============================================================================
# Continuous Listening Heartbeat
# ============================================================================



# === _maybe_voice_heartbeat (803-843) ===
def _maybe_voice_heartbeat() -> None:
    from tournament_platform.app.pages.voice_scorekeeper import is_voice_scoring_enabled
    """Trigger a lightweight rerun while continuous listening is active.
    
    This is the browser-driven heartbeat that ensures accepted voice commands
    from background audio callbacks become visible on the live scoreboard
    without requiring manual user interaction.
    
    Runs in the main Streamlit thread only. Uses adaptive timing:
    - Faster (250ms) when there are pending events to drain
    - Slower (1000ms) when idle to avoid unnecessary reruns
    
    Only active when voice scoring is enabled and continuous listening is on.
    """
    if not is_voice_scoring_enabled():
        return
    
    if not st.session_state.get("voice_listening"):
        return
    
    # Check if there are pending events from the WebRTC processor
    ctx = st.session_state.get("voice_webrtc_ctx")
    has_pending = False
    if ctx and ctx.get("processor"):
        processor = ctx["processor"]
        if hasattr(processor, 'has_pending_events'):
            has_pending = processor.has_pending_events()
    
    # Adaptive interval: faster when draining events, slower when idle
    interval = 0.25 if has_pending else 1.0
    
    # Only rerun if we haven't rerun recently (simple throttle)
    last_heartbeat = st.session_state.get("voice_last_heartbeat", 0.0)
    now = time.time()
    if now - last_heartbeat < interval:
        return
    
    st.session_state.voice_last_heartbeat = now
    time.sleep(0.1)  # Brief pause to avoid tight loop
    st.rerun()




# === _process_tt_sounds_events (952-963) ===
def _process_tt_sounds_events() -> None:
    """Drain audio events even when voice scoring is disabled."""
    if not st.session_state.get("tt_sounds_enabled"):
        return
    ctx = st.session_state.get("voice_webrtc_ctx")
    proc = ctx.get("tt_sounds_processor") if ctx else None
    if proc is None:
        return
    for event in proc.get_events():
        _handle_tt_sounds_event(event)




# === _handle_tt_sounds_event (964-985) ===
def _handle_tt_sounds_event(event: Any) -> None:
    """Process a single TTAudioEvent: update rally context and recent events."""
    from tournament_platform.app.services.tt_sounds import RallyManager
    
    if "tt_sounds_rally_manager" not in st.session_state:
        st.session_state.tt_sounds_rally_manager = RallyManager()
    
    manager = st.session_state.tt_sounds_rally_manager
    summary = manager.add_event(event)
    if summary is not None:
        st.session_state.tt_sounds_audio_summaries.append(summary)
    
    st.session_state.tt_sounds_rally_context = manager.current_context()
    
    recent = st.session_state.get("tt_sounds_recent_events", [])
    recent.append(event)
    if len(recent) > 200:
        st.session_state.tt_sounds_recent_events = recent[-200:]
    else:
        st.session_state.tt_sounds_recent_events = recent




# === _maybe_tt_sounds_heartbeat (986-1004) ===
def _maybe_tt_sounds_heartbeat() -> None:
    """Rerun UI to update debug panel and rally summary when audio events pending."""
    if not st.session_state.get("tt_sounds_enabled"):
        return
    ctx = st.session_state.get("voice_webrtc_ctx")
    proc = ctx.get("tt_sounds_processor") if ctx else None
    if proc is None:
        return
    has_pending = len(proc.get_events()) > 0
    interval = 0.5 if has_pending else 1.0
    now = time.time()
    last = st.session_state.get("tt_sounds_last_heartbeat", 0.0)
    if now - last < interval:
        return
    st.session_state.tt_sounds_last_heartbeat = now
    time.sleep(0.1)
    st.rerun()




# === _process_voice_transcript (1420-1519) ===
def _process_voice_transcript(
    transcript: str,
    source: str = "debug",
    enable_confirmation: bool = VOICE_ENABLE_CONFIRMATION,
    selected_match_id: Optional[int] = None,
) -> Dict[str, Any]:
    from tournament_platform.app.pages.voice_scorekeeper import (
        _append_voice_audit,
        apply_score_event_and_refresh_ui,
    )
    from tournament_platform.app.services.voice_parser import VoiceScoreEvent
    """Shared transcript processing for push-to-talk, continuous, and debug.

    Central voice command processor:
    1. Validate match context (voice_selected_match_id == active match).
    2. Normalize transcript.
    3. Parse with VoiceCommandGrammar.
    4. Route with CommandRouter.
    5. If APPLY, call MatchManager.apply_voice_event().
    6. Return structured result for UI display.

    Returns a dict with keys:
        success, reason, previous_score, new_score, parsed, route_result
    """
    mm = st.session_state.match_manager

    # Track source-specific transcript
    if source == "debug":
        st.session_state.last_voice_debug_transcript = transcript
    elif source == "push_to_talk":
        st.session_state.last_voice_push_to_talk_transcript = transcript
    elif source == "continuous":
        st.session_state.last_voice_continuous_transcript = transcript

    # Resolve selected match ID: prefer explicit arg, fall back to session state.
    if selected_match_id is None:
        selected_match_id = st.session_state.get("voice_selected_match_id")

    # Match-context validation: voice scoring requires an active match selection.
    if not selected_match_id:
        st.session_state.last_voice_feedback = "no_match_selected"
        st.session_state.last_voice_rejection_reason = "no_match_selected"
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "rejected"
        _append_voice_audit(
            VoiceScoreEvent(type="unknown", raw_text=transcript, confidence=0.0),
            source=source,
            accepted=False,
            previous_score=mm.state.get_score_string(),
            new_score=mm.state.get_score_string(),
            note="no_match_selected",
        )
        return {
            "success": False,
            "reason": "no_match_selected",
            "previous_score": mm.state.get_score_string(),
            "new_score": mm.state.get_score_string(),
            "parsed": None,
            "route_result": None,
        }

    # Match-context validation: ensure MatchManager players match the selected match.
    _selected_p1_id = st.session_state.get("voice_selected_player1_id")
    _selected_p2_id = st.session_state.get("voice_selected_player2_id")
    if _selected_p1_id is not None and _selected_p2_id is not None:
        if (
            mm.state.player_a_id != _selected_p1_id
            or mm.state.player_b_id != _selected_p2_id
        ):
            st.session_state.last_voice_feedback = "voice_match_context_mismatch"
            st.session_state.last_voice_rejection_reason = "voice_match_context_mismatch"
            st.session_state.last_voice_success_message = ""
            st.session_state.last_voice_action_taken = "rejected"
            _append_voice_audit(
                VoiceScoreEvent(type="unknown", raw_text=transcript, confidence=0.0),
                source=source,
                accepted=False,
                previous_score=mm.state.get_score_string(),
                new_score=mm.state.get_score_string(),
                note="voice_match_context_mismatch",
            )
            return {
                "success": False,
                "reason": "voice_match_context_mismatch",
                "previous_score": mm.state.get_score_string(),
                "new_score": mm.state.get_score_string(),
                "parsed": None,
                "route_result": None,
            }

    result = apply_score_event_and_refresh_ui(
        transcript=transcript,
        source=source,
        enable_confirmation=enable_confirmation,
    )
    return {
        "success": result.success,
        "reason": result.reason,
        "previous_score": result.previous_score,
        "new_score": result.new_score,
        "parsed": result.parsed,
        "route_result": result.route_result,
    }




# === _process_voice_events (2630-2762) ===
def _process_voice_events() -> None:
    from tournament_platform.app.pages.voice_scorekeeper import (
        _append_continuous_trace,
        _get_webrtc_playing_state,
        is_voice_scoring_enabled,
        _process_voice_transcript,
        _process_quick_voice_event,
    )
    """Process pending voice events from the WebRTC audio processor.

    Runs in the main Streamlit thread. Reads events from the processor's
    queue and delegates to the canonical ``apply_score_event_and_refresh_ui``.

    The continuous listening loop calls ``st.rerun()`` at the end to drain
    queued events promptly (streamlit-webrtc does not rerun on audio data).
    """
    if not st.session_state.get("voice_listening") or not st.session_state.get("voice_events_enabled"):
        return

    # Clear any one-shot rerun request from the previous run; the continuous
    # listening loop below will continue draining events and rerunning.
    st.session_state.pop(_VOICE_RERUN_KEY, None)
    st.session_state.pop(_VOICE_RERUN_REASON_KEY, None)

    ctx = st.session_state.get("voice_webrtc_ctx")
    if ctx is None:
        logger.debug("_process_voice_events: no webrtc ctx")
        return

    processor = ctx.get("processor")
    if processor is None:
        logger.debug("_process_voice_events: no processor in ctx")
        return

    events = processor.get_events()
    if not events:
        logger.debug("_process_voice_events: no events in queue")
        _append_continuous_trace("queue_empty", "no_pending_events")
        return

    _append_continuous_trace("continuous_event_consumed", f"{len(events)}_events")

    # If the match is already won, stop listening and disable voice updates.
    _engine = st.session_state.match_manager.engine
    if _engine.match_status == "match_won":
        st.session_state.voice_listening = False
        st.session_state.last_voice_feedback = "Match complete — voice listening stopped"
        if ctx and ctx.get("processor"):
            ctx["processor"].stop()
        _append_continuous_trace("continuous_stopped", "match_won")
        return

    logger.info("_process_voice_events: processing %d events", len(events))
    _append_continuous_trace("continuous_event_enqueued", f"{len(events)}_events")
    _current_session_id = st.session_state.get("voice_continuous_session_id")
    _session_start = st.session_state.get("voice_continuous_session_start", 0.0)
    _applied_ids = st.session_state.get("last_applied_voice_event_ids", [])
    _webrtc_playing = _get_webrtc_playing_state()
    for raw_text, text, event in events:
        if st.session_state.get("quick_voice_mode") == "quick":
            _process_quick_voice_event(text)
        else:
            _event_id = getattr(event, 'event_id', '')
            _event_ts = getattr(event, 'timestamp', 0.0)
            _event_session_id = getattr(event, 'session_id', None)
            _stale_reason = None

            if _event_session_id and _current_session_id and _event_session_id != _current_session_id:
                _stale_reason = "stale_event_old_session"
            elif _event_ts < _session_start:
                _stale_reason = "stale_event_after_stop"
            elif _event_id in _applied_ids:
                _stale_reason = "duplicate_event"
            elif not _webrtc_playing and getattr(event, 'source', '') == "continuous":
                _stale_reason = "webrtc_not_playing"

            if _stale_reason:
                st.session_state.voice_stale_events_ignored = st.session_state.get("voice_stale_events_ignored", 0) + 1
                _append_continuous_trace("stale_event_ignored", f"{_stale_reason}:{_event_id[:8]}")
                logger.debug("Ignoring stale continuous event: %s (id=%s)", _stale_reason, _event_id[:8])
                continue

            _current_score_a = st.session_state.match_manager.state.score_a
            _current_score_b = st.session_state.match_manager.state.score_b

            result = _process_voice_transcript(
                text,
                source="continuous",
                enable_confirmation=VOICE_ENABLE_CONFIRMATION,
            )

            if result.get("success") and _event_id:
                _applied_ids.append(_event_id)
                if len(_applied_ids) > 100:
                    _applied_ids = _applied_ids[-100:]
                st.session_state.last_applied_voice_event_ids = _applied_ids

            _append_continuous_trace(
                "continuous_event_processed",
                f"success={result.get('success')},reason={result.get('reason')}",
            )

            # Update structured fields (success/rejection separation)
            if not result.get("success") and result.get("reason"):
                st.session_state.last_voice_feedback = result.get("reason")
                st.session_state.last_voice_rejection_reason = result.get("reason")
                st.session_state.last_voice_success_message = ""
                st.session_state.last_voice_action_taken = "rejected"
            elif result.get("success"):
                st.session_state.last_voice_feedback = result.get("reason")
                st.session_state.last_voice_success_message = result.get("reason")
                st.session_state.last_voice_rejection_reason = ""
                _parsed = result.get("parsed")
                if _parsed and hasattr(_parsed, 'type'):
                    _etype = _parsed.type
                    if _etype == "increment":
                        st.session_state.last_voice_action_taken = "score_update_success"
                    elif _etype == "undo":
                        st.session_state.last_voice_action_taken = "undo_success"
                    elif _etype == "set_score":
                        st.session_state.last_voice_action_taken = "set_score_success"
                    else:
                        st.session_state.last_voice_action_taken = "applied"
                else:
                    st.session_state.last_voice_action_taken = "applied"

            # Log result for observability
            logger.debug(
                "Voice event processed: transcript='%s', success=%s, reason='%s', "
                "prev='%s' -> new='%s'",
                text, result.get("success"), result.get("reason"),
                result.get("previous_score"), result.get("new_score"),
            )

    # Note: We do NOT call st.rerun() here anymore. The heartbeat at the end
    # of the page handles rerunning while continuous listening is active.
    # This avoids conflicting rerun calls from both the event processor and
    # the heartbeat.



