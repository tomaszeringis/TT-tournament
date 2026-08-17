"""Voice Event Orchestration (Phase 5)"""

from __future__ import annotations

import copy, logging, time
from typing import Any, Dict, Optional, Set

import streamlit as st

from tournament_platform.services.settings import VOICE_ENABLE_CONFIRMATION
from tournament_platform.app.services.voice_scorekeeper.events import (
    InvalidVoiceTranscriptEvent,
    VoiceDrainResult,
    VoiceRuntimeMode,
    VoiceTranscriptEvent,
    VoiceTranscriptSource,
    FinalizedUtterance,
    normalize_voice_transcript_event,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    _voice_lifecycle_events,
    VoiceLifecycleEvent,
    WebRtcRenderSnapshot,
)
from tournament_platform.app.services.voice_calibration.models import (
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationPhase,
)
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService

try:
    from tournament_platform.app.pages.voice_scorekeeper import apply_score_event_and_refresh_ui
except ImportError:
    apply_score_event_and_refresh_ui = None

logger = logging.getLogger(__name__)

_VOICE_RERUN_KEY = "_voice_needs_rerun"
_VOICE_RERUN_REASON_KEY = "_voice_rerun_reason"

_CALIBRATION_PROCESSED_IDS: Dict[str, Set[str]] = {}
_MAX_CALIBRATION_PROCESSED_IDS = 500

_DRAIN_INVOCATION_COUNT = 0
_DRAIN_LAST_TIMESTAMP = 0.0
_DRAIN_LAST_PROCESSOR_ID = None
_DRAIN_LAST_QUEUE_ID = None
_DRAIN_LAST_QUEUE_SIZE_BEFORE = 0
_DRAIN_LAST_QUEUE_SIZE_AFTER = 0
_DRAIN_LAST_SKIPPED_REASON = ""
_DRAIN_LAST_EXCEPTION = None
_DRAIN_LAST_QUEUE_EMPTY_TS = 0.0
_DRAIN_QUEUE_EMPTY_COUNT = 0


def clear_processed_voice_event_ids() -> None:
    """Legacy helper; currently we use session state for applied IDs."""
    pass


def clear_calibration_processed_ids() -> None:
    _CALIBRATION_PROCESSED_IDS.clear()


def reset_drain_diagnostics() -> None:
    global _DRAIN_INVOCATION_COUNT, _DRAIN_LAST_TIMESTAMP, _DRAIN_LAST_PROCESSOR_ID
    global _DRAIN_LAST_QUEUE_ID, _DRAIN_LAST_QUEUE_SIZE_BEFORE, _DRAIN_LAST_QUEUE_SIZE_AFTER
    global _DRAIN_LAST_SKIPPED_REASON, _DRAIN_LAST_EXCEPTION
    global _DRAIN_LAST_QUEUE_EMPTY_TS, _DRAIN_QUEUE_EMPTY_COUNT
    _DRAIN_INVOCATION_COUNT = 0
    _DRAIN_LAST_TIMESTAMP = 0.0
    _DRAIN_LAST_PROCESSOR_ID = None
    _DRAIN_LAST_QUEUE_ID = None
    _DRAIN_LAST_QUEUE_SIZE_BEFORE = 0
    _DRAIN_LAST_QUEUE_SIZE_AFTER = 0
    _DRAIN_LAST_SKIPPED_REASON = ""
    _DRAIN_LAST_EXCEPTION = None
    _DRAIN_LAST_QUEUE_EMPTY_TS = 0.0
    _DRAIN_QUEUE_EMPTY_COUNT = 0


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


def _maybe_voice_heartbeat(snapshot: WebRtcRenderSnapshot | None = None) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import is_voice_scoring_enabled
    if st.session_state.get("VOICE_DEBUG_DISABLE_HEARTBEAT"):
        return

    if not is_voice_scoring_enabled():
        return
    
    if not st.session_state.get("voice_listening"):
        return
    
    processor = None
    if snapshot is not None:
        processor = snapshot.processor
    else:
        ctx = st.session_state.get("voice_webrtc_ctx")
        processor = ctx.get("processor") if ctx else None

    has_pending = False
    if processor:
        if hasattr(processor, 'has_pending_events'):
            has_pending = processor.has_pending_events()
    
    interval = 0.25 if has_pending else 1.0
    last_heartbeat = st.session_state.get("voice_last_heartbeat", 0.0)
    now = time.time()
    if now - last_heartbeat < interval:
        return
    
    st.session_state.voice_last_heartbeat = now
    time.sleep(0.05)
    st.rerun()


def _process_voice_transcript(
    transcript: str,
    source: str = "debug",
    enable_confirmation: bool = True,
    selected_match_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Internal delegator to the authoritative application-layer processor."""
    import tournament_platform.app.pages.voice_scorekeeper as vs_page
    
    res_obj = vs_page.apply_score_event_and_refresh_ui(
        transcript=transcript,
        source=source,
        enable_confirmation=enable_confirmation,
        selected_match_id=selected_match_id,
    )
    return {
        "success": res_obj.success,
        "reason": res_obj.reason,
        "previous_score": res_obj.previous_score,
        "new_score": res_obj.new_score,
        "parsed": res_obj.parsed,
        "route_result": res_obj.route_result,
    }


def _process_voice_events(
    calibration_service: VoiceCalibrationService | None = None,
    snapshot: WebRtcRenderSnapshot | None = None,
) -> VoiceDrainResult:
    from tournament_platform.app.pages.voice_scorekeeper import (
        _append_continuous_trace,
        _get_webrtc_playing_state,
        is_voice_scoring_enabled,
        _process_quick_voice_event,
    )
    
    st.session_state.pop(_VOICE_RERUN_KEY, None)
    st.session_state.pop(_VOICE_RERUN_REASON_KEY, None)

    if snapshot is not None:
        processor = snapshot.processor
    else:
        ctx = st.session_state.get("voice_webrtc_ctx")
        processor = ctx.get("processor") if ctx else None

    if processor is None:
        global _DRAIN_LAST_SKIPPED_REASON
        _DRAIN_LAST_SKIPPED_REASON = "no_processor"
        return VoiceDrainResult()

    global _DRAIN_INVOCATION_COUNT, _DRAIN_LAST_TIMESTAMP, _DRAIN_LAST_PROCESSOR_ID
    _DRAIN_INVOCATION_COUNT += 1
    _DRAIN_LAST_TIMESTAMP = time.time()
    _DRAIN_LAST_PROCESSOR_ID = id(processor)

    result = VoiceDrainResult()

    # 1. Drain lifecycle events
    lifecycle_events = _voice_lifecycle_events.drain()
    for le in lifecycle_events:
        _append_continuous_trace(
            f"lifecycle_{le.event_type}",
            f"proc_id={le.processor_id} gen={le.processor_generation} ts={le.timestamp} "
            f"desired={le.desired_mic_playing} note={le.extra.get('note', '')}",
        )
        if le.event_type == "webrtc_state_change":
             st.session_state[_VOICE_RERUN_KEY] = True
             st.session_state[_VOICE_RERUN_REASON_KEY] = "async_webrtc_state_change"

    try:
        _drain_acoustic_measurements(processor=processor, result=result)
    except Exception as exc:
        logger.debug("Acoustic measurement drain failed: %s", exc)
        result.last_exception = "measurement_drain_exception"

    # 2. Drain transcripts
    # Start with a fresh list for this drain cycle
    raw_events = []
    
    # Batch events (Faster Whisper)
    try:
        raw_events.extend(list(processor.get_events()))
    except Exception as exc:
        logger.debug("Batch event drain failed: %s", exc)

    # Streaming events (Deepgram)
    if hasattr(processor, "drain_streaming_events"):
        try:
            streaming_utterances = processor.drain_streaming_events()
            result.streaming_events_drained = len(streaming_utterances)
            # Convert FinalizedUtterance to standard event format
            for utt in streaming_utterances:
                raw_events.append(VoiceTranscriptEvent(
                    transcript=utt.transcript,
                    raw_transcript=utt.raw_transcript,
                    event_id=utt.utterance_id,
                    source=VoiceTranscriptSource.CONTINUOUS,
                    runtime_session_id=utt.voice_session_id,
                    match_id=utt.match_id,
                    created_at=utt.created_at,
                    confidence=getattr(utt, "confidence", 1.0),
                ))
        except Exception as exc:
            logger.debug("Streaming event drain failed: %s", exc)
            result.streaming_events_failed += 1

    if not raw_events:
        return result

    _append_continuous_trace("continuous_event_consumed", f"{len(raw_events)}_events")

    _engine = st.session_state.match_manager.engine
    _current_session_id = st.session_state.get("voice_continuous_session_id")
    _session_start = st.session_state.get("voice_continuous_session_start", 0.0)
    _applied_ids = st.session_state.get("last_applied_voice_event_ids", [])
    _webrtc_playing = _get_webrtc_playing_state()
    _current_match_id = st.session_state.match_manager.match_id if hasattr(st.session_state.match_manager, "match_id") else None

    result.events_drained = len(raw_events)
    _runtime_mode = get_voice_runtime_mode()
    _match_won = _engine.match_status == "match_won"

    # Diagnostics for silent skips
    _ss = st.session_state
    if "voice_events_skip_listening" not in _ss: _ss.voice_events_skip_listening = 0
    if "voice_events_skip_match_won" not in _ss: _ss.voice_events_skip_match_won = 0
    if "voice_events_skip_unknown_type" not in _ss: _ss.voice_events_skip_unknown_type = 0

    for event in raw_events:
        # Uniform attribute extraction with fallbacks
        if isinstance(event, VoiceTranscriptEvent):
            text = event.transcript
            _event_source = event.source
            _event_id = event.event_id
            _event_ts = event.created_at
            _event_session_id = event.runtime_session_id
            _event_match_id = event.match_id
        elif isinstance(event, tuple) and len(event) == 3:
            _, text, event_obj = event
            _event_source = getattr(event_obj, 'source', 'batch')
            _event_id = getattr(event_obj, 'event_id', '')
            _event_ts = getattr(event_obj, 'timestamp', 0.0)
            _event_session_id = getattr(event_obj, 'session_id', None)
            _event_match_id = getattr(event_obj, 'match_id', None)
        else:
            # Try duck-typing for mocks or other types
            text = getattr(event, 'transcript', None)
            if text is None:
                _ss.voice_events_skip_unknown_type += 1
                continue
            _event_source = getattr(event, 'source', 'unknown')
            _event_id = getattr(event, 'event_id', '')
            _event_ts = getattr(event, 'created_at', getattr(event, 'timestamp', 0.0))
            _event_session_id = getattr(event, 'runtime_session_id', getattr(event, 'session_id', None))
            _event_match_id = getattr(event, 'match_id', None)

        if _event_source == "calibration" or _runtime_mode == VoiceRuntimeMode.CALIBRATION:
            # Handle calibration (simplified for this cleanup)
            continue

        if st.session_state.get("quick_voice_mode") == "quick":
            _process_quick_voice_event(text)
            result.events_accepted += 1
            continue

        if not st.session_state.get("voice_listening") or not st.session_state.get("voice_events_enabled"):
            _ss.voice_events_skip_listening += 1
            continue

        if _match_won:
            _ss.voice_events_skip_match_won += 1
            continue

        _stale_reason = None
        if _event_session_id and _current_session_id and _event_session_id != _current_session_id:
            _stale_reason = "stale_event_old_session"
            st.session_state.last_streaming_event_rejection_reason = (
                f"session_mismatch: event={_event_session_id[:8]} current={_current_session_id[:8]}"
            )
        elif _event_ts < _session_start:
            _stale_reason = "stale_event_after_stop"
            st.session_state.last_streaming_event_rejection_reason = (
                f"timestamp_too_early: event={_event_ts:.2f} session_start={_session_start:.2f}"
            )
        elif _event_id in _applied_ids:
            _stale_reason = "duplicate_event"
            st.session_state.last_streaming_event_rejection_reason = f"duplicate: id={_event_id}"
        elif _event_match_id and _current_match_id and str(_event_match_id) != str(_current_match_id):
            _stale_reason = "match_mismatch"
            st.session_state.last_streaming_event_rejection_reason = f"match_mismatch: event={_event_match_id} current={_current_match_id}"
        elif not _webrtc_playing and _event_source == VoiceTranscriptSource.CONTINUOUS:
            _stale_reason = "webrtc_not_playing"
            st.session_state.last_streaming_event_rejection_reason = "webrtc_not_playing"

        if _stale_reason:
            st.session_state.voice_stale_events_ignored = st.session_state.get("voice_stale_events_ignored", 0) + 1
            _append_continuous_trace("stale_event_ignored", f"{_stale_reason}:{_event_id[:8]}")
            result.events_stale += 1
            continue

        # If we got here, we are about to process a valid event
        st.session_state.last_voice_continuous_transcript = text
        st.session_state.last_streaming_event_rejection_reason = None

        res_dict = _process_voice_transcript(
            transcript=text,
            source="continuous",
            enable_confirmation=VOICE_ENABLE_CONFIRMATION,
        )

        if (res_dict.get("success") or res_dict.get("reason") == "applied") and _event_id:
            _applied_ids = list(st.session_state.get("last_applied_voice_event_ids", []))
            if _event_id not in _applied_ids:
                _applied_ids.append(_event_id)
            if len(_applied_ids) > 100:
                _applied_ids = _applied_ids[-100:]
            st.session_state["last_applied_voice_event_ids"] = _applied_ids

        _append_continuous_trace(
            "continuous_event_processed",
            f"success={res_dict.get('success')},reason={res_dict.get('reason')}",
        )

        if res_dict.get("success"):
            result.events_accepted += 1
            result.last_transcript = text
            result.last_command_source = _event_source
        else:
            result.events_rejected += 1
            result.last_rejection_reason = res_dict.get("reason") or "unknown"

    return result


def get_voice_runtime_mode() -> VoiceRuntimeMode:
    raw = st.session_state.get("voice_runtime_mode", VoiceRuntimeMode.OFF)
    try:
        return VoiceRuntimeMode(raw)
    except (TypeError, ValueError):
        return VoiceRuntimeMode.OFF


def _drain_acoustic_measurements(processor: Any, result: VoiceDrainResult) -> None:
    if processor is None:
        return
    measurements = getattr(processor, "drain_acoustic_measurement_results", lambda: [])()
    for m in measurements:
        result.calibration_measurements.append(m)
        result.calibration_measurements_evaluated += 1


def get_drain_diagnostics() -> Dict[str, Any]:
    return {
        "invocation_count": _DRAIN_INVOCATION_COUNT,
        "last_timestamp": _DRAIN_LAST_TIMESTAMP,
        "last_processor_id": _DRAIN_LAST_PROCESSOR_ID,
        "last_queue_id": _DRAIN_LAST_QUEUE_ID,
        "last_queue_size_before": _DRAIN_LAST_QUEUE_SIZE_BEFORE,
        "last_queue_size_after": _DRAIN_LAST_QUEUE_SIZE_AFTER,
        "last_skipped_reason": _DRAIN_LAST_SKIPPED_REASON,
        "last_exception": _DRAIN_LAST_EXCEPTION,
        "last_queue_empty_ts": _DRAIN_LAST_QUEUE_EMPTY_TS,
        "queue_empty_count": _DRAIN_QUEUE_EMPTY_COUNT,
    }


def get_active_voice_processor() -> Any:
    """Return the active WebRTC voice processor from session state, or None."""
    ctx = st.session_state.get("voice_webrtc_ctx") or {}
    return ctx.get("processor")


def is_canonical_voice_enabled() -> bool:
    """Return True if canonical voice scoring is enabled."""
    return st.session_state.get("voice_scoring_enabled", False)


def get_canonical_skip_reason() -> Optional[str]:
    """Return the reason canonical voice scoring is skipped, or None."""
    if not st.session_state.get("voice_scoring_enabled", False):
        return "voice_scoring_disabled"
    return None


class ContinuousRuntimeSnapshot:
    """Placeholder for runtime snapshot data (expected by UI)."""
    pass


def _handle_tt_sounds_event(event: Any) -> None:
    pass


def _process_tt_sounds_events(snapshot: WebRtcRenderSnapshot | None = None) -> None:
    pass


def _maybe_tt_sounds_heartbeat(snapshot: WebRtcRenderSnapshot | None = None) -> None:
    pass
