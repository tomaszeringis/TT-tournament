"""
Voice-Activated Tournament Scorekeeper

A privacy-focused scorekeeping system using:
- streamlit-webrtc for continuous microphone capture
- faster-whisper for local transcription
- VoiceParser for structured intent parsing
- Manual scoring always available
"""

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

# Only configure the page when running as a Streamlit script (not on import),
# so the module stays import-safe for unit tests.
if get_script_run_ctx() is not None:
    st.set_page_config(page_title="LIT_IT Voice Scorekeeper", layout="wide")

import copy
import uuid
import threading
import queue
import logging
import time
import numpy as np
from datetime import datetime, timezone
from typing import Any, Optional, Tuple, Dict, List
from dataclasses import dataclass, is_dataclass, asdict

# Import audio format constants
from tournament_platform.app.services.voice_audio import (
    SAMPLE_FORMAT_FLOAT32,
    SAMPLE_FORMAT_INT16,
)

# streamlit-webrtc processor base. Voice scoring degrades gracefully to
# push-to-talk if the package is unavailable, so fall back to ``object``.
try:
    from streamlit_webrtc import AudioProcessorBase
except Exception:  # pragma: no cover - optional dependency
    AudioProcessorBase = object  # type: ignore

# PyAV is used for audio frame handling in the fallback callback.
try:
    import av
except Exception:  # pragma: no cover - optional dependency
    av = None  # type: ignore

logger = logging.getLogger(__name__)

# Reduce noisy streamlit-webrtc.process warnings after implementing bounded
# queues and non-blocking callbacks. Keep the logger at ERROR so genuine
# failures still surface, but suppress the "queued frames not consumed"
# informational spam.
try:
    logging.getLogger("streamlit_webrtc.process").setLevel(logging.ERROR)
except Exception:
    pass

# Import the MatchManager
from tournament_platform.services.match_manager import MatchManager, MatchState
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament
from tournament_platform.app.utils import format_player_label, api_request
from tournament_platform.services.settings import (
    KEEP_AUDIO_FILES,
    VOICE_DEBUG_EVENTS,
    VOICE_ENABLE_CONFIRMATION,
    VOICE_DATASET_OPT_IN,
    VOICE_ENABLE_NOISE_FILTERING,
    VOICE_NOISE_THRESHOLD,
    VOICE_RETENTION_DAYS,
    VOICE_STRICT_MODE,
    VOICE_ASR_MODEL_SIZE,
    VOICE_ASR_DEVICE,
    VOICE_ASR_COMPUTE_TYPE,
    VOICE_MIC_START_TIMEOUT_SECONDS,
    VOICE_PROCESSOR_WAIT_TIMEOUT_SECONDS,
)
from tournament_platform.services.schemas import ActiveMatchResponse
from tournament_platform.app.services.score_engine import (
    best_of_to_games_to_win,
    games_to_win_to_best_of,
    is_deuce,
    get_serving_player,
    get_point_log,
    get_live_stats,
)
from tournament_platform.app.services.ui_feedback import play_cue, render_sound_toggle
from tournament_platform.app.services.voice_speaker import SpeakerTagger, DEFAULT_SPEAKERS
from tournament_platform.app.services.voice_tts import TTSConfirmationAdapter, TTSMode
# Import voice scoring modules
from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.app.services.voice.commands import VoiceIntent, parse as parse_command, cheat_sheet as command_cheat_sheet
from tournament_platform.app.services.voice.confirmation import policy_decision
from tournament_platform.app.services.voice.vad import VoiceActivityDetector, create_vad
from tournament_platform.app.services.voice.hf_token import get_hf_token
from tournament_platform.app.services.voice.asr_diagnostics import (
    get_voice_setting,
    diagnose_faster_whisper_environment,
    log_voice_asr_environment_once,
)
from tournament_platform.app.services.voice.dataset_recorder import VoiceDatasetRecorder, VoiceDatasetSample
from tournament_platform.app.services.voice.quick_voice import QuickVoiceScoringEngine
from tournament_platform.app.services.voice_audio import VoiceAudioBuffer, AudioChunk
from tournament_platform.app.services.voice_asr import LocalASR, LocalASRError
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice_audit import EventLogger
from tournament_platform.app.services.voice_noise import NoiseFilter, NoiseProfiler
from tournament_platform.app.services.voice.runtime_state import migrate_from_session_state, get_state, set_state, sync_legacy_keys
from tournament_platform.app.services.voice_scorekeeper.scoring_actions import ScoreAction, ScoreActionType, apply_manual_score_action, ScoreApplyResult
from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
from tournament_platform.app.services.voice_scorekeeper.event_drain import (
    _on_quick_voice_mode_changed,
    _apply_quick_voice_point,
    _process_quick_voice_event,
    _maybe_voice_heartbeat,
    _process_tt_sounds_events,
    _handle_tt_sounds_event,
    _maybe_tt_sounds_heartbeat,
    _process_voice_events,
    normalize_voice_transcript_event,
    VoiceTranscriptEvent,
    InvalidVoiceTranscriptEvent,
    ContinuousRuntimeSnapshot,
    VoiceDrainResult,
    get_active_voice_processor,
    get_drain_diagnostics,
    is_canonical_voice_enabled,
    get_canonical_skip_reason,
    VoiceTranscriptSource,
)
from tournament_platform.app.services.voice_scorekeeper.commentary import (
    _get_commentary_settings,
    _is_critical_moment,
    _apply_critical_cooldown,
    _synthesize_piper_audio,
    play_commentary,
    _event_type_to_tt,
    _build_local_commentary,
    _build_and_store_commentary,
    _emit_set_win_commentary,
    _reconcile_finished_games,
    render_commentary_settings,
    render_pending_commentary,
  )
from tournament_platform.app.services.voice_scorekeeper.ui_helpers import (
    _render_audio_rally_insights,
    _render_confirm_panel,
    _render_dataset_panel,
    _render_match_diagnostics,
    render_active_match_selector,
    render_selected_match_summary,
)

try:
    from tournament_platform.app.services.voice_calibration.models import (
        CalibrationSession,
        CommandTrial,
        TrialClassification,
    )
except Exception:  # pragma: no cover - import-safe, optional
    CalibrationSession = None  # type: ignore
    CommandTrial = None  # type: ignore
    TrialClassification = None  # type: ignore

try:
    from tournament_platform.app.services.voice_calibration.service import (
        VoiceCalibrationService,
    )
except Exception:  # pragma: no cover - import-safe, optional
    VoiceCalibrationService = None  # type: ignore

try:
    from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
        render_voice_calibration,
        consume_calibration_trials,
        find_measurement_result,
        _get_command_trial_ui_state,
        _set_command_trial_ui_state,
        _render_live_profile_recommendation,
        _render_effective_configuration,
        _render_post_activation_verification,
        _activate_calibrated_voice_profile,
        _undo_calibrated_settings,
        VoiceProfileActivationStatus,
        RecommendationStatus,
        CommandTrialUIStatus,
        CommandTrialUIState,
    )
except Exception:  # pragma: no cover - import-safe, optional
    render_voice_calibration = None  # type: ignore
    consume_calibration_trials = None  # type: ignore
    _render_live_profile_recommendation = None  # type: ignore
    _render_effective_configuration = None  # type: ignore
    _render_post_activation_verification = None  # type: ignore
    _activate_calibrated_voice_profile = None  # type: ignore
    _undo_calibrated_settings = None  # type: ignore
    VoiceProfileActivationStatus = None  # type: ignore
    RecommendationStatus = None  # type: ignore


from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
    _frame_to_ndarray,
    _audio_input_to_pcm,
    _audio_frame_to_mono_float32,
    _pcm_float32_to_int16,
    build_audio_processor_factory,
    tracked_audio_processor_factory,
    VoiceProcessorFactory,
    VoiceProcessorConfigHolder,
    StreamingSessionIdentity,
    WebRtcRenderSnapshot,
    VoiceLifecycleEventQueue,
    _audio_callback_count,
    _audio_callback_lock,
    _last_audio_frame_rms,
    _last_audio_frame_shape,
    _last_audio_frame_sample_rate,
    _last_audio_frame_method,
    _last_audio_frame_timestamp,
)
from tournament_platform.app.services.voice.confirmation import VoiceConfirmationStateMachine
from tournament_platform.app.api_client import api_client
from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.app.components.tour import render_tour
from tournament_platform.app.components.page_header import render_page_header
from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    CommentaryLanguage,
    CommentaryMode,
    CommentaryIntensity,
    ImportanceLevel,
    SpokenScoreState,
    CommentaryLine,
    ScoreMoment,
    log_commentary_event,
)
from tournament_platform.app.services.match_analytics import MatchAnalyticsService
from tournament_platform.app.components.spoken_commentary import (
    speak_commentary,
    play_local_audio,
    speak_commentary_audio_file,
)
from tournament_platform.services.commentary_templates import (
    normalize_commentary_style,
    SUPPORTED_COMMENTARY_STYLES,
)

# Renderable voice styles exposed in the "Voice style" dropdown. ``silent`` is
# a verbosity/mode, not a renderable style, so it is excluded.
COMMENTARY_STYLE_OPTIONS = list(SUPPORTED_COMMENTARY_STYLES.keys())
from tournament_platform.app.services.commentary import (
    CommentaryEngine,
    CommentaryEventData,
    MatchContext,
    MatchContextBuilder,
    TTEventType,
    generate_match_summary,
)
from tournament_platform.app.services.commentary_voice.piper_runtime import is_piper_available

# Stabilized media stream constraints — identity must not change between reruns
# or streamlit-webrtc treats it as a changed constraint and resets the component.
_WEBRTC_AUDIO_CONSTRAINTS = {"audio": True, "video": False}


@dataclass
class ContinuousWebRTCResult:
    """Shared WebRTC render result consumed by the entire page per Streamlit run.

    Produced exactly once by the single ``webrtc_streamer()`` call and passed
    to state reconciliation, the connection badge, button rules, microphone
    health checks, backend ownership validation, diagnostics, and event draining.
    """

    context: object | None = None
    processor: object | None = None
    component_mounted: bool = False
    playing: bool = False
    signalling: bool = False
    processor_id: int | None = None
    processor_generation: int | None = None
    error_category: str | None = None
    error_message_safe: str | None = None


def _build_webrtc_result(ctx: object | None, mount_error: str | None = None) -> ContinuousWebRTCResult:
    """Extract a stable ``ContinuousWebRTCResult`` from the current WebRTC context."""
    if ctx is None:
        return ContinuousWebRTCResult(
            component_mounted=False,
            error_category="component_not_mounted" if mount_error else None,
            error_message_safe=mount_error,
        )

    _proc = _get_voice_webrtc_processor(ctx)
    _playing = getattr(ctx, "state", None)
    if _playing is not None and not isinstance(_playing, dict):
        _playing = getattr(_playing, "playing", False)
    elif isinstance(_playing, dict):
        _playing = _playing.get("playing", False)
    else:
        _playing = False

    _signalling = False
    if _playing is not None and not isinstance(_playing, dict):
        _signalling = getattr(ctx.state, "signalling", False) if hasattr(ctx, "state") else False
    elif isinstance(_playing, dict):
        _signalling = _playing.get("signalling", False)

    _proc_id = id(_proc) if _proc is not None else None
    _proc_gen = getattr(_proc, "_processor_generation", None) if _proc is not None else None

    return ContinuousWebRTCResult(
        context=ctx,
        processor=_proc,
        component_mounted=_proc is not None,
        playing=bool(_playing),
        signalling=bool(_signalling),
        processor_id=_proc_id,
        processor_generation=_proc_gen,
        error_category=None,
        error_message_safe=None,
    )


def _reconcile_voice_lifecycle(
    webrtc_result: ContinuousWebRTCResult,
    *,
    current_time: float | None = None,
) -> dict:
    """Reconcile the full voice-scoring lifecycle from the current WebRTC result.

    Returns a dict with keys:
        connection_state, connection_state_reason,
        desired_mic_playing, webrtc_component_mounted, webrtc_playing,
        webrtc_signalling, microphone_confirmed_at,
        audio_processor_created, current_processor_id, current_processor_generation,
        streaming_backend_attached, backend_connection_state,
        streaming_processor_id, streaming_generation,
        backend_identity_matches_current_processor,
        stale_backend_detected, unexpected_webrtc_stop,
        start_enabled, stop_enabled,
    """
    if current_time is None:
        current_time = time.monotonic()

    _webrtc = webrtc_result
    _proc = _webrtc.processor
    _playing = _webrtc.playing
    _desired = bool(st.session_state.get("desired_mic_playing", False))
    _start_requested = bool(st.session_state.get("voice_start_requested", False))
    _prev_playing = bool(st.session_state.get("_voice_prev_webrtc_playing", False))
    _mic_confirmed_at = st.session_state.get("streaming_start_microphone_confirmed_at")
    _backend_gen = st.session_state.get("voice_streaming_backend_gen", 0)
    _streaming_proc_id = st.session_state.get("streaming_processor_id")
    _streaming_gen = st.session_state.get("streaming_processor_generation")
    _voice_session_id = st.session_state.get("voice_continuous_session_id")
    _match_id = st.session_state.get("voice_selected_match_id")

    _state = {
        "connection_state": "disabled",
        "connection_state_reason": "desired_mic_playing is False",
        "desired_mic_playing": _desired,
        "webrtc_component_mounted": _webrtc.component_mounted,
        "webrtc_playing": _playing,
        "webrtc_signalling": _webrtc.signalling,
        "microphone_confirmed_at": _mic_confirmed_at,
        "audio_processor_created": _proc is not None,
        "current_processor_id": _webrtc.processor_id,
        "current_processor_generation": _webrtc.processor_generation,
        "streaming_backend_attached": False,
        "backend_connection_state": "none",
        "streaming_processor_id": _streaming_proc_id,
        "streaming_generation": _streaming_gen,
        "backend_identity_matches_current_processor": False,
        "stale_backend_detected": False,
        "unexpected_webrtc_stop": False,
        "start_enabled": False,
        "stop_enabled": False,
    }

    if _proc is not None:
        _backend = getattr(_proc, "_streaming_backend", None)
        _state["streaming_backend_attached"] = _backend is not None
        if _backend is not None and hasattr(_backend, "connection_state"):
            _state["backend_connection_state"] = _backend.connection_state()
        if _backend is not None and hasattr(_backend, "get_connection_info"):
            try:
                _conn = _backend.get_connection_info() or {}
                _state["backend_connection_state"] = _conn.get("connection_state", _state["backend_connection_state"])
            except Exception:
                pass

        _state["backend_identity_matches_current_processor"] = (
            _streaming_proc_id == _webrtc.processor_id
            and _streaming_gen == _webrtc.processor_generation
            and _streaming_gen is not None
            and _streaming_gen > 0
        )

        if _streaming_proc_id is not None and _webrtc.processor_id is not None and _streaming_proc_id != _webrtc.processor_id:
            _state["stale_backend_detected"] = True

    # --- Desired=False path ---
    if not _desired:
        _state["connection_state"] = "disabled"
        _state["connection_state_reason"] = "desired_mic_playing is False"
        _state["start_enabled"] = True
        _state["stop_enabled"] = False
        return _state

    # --- Desired=True path ---
    _state["stop_enabled"] = True

    # Playing=False + desired=True + microphone never confirmed + startup timeout not elapsed
    if not _playing and _mic_confirmed_at is None and _start_requested:
        _timeout = st.session_state.get("streaming_start_requested_at")
        if _timeout is not None and (time.time() - _timeout) > VOICE_MIC_START_TIMEOUT_SECONDS:
            _state["connection_state"] = "failed"
            _state["connection_state_reason"] = "microphone_start_timeout"
            _state["start_enabled"] = True
            _state["stop_enabled"] = True
        else:
            _state["connection_state"] = "starting_microphone"
            _state["connection_state_reason"] = "waiting for browser microphone to become active"
            _state["start_enabled"] = False
            _state["stop_enabled"] = True
        return _state

    # Playing=False + desired=True + microphone was previously confirmed = unexpected stop
    if not _playing and _mic_confirmed_at is not None and _prev_playing:
        _state["connection_state"] = "failed"
        _state["connection_state_reason"] = "unexpected_microphone_stop"
        _state["unexpected_webrtc_stop"] = True
        _state["start_enabled"] = True
        _state["stop_enabled"] = False
        return _state

    # Playing=False + desired=True + not previously confirmed (first-time permission timeout)
    if not _playing and _desired:
        _state["connection_state"] = "starting_microphone"
        _state["connection_state_reason"] = "microphone not yet confirmed by browser"
        _state["start_enabled"] = False
        _state["stop_enabled"] = True
        return _state

    # Playing=True + processor missing
    if _playing and _proc is None:
        _state["connection_state"] = "waiting_for_processor"
        _state["connection_state_reason"] = "WebRTC playing but audio processor is not yet available"
        _state["start_enabled"] = False
        _state["stop_enabled"] = True
        return _state

    # Playing=True + processor exists + backend connecting
    if _playing and _proc is not None:
        _backend = getattr(_proc, "_streaming_backend", None)
        if _backend is None:
            _state["connection_state"] = "connecting"
            _state["connection_state_reason"] = "processor ready, backend not yet attached"
            _state["start_enabled"] = False
            _state["stop_enabled"] = True
            return _state

        _backend_state = _state["backend_connection_state"]
        if _backend_state in ("connecting", "starting", "reconnecting"):
            _state["connection_state"] = "connecting"
            _state["connection_state_reason"] = f"backend connection state: {_backend_state}"
            _state["start_enabled"] = False
            _state["stop_enabled"] = True
            return _state

    # Playing=True + current backend connected
    if _playing and _proc is not None and _state["backend_connection_state"] == "connected":
        # Verify processor ownership
        if not _state["backend_identity_matches_current_processor"]:
            _state["connection_state"] = "failed"
            _state["connection_state_reason"] = "backend_processor_identity_mismatch"
            _state["stale_backend_detected"] = True
            _state["start_enabled"] = True
            _state["stop_enabled"] = False
            return _state

        _state["connection_state"] = "ready"
        _state["connection_state_reason"] = "webrtc_playing=True backend_connected processor_identity_matches"
        _state["start_enabled"] = False
        _state["stop_enabled"] = True
        return _state

    # Playing=True + backend not connected (stale connected backend)
    if _playing and _proc is not None and _state["backend_connection_state"] in ("connected", "connecting", "reconnecting"):
        if _state["backend_connection_state"] == "connected" and not _playing:
            _state["connection_state"] = "failed"
            _state["connection_state_reason"] = "stale_connected_backend_detected"
            _state["stale_backend_detected"] = True
            _state["start_enabled"] = True
            _state["stop_enabled"] = False
            return _state

    # Fallback
    _state["connection_state"] = "disabled"
    _state["connection_state_reason"] = "no matching readiness condition"
    _state["start_enabled"] = True
    _state["stop_enabled"] = False
    return _state

def is_streamlit_cloud() -> bool:
    """Detect whether the app is running on Streamlit Cloud.

    Used only as a hint (e.g. to pick friendlier defaults). The app must still
    work gracefully in any environment where Piper is missing.
    """
    import os

    return bool(os.getenv("STREAMLIT_SERVER_HEADLESS")) or bool(os.getenv("STREAMLIT_SHARING_MODE"))


def piper_unavailable_session_key() -> str:
    """Stable session-state key used to surface a one-time Piper notice."""
    return "voice_piper_unavailable_notice_shown"


def notify_piper_unavailable_once(message: str, *, level: str = "info") -> None:
    """Show a friendly Piper-unavailable notice once per session.

    Avoids warning spam on every score update. ``level`` is ``"info"`` or
    ``"warning"`` — never ``"error"``.
    """
    import streamlit as st

    key = piper_unavailable_session_key()
    if st.session_state.get(key):
        return
    if level == "warning":
        st.warning(message)
    else:
        st.info(message)
    st.session_state[key] = True


def detect_webrtc_available() -> bool:
    """Safely detect whether ``streamlit-webrtc`` is importable.

    Never raises; returns False when the optional package is missing.
    """
    try:
        import streamlit_webrtc  # noqa: F401

        return True
    except ImportError:
        return False


# Computed once at module import time. ``streamlit-webrtc`` is a normal runtime
# dependency, so this is True on Streamlit Cloud; it gracefully falls back to
# False (friendly notice, no crash) where it is absent.
WEBRTC_AVAILABLE = detect_webrtc_available()


def ensure_webrtc_diag_state() -> None:
    """Store WebRTC availability in session state for the diagnostics panel."""
    import streamlit as st

    if "webrtc_diag_available" not in st.session_state:
        st.session_state.webrtc_diag_available = WEBRTC_AVAILABLE


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
# Session State Initialization
# ============================================================================

# Initialize MatchManager in session state
if 'match_manager' not in st.session_state:
    st.session_state.match_manager = MatchManager()

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

# Voice scoring (WebRTC) state
if 'voice_scoring_enabled' not in st.session_state:
    st.session_state.voice_scoring_enabled = False
if 'voice_listening' not in st.session_state:
    st.session_state.voice_listening = False
if 'voice_capture_requested' not in st.session_state:
    st.session_state.voice_capture_requested = False
if 'voice_stop_requested' not in st.session_state:
    st.session_state.voice_stop_requested = False
if 'voice_events_enabled' not in st.session_state:
    st.session_state.voice_events_enabled = False
if 'last_voice_transcript' not in st.session_state:
    st.session_state.last_voice_transcript = ""
if 'last_voice_event' not in st.session_state:
    st.session_state.last_voice_event = None
if 'last_voice_feedback' not in st.session_state:
    st.session_state.last_voice_feedback = ""
if 'last_voice_rejection_reason' not in st.session_state:
    st.session_state.last_voice_rejection_reason = ""
if 'last_voice_success_message' not in st.session_state:
    st.session_state.last_voice_success_message = ""
if 'last_voice_action_taken' not in st.session_state:
    st.session_state.last_voice_action_taken = ""
if 'voice_event_log' not in st.session_state:
    st.session_state.voice_event_log = []
if 'voice_audit_events' not in st.session_state:
    st.session_state.voice_audit_events = []

# Hardened, structured voice event logger (Phase 1 / observability).
# Bounded in-memory ring; recording is gated by VOICE_DEBUG_EVENTS.
if 'voice_event_logger' not in st.session_state:
    st.session_state.voice_event_logger = EventLogger()

# Noise robustness (Phase 5) — session-overridable config + calibration samples.
if 'voice_noise_filtering' not in st.session_state:
    st.session_state.voice_noise_filtering = VOICE_ENABLE_NOISE_FILTERING
if 'voice_noise_threshold' not in st.session_state:
    st.session_state.voice_noise_threshold = VOICE_NOISE_THRESHOLD
if 'voice_strict_mode' not in st.session_state:
    st.session_state.voice_strict_mode = VOICE_STRICT_MODE
if 'voice_rms_samples' not in st.session_state:
    st.session_state.voice_rms_samples = []
if 'voice_last_chunk_rms' not in st.session_state:
    st.session_state.voice_last_chunk_rms = 0.0

# Live Voice Profile recommendation (plan 1785757678522)
if 'voice_live_profile_recommendation' not in st.session_state:
    st.session_state.voice_live_profile_recommendation = None
if 'voice_live_profile_activation_status' not in st.session_state:
    st.session_state.voice_live_profile_activation_status = None
if 'voice_live_profile_settings_snapshot' not in st.session_state:
    st.session_state.voice_live_profile_settings_snapshot = None
if 'voice_live_profile_config_revision' not in st.session_state:
    st.session_state.voice_live_profile_config_revision = 0
if 'voice_calibration_auto_apply' not in st.session_state:
    st.session_state.voice_calibration_auto_apply = False
if 'voice_profile_activation_verification' not in st.session_state:
    st.session_state.voice_profile_activation_verification = {}
if 'voice_asr_status' not in st.session_state:
    st.session_state.voice_asr_status = None
if 'voice_webrtc_ctx' not in st.session_state:
    st.session_state.voice_webrtc_ctx = None
if 'voice_webrtc_streamer_state' not in st.session_state:
    st.session_state.voice_webrtc_streamer_state = {"playing": False, "signalling": False}
if '_voice_prev_webrtc_playing' not in st.session_state:
    st.session_state._voice_prev_webrtc_playing = False
if '_voice_current_processor_id' not in st.session_state:
    st.session_state._voice_current_processor_id = None
if 'voice_continuous_session_id' not in st.session_state:
    st.session_state.voice_continuous_session_id = None
if 'voice_continuous_session_start' not in st.session_state:
    st.session_state.voice_continuous_session_start = 0.0
if 'voice_stale_events_ignored' not in st.session_state:
    st.session_state.voice_stale_events_ignored = 0
if 'voice_continuous_requested' not in st.session_state:
    st.session_state.voice_continuous_requested = False

# Step 9: Streaming voice scoring config (frozen at session start)
if 'voice_streaming_provider' not in st.session_state:
    st.session_state.voice_streaming_provider = None
if 'voice_streaming_language' not in st.session_state:
    st.session_state.voice_streaming_language = "lt"
if 'voice_streaming_state' not in st.session_state:
    st.session_state.voice_streaming_state = "disabled"
if 'voice_streaming_session_id' not in st.session_state:
    st.session_state.voice_streaming_session_id = None
if 'voice_streaming_backend_gen' not in st.session_state:
    st.session_state.voice_streaming_backend_gen = 0
if 'voice_streaming_error' not in st.session_state:
    st.session_state.voice_streaming_error = None
if 'voice_streaming_last_finalized' not in st.session_state:
    st.session_state.voice_streaming_last_finalized = ""
if 'voice_streaming_last_interim' not in st.session_state:
    st.session_state.voice_streaming_last_interim = ""
if 'voice_streaming_diagnostics' not in st.session_state:
    st.session_state.voice_streaming_diagnostics = {}
if 'voice_streaming_last_refresh' not in st.session_state:
    st.session_state.voice_streaming_last_refresh = 0.0
if 'voice_streaming_config_frozen' not in st.session_state:
    st.session_state.voice_streaming_config_frozen = False

# One-click streaming startup state
if 'voice_start_requested' not in st.session_state:
    st.session_state.voice_start_requested = False
if 'desired_mic_playing' not in st.session_state:
    st.session_state.desired_mic_playing = False
if 'last_desired_mic_writer' not in st.session_state:
    st.session_state.last_desired_mic_writer = None
if 'last_desired_mic_reason' not in st.session_state:
    st.session_state.last_desired_mic_reason = None
if 'unexpected_webrtc_stop_ts' not in st.session_state:
    st.session_state.unexpected_webrtc_stop_ts = None
if 'unexpected_webrtc_stop_count' not in st.session_state:
    st.session_state.unexpected_webrtc_stop_count = 0
if 'processor_ownership_mismatch' not in st.session_state:
    st.session_state.processor_ownership_mismatch = False
if 'last_session_termination_reason' not in st.session_state:
    st.session_state.last_session_termination_reason = None
if 'voice_webrtc_streamer_state' not in st.session_state:
    st.session_state.streaming_ui_state = "disabled"
if 'streaming_start_request_id' not in st.session_state:
    st.session_state.streaming_start_request_id = None
if 'streaming_start_requested_at' not in st.session_state:
    st.session_state.streaming_start_requested_at = None
if 'streaming_start_microphone_confirmed_at' not in st.session_state:
    st.session_state.streaming_start_microphone_confirmed_at = None
if 'streaming_start_backend_attached_at' not in st.session_state:
    st.session_state.streaming_start_backend_attached_at = None
if 'streaming_start_completed_at' not in st.session_state:
    st.session_state.streaming_start_completed_at = None
if 'streaming_processor_id' not in st.session_state:
    st.session_state.streaming_processor_id = None
if 'streaming_processor_generation' not in st.session_state:
    st.session_state.streaming_processor_generation = None

# Quick Voice Scoring state
if 'quick_voice_mode' not in st.session_state:
    st.session_state.quick_voice_mode = "off"
if 'quick_voice_point_trail' not in st.session_state:
    st.session_state.quick_voice_point_trail = []
if 'quick_voice_current_streak' not in st.session_state:
    st.session_state.quick_voice_current_streak = 0
if 'quick_voice_max_streak_a' not in st.session_state:
    st.session_state.quick_voice_max_streak_a = 0
if 'quick_voice_max_streak_b' not in st.session_state:
    st.session_state.quick_voice_max_streak_b = 0
if 'quick_voice_biggest_lead' not in st.session_state:
    st.session_state.quick_voice_biggest_lead = {"player": None, "margin": 0}
if 'quick_voice_last_player' not in st.session_state:
    st.session_state.quick_voice_last_player = None
if 'quick_voice_last_ts' not in st.session_state:
    st.session_state.quick_voice_last_ts = 0.0
if 'quick_voice_last_phrase' not in st.session_state:
    st.session_state.quick_voice_last_phrase = ""
if 'quick_voice_last_status' not in st.session_state:
    st.session_state.quick_voice_last_status = "idle"

# Audio Rally Assistant (TT Sounds) state
if 'tt_sounds_enabled' not in st.session_state:
    st.session_state.tt_sounds_enabled = False
if 'tt_sounds_recent_events' not in st.session_state:
    st.session_state.tt_sounds_recent_events = []
if 'tt_sounds_rally_context' not in st.session_state:
    st.session_state.tt_sounds_rally_context = None
if 'tt_sounds_audio_summaries' not in st.session_state:
    st.session_state.tt_sounds_audio_summaries = []
if 'tt_sounds_unavailable_notice_shown' not in st.session_state:
    st.session_state.tt_sounds_unavailable_notice_shown = False

# Speaker identification (Phase 2)
if 'voice_speaker_tagger' not in st.session_state:
    from tournament_platform.services.settings import (
        VOICE_ENABLE_SPEAKER_ID,
        VOICE_SPEAKER_MODE,
        VOICE_SPEAKER_REQUIRE,
    )
    _allowed = DEFAULT_SPEAKERS if VOICE_ENABLE_SPEAKER_ID else []
    _require = VOICE_SPEAKER_REQUIRE.split(",") if VOICE_SPEAKER_REQUIRE else []
    st.session_state.voice_speaker_tagger = SpeakerTagger(
        mode=VOICE_SPEAKER_MODE if VOICE_ENABLE_SPEAKER_ID else "off",
        allowed_speakers=_allowed or DEFAULT_SPEAKERS,
        require_speaker=bool(_require),
    )
if 'voice_current_speaker' not in st.session_state:
    st.session_state.voice_current_speaker = None

# TTS confirmation adapter (Phase 4)
if 'voice_tts_adapter' not in st.session_state:
    from tournament_platform.services.settings import (
        VOICE_ENABLE_TTS_CONFIRMATION,
        VOICE_TTS_MODE,
        VOICE_TTS_PROVIDER,
    )
    st.session_state.voice_tts_adapter = TTSConfirmationAdapter(
        mode=VOICE_TTS_MODE,
        provider=VOICE_TTS_PROVIDER,
        enabled=VOICE_ENABLE_TTS_CONFIRMATION,
    )


# ---------------------------------------------------------------------------
# Audio helpers (Sound cues + browser-native TTS routing)
# ---------------------------------------------------------------------------
# The audio-control wiring (TTS label mapping, mode->enabled selection, and
# browser speech routing) lives in audio_cues.py so it is unit-testable
# without importing this full page module.
from tournament_platform.app.services.audio_cues import (
    TTS_FRIENDLY_LABELS,
    apply_tts_selection,
    build_test_tts_message,
    maybe_speak_tts,
    tts_mode_options,
)

# Backwards-compatible aliases used by the scoring handlers below.
_maybe_speak_tts = maybe_speak_tts


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

# Live Scoreboard result-review / submission state.
# ``completed_games`` is DERIVED from ``engine.round_scores`` on every render
# (the engine remains the single source of truth during play). The flags below
# gate the pending-review -> Submit Result -> saved lifecycle so the DB is only
# written when the operator explicitly clicks Submit Result.
if 'completed_games' not in st.session_state:
    st.session_state.completed_games = []
if 'match_complete' not in st.session_state:
    st.session_state.match_complete = False
if 'pending_result_submission' not in st.session_state:
    st.session_state.pending_result_submission = False
if 'result_submitted' not in st.session_state:
    st.session_state.result_submitted = False

# Duplicate-command cooldown (Phase 4 / PingScore port).
# Ignore identical (type, player, score_a, score_b) events within COOLDOWN_MS.
if 'voice_last_applied_event_key' not in st.session_state:
    st.session_state.voice_last_applied_event_key = None
if 'voice_last_applied_event_ts' not in st.session_state:
    st.session_state.voice_last_applied_event_ts = 0.0

# Continuous listening safe rerun state.
if 'voice_continuous_session_id' not in st.session_state:
    st.session_state.voice_continuous_session_id = None
if 'voice_calibration_active_session_id' not in st.session_state:
    st.session_state.voice_calibration_active_session_id = None
if 'voice_continuous_session_start' not in st.session_state:
    st.session_state.voice_continuous_session_start = 0.0

# Calibration session state.
if 'voice_calibration_session' not in st.session_state:
    st.session_state.voice_calibration_session = None
if 'voice_calibration_active_trial_id' not in st.session_state:
    st.session_state.voice_calibration_active_trial_id = None
if 'voice_calibration_active_measurement_id' not in st.session_state:
    st.session_state.voice_calibration_active_measurement_id = None
if 'voice_calibration_active_measurement_kind' not in st.session_state:
    st.session_state.voice_calibration_active_measurement_kind = None
if 'voice_calibration_measurement_started_at' not in st.session_state:
    st.session_state.voice_calibration_measurement_started_at = None
if 'voice_calibration_phase' not in st.session_state:
    st.session_state.voice_calibration_phase = None
if 'voice_calibration_previous_runtime_mode' not in st.session_state:
    st.session_state.voice_calibration_previous_runtime_mode = None
if 'voice_runtime_mode' not in st.session_state:
    st.session_state.voice_runtime_mode = None

_VOICE_RERUN_KEY = "_voice_needs_rerun"
_VOICE_RERUN_REASON_KEY = "_voice_rerun_reason"


def _request_voice_rerun(reason: str = "") -> None:
    st.session_state[_VOICE_RERUN_KEY] = True
    st.session_state[_VOICE_RERUN_REASON_KEY] = reason


def _maybe_voice_rerun() -> None:
    if st.session_state.get(_VOICE_RERUN_KEY):
        st.session_state[_VOICE_RERUN_KEY] = False
        st.rerun()


def _on_webrtc_state_change() -> None:
    """WebRTC component state-change callback.

    Pushes a lifecycle event to the thread-safe queue. The main Streamlit
    thread drains this queue in _process_voice_events() to update diagnostics
    and audit logs (plan §6).
    """
    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        _voice_lifecycle_events,
        VoiceLifecycleEvent,
    )

    _voice_lifecycle_events.push(
        VoiceLifecycleEvent(
            event_type="webrtc_state_change",
            processor_id=None,
            processor_generation=None,
            timestamp=time.time(),
            desired_mic_playing=None,
            last_frame_age_ms=None,
            extra={"note": "webrtc_state_changed_callback"},
        )
    )


def _set_desired_mic_playing(value: bool, *, reason: str, caller: str) -> None:
    """Central write to desired_mic_playing with audit trail."""
    old = bool(st.session_state.get("desired_mic_playing", False))
    if old == value:
        return
    st.session_state.desired_mic_playing = value
    st.session_state.last_desired_mic_writer = caller
    st.session_state.last_desired_mic_reason = reason
    _append_continuous_trace(
        "desired_mic_playing_changed",
        f"old={old} new={value} reason={reason} caller={caller}",
    )


def _is_continuous_mic_active() -> bool:
    """Return True only when user requested listening AND WebRTC mic is playing."""
    return bool(st.session_state.get("voice_listening")) and _get_webrtc_playing_state()


def _append_continuous_trace(stage: str, note: str = "") -> None:
    """Append a continuous listening trace event to the audit log."""
    from tournament_platform.app.services.voice_parser import VoiceScoreEvent
    _trace_event = VoiceScoreEvent(
        type="trace",
        raw_text="",
        confidence=0.0,
        timestamp=time.time(),
        language=st.session_state.get("voice_streaming_language", "lt"),
    )
    _append_voice_audit(
        _trace_event,
        source="continuous",
        accepted=False,
        previous_score="",
        new_score="",
        note=note,
        stage=stage,
    )


def _append_voice_audit(
    event,
    *,
    source: str,
    accepted: bool,
    previous_score: str = "",
    new_score: str = "",
    note: str = "",
    stage: str = "",
) -> None:
    """Append a structured audit entry to the unified voice_audit_events list."""
    entry = {
        "timestamp": getattr(event, "timestamp", time.time()),
        "event_id": getattr(event, "event_id", ""),
        "source": source,
        "stage": stage,
        "event_type": getattr(event, "type", "unknown"),
        "transcript": getattr(event, "raw_text", getattr(event, "transcript", "")),
        "player": getattr(event, "player", None),
        "score_a": getattr(event, "score_a", None),
        "score_b": getattr(event, "score_b", None),
        "confidence": getattr(event, "confidence", 0.0),
        "accepted": accepted,
        "previous_score": previous_score,
        "new_score": new_score,
        "note": note,
        "speaker_label": getattr(event, "speaker_label", None),
        "language": getattr(event, "language", "en"),
        "asr_latency_ms": getattr(event, "asr_latency_ms", None),
        "noise_rms": getattr(event, "noise_rms", None),
    }
    st.session_state.setdefault("voice_audit_events", []).append(entry)
    if len(st.session_state.voice_audit_events) > 1000:
        st.session_state.voice_audit_events = st.session_state.voice_audit_events[-1000:]


READINESS_FRAME_MAX_AGE_SECONDS = 5.0
READINESS_NO_FRAME_TIMEOUT_SECONDS = 10.0


def resolve_continuous_listening_readiness(
    *,
    webrtc_playing: bool,
    processor: object | None,
    current_time: float | None = None,
) -> dict:
    """Resolve continuous listening readiness from current state.

    Returns a dict with keys:
        ready, status, processor_id, processor_generation,
        webrtc_playing, processor_present, recent_frame_received,
        frame_age_seconds, audio_frames_received, callback_count,
        last_audio_activity_timestamp
    """
    if current_time is None:
        current_time = time.monotonic()

    if not webrtc_playing:
        return {
            "ready": False,
            "status": "MICROPHONE_STOPPED",
            "processor_id": id(processor) if processor is not None else None,
            "processor_generation": getattr(processor, "_processor_generation", None) if processor is not None else None,
            "webrtc_playing": False,
            "processor_present": processor is not None,
            "recent_frame_received": False,
            "frame_age_seconds": None,
            "audio_frames_received": 0,
            "callback_count": 0,
            "last_audio_activity_timestamp": None,
        }

    if processor is None:
        return {
            "ready": False,
            "status": "WAITING_FOR_PROCESSOR",
            "processor_id": None,
            "processor_generation": None,
            "webrtc_playing": webrtc_playing,
            "processor_present": False,
            "recent_frame_received": False,
            "frame_age_seconds": None,
            "audio_frames_received": 0,
            "callback_count": 0,
            "last_audio_activity_timestamp": None,
        }

    processor_id = id(processor)
    processor_generation = getattr(processor, "_processor_generation", None)
    diag = getattr(processor, "get_processor_diagnostics", lambda: {})()
    audio_frames_received = diag.get("audio_frames_received", 0)
    callback_count = diag.get("callback_count", 0)

    # Use ALL available audio-activity timestamps to determine recent activity.
    # The processor exposes last_recv_timestamp, last_recv_queued_timestamp,
    # and last_ingest_timestamp.  Any of these being recent means the
    # microphone is actively delivering audio.
    # Also check last_frame_timestamp for backward compatibility with
    # existing mocks/tests.
    last_recv_ts = diag.get("last_recv_timestamp")
    last_recv_queued_ts = diag.get("last_recv_queued_timestamp")
    last_ingest_ts = diag.get("last_ingest_timestamp")
    last_frame_ts = diag.get("last_frame_timestamp")

    last_audio_activity = None
    for ts in (last_recv_ts, last_recv_queued_ts, last_ingest_ts, last_frame_ts):
        if ts is not None:
            if last_audio_activity is None or ts > last_audio_activity:
                last_audio_activity = ts

    frame_age_seconds = None
    recent_frame = False

    if last_audio_activity is not None:
        frame_age_seconds = current_time - last_audio_activity
        recent_frame = frame_age_seconds <= READINESS_FRAME_MAX_AGE_SECONDS

    if audio_frames_received == 0 and not recent_frame:
        status = "WAITING_FOR_FIRST_FRAME"
    elif recent_frame:
        status = "READY"
    else:
        status = "STALLED"

    return {
        "ready": status == "READY",
        "status": status,
        "processor_id": processor_id,
        "processor_generation": processor_generation,
        "webrtc_playing": webrtc_playing,
        "processor_present": True,
        "recent_frame_received": recent_frame,
        "frame_age_seconds": frame_age_seconds,
        "audio_frames_received": audio_frames_received,
        "callback_count": callback_count,
        "last_audio_activity_timestamp": last_audio_activity,
    }


def _get_webrtc_playing_state() -> bool:
    """Return True if the currently mounted WebRTC streamer is actively playing.

    Reads directly from the current WebRTC context's ``state.playing`` attribute
    — NOT from the cached ``voice_webrtc_streamer_state`` dict, which may be
    stale. The cache was updated by the on_change callback from the previous
    run; the live context reflects the actual frontend state as of this render.

    Falls back to the cached ``voice_webrtc_streamer_state`` dict when the
    live context is not available (e.g. in unit tests).
    """
    raw_ctx = _get_raw_voice_webrtc_context()
    if raw_ctx is not None:
        return bool(getattr(getattr(raw_ctx, "state", None), "playing", False))
    # Fallback for unit tests / backward compatibility
    state = st.session_state.get("voice_webrtc_streamer_state", {})
    return bool(state.get("playing", False) if isinstance(state, dict) else getattr(state, "playing", False))


def _get_raw_voice_webrtc_context():
    """Return the actual WebRtcStreamerContext from streamlit-webrtc.

    This is the single source of truth for the live WebRTC context — it is
    the object stored by streamlit-webrtc itself under the component key
    ``st.session_state["voice_scorekeeper_continuous_webrtc"]``.

    We do NOT use ``st.session_state.voice_webrtc_ctx`` (a page-managed dict
    that may be stale or hold a different processor).
    """
    return st.session_state.get("voice_scorekeeper_continuous_webrtc")


def _reconcile_calibration_measurements(drain_result: object) -> None:
    session = st.session_state.get("voice_calibration_session")
    if session is None or not getattr(drain_result, "calibration_measurements", []):
        return

    from tournament_platform.app.services.voice_calibration.models import (
        CompletedMeasurementRef,
        CalibrationMeasurementKind,
    )

    active_id = st.session_state.get("voice_calibration_active_measurement_id")
    active_kind_str = st.session_state.get("voice_calibration_active_measurement_kind")
    active_kind = (
        CalibrationMeasurementKind(active_kind_str)
        if active_kind_str
        else None
    )

    _append_continuous_trace(
        "calibration_acoustic_reconciliation_started",
        f"session_id={session.session_id[:8]} "
        f"measurements_count={len(drain_result.calibration_measurements)} "
        f"active_id={active_id[:8] if active_id else 'none'} "
        f"active_kind={active_kind.value if active_kind else 'none'}",
    )

    previous_count = len(session.measurements)
    reconciliation = VoiceCalibrationService().reconcile_acoustic_measurements(
        session=session,
        measurements=tuple(drain_result.calibration_measurements),
        active_measurement_id=active_id,
        active_measurement_kind=active_kind,
    )

    if reconciliation.rejection_reasons:
        _append_continuous_trace(
            "calibration_acoustic_reconciliation_skipped",
            f"reasons={','.join(reconciliation.rejection_reasons)} "
            f"consumed={len(reconciliation.consumed_measurement_ids)} "
            f"ignored={len(reconciliation.ignored_measurement_ids)}",
        )
    else:
        _append_continuous_trace(
            "calibration_acoustic_reconciliation_complete",
            f"session_id={reconciliation.session.session_id[:8]} "
            f"consumed={len(reconciliation.consumed_measurement_ids)} "
            f"completed={'yes' if reconciliation.completed_ref else 'no'}",
        )

    st.session_state["voice_calibration_session"] = reconciliation.session
    _append_continuous_trace(
        "calibration_acoustic_session_persisted",
        f"session_id={reconciliation.session.session_id[:8]} "
        f"measurements_before={previous_count} "
        f"measurements_after={len(reconciliation.session.measurements)}",
    )

    if reconciliation.completed_ref is not None:
        st.session_state["calibration_completed_measurement_ref"] = (
            reconciliation.completed_ref
        )
        _append_continuous_trace(
            "calibration_acoustic_completed_ref_stored",
            f"measurement_id={reconciliation.completed_ref.measurement_id[:8]} "
            f"kind={reconciliation.completed_ref.kind.value}",
        )
    else:
        st.session_state.pop("calibration_completed_measurement_ref", None)

    st.session_state.pop("voice_calibration_active_measurement_id", None)
    st.session_state.pop("voice_calibration_active_measurement_kind", None)
    st.session_state.pop("voice_calibration_measurement_started_at", None)
    st.session_state.pop("voice_calibration_arm_error", None)
    st.session_state.pop("voice_calibration_reconciliation_error", None)

    _append_continuous_trace(
        "calibration_acoustic_active_keys_cleared",
        f"completed_ref_available={'yes' if reconciliation.completed_ref else 'no'}",
    )


# ============================================================================
# Voice Session Epoch
# ============================================================================

def _get_voice_session_epoch() -> int:
    current = st.session_state.get("voice_session_epoch", 1)
    st.session_state.voice_session_epoch = current
    return current


def _increment_voice_session_epoch() -> None:
    current = st.session_state.get("voice_session_epoch", 1)
    st.session_state.voice_session_epoch = current + 1


def _disable_continuous_listening() -> None:
    """Stop continuous listening, clear queues, and deactivate the WebRTC component."""
    st.session_state.voice_listening = False
    st.session_state.voice_capture_requested = False
    st.session_state.voice_events_enabled = False
    st.session_state.voice_continuous_session_id = None
    st.session_state.voice_continuous_session_start = 0.0

    _proc = _get_current_webrtc_processor()
    if _proc is not None:
        try:
            _proc.stop()
            with _proc._lock:
                while not _proc._chunk_queue.empty():
                    try:
                        _proc._chunk_queue.get_nowait()
                    except queue.Empty:
                        break
                while not _proc.event_queue.empty():
                    try:
                        _proc.event_queue.get_nowait()
                    except queue.Empty:
                        break
        except Exception:
            pass

    st.session_state.pending_confirmations = []
    st.session_state.last_voice_transcript = ""
    st.session_state.last_voice_event = None
    st.session_state.last_voice_feedback = ""
    st.session_state.last_voice_rejection_reason = ""
    st.session_state.last_voice_success_message = ""
    st.session_state.last_voice_action_taken = ""
    st.session_state.last_voice_continuous_transcript = ""
    st.session_state.last_voice_push_to_talk_transcript = ""
    st.session_state.last_voice_debug_transcript = ""
    st.session_state.voice_event_log = []
    st.session_state.voice_audit_events = []
    st.session_state.voice_scoreboard_rerun_requested = False
    st.session_state.voice_scoreboard_rerun_reason = ""
    st.session_state.voice_scoreboard_rerun_event_id = None
    st.session_state.voice_scoreboard_rerun_consumed_at = 0.0
    st.session_state.last_applied_voice_event_ids = []
    st.session_state.voice_last_applied_event_key = None
    st.session_state.voice_last_applied_event_ts = 0.0
    _increment_voice_session_epoch()

    machine = st.session_state.get("voice_confirmation_machine")
    if machine:
        machine.reset()


# ============================================================================
# Audio Rally Assistant (TT Sounds) Helpers
# ============================================================================

def _clear_tt_sounds_state() -> None:
    """Disable audio rally assistant and clear all pending tt_sounds state."""
    st.session_state.tt_sounds_enabled = False
    st.session_state.tt_sounds_recent_events = []
    st.session_state.tt_sounds_rally_context = None
    st.session_state.tt_sounds_audio_summaries = []
    st.session_state.tt_sounds_unavailable_notice_shown = False
    _proc = _get_current_webrtc_processor()
    if _proc is not None:
        try:
            tt_proc = getattr(_proc, "tt_sounds_processor", None)
            if tt_proc is not None:
                tt_proc.stop()
        except Exception:
            pass


def finalize_current_audio_rally(reason: str = "gap") -> Optional[Any]:
    """Finalize the current audio rally and store the summary."""
    manager = st.session_state.get("tt_sounds_rally_manager")
    if manager is None:
        return None
    summary = manager.finalize_current_rally(last_action=reason)
    if summary is not None:
        st.session_state.tt_sounds_rally_context = manager.current_context()
    return summary


def _mark_last_audio_summary_action(last_action: str) -> None:
    """Mark the most recent audio summary with the given action."""
    summaries = st.session_state.get("tt_sounds_audio_summaries", [])
    if summaries:
        summaries[-1].last_action = last_action


def _enable_continuous_listening() -> None:
    """Arm continuous listening mode and request WebRTC microphone capture."""
    import uuid
    st.session_state.voice_listening = True
    st.session_state.voice_capture_requested = True
    st.session_state.voice_stop_requested = False
    st.session_state.voice_events_enabled = True
    st.session_state.voice_continuous_session_id = str(uuid.uuid4())
    st.session_state.voice_continuous_session_start = time.time()
    st.session_state.voice_stale_events_ignored = 0

    st.session_state.last_voice_transcript = ""
    st.session_state.last_voice_event = None
    st.session_state.last_voice_feedback = ""
    st.session_state.last_voice_rejection_reason = ""
    st.session_state.last_voice_success_message = ""
    st.session_state.last_voice_action_taken = ""
    st.session_state.last_voice_continuous_transcript = ""
    st.session_state.last_voice_push_to_talk_transcript = ""
    st.session_state.last_voice_debug_transcript = ""
    _append_continuous_trace("continuous_requested", f"session={st.session_state.voice_continuous_session_id[:8]}")


def _start_streaming_voice_session() -> None:
    """Record startup intent for one-click streaming voice scoring.

    Does not create or attach any backend.  The actual two-phase startup
    (microphone + Deepgram) is performed by ``_process_streaming_startup()``
    after the WebRTC component is rendered and the processor is available.
    """
    import uuid as _uuid

    st.session_state.voice_start_requested = True
    _set_desired_mic_playing(True, reason="user_start_clicked", caller="_start_streaming_voice_session")
    st.session_state.streaming_ui_state = "starting_microphone"
    st.session_state.streaming_start_request_id = str(_uuid.uuid4())
    st.session_state.streaming_start_requested_at = time.time()
    st.session_state.streaming_start_microphone_confirmed_at = None
    st.session_state.streaming_start_backend_attached_at = None
    st.session_state.streaming_start_completed_at = None
    st.session_state.voice_streaming_error = None
    st.session_state.voice_streaming_last_error_code = None

    _provider_name = st.session_state.get("voice_streaming_provider") or "deepgram"
    _language = st.session_state.get("voice_streaming_language") or "lt"
    _match_id = st.session_state.get("voice_selected_match_id")
    _session_id = st.session_state.get("voice_continuous_session_id") or str(_uuid.uuid4())

    st.session_state.voice_streaming_diagnostics = {
        "provider": _provider_name,
        "language": _language,
        "match_id": str(_match_id) if _match_id else "none",
        "voice_session_id": _session_id[:8] + "...",
        "backend_generation": st.session_state.voice_streaming_backend_gen,
        "audio_delivery_mode": "batch",
    }


def _stop_streaming_voice_session() -> None:
    """Stop the streaming backend session (Step 9: voice scoring stop).

    Invalidates generation -> closes backend -> drains queues.
    Idempotent: safe to call multiple times.
    """
    st.session_state.voice_streaming_state = "stopping"
    st.session_state.streaming_ui_state = "stopping"
    st.session_state.streaming_start_request_id = None
    st.session_state.streaming_start_requested_at = None
    st.session_state.streaming_start_microphone_confirmed_at = None
    st.session_state.streaming_start_backend_attached_at = None
    st.session_state.streaming_start_completed_at = None

    _terminate_streaming_voice_session(
        reason="user_stop_clicked",
        final_state="disabled",
    )


def _process_streaming_startup() -> None:
    """Two-phase streaming startup: wait for microphone, then attach Deepgram.

    Phase A: wait for WebRTC microphone to become active.
    Phase B: wait for VoiceAudioProcessor, then attach and start Deepgram.

    Idempotent: repeated calls during the same startup request are safe.
    """
    import time as _time

    _request_id = st.session_state.get("streaming_start_request_id")
    if not _request_id:
        return

    _requested_at = st.session_state.get("streaming_start_requested_at") or _time.time()
    _mic_confirmed_at = st.session_state.get("streaming_start_microphone_confirmed_at")
    _backend_attached_at = st.session_state.get("streaming_start_backend_attached_at")
    _completed_at = st.session_state.get("streaming_start_completed_at")

    # If startup already completed, nothing to do.
    if _completed_at is not None:
        return

    # Invalidate confirmation timestamps from previous requests.
    if _mic_confirmed_at is not None and _mic_confirmed_at < _requested_at:
        st.session_state.streaming_start_microphone_confirmed_at = None
        _mic_confirmed_at = None
    if _backend_attached_at is not None and _backend_attached_at < _requested_at:
        st.session_state.streaming_start_backend_attached_at = None
        _backend_attached_at = None
    if _completed_at is not None and _completed_at < _requested_at:
        st.session_state.streaming_start_completed_at = None
        _completed_at = None

    _webrtc_ctx = _get_raw_voice_webrtc_context()
    _proc = _get_current_webrtc_processor()
    _webrtc_playing = _get_webrtc_playing_state()

    # --- Terminal state: microphone confirmed ---
    if _webrtc_playing and _mic_confirmed_at is None:
        st.session_state.streaming_start_microphone_confirmed_at = _time.time()
        _append_continuous_trace(
            "microphone_start_confirmed",
            f"request_id={_request_id[:8]} processor_id={id(_proc) if _proc is not None else 'none'}",
        )

    # --- Phase A: microphone startup (only if not confirmed) ---
    if not _webrtc_playing:
        if _mic_confirmed_at is not None:
            # Microphone was playing but stopped. This is handled by
            # _refresh_streaming_diagnostics() unexpected-stop logic.
            return

        _mic_elapsed = _time.time() - _requested_at
        if _mic_elapsed > VOICE_MIC_START_TIMEOUT_SECONDS:
            _fail_startup(
                request_id=_request_id,
                phase="microphone_start",
                category="microphone_timeout",
                safe_message=(
                    "Microphone did not become active within timeout. "
                    "Check browser microphone permission, audio device, and secure origin (HTTPS)."
                ),
            )
            return

        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.voice_streaming_state = "starting_microphone"
        return

    # Microphone is playing. If no processor yet, wait for it.
    if _proc is None:
        _proc_elapsed = _time.time() - _requested_at
        if _proc_elapsed > VOICE_PROCESSOR_WAIT_TIMEOUT_SECONDS:
            _fail_startup(
                request_id=_request_id,
                phase="processor_wait",
                category="processor_timeout",
                safe_message="WebRTC microphone started but audio processor is not available.",
            )
            return

        st.session_state.streaming_ui_state = "waiting_for_processor"
        st.session_state.voice_streaming_state = "waiting_for_processor"
        return

    # --- Phase B: Deepgram attachment ---
    _provider_name = st.session_state.get("voice_streaming_provider") or "deepgram"
    _language = st.session_state.get("voice_streaming_language") or "lt"
    _match_id = st.session_state.get("voice_selected_match_id")
    _session_id = st.session_state.get("voice_continuous_session_id") or str(uuid.uuid4())

    # Build domain-specific keyterms (Phase 10)
    _biasing_terms = []
    try:
        from tournament_platform.app.services.voice_vocab import VoiceVocabulary
        _vocab = VoiceVocabulary.load()
        _biasing_terms.extend(_vocab.get_biasing_words())
        
        # Add Lithuanian-specific scoring terms if language matches
        if _language == "lt":
            _biasing_terms.extend(["taškas", "kairė", "dešinė", "atšaukti", "atgal"])
            
        # Add current player names for biasing
        _p1_name = st.session_state.get("selected_player_a", {}).get("name")
        _p2_name = st.session_state.get("selected_player_b", {}).get("name")
        if _p1_name: _biasing_terms.append(_p1_name)
        if _p2_name: _biasing_terms.append(_p2_name)
    except Exception as exc:
        logger.debug("Failed to build biasing terms: %s", exc)

    _proc_id = id(_proc)
    _proc_gen = getattr(_proc, "_processor_generation", 0)

    # If backend already attached to this processor, mark completed and return.
    if st.session_state.get("streaming_processor_id") == _proc_id:
        _existing_gen = st.session_state.get("streaming_processor_generation")
        _current_gen = getattr(_proc, "_streaming_generation", 0)
        if _existing_gen is not None and _current_gen == _existing_gen and _current_gen > 0:
            if st.session_state.get("streaming_start_completed_at") is None:
                st.session_state.streaming_start_completed_at = _time.time()
                st.session_state.streaming_start_request_id = None
                st.session_state.streaming_start_requested_at = None
                st.session_state.voice_start_requested = False
                _append_continuous_trace(
                    "startup_completed",
                    f"request_id={_request_id[:8]} processor_id={_proc_id} generation={_proc_gen}",
                )
            st.session_state.voice_streaming_state = "connecting"
            st.session_state.streaming_ui_state = "connecting"
            return

    _result = ASRBackendFactory.create_streaming(backend_name=_provider_name)
    if not _result.available:
        _fail_startup(
            request_id=_request_id,
            phase="backend_attach",
            category="provider_unavailable",
            safe_message=_result.safe_message,
        )
        return

    _backend = _result.backend
    if _backend is None:
        _fail_startup(
            request_id=_request_id,
            phase="backend_attach",
            category="backend_missing",
            safe_message="Streaming backend is not available.",
        )
        return

    try:
        _proc.set_streaming_backend(
            _backend,
            voice_session_id=_session_id,
            match_id=_match_id,
            language=_language,
            keyterms=_biasing_terms,
        )
    except Exception as exc:
        _fail_startup(
            request_id=_request_id,
            phase="backend_attach",
            category="backend_attach_exception",
            safe_message=str(exc),
        )
        return

    _new_gen = getattr(_proc, "_streaming_generation", 0)
    _new_session_id = getattr(_proc, "_streaming_voice_session_id", None)

    if _new_gen <= 0 or not _new_session_id:
        _fail_startup(
            request_id=_request_id,
            phase="backend_attach",
            category="invalid_streaming_session",
            safe_message="Backend attachment did not produce a valid streaming session.",
        )
        return

    st.session_state.voice_streaming_config_frozen = True
    st.session_state.voice_streaming_state = "connecting"
    st.session_state.streaming_ui_state = "connecting"
    st.session_state.voice_streaming_session_id = _new_session_id
    st.session_state.voice_streaming_backend_gen = _new_gen
    st.session_state.voice_continuous_session_id = _new_session_id
    st.session_state.voice_listening = True
    st.session_state.voice_events_enabled = True
    st.session_state.streaming_processor_id = _proc_id
    st.session_state.streaming_processor_generation = _new_gen
    # Capture canonical identity tuple for validation (plan §7)
    st.session_state.streaming_session_identity = StreamingSessionIdentity(
        voice_session_id=_new_session_id,
        processor_id=_proc_id,
        processor_generation=_proc_gen,
        backend_generation=_new_gen,
        match_id=str(_match_id) if _match_id else "",
        language=_language,
    )
    st.session_state.voice_streaming_diagnostics = {
        "provider": _provider_name,
        "language": _language,
        "match_id": str(_match_id) if _match_id else "none",
        "voice_session_id": _new_session_id[:8] + "...",
        "backend_generation": _new_gen,
        "audio_delivery_mode": "stream",
    }

    st.session_state.streaming_start_backend_attached_at = _time.time()
    st.session_state.streaming_start_completed_at = _time.time()
    st.session_state.streaming_start_request_id = None
    st.session_state.streaming_start_requested_at = None
    st.session_state.voice_start_requested = False

    _append_continuous_trace(
        "streaming_backend_attached",
        f"backend={_provider_name} language={_language} request_id={_request_id[:8]} processor_id={_proc_id} generation={_proc_gen}",
    )


def _fail_startup(
    *,
    request_id: str,
    phase: str,
    category: str,
    safe_message: str,
) -> None:
    """Rollback a failed startup attempt and re-enable Start.

    Validates that the failure belongs to the current active request and
    that the microphone was not already confirmed for this request.
    """
    _current_request_id = st.session_state.get("streaming_start_request_id")
    if _current_request_id != request_id:
        _append_continuous_trace(
            "stale_startup_timeout_ignored",
            f"request_id={request_id[:8]} current={(_current_request_id or 'none')[:8]} phase={phase}",
        )
        return

    _mic_confirmed_at = st.session_state.get("streaming_start_microphone_confirmed_at")
    if _mic_confirmed_at is not None and phase == "microphone_start":
        _append_continuous_trace(
            "stale_startup_timeout_ignored",
            f"request_id={request_id[:8]} phase={phase} microphone_already_confirmed={_mic_confirmed_at}",
        )
        return

    _completed_at = st.session_state.get("streaming_start_completed_at")
    if _completed_at is not None:
        _append_continuous_trace(
            "stale_startup_timeout_ignored",
            f"request_id={request_id[:8]} phase={phase} startup_already_completed={_completed_at}",
        )
        return

    _proc = _get_current_webrtc_processor()
    if _proc is not None and hasattr(_proc, "clear_streaming_backend"):
        try:
            _proc.clear_streaming_backend()
        except Exception:
            pass

    st.session_state.voice_start_requested = False
    _set_desired_mic_playing(False, reason=category, caller="_fail_startup")
    st.session_state.streaming_ui_state = "failed"
    st.session_state.voice_streaming_state = "failed"
    st.session_state.voice_streaming_config_frozen = False
    st.session_state.voice_streaming_error = safe_message
    st.session_state.voice_streaming_last_error_code = category
    st.session_state.streaming_processor_id = None
    st.session_state.streaming_processor_generation = None
    st.session_state.streaming_start_request_id = None
    st.session_state.streaming_start_requested_at = None
    st.session_state.streaming_start_microphone_confirmed_at = None
    st.session_state.streaming_start_backend_attached_at = None
    st.session_state.streaming_start_completed_at = None

    _append_continuous_trace(
        "startup_failed",
        f"request_id={request_id[:8]} phase={phase} category={category} reason={safe_message}",
    )


def _get_start_block_reason(
    can_start: bool,
    config_frozen: bool,
    status: Any,
    has_active_backend: bool,
    ui_state_now: str,
    voice_mode_allows_streaming: bool,
) -> str:
    """Return a human-readable reason why Start is disabled, or 'allowed'."""
    if can_start:
        return "allowed"
    if config_frozen:
        return "config_frozen"
    if not voice_mode_allows_streaming:
        return "voice_mode_off"
    if not status.available:
        return "backend_not_configured"
    if has_active_backend:
        return "active_backend_running"
    if ui_state_now not in ("disabled", "failed", "microphone_stopped"):
        return f"ui_state={ui_state_now}"
    return "unknown"


def _terminate_streaming_voice_session(
    *,
    reason: str,
    final_state: str = "failed",
) -> None:
    """Canonical idempotent cleanup for terminating a streaming voice session.

    Used for: user stop, unexpected WebRTC stop, processor replacement,
    backend failure, match change, language change, startup rollback.

    Clears all session state, closes the backend, and resets the processor.
    Safe to call multiple times.
    """
    _proc = _get_current_webrtc_processor()

    _backend = getattr(_proc, "_streaming_backend", None) if _proc is not None else None
    if _backend is None:
        _backend = st.session_state.get("voice_streaming_backend")

    if _proc is not None and hasattr(_proc, "clear_streaming_backend"):
        try:
            _proc.clear_streaming_backend()
        except Exception as exc:
            logger.debug("_terminate_streaming_voice_session: clear_streaming_backend error: %s", exc)
    # Explicitly null the backend reference on the proc for idempotency
    if _proc is not None:
        _proc._streaming_backend = None

    # Also close the backend directly from session_state if still present
    if _backend is not None:
        if hasattr(_backend, "close"):
            try:
                _backend.close()
            except Exception as exc:
                logger.debug("_terminate_streaming_voice_session: backend close error: %s", exc)
        try:
            if hasattr(_backend, "clear_pending_media"):
                _backend.clear_pending_media()
        except Exception as exc:
            logger.debug("_terminate_streaming_voice_session: clear_pending_media error: %s", exc)

    # Cancel any pending startup/connect timers
    _start_requested = bool(st.session_state.get("voice_start_requested", False))
    st.session_state.voice_start_requested = False

    # Clear all streaming-related session state
    st.session_state.voice_streaming_state = final_state
    st.session_state.streaming_ui_state = final_state
    st.session_state.voice_streaming_config_frozen = False
    st.session_state.voice_streaming_session_id = None
    st.session_state.voice_streaming_backend_gen = 0
    st.session_state.voice_continuous_session_id = None
    st.session_state.streaming_processor_id = None
    st.session_state.streaming_processor_generation = None
    st.session_state.voice_listening = False
    st.session_state.voice_events_enabled = False
    st.session_state.voice_capture_requested = False
    st.session_state.voice_continuous_requested = False
    st.session_state.desired_mic_playing = False
    st.session_state.last_desired_mic_writer = "_terminate_streaming_voice_session"
    st.session_state.last_desired_mic_reason = reason
    st.session_state.unexpected_webrtc_stop_ts = None
    st.session_state.unexpected_webrtc_stop_count = st.session_state.get("unexpected_webrtc_stop_count", 0) + (1 if "unexpected" in reason else 0)
    st.session_state.last_session_termination_reason = reason
    st.session_state._voice_current_processor_id = None
    st.session_state.voice_streaming_backend = None

    # Record recovery metrics
    _diag = st.session_state.get("voice_streaming_diagnostics", {})
    _diag["streaming_config_frozen"] = False
    _diag["last_session_termination_reason"] = reason
    _diag["unexpected_webrtc_stop_count"] = st.session_state.get("unexpected_webrtc_stop_count", 0)
    _diag["audio_delivery_mode"] = getattr(_proc, "effective_delivery_mode", "batch") if _proc else "batch"
    st.session_state.voice_streaming_diagnostics = _diag

    _append_continuous_trace(
        "streaming_session_terminated",
        f"reason={reason} final_state={final_state} gen_invalidated=True",
    )

    if _start_requested:
        _append_continuous_trace("start_request_cancelled", f"reason={reason}")


def _refresh_streaming_diagnostics(snapshot: WebRtcRenderSnapshot) -> None:
    """Throttled diagnostic refresh (250-500 ms).  Interim is droppable; finalized is not."""
    # --- Current processor: read from the authoritative snapshot ---
    _proc = snapshot.processor
    _current_processor_id = snapshot.processor_id
    _prev_processor_id = st.session_state.get("_voice_current_processor_id")

    # --- Current WebRTC playing state: read from the authoritative snapshot ---
    _webrtc_playing = snapshot.playing
    _desired_mic_playing = bool(st.session_state.get("desired_mic_playing", False))

    if _proc is None:
        # If playing=True but processor is None, this is a transient reference
        # gap during worker/context transitions. Preserve previous ownership
        # for a bounded reconciliation period (500ms) rather than immediately
        # disabling the session.
        if _webrtc_playing and _desired_mic_playing and _prev_processor_id is not None:
            _gap_ts = st.session_state.get("_voice_processor_gap_ts")
            if _gap_ts is None:
                st.session_state._voice_processor_gap_ts = time.time()
                _append_continuous_trace(
                    "processor_reference_temporarily_unavailable",
                    f"playing=True processor=None "
                    f"prev_processor_id={_prev_processor_id} "
                    f"reconciliation_window=500ms",
                )
                return  # wait for reconciliation — do NOT terminate
            elif time.time() - _gap_ts < 0.5:
                return  # still within reconciliation window
            else:
                # Gap timeout — the processor didn't come back. Terminate.
                _append_continuous_trace(
                    "processor_reference_timed_out",
                    f"timeout=500ms prev_processor_id={_prev_processor_id}",
                )
                st.session_state._voice_processor_gap_ts = None

        st.session_state.voice_streaming_state = "disabled"
        st.session_state.streaming_ui_state = "disabled"
        st.session_state.voice_streaming_config_frozen = False
        st.session_state._voice_current_processor_id = None
        st.session_state._voice_processor_gap_ts = None
        _diag = st.session_state.get("voice_streaming_diagnostics", {})
        _diag.pop("connection_state", None)
        _diag.pop("connection_opened_at", None)
        _diag.pop("last_error_category", None)
        _diag.pop("last_error_message_safe", None)
        _diag.pop("last_close_code", None)
        _diag.pop("last_close_reason_safe", None)
        _diag.pop("credentials_configured", None)
        _diag["audio_delivery_mode"] = "batch"
        st.session_state.voice_streaming_diagnostics = _diag
        return

    # --- Detect processor replacement (ownership change) ---
    _processor_changed = (_current_processor_id != _prev_processor_id)
    if _processor_changed:
        if _prev_processor_id is not None:
            # The previous processor has been replaced. Its backend is stale.
            # Close immediately — do NOT use the page-managed voice_webrtc_ctx
            # dict which may point to the wrong processor.
            _prev_session = st.session_state.get("voice_webrtc_ctx")
            _prev_proc = None
            if _prev_session and isinstance(_prev_session, dict):
                _prev_proc = _prev_session.get("processor")
            # If the cached proc doesn't match the old ID, we can't close it
            # by reference — log the mismatch.
            if _prev_proc is not None and id(_prev_proc) == _prev_processor_id:
                _prev_backend = getattr(_prev_proc, "_streaming_backend", None)
                if _prev_backend is not None and hasattr(_prev_backend, "close"):
                    try:
                        _prev_backend.close()
                    except Exception:
                        pass
            _append_continuous_trace(
                "processor_replacement_candidate",
                f"old_processor_id={_prev_processor_id} "
                f"new_processor_id={_current_processor_id} "
                f"webrtc_playing={_webrtc_playing} "
                f"desired_mic_playing={_desired_mic_playing} "
                f"factory_object_id={id(st.session_state.get('voice_webrtc_tracked_factory'))} "
                f"voice_session_id={st.session_state.get('voice_continuous_session_id', '—')}",
            )
            _append_continuous_trace(
                "processor_replacement_confirmed",
                f"old_processor_id={_prev_processor_id} "
                f"new_processor_id={_current_processor_id} "
                f"webrtc_playing={_webrtc_playing} "
                f"desired_mic_playing={_desired_mic_playing}",
            )
        st.session_state._voice_current_processor_id = _current_processor_id
    # NOTE: Do NOT clear unexpected_webrtc_stop_ts when processor hasn't changed.
    # It must only be cleared when WebRTC is playing again (in the stop check below).

    # Update streaming_processor_id/streaming_processor_generation in session state
    # if this is a valid processor that should own the backend.
    _streaming_proc_id = st.session_state.get("streaming_processor_id")
    _streaming_proc_gen = st.session_state.get("streaming_processor_generation")
    if _streaming_proc_id is not None:
        if _current_processor_id != _streaming_proc_id:
            # --- Ownership mismatch: stale backend attached to old processor ---
            st.session_state.processor_ownership_mismatch = True
            _append_continuous_trace(
                "processor_ownership_mismatch",
                f"current_processor_id={_current_processor_id} "
                f"streaming_processor_id={_streaming_proc_id} "
                f"webrtc_playing={_webrtc_playing} "
                f"desired_mic_playing={_desired_mic_playing}",
            )
            # Immediate controlled recovery: close backend on OLD processor,
            # invalidate session, keep Start enabled.
            _terminate_streaming_voice_session(
                reason="processor_ownership_mismatch",
                final_state="failed",
            )
            _append_continuous_trace(
                "processor_ownership_mismatch_cleanup",
                f"backend_closed current_processor_id={_current_processor_id} "
                f"streaming_processor_id={_streaming_proc_id}",
            )
            return

    _backend = getattr(_proc, "_streaming_backend", None)
    _backend_state = "disabled"
    _connection_info = {}
    if _backend is not None and hasattr(_backend, "connection_state"):
        _backend_state = _backend.connection_state()
        if hasattr(_backend, "get_connection_info"):
            _connection_info = _backend.get_connection_info() or {}

    _state = st.session_state.voice_streaming_state

    # --- Unexpected WebRTC stop while backend is active ---
    # Use a short grace period (250ms) for transient drops, then clean up.
    # Do NOT skip cleanup on processor change — the new processor is the
    # authority and its backend state should be respected.
    if _backend is not None and _backend_state in ("connected", "connecting", "reconnecting"):
        if not _webrtc_playing:
            _stop_ts = st.session_state.get("unexpected_webrtc_stop_ts")
            if _stop_ts is None:
                st.session_state.unexpected_webrtc_stop_ts = time.time()
                _append_continuous_trace(
                    "unexpected_webrtc_stop_candidate",
                    f"desired_mic_playing={_desired_mic_playing} "
                    f"webrtc_playing=False stop_ts={time.time()}",
                )
            elif time.time() - _stop_ts >= 0.25:
                _terminate_streaming_voice_session(
                    reason="unexpected_webrtc_stop",
                    final_state="failed",
                )
                _append_continuous_trace(
                    "unexpected_webrtc_stop_confirmed",
                    "backend_closed_after_grace_period",
                )
                return
        else:
            st.session_state.unexpected_webrtc_stop_ts = None
    else:
        st.session_state.unexpected_webrtc_stop_ts = None

    # Stale connected backend: backend connected but WebRTC is not playing
    # and the microphone was never confirmed as playing. Close immediately.
    if _backend is not None and _backend_state == "connected" and not _webrtc_playing and not _desired_mic_playing:
        _terminate_streaming_voice_session(
            reason="stale_connected_backend",
            final_state="disabled",
        )
        return

    if _backend is None:
        _terminate_streaming_voice_session(
            reason="backend_detached",
            final_state="disabled",
        )
        return

    if _backend_state == "connected":
        if _state in ("connecting", "reconnecting"):
            if not _webrtc_playing:
                st.session_state.voice_streaming_state = "microphone_stopped"
                st.session_state.streaming_ui_state = "microphone_stopped"
            else:
                st.session_state.voice_streaming_state = "ready"
                st.session_state.streaming_ui_state = "ready"
        elif _state == "ready":
            if st.session_state.voice_listening and _webrtc_playing:
                st.session_state.voice_streaming_state = "listening"
                st.session_state.streaming_ui_state = "listening"
            elif not _webrtc_playing:
                # playing=False must never produce Ready.
                st.session_state.voice_streaming_state = "microphone_stopped"
                st.session_state.streaming_ui_state = "microphone_stopped"
            else:
                st.session_state.voice_streaming_state = "ready"
                st.session_state.streaming_ui_state = "ready"
        elif _state == "listening":
            if not _desired_mic_playing or not _webrtc_playing:
                st.session_state.voice_streaming_state = "ready"
                st.session_state.streaming_ui_state = "ready"
    elif _backend_state == "failed":
        st.session_state.voice_streaming_state = "failed"
        st.session_state.streaming_ui_state = "failed"
        if _connection_info.get("last_error_message_safe"):
            st.session_state.voice_streaming_error = _connection_info["last_error_message_safe"]
        elif _connection_info.get("last_error_category"):
            st.session_state.voice_streaming_error = _connection_info["last_error_category"].replace("_", " ").title()
    elif _backend_state in ("connecting", "starting", "reconnecting"):
        if _state not in ("disabled", "stopping", "failed"):
            st.session_state.voice_streaming_state = _backend_state
            st.session_state.streaming_ui_state = _backend_state
    elif _backend_state in ("stopped", "disconnected"):
        if _state not in ("disabled", "stopping", "failed"):
            st.session_state.voice_streaming_state = "disabled"
            st.session_state.streaming_ui_state = "disabled"

    _finalized_diags = getattr(_proc, "get_streaming_diagnostics", lambda: {})()
    _finalized = _finalized_diags.get("last_final_text", "")
    if _finalized:
        st.session_state.voice_streaming_last_finalized = _finalized
    _interim = _finalized_diags.get("last_interim_text", "")
    if _interim:
        st.session_state.voice_streaming_last_interim = _interim

    _diag = st.session_state.get("voice_streaming_diagnostics", {})
    _diag.update(_finalized_diags)
    _diag.update(_connection_info)
    _diag["audio_delivery_mode"] = getattr(_proc, "effective_delivery_mode", "batch")
    # Expose provider_connected separately from voice_scoring_ready
    _diag["provider_connected"] = (_backend_state == "connected")
    _diag["backend_identity_matches_current_processor"] = (
        _current_processor_id == _streaming_proc_id
    )
    _diag["voice_scoring_ready"] = bool(
        _webrtc_playing
        and _proc is not None
        and _backend is not None
        and _backend_state == "connected"
        and _current_processor_id == _streaming_proc_id
    )
    _diag["processor_ownership_mismatch"] = bool(
        _streaming_proc_id is not None
        and _current_processor_id != _streaming_proc_id
    )
    st.session_state.voice_streaming_diagnostics = _diag
    st.session_state.voice_streaming_last_refresh = time.time()


def _append_audio_commentary_line(audio_summary: Any) -> None:
    """Append a conservative audio commentary line after score commentary."""
    if audio_summary is None:
        return
    n = audio_summary.impact_count
    lang = st.session_state.get("commentary_language", "en")
    if lang == "lt":
        text = f"Garso sistema aptiko galimus {n} smūgius prieš tašką."
    else:
        text = f"Possible rally of {n} impacts detected before the point."
    st.session_state.pending_commentary = text


def is_voice_scoring_enabled() -> bool:
    """Return True when the voice scoring toggle is enabled in session state."""
    return bool(st.session_state.get("voice_scoring_enabled", False))


def reject_if_voice_disabled(source: str) -> bool:
    """Return True if the given voice source should be rejected because voice scoring is disabled."""
    if source in {"voice", "continuous", "push_to_talk", "asr", "webrtc", "debug_voice"}:
        return not is_voice_scoring_enabled()
    return False


def apply_score_event_and_refresh_ui(
    transcript: str,
    source: str = "asr",
    enable_confirmation: bool = VOICE_ENABLE_CONFIRMATION,
    current_score_a: Optional[int] = None,
    current_score_b: Optional[int] = None,
    selected_match_id: Optional[int] = None,
) -> ScoreApplyResult:
    """Canonical function for all voice scoring paths.

    Single pipeline: validate context → normalize → parse → route → apply → refresh UI.
    """
    mm = st.session_state.get("match_manager")
    if mm is None:
        return ScoreApplyResult(
            success=False,
            reason="no_match_manager",
            previous_score="",
            new_score="",
            parsed=None,
            route_result=None,
        )

    # Resolve selected match ID: prefer explicit arg, fall back to session state.
    if selected_match_id is None:
        selected_match_id = st.session_state.get("voice_selected_match_id")

    # Match-context validation: voice scoring requires an active match selection.
    if not selected_match_id:
        st.session_state.last_voice_feedback = "no_match_selected"
        st.session_state.last_voice_rejection_reason = "no_match_selected"
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "rejected"
        return ScoreApplyResult(
            success=False,
            reason="no_match_selected",
            previous_score=mm.state.get_score_string(),
            new_score=mm.state.get_score_string(),
            parsed=None,
            route_result=None,
        )

    # Match-context validation: ensure MatchManager players match the selected match.
    _selected_p1_id = st.session_state.get("voice_selected_player1_id")
    _selected_p2_id = st.session_state.get("voice_selected_player2_id")
    if _selected_p1_id is not None and _selected_p2_id is not None:
        if (
            str(mm.state.player_a_id) != str(_selected_p1_id)
            or str(mm.state.player_b_id) != str(_selected_p2_id)
        ):
            _err_msg = f"match_context_mismatch: mm_p1={mm.state.player_a_id} sel_p1={_selected_p1_id}"
            st.session_state.last_voice_feedback = "voice_match_context_mismatch"
            st.session_state.last_voice_rejection_reason = _err_msg
            st.session_state.last_voice_success_message = ""
            st.session_state.last_voice_action_taken = "rejected"
            return ScoreApplyResult(
                success=False,
                reason="voice_match_context_mismatch",
                previous_score=mm.state.get_score_string(),
                new_score=mm.state.get_score_string(),
                parsed=None,
                route_result=None,
            )

    current_score = mm.state.get_score_string()

    if source in {VoiceTranscriptSource.CALIBRATION, "calibration"}:
        return ScoreApplyResult(
            success=False,
            reason="calibration_source_cannot_mutate_score",
            previous_score=current_score,
            new_score=current_score,
            parsed=None,
            route_result=None,
        )

    # HARD GATE: reject all voice commands when voice scoring is disabled
    if reject_if_voice_disabled(source):
        st.session_state.last_voice_feedback = "voice_scoring_disabled"
        st.session_state.last_voice_rejection_reason = "voice_scoring_disabled"
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "rejected"
        return ScoreApplyResult(
            success=False,
            reason="voice_scoring_disabled",
            previous_score=current_score,
            new_score=current_score,
            parsed=None,
            route_result=None,
        )

    if current_score_a is None:
        current_score_a = mm.state.score_a
    if current_score_b is None:
        current_score_b = mm.state.score_b

    language = st.session_state.get("voice_selected_language", "en")

    # 1. Normalize
    processed = TranscriptPostProcessor(VoiceVocabulary.load()).process(transcript, language=language)

    # 2. Parse
    parsed = parse_command(
        processed,
        current_score_a=current_score_a,
        current_score_b=current_score_b,
    )
    st.session_state.voice_parser_last_result = f"intent={parsed.intent}, side={getattr(parsed, 'target_side', 'N/A')}"
    st.session_state.voice_last_confidence = parsed.confidence
    parsed.source = source
    parsed.language = language

    # Resolve target_side to player if present
    if getattr(parsed, 'target_side', None) and parsed.intent == VoiceIntent.SCORE_POINT:
        from tournament_platform.app.services.voice_scorekeeper.scoring_actions import resolve_side_to_player
        resolved_player = resolve_side_to_player(parsed.target_side, mm.engine)
        if resolved_player:
            parsed.slots["player"] = resolved_player

    # Capture the game index BEFORE applying so we can detect a game-completed
    # transition on this command and refresh dedup/voice state accordingly.
    _game_index_before = len(mm.engine.round_scores)

    # 3. Route
    _route_ctx = RouteContext(
        current_score_a=current_score_a,
        current_score_b=current_score_b,
        current_game_index=_game_index_before,
        strict_mode=st.session_state.get("voice_strict_mode", False),
        enable_confirmation=enable_confirmation,
        last_applied_event_key=st.session_state.get("voice_last_applied_event_key"),
        last_applied_event_ts=st.session_state.get("voice_last_applied_event_ts", 0.0),
        min_confidence_to_apply=st.session_state.get("voice_confidence_threshold", 0.5),
        min_confidence_to_confirm=st.session_state.get("voice_confidence_threshold", 0.5),
    )
    route_result = route_and_update_context(parsed, _route_ctx)

    prev_score = mm.state.get_score_string()

    # REJECT
    if route_result.decision == RouteDecision.REJECT:
        st.session_state.last_voice_feedback = route_result.reason
        st.session_state.last_voice_rejection_reason = route_result.reason
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "rejected"
        return ScoreApplyResult(
            success=False,
            reason=route_result.reason,
            previous_score=prev_score,
            new_score=prev_score,
            parsed=parsed,
            route_result=route_result,
        )

    # IGNORE (duplicate suppressed)
    if route_result.decision == RouteDecision.IGNORE:
        st.session_state.last_voice_feedback = "duplicate_suppressed"
        st.session_state.last_voice_rejection_reason = "duplicate_suppressed"
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "duplicate_suppressed"
        return ScoreApplyResult(
            success=False,
            reason="duplicate_suppressed",
            previous_score=prev_score,
            new_score=prev_score,
            parsed=parsed,
            route_result=route_result,
        )

    # CONFIRM
    if route_result.decision == RouteDecision.CONFIRM:
        _machine = st.session_state.get("voice_confirmation_machine")
        if _machine is None:
            _machine = VoiceConfirmationStateMachine(ttl_seconds=8.0)
            st.session_state.voice_confirmation_machine = _machine
        _pending_decision = _machine.submit(parsed)
        if _pending_decision == "pending":
            _pending = {
                "event_id": parsed.event_id,
                "intent": parsed.intent.value if hasattr(parsed.intent, 'value') else str(parsed.intent),
                "slots": parsed.slots,
                "confidence": parsed.confidence,
                "raw_transcript": parsed.raw_transcript,
                "predicted_score_before": prev_score,
                "predicted_score_after": _predict_score_after(parsed),
                "received_at": time.time(),
                "source": source,
            }
            st.session_state.pending_confirmations.append(_pending)
            st.session_state.last_voice_transcript = parsed.raw_transcript
            st.session_state.last_voice_event = parsed.to_score_event()
            st.session_state.last_voice_feedback = "Awaiting confirmation"
            st.session_state.last_voice_rejection_reason = ""
            st.session_state.last_voice_success_message = ""
            st.session_state.last_voice_action_taken = "confirmation_required"
        else:
            st.session_state.last_voice_feedback = "Confirmation busy — try again"
            st.session_state.last_voice_rejection_reason = "confirmation_busy"
            st.session_state.last_voice_success_message = ""
            st.session_state.last_voice_action_taken = "rejected"
        return ScoreApplyResult(
            success=False,
            reason="pending",
            previous_score=prev_score,
            new_score=prev_score,
            parsed=parsed,
            route_result=route_result,
        )

    # APPLY
    _score_event = parsed.to_score_event()
    _score_event.source = source

    # Phase 3: Handle non-scoring intents (navigation, admin, rules, accessibility)
    _phase3_result = _handle_phase3_intent(_score_event, parsed)
    if _phase3_result is not None:
        st.session_state.last_voice_transcript = parsed.raw_transcript
        st.session_state.last_voice_event = _score_event
        st.session_state.last_voice_feedback = _phase3_result.get("message", "")
        st.session_state.last_voice_success_message = _phase3_result.get("message", "")
        st.session_state.last_voice_rejection_reason = ""
        st.session_state.last_voice_action_taken = _phase3_result.get("action", "phase3_applied")
        st.toast(f"🎤 {_phase3_result.get('message', '')}", icon="✅")
        _append_voice_audit(
            _score_event,
            source=source,
            accepted=True,
            previous_score=prev_score,
            new_score=prev_score,
            note=_phase3_result.get("action", "phase3"),
        )
        _request_voice_rerun("phase3")
        return ScoreApplyResult(
            success=True,
            reason=_phase3_result.get("message", ""),
            previous_score=prev_score,
            new_score=prev_score,
            parsed=parsed,
            route_result=route_result,
        )

    # Apply the event to the match manager
    if _score_event.type != "unknown":
        success, msg = mm.apply_voice_event(_score_event)
        st.session_state.voice_score_application_last_result = f"success={success}, msg={msg}, score_before={prev_score}"
        new_score = mm.state.get_score_string()
        note = "" if success else msg

        # Detect a game-completion transition produced by this command so we can
        # reset voice dedupe / cooldown state at the game boundary. This is the
        # root cause of "voice stops scoring after the first game": the last
        # command of Game 1 (e.g. "blue") collided with the first command of
        # Game 2 as a duplicate, silently blocking all further voice scoring.
        _game_index_after = len(mm.engine.round_scores)
        _game_completed = _game_index_after > _game_index_before

        if success:
            # Check if this was an auto-confirmed high-confidence command
            is_auto_confirmed = (
                parsed.confidence >= 0.70
                and route_result is not None
                and route_result.decision == RouteDecision.APPLY
            )
            if is_auto_confirmed:
                confidence_pct = int(parsed.confidence * 100)
                msg = f"Auto-confirmed ({confidence_pct}%): {msg}"
                note = f"auto_confirmed_{confidence_pct}pct"

            # Update cooldown tracking
            event_key = route_result.event_key
            event_ts = time.time()
            st.session_state.voice_last_applied_event_key = event_key
            st.session_state.voice_last_applied_event_ts = event_ts

            # Reset dedupe/cooldown state across the game boundary so the first
            # command of the next game is never suppressed as a duplicate.
            if _game_completed:
                st.session_state.voice_last_applied_event_key = None
                st.session_state.voice_last_applied_event_ts = 0.0

            st.session_state.last_voice_feedback = msg
            st.session_state.last_voice_success_message = msg
            st.session_state.last_voice_rejection_reason = ""
            if _score_event.type == "increment":
                st.session_state.last_voice_action_taken = "score_update_success"
            elif _score_event.type == "undo":
                st.session_state.last_voice_action_taken = "undo_success"
            elif _score_event.type == "set_score":
                st.session_state.last_voice_action_taken = "set_score_success"
            else:
                st.session_state.last_voice_action_taken = "applied"
            st.session_state.last_voice_transcript = parsed.raw_transcript
            st.session_state.last_voice_event = _score_event
            st.toast(f"🎤 {msg}", icon="✅")

            # Sound cues
            if _score_event.type == "increment":
                play_cue("point")
            elif _score_event.type == "undo":
                play_cue("undo")
            elif _score_event.type == "set_score":
                _e2 = mm.engine
                if _e2.match_status == "game_won":
                    play_cue("game")
                elif _e2.match_status == "match_won":
                    play_cue("match")

            # TTS confirmation
            _maybe_speak_tts(
                msg,
                _score_event.type,
                confidence=getattr(_score_event, "confidence", 1.0),
            )

            if st.session_state.get("commentary_engine") == "local":
                _build_local_commentary(
                    "voice_score_confirmed",
                    mm.state,
                    None,
                    _get_commentary_settings(),
                    str(uuid.uuid4()),
                )

            # Immediately re-derive UI state so it's available on next render.
            # This ensures completed_games and match_complete are never stale.
            st.session_state.completed_games = compute_completed_games(mm.engine)
            st.session_state.match_complete = (mm.engine.match_status == "match_won")
            if mm.engine.match_status == "match_won":
                st.session_state.pending_result_submission = True

            # Audio Rally Assistant: finalize or mark rally on score change
            if st.session_state.get("tt_sounds_enabled"):
                if _score_event.type == "undo":
                    _mark_last_audio_summary_action("undo")
                else:
                    audio_summary = finalize_current_audio_rally(reason="point_scored")
                    st.session_state["_pending_audio_summary_for_commentary"] = audio_summary
                    if audio_summary and audio_summary.confidence >= 0.55:
                        _append_audio_commentary_line(audio_summary)

            # Persist live match state so the Public Board can see the active match.
            try:
                _selected_match_id = st.session_state.get("voice_selected_match_id")
                if _selected_match_id:
                    persist_voice_match_to_db(_selected_match_id, mm.engine)
            except Exception:
                pass

            _request_voice_rerun("applied")
        else:
            st.session_state.last_voice_feedback = msg
            st.session_state.last_voice_rejection_reason = msg
            st.session_state.last_voice_success_message = ""
            st.session_state.last_voice_action_taken = "rejected"
            st.warning(f"🎤 Voice: {msg}")
            play_cue("reject")
            if st.session_state.get("commentary_engine") == "local":
                _build_local_commentary("voice_score_rejected", mm.state, None, _get_commentary_settings(), str(uuid.uuid4()))
    else:
        success = False
        msg = "Unknown command"
        st.session_state.voice_score_application_last_result = f"success=False, msg={msg}, score_before={prev_score}"
        st.session_state.last_voice_feedback = msg
        st.session_state.last_voice_rejection_reason = msg
        st.session_state.last_voice_success_message = ""
        st.session_state.last_voice_action_taken = "unknown_command"
        new_score = prev_score
        note = "unrecognized transcript"

    # Unified structured event logging (replaces separate voice_event_log + voice_event_logger)
    _append_voice_audit(
        _score_event,
        source=source,
        accepted=success,
        previous_score=prev_score,
        new_score=new_score,
        note=note,
    )

    # Dataset recorder
    if VOICE_DATASET_OPT_IN:
        try:
            recorder = st.session_state.get("voice_dataset_recorder")
            if recorder is not None:
                recorder.record(
                    transcript=transcript,
                    parsed_intent=_score_event.type if hasattr(_score_event, 'type') else None,
                    expected_intent=_score_event.type if success else None,
                    match_id=st.session_state.get("voice_selected_match_id"),
                    match_context={
                        "score_before": prev_score,
                        "score_after": new_score,
                        "confidence": getattr(_score_event, 'confidence', 0.0),
                    },
                    mic_type=source,
                    noise_condition="low" if (getattr(_score_event, 'noise_rms', 0) or 0.0) > 0.01 else "high",
                )
        except Exception as exc:
            logger.debug("Dataset record skipped: %s", exc)

    return ScoreApplyResult(
        success=success,
        reason=msg,
        previous_score=prev_score,
        new_score=new_score,
        parsed=parsed,
        route_result=route_result,
        event_key=st.session_state.get("voice_last_applied_event_key"),
        event_ts=st.session_state.get("voice_last_applied_event_ts", 0.0),
    )


def _process_voice_transcript(
    transcript: str,
    source: str = "debug",
    enable_confirmation: bool = VOICE_ENABLE_CONFIRMATION,
    selected_match_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Legacy compatibility wrapper for apply_score_event_and_refresh_ui."""
    res_obj = apply_score_event_and_refresh_ui(
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


def persist_voice_match_to_db(match_id: int, engine) -> None:
    """
    Persist the current voice MatchManager engine state to the DB ``Match`` row.

    The ``score`` column follows the app-wide convention of "gamesWonA-gamesWonB"
    (the match result). While the match is in progress the row is marked
    ``active`` and the running games-won tally is stored; when the match is won
    the row is marked ``completed`` with ``winner``/``winner_id``/``completed_at``
    so completed games/matches survive session restarts.
    """
    import json
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if match is None:
            return

        match.score = f"{engine.games_won_a}-{engine.games_won_b}"
        match.game_scores = (
            ", ".join(f"{a}-{b}" for a, b in engine.round_scores)
            if engine.round_scores
            else None
        )

        if engine.match_status == "match_won":
            match.status = MatchStatus.completed
            match.call_status = "completed"
            winner_label = "A" if engine.games_won_a > engine.games_won_b else "B"
            match.winner = (
                engine.player_a_name if winner_label == "A" else engine.player_b_name
            )
            match.winner_id = (
                engine.player_a_id if winner_label == "A" else engine.player_b_id
            )
            if match.completed_at is None:
                match.completed_at = datetime.now(timezone.utc)
            match.operator_note = None
        else:
            match.status = MatchStatus.active
            match.call_status = "active"
            match.winner = None
            match.winner_id = None
            match.started_at = match.started_at or datetime.now(timezone.utc)
            try:
                live_snapshot = {
                    "current_game_score": [engine.score_a, engine.score_b],
                    "games_won": [engine.games_won_a, engine.games_won_b],
                    "server": getattr(engine, "serving_player", None),
                }
                match.operator_note = json.dumps(live_snapshot)
            except Exception:
                match.operator_note = None

        db.commit()
    except Exception as e:
        logger.error("Failed to persist voice match %s to DB: %s", match_id, e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _get_persisted_match_meta(match_id: int, engine) -> Dict[str, Any]:
    """Get match metadata from the DB row if available, falling back to engine state."""
    db = SessionLocal()
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if match:
            game_scores_list = []
            if match.game_scores:
                game_scores_list = [s.strip() for s in match.game_scores.split(",") if s.strip()]
            return {
                "score": match.score or f"{engine.games_won_a}-{engine.games_won_b}",
                "winner": match.winner
                or (
                    engine.player_a_name
                    if engine.games_won_a > engine.games_won_b
                    else engine.player_b_name
                ),
                "game_scores": game_scores_list
                or [f"{a}-{b}" for a, b in engine.round_scores],
            }
    finally:
        db.close()
    return {
        "score": f"{engine.games_won_a}-{engine.games_won_b}",
        "winner": engine.player_a_name
        if engine.games_won_a > engine.games_won_b
        else engine.player_b_name,
        "game_scores": [f"{a}-{b}" for a, b in engine.round_scores],
    }


def finalize_voice_match(match_id: int, engine) -> None:
    """Validate, complete, persist game_scores, and update ratings for a won match.

    Guarded against double-run via the persisted DB ``Match.status`` check.
    """
    from tournament_platform.services.match_reporting import (
        ReportMatchCommand,
        report_existing_match,
        MatchAlreadyCompletedError,
    )
    from tournament_platform.services.ranking_service import RatingManager

    db = SessionLocal()
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if match is None or match.status == MatchStatus.completed:
            return

        winner_name = (
            engine.player_a_name
            if engine.games_won_a > engine.games_won_b
            else engine.player_b_name
        )
        score_str = f"{engine.games_won_a}-{engine.games_won_b}"
        game_scores_str = (
            ", ".join(f"{a}-{b}" for a, b in engine.round_scores)
            if engine.round_scores
            else None
        )

        command = ReportMatchCommand(
            match_id=match_id,
            winner=winner_name,
            score=score_str,
            game_scores=game_scores_str,
        )
        updated_match = report_existing_match(db, command)

        if (
            updated_match.winner_id
            and updated_match.player1_id
            and updated_match.player2_id
        ):
            winner_id = updated_match.winner_id
            loser_id = (
                updated_match.player2_id
                if winner_id == updated_match.player1_id
                else updated_match.player1_id
            )
            rating_manager = RatingManager()
            rating_manager.update_ratings(winner_id, loser_id, db_session=db)
    except MatchAlreadyCompletedError:
        pass
    except Exception as exc:
        logger.error(
            "Failed to finalize voice match %s: %s", match_id, exc
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def compute_completed_games(engine) -> List[Dict[str, Any]]:
    """Return a normalized list of completed games derived from the engine.

    The engine's ``round_scores`` is the single source of truth: it holds every
    finished game (including the final one that decided the match). This helper
    projects those ``(score_a, score_b)`` tuples into UI-friendly dicts and never
    mutates the engine.
    """
    games: List[Dict[str, Any]] = []
    for i, (a, b) in enumerate(engine.round_scores):
        games.append(
            {
                "game": i + 1,
                "player_a_score": a,
                "player_b_score": b,
                "winner": "A" if a > b else "B",
            }
        )
    return games


def compute_match_score(completed_games: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Return ``(games_won_a, games_won_b)`` derived from completed games only.

    This intentionally does NOT read ``engine.games_won_*`` so the displayed
    match score can never claim more games than are actually recorded.
    """
    games_a = sum(1 for g in completed_games if g["winner"] == "A")
    games_b = sum(1 for g in completed_games if g["winner"] == "B")
    return games_a, games_b


def clear_result_review_state() -> None:
    """Reset the Live Scoreboard result-review / submission session state.

    Called on match switch, reset, and rematch so a prior match's completed
    games and submission flags never leak into a new match.
    """
    st.session_state.completed_games = []
    st.session_state.match_complete = False
    st.session_state.pending_result_submission = False
    st.session_state.result_submitted = False
    st.session_state.commentary_emitted_game_keys = []
    st.session_state.commentary_log_entries = []
    st.session_state.commentary_log_match_id = None


st.session_state.setdefault("commentary_voice", "default")
st.session_state.setdefault("commentary_voice_profile", "browser_default")
st.session_state.setdefault("commentary_log_entries", [])
st.session_state.setdefault("commentary_log_match_id", None)


def _process_push_to_talk_audio(audio_file: Any) -> Optional[VoiceScoreEvent]:
    """Process push-to-talk audio through ASR -> parse -> confirmation."""
    pcm_bytes = _audio_input_to_pcm(audio_file)
    if not pcm_bytes:
        st.warning("Could not read audio input. Please try again.")
        return None

    if "voice_asr" not in st.session_state:
        st.session_state.voice_asr = LocalASR(vocabulary=VoiceVocabulary.load())

    asr = st.session_state.voice_asr
    try:
        raw_text = asr.transcribe_chunk(pcm_bytes)
    except Exception as exc:
        logger.error("Push-to-talk ASR failed: %s", exc)
        st.warning("Transcription failed. Please try again.")
        return None

    if not raw_text or not raw_text.strip():
        st.warning("No speech detected. Please try again.")
        return None

    res_obj = apply_score_event_and_refresh_ui(raw_text, source="push_to_talk")
    # Convert result object back to dict for legacy compatibility in this block
    result = {
        "success": res_obj.success,
        "reason": res_obj.reason,
        "previous_score": res_obj.previous_score,
        "new_score": res_obj.new_score,
        "parsed": res_obj.parsed,
        "route_result": res_obj.route_result,
    }

    if VOICE_DATASET_OPT_IN:
        try:
            recorder = st.session_state.get("voice_dataset_recorder")
            if recorder is not None:
                processed = TranscriptPostProcessor(VoiceVocabulary.load()).process(raw_text)
                recorder.record(
                    transcript=processed,
                    parsed_intent=result.get("parsed").intent if result.get("parsed") else None,
                    expected_intent=result.get("parsed").intent if result.get("parsed") and result.get("success") else None,
                    match_id=st.session_state.get("voice_selected_match_id"),
                    match_context={
                        "score_before": result.get("previous_score", ""),
                        "score_after": result.get("new_score", ""),
                        "confidence": result.get("parsed").confidence if result.get("parsed") else 0.0,
                    },
                    mic_type="push_to_talk",
                    noise_condition="unknown",
                )
        except Exception as exc:
            logger.debug("Push-to-talk dataset record skipped: %s", exc)

    return result.get("parsed").to_score_event() if result.get("parsed") else None


def _predict_score_after(parsed: VoiceParseResult) -> str:
    if parsed.intent == VoiceIntent.SCORE_POINT:
        player = parsed.slots.get("player", "A")
        score_a = st.session_state.match_manager.state.score_a
        score_b = st.session_state.match_manager.state.score_b
        if player == "A":
            score_a += 1
        else:
            score_b += 1
        return f"{score_a}-{score_b}"
    if parsed.intent == VoiceIntent.SET_SCORE:
        score_a = parsed.slots.get("score_a")
        score_b = parsed.slots.get("score_b")
        if score_a is not None and score_b is not None:
            return f"{score_a}-{score_b}"
    return st.session_state.match_manager.state.get_score_string()


PHASE3_NAVIGATION_INTENTS = {
    VoiceIntent.NAVIGATE_DASHBOARD,
    VoiceIntent.NAVIGATE_BRACKET,
    VoiceIntent.NAVIGATE_RANKINGS,
    VoiceIntent.NAVIGATE_PUBLIC_BOARD,
    VoiceIntent.NAVIGATE_CURRENT_MATCH,
    VoiceIntent.NAVIGATE_SCORING,
    VoiceIntent.NAVIGATE_HELP,
}

PHASE3_ADMIN_INTENTS = {
    VoiceIntent.ADMIN_CALL_NEXT,
    VoiceIntent.ADMIN_TABLE_READY,
    VoiceIntent.ADMIN_ASSIGN_TABLE,
    VoiceIntent.ADMIN_MARK_UNAVAILABLE,
    VoiceIntent.ADMIN_PUBLISH_RESULT,
    VoiceIntent.ADMIN_MARK_NO_SHOW,
    VoiceIntent.ADMIN_DROP_PLAYER,
    VoiceIntent.ADMIN_START_NEXT_ROUND,
}

PHASE3_RULES_INTENTS = {
    VoiceIntent.RULES_QUERY,
}

PHASE3_ACCESSIBILITY_INTENTS = {
    VoiceIntent.ACCESS_REPEAT,
    VoiceIntent.ACCESS_ANNOUNCE_SCORE,
    VoiceIntent.ACCESS_LOUDER,
    VoiceIntent.ACCESS_QUIETER,
    VoiceIntent.ACCESS_MUTE,
    VoiceIntent.ACCESS_UNMUTE,
    VoiceIntent.ACCESS_SLOWER,
    VoiceIntent.ACCESS_FASTER,
    VoiceIntent.ACCESS_LARGE_TEXT,
    VoiceIntent.ACCESS_HIGH_CONTRAST,
    VoiceIntent.ACCESS_HELP,
}


def _handle_phase3_intent(event: Any, parsed: VoiceParseResult) -> Optional[Dict[str, Any]]:
    intent = parsed.intent

    if intent in PHASE3_NAVIGATION_INTENTS:
        from tournament_platform.app.services.voice.navigation import NavigationCommandHandler
        handler = NavigationCommandHandler()
        result = handler.execute(intent, st.session_state.get("voice_runtime_state", {}).__dict__ if hasattr(st.session_state.get("voice_runtime_state", {}), "__dict__") else {})
        if result.action == "navigate":
            st.toast(f"🎤 Navigate: {result.payload.get('target')}", icon="🧭")
            return {"action": "navigate", "message": result.message}
        return {"action": "blocked", "message": result.message}

    if intent in PHASE3_ADMIN_INTENTS:
        from tournament_platform.app.services.voice.admin import AdminCommandHandler
        handler = AdminCommandHandler()
        action = handler.execute(intent, parsed.slots)
        if action.requires_confirmation:
            _pending = {
                "event_id": parsed.event_id,
                "intent": parsed.intent,
                "slots": parsed.slots,
                "confidence": parsed.confidence,
                "raw_transcript": parsed.raw_transcript,
                "predicted_score_before": st.session_state.match_manager.state.get_score_string(),
                "predicted_score_after": st.session_state.match_manager.state.get_score_string(),
                "received_at": time.time(),
                "source": parsed.source,
                "warning": handler.get_warning(intent),
            }
            st.session_state.pending_confirmations.append(_pending)
            return {"action": "admin_pending", "message": f"Admin command pending: {action.message}"}
        st.toast(f"🎤 Admin: {action.message}", icon="⚙️")
        return {"action": "admin", "message": action.message}

    if intent in PHASE3_RULES_INTENTS:
        from tournament_platform.app.services.voice.rules_assistant import RulesAssistantHandler
        handler = RulesAssistantHandler()
        action = handler.execute(intent, parsed.slots)
        st.info(f"📖 {action.message}")
        return {"action": "rules", "message": action.message}

    if intent in PHASE3_ACCESSIBILITY_INTENTS:
        from tournament_platform.app.services.voice.accessibility import AccessibilityCommandHandler
        handler = AccessibilityCommandHandler()
        action = handler.execute(intent, parsed.slots, {})
        st.toast(f"🎤 {action.message}", icon="♿")
        return {"action": "accessibility", "message": action.message}

    return None


def _apply_pending(idx: int) -> None:
    """Apply a pending confirmed voice command via the canonical pipeline."""
    _machine = st.session_state.get("voice_confirmation_machine")
    if _machine:
        _machine.confirm()
        _machine.reset()
    item = st.session_state.pending_confirmations.pop(idx)
    raw = item.get("raw_transcript", "")
    source = item.get("source", "asr")
    intent_str = item.get("intent", "unknown")

    # Handle admin intents separately (they go through AdminCommandHandler, not ScoreEngine)
    if intent_str in [i.value for i in PHASE3_ADMIN_INTENTS]:
        from tournament_platform.app.services.voice.admin import AdminCommandHandler
        handler = AdminCommandHandler()
        intent_enum = VoiceIntent(intent_str)
        action = handler.execute(intent_enum, item.get("slots", {}))
        st.toast(f"🎤 Admin: {action.message}", icon="⚙️")
        st.session_state.last_voice_feedback = action.message
        st.session_state.last_voice_success_message = action.message
        st.session_state.last_voice_rejection_reason = ""
        st.session_state.last_voice_action_taken = "admin_applied"
        _append_voice_audit(
            VoiceScoreEvent(type=intent_str, raw_text=raw, confidence=item.get("confidence", 0.0)),
            source=source,
            accepted=True,
            previous_score=st.session_state.match_manager.state.get_score_string(),
            new_score=st.session_state.match_manager.state.get_score_string(),
            note="admin_confirmed",
        )
        _request_voice_rerun("admin_confirmed")
        return

    # Use the canonical function for all scoring intents
    result = apply_score_event_and_refresh_ui(
        transcript=raw,
        source=source,
        enable_confirmation=False,  # Already confirmed by user
    )

    if result.success:
        st.toast(f"🎤 {result.reason}", icon="✅")
    else:
        st.warning(f"🎤 Voice: {result.reason}")


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


def is_running_on_streamlit_cloud() -> bool:
    """Detect Streamlit Cloud so we can degrade voice features gracefully.

    Streamlit Cloud sets ``IS_STREAMLIT_CLOUD`` (and historically
    ``STREAMLIT_SHARING_MODE``). Local microphone/audio backends and optional
    ASR models are typically unavailable there, so callers can avoid showing
    local-setup error text and instead show a cloud-friendly notice.
    """
    import os

    return bool(
        os.environ.get("IS_STREAMLIT_CLOUD")
        or os.environ.get("STREAMLIT_SHARING_MODE")
    )


def _normalize_status(value) -> str:
    """Lowercase/trim a match status, handling None gracefully."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_status_dict(value, default_reason: str = "Status unavailable") -> Dict[str, Any]:
    """Coerce any ASR/cloud status value into a safe, ``dict``-shaped object.

    The Streamlit Cloud crash originated from ``_asr_status`` being a
    ``BackendStatus`` dataclass, ``None``, a ``bool``, a ``str``, or an
    exception object instead of a plain ``dict``. This helper guarantees the
    returned value always supports ``.get(...)`` and carries the keys the UI
    expects (``available``, ``reason``, ``provider``).
    """
    if is_dataclass(value):
        value = asdict(value)

    if isinstance(value, dict):
        merged = dict(value)
        merged["available"] = bool(value.get("available", False))
        merged["reason"] = value.get("reason") or value.get("message") or value.get("load_error") or default_reason
        if "provider" not in merged:
            _prov = value.get("backend_name")
            merged["provider"] = _prov if _prov else ("none" if not merged["available"] else "local")
        return merged

    if isinstance(value, bool):
        return {
            "available": value,
            "reason": "Available" if value else default_reason,
            "provider": "none" if not value else "local",
        }

    if value is None:
        return {
            "available": False,
            "reason": default_reason,
            "provider": "none",
        }

    return {
        "available": False,
        "reason": str(value),
        "provider": "none",
    }


def _get_voice_webrtc_processor(ctx: object | None) -> object | None:
    """Safely return the active WebRTC/audio processor.

    Streamlit session_state may contain None, a dict, a streamlit-webrtc
    context object, or another object without processor fields. Never
    assume ctx supports .get().
    """
    if ctx is None:
        return None

    if isinstance(ctx, dict):
        return (
            ctx.get("audio_processor")
            or ctx.get("processor")
            or ctx.get("voice_processor")
        )

    # For streamlit-webrtc context objects, only check audio_processor
    # (the standard attribute). Do not fall through to processor/voice_processor
    # which may exist as stale or unrelated attributes on the context.
    processor = getattr(ctx, "audio_processor", None)
    return processor


def _get_current_webrtc_processor() -> object | None:
    """Authoritative helper — read the processor from the live WebRTC context.

    Reads directly from the streamlit-webrtc-managed context object stored
    under the component key in ``st.session_state``, NOT from the page-managed
    ``voice_webrtc_ctx`` dict which may hold a stale processor reference from
    a previous render.

    Falls back to ``voice_webrtc_ctx`` only when the live context is not
    present (e.g. in unit tests where webrtc_streamer() is not called).

    Returns None if the component is not mounted or the context has no
    processor yet.
    """
    raw_ctx = _get_raw_voice_webrtc_context()
    if raw_ctx is not None:
        proc = _get_voice_webrtc_processor(raw_ctx)
        if proc is not None:
            return proc
    # Fallback for unit tests / backward compatibility
    webrtc_ctx = st.session_state.get("voice_webrtc_ctx")
    if webrtc_ctx is not None:
        return _get_voice_webrtc_processor(webrtc_ctx)
    return None


def _create_webrtc_snapshot(webrtc_ctx: object | None, mount_error: str | None = None) -> WebRtcRenderSnapshot:
    """Create an immutable per-render snapshot of the WebRTC streamer context.

    This is the sole authority for current WebRTC state for the remainder of
    the render. It is captured immediately after ``webrtc_streamer()`` returns
    and passed to all downstream functions, eliminating the split-brain problem
    where different functions read from different sources.

    The ``processor`` field may be None during transient worker/context
    transitions even when ``playing=True``. This must be treated as
    "unknown/transitional", NOT as a processor replacement.
    """
    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        _voice_lifecycle_events,
        VoiceLifecycleEvent,
    )
    processor = _get_voice_webrtc_processor(webrtc_ctx)
    playing = bool(getattr(getattr(webrtc_ctx, "state", None), "playing", False))
    signalling = bool(getattr(getattr(webrtc_ctx, "state", None), "signalling", False))
    processor_id = id(processor) if processor is not None else None
    processor_generation = (
        getattr(processor, "_processor_generation", None)
        if processor is not None
        else None
    )
    audio_frames_received = (
        getattr(processor, "_audio_frames_received", 0)
        if processor is not None
        else 0
    )

    # Point 5: Detailed connection states from streamlit-webrtc / aiortc
    worker = getattr(webrtc_ctx, "_worker", None)
    pc = getattr(worker, "pc", None) if worker else None

    # Point 6: Instrument peer-connection lifecycle via thread-safe queue
    if pc is not None and not hasattr(pc, "_voice_listeners_attached"):
        try:
            def _push_pc_event(event_name: str, extra: dict = None):
                try:
                    _voice_lifecycle_events.push(
                        VoiceLifecycleEvent(
                            event_type=f"webrtc_pc_{event_name}",
                            processor_id=processor_id,
                            processor_generation=processor_generation,
                            timestamp=time.time(),
                            desired_mic_playing=None,
                            last_frame_age_ms=None,
                            extra=extra or {},
                        )
                    )
                except Exception:
                    pass

            @pc.on("connectionstatechange")
            def on_connectionstatechange():
                _push_pc_event("connectionstatechange", {"state": pc.connectionState})

            @pc.on("iceconnectionstatechange")
            def on_iceconnectionstatechange():
                _push_pc_event("iceconnectionstatechange", {"state": pc.iceConnectionState})

            @pc.on("icegatheringstatechange")
            def on_icegatheringstatechange():
                _push_pc_event("icegatheringstatechange", {"state": pc.iceGatheringState})

            @pc.on("signalingstatechange")
            def on_signalingstatechange():
                _push_pc_event("signalingstatechange", {"state": pc.signalingState})

            setattr(pc, "_voice_listeners_attached", True)
            _push_pc_event("listeners_attached")
        except Exception as exc:
            logger.debug("Failed to attach WebRTC listeners: %s", exc)

    # Use actual installed API names if exposed
    connection_state = getattr(pc, "connectionState", None) if pc else None
    ice_connection_state = getattr(pc, "iceConnectionState", None) if pc else None
    ice_gathering_state = getattr(pc, "iceGatheringState", None) if pc else None
    signaling_state = getattr(pc, "signalingState", None) if pc else None

    return WebRtcRenderSnapshot(
        context=webrtc_ctx,
        playing=playing,
        signalling=signalling,
        processor=processor,
        processor_id=processor_id,
        processor_generation=processor_generation,
        audio_frames_received=audio_frames_received,
        connection_state=connection_state,
        ice_connection_state=ice_connection_state,
        ice_gathering_state=ice_gathering_state,
        signaling_state=signaling_state,
        component_rendered=True,
        mount_error=mount_error,
    )


def _safe_queue_size(queue_obj: object | None) -> int:
    """Return qsize safely for queue-like objects."""
    if queue_obj is None:
        return 0

    qsize = getattr(queue_obj, "qsize", None)
    if not callable(qsize):
        return 0

    try:
        return int(qsize())
    except Exception:
        return 0


def _debug_value(value: Any, max_len: int = 300) -> str:
    if value is None:
        return "—"
    text = str(value).replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def get_asr_diagnostic() -> Dict[str, Any]:
    """Return a precise, UI-safe ASR diagnostic dict for the Voice Scorekeeper.

    Combines the backend factory status (which now carries ``state``/``reason``)
    with the dependency-import probe so the UI never shows only a vague
    "Status unavailable". The returned dict is safe to render as JSON.
    """
    diag = diagnose_faster_whisper_environment()
    try:
        backend_status = ASRBackendFactory.backend_status()
        status = _normalize_status_dict(backend_status, default_reason="not_configured")
    except Exception as exc:
        status = {
            "available": False,
            "state": "import_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "provider": "faster_whisper",
        }

    status["imports"] = diag.get("imports", {})
    status["provider"] = status.get("provider") or "faster_whisper"
    # Surface the precise state; prefer the backend's own state/reason.
    status["state"] = status.get("state") or (
        "ready" if status.get("available") else (status.get("reason") or "not_configured")
    )
    return status


def get_asr() -> Optional[object]:
    """Lazily build/return a ready ASR backend for diagnostics/test buttons.

    Returns ``None`` when no backend is available; never raises.
    """
    try:
        return ASRBackendFactory.create()
    except Exception:
        return None


def _quick_voice_asr_ready() -> bool:
    """Return True only if a transcript provider (faster-whisper) is ready.

    Quick Voice Scoring relies on the active transcript pipeline, so it must
    not be presented as "listening" when ASR is unavailable. Browser Web
    Speech fallback is intentionally out of scope for this fix.
    """
    try:
        diag = get_asr_diagnostic()
        return bool(diag.get("available"))
    except Exception:
        return False


def fetch_active_matches(tournament_id: int, statuses: Optional[List[str]] = None) -> List[Dict]:
    """Fetch scorable matches for a tournament from the local database.

    The canonical match source is the ``Match`` table (the same source the
    Tournament page reads via ``tournament.matches``). We read it directly
    rather than going through the FastAPI server, because the API is optional
    and not available in Streamlit Cloud local mode.

    If an external API is explicitly configured AND reachable, we still fall
    back to the local DB on any failure so match loading never blocks.
    """
    allowed = set()
    for s in (statuses or []):
        norm = _normalize_status(s)
        if norm:
            allowed.add(norm)
    if not allowed:
        allowed = {MatchStatus.active.value, MatchStatus.pending.value}

    db = SessionLocal()
    try:
        query = db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status.in_(allowed),
        )
        matches = query.all()

        def sort_key(m: Match):
            status_priority = 0 if _normalize_status(m.status.value) in {"active", "in_progress"} else 1
            return (
                status_priority,
                m.round_number or 0,
                m.bracket_index or 0,
                m.scheduled_time or datetime.min,
                m.id,
            )

        matches = sorted(matches, key=sort_key)

        result = []
        for m in matches:
            p1 = db.query(Player).filter(Player.id == m.player1_id).first() if m.player1_id else None
            p2 = db.query(Player).filter(Player.id == m.player2_id).first() if m.player2_id else None
            incomplete = not (m.player1_id and m.player2_id and p1 and p2)
            result.append({
                "match_id": m.id,
                "player1_id": m.player1_id,
                "player1_name": p1.name if p1 else (m.player1 or "TBD"),
                "player2_id": m.player2_id,
                "player2_name": p2.name if p2 else (m.player2 or "TBD"),
                "status": m.status.value if isinstance(m.status, MatchStatus) else str(m.status),
                "round_number": m.round_number,
                "bracket_index": m.bracket_index,
                "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None,
                "location": m.location,
                "score": m.score,
                "winner": m.winner,
                "incomplete": incomplete,
            })
        return result
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Failed to load active matches from DB: %s", e, exc_info=True)
        return []
    finally:
        db.close()


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
            from datetime import datetime, timezone
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
        st.session_state.match_manager.reset_match()
        clear_result_review_state()


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
    clear_result_review_state()


def _initialize_webrtc_session() -> WebRtcRenderSnapshot:
    """Authoritative per-render WebRTC mount point (Canonical Order §2).
    
    This function must be called exactly once per render pass to mount the
    WebRTC component and capture the current context as an immutable snapshot.
    """
    from streamlit_webrtc import webrtc_streamer, WebRtcMode
    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        VOICE_RUNTIME_IMPLEMENTATION_VERSION,
        VOICE_AUDIO_PROCESSOR_API_VERSION,
        VoiceProcessorFactory,
        VoiceProcessorConfigHolder,
    )

    # 1. Resolve selected mode/provider/language deterministically
    _streaming_backends = ASRBackendFactory.streaming_backends()
    _config_frozen = bool(st.session_state.get("voice_streaming_config_frozen", False))
    _provider_key = "voice_streaming_provider"
    _current_provider = st.session_state.get(_provider_key) or "deepgram"
    _current_language = st.session_state.get("voice_streaming_language") or "lt"
    _resolved_voice_mode = st.session_state.get("quick_voice_mode", "off")
    _voice_mode_allows_streaming = _resolved_voice_mode in ("full", "quick")

    # If Voice Mode is Off and a streaming session is active, stop it
    if not _voice_mode_allows_streaming and _config_frozen:
        _stop_streaming_voice_session()

    # 2. Build/update stable VoiceProcessorFactory config
    ensure_webrtc_diag_state()
    if not WEBRTC_AVAILABLE:
        return WebRtcRenderSnapshot.unavailable()

    _api_version_str = VOICE_AUDIO_PROCESSOR_API_VERSION
    _impl_version_str = VOICE_RUNTIME_IMPLEMENTATION_VERSION
    current_version = f"{_api_version_str}:{_impl_version_str}"
    cached_version = st.session_state.get("_voice_processor_version")
    if cached_version != current_version:
        for _cache_key in list(st.session_state.keys()):
            if str(_cache_key).startswith("__PROCESSOR_TRACK_CACHE__"):
                del st.session_state[_cache_key]
        st.session_state._voice_processor_version = current_version
    st.session_state._voice_processor_cache_cleared = True

    _factory_key = "voice_webrtc_tracked_factory"
    _config_key = "voice_webrtc_processor_config_holder"

    _filtering = bool(st.session_state.get("voice_noise_filtering", False))
    _threshold = float(st.session_state.get("voice_noise_threshold", 0.0))
    _strict = bool(st.session_state.get("voice_strict_mode", False))
    _tt_enabled = bool(st.session_state.get("tt_sounds_enabled", False))
    _vad = create_vad()

    _config_version = f"{_api_version_str}:{_impl_version_str}:{_filtering}:{_threshold}:{_strict}:{_tt_enabled}"
    _config = st.session_state.get(_config_key)
    if _config is None:
        _config = VoiceProcessorConfigHolder(
            filtering=_filtering,
            threshold=_threshold,
            strict=_strict,
            vad=_vad,
            tt_sounds_enabled=_tt_enabled,
        )
        st.session_state[_config_key] = _config
        _config_updated = False
    else:
        _config_updated = _config.version_string() != _config_version
        if _config_updated:
            _config.update(
                filtering=_filtering,
                threshold=_threshold,
                strict=_strict,
                vad=_vad,
                tt_sounds_enabled=_tt_enabled,
            )

    if _config_updated:
        _append_continuous_trace(
            "processor_factory_config_updated",
            f"factory_id={id(st.session_state.get(_factory_key))} "
            f"config_version={_config_version}",
        )

    st.session_state[_config_key] = _config

    if _factory_key not in st.session_state:
        def _emit_processor_fingerprint(processor):
            from tournament_platform.app.services.voice_scorekeeper.runtime import (
                VOICE_RUNTIME_IMPLEMENTATION_VERSION,
                VOICE_RUNTIME_SOURCE_FILE,
                VOICE_AUDIO_PROCESSOR_API_VERSION,
            )
            import os
            _append_continuous_trace(
                "voice_runtime_fingerprint",
                f"implementation_version={VOICE_RUNTIME_IMPLEMENTATION_VERSION} "
                f"runtime_source_file={VOICE_RUNTIME_SOURCE_FILE} "
                f"processor_id={id(processor)} "
                f"processor_created_at={getattr(processor, '_created_at', 'N/A')} "
                f"process_id={os.getpid()} "
                f"worker_queue_id={id(getattr(processor, '_chunk_queue', None))} "
                f"event_queue_id={id(getattr(processor, 'event_queue', None))} "
                f"api_version={VOICE_AUDIO_PROCESSOR_API_VERSION}",
            )

        st.session_state[_factory_key] = VoiceProcessorFactory(
            config_holder=_config,
            session_state=st.session_state,
            post_init_callback=_emit_processor_fingerprint,
        )
        st.session_state._voice_factory_creation_count = (
            st.session_state.get("_voice_factory_creation_count", 0) + 1
        )
        st.session_state._voice_factory_call_count = 0
        st.session_state._voice_factory_last_error = None
        st.session_state._voice_last_processor_id = None
        st.session_state._voice_last_processor_class = None
        st.session_state._voice_processor_callback_count = 0
        st.session_state._voice_last_processor_exception = None

    _tracked_factory = st.session_state[_factory_key]

    # 3. Authoritative WebRTC configuration and call
    _webrtc_static_config = {
        "key": "voice_scorekeeper_continuous_webrtc",
        "mode": str(WebRtcMode.SENDONLY),
        "factory_id": id(_tracked_factory),
        "rtc_configuration": {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        "media_stream_constraints": _WEBRTC_AUDIO_CONSTRAINTS,
        "async_processing": True,
    }
    _webrtc_fingerprint = hash(str(_webrtc_static_config))
    _prev_fingerprint = st.session_state.get("_voice_webrtc_static_fingerprint")
    if _prev_fingerprint is not None and _prev_fingerprint != _webrtc_fingerprint:
        _append_continuous_trace(
            "webrtc_static_config_changed",
            f"old={_prev_fingerprint} new={_webrtc_fingerprint} config={_webrtc_static_config}",
        )
    st.session_state._voice_webrtc_static_fingerprint = _webrtc_fingerprint

    _desired_playing = bool(st.session_state.get("desired_mic_playing", False))
    _render_seq = st.session_state.get("_voice_render_sequence", 0) + 1
    st.session_state._voice_render_sequence = _render_seq

    if _render_seq % 50 == 0 or _render_seq == 1:
        _append_continuous_trace(
            "webrtc_render_audit",
            f"seq={_render_seq} desired={_desired_playing} fingerprint={_webrtc_fingerprint}",
        )

    try:
        ctx = webrtc_streamer(
            key="voice_scorekeeper_continuous_webrtc",
            mode=WebRtcMode.SENDONLY,
            audio_processor_factory=_tracked_factory,
            rtc_configuration=_webrtc_static_config["rtc_configuration"],
            media_stream_constraints=_webrtc_static_config["media_stream_constraints"],
            async_processing=_webrtc_static_config["async_processing"],
            desired_playing_state=_desired_playing,
            on_change=_on_webrtc_state_change,
        )
        st.session_state["voice_webrtc_mount_error"] = None
        mount_error = None
    except Exception as exc:
        mount_error = f"{type(exc).__name__}: {exc}"
        st.session_state["voice_webrtc_mount_error"] = mount_error
        logger.error("WebRTC mount failed: %s", mount_error, exc_info=True)
        ctx = None

    # 4. Immediately build WebRtcRenderSnapshot
    _webrtc_snapshot = _create_webrtc_snapshot(ctx, mount_error=mount_error)

    # Also update the streamlit-webrtc-managed session-state key
    # for backward compatibility with cross-module callers.
    st.session_state["voice_scorekeeper_continuous_webrtc"] = ctx

    return _webrtc_snapshot


def _render_ui() -> None:
    _ss = st.session_state
    # Point 1: Authoritative per-render WebRTC snapshot initialized at the top
    # to avoid UnboundLocalError and split-brain state.
    from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
    _webrtc_snapshot = WebRtcRenderSnapshot.unavailable()

    render_page_header(
        title="Voice Scorekeeper",
        icon_name="voice_scorekeeper",
    )
    # Log ASR environment/dependency diagnostics once per process (Cloud-safe).
    try:
        log_voice_asr_environment_once()
    except Exception:
        pass
    if get_script_run_ctx() is not None:
        render_tour("voice_scorekeeper")
        apply_global_styles()
        st.caption("Speak to update scores. The system uses local transcription - no data leaves your machine.")

        # ============================================================================
        # Step 1: Initialize WebRTC authoritatively (Canonical Order §2)
        # ============================================================================
        # We must call webrtc_streamer() exactly once per render to get the
        # current context. We do this before event draining so the scoreboard
        # reflects current voice commands.
        if st.session_state.get("voice_scoring_enabled") or st.session_state.get("tt_sounds_enabled"):
            _webrtc_snapshot = _initialize_webrtc_session()

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
    else:
        return
    
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
    
    # ============================================================================
    # Reconciliation & Event Draining (Canonical Order §2)
    # ============================================================================
    # 1. Reconcile voice lifecycle and provider backend BEFORE draining events.
    if WEBRTC_AVAILABLE:
        _now = time.time()
        _last_refresh = _ss.get("voice_streaming_last_refresh", 0.0)
        _config_frozen = _ss.get("voice_streaming_config_frozen", False)
        if _config_frozen and (_now - _last_refresh) >= 0.3:
            _refresh_streaming_diagnostics(_webrtc_snapshot)

    # 2. Drain pending continuous voice events BEFORE rendering the live scoreboard.
    # This ensures accepted commands from background audio callbacks are applied
    # and reflected in the UI on the same render cycle.
    drain_result = _process_voice_events(snapshot=_webrtc_snapshot)
    _process_tt_sounds_events(snapshot=_webrtc_snapshot)

    if consume_calibration_trials is not None and VoiceCalibrationService is not None:
        try:
            updated_session = consume_calibration_trials(
                service=VoiceCalibrationService(),
                session=st.session_state.get("voice_calibration_session"),
                trials=tuple(drain_result.calibration_trial_results) if drain_result else (),
            )
            if updated_session is not None:
                st.session_state["voice_calibration_session"] = updated_session
            if drain_result and drain_result.calibration_trial_results:
                last_trial = drain_result.calibration_trial_results[-1]
                trial_count_before = 0
                session_for_count = st.session_state.get("voice_calibration_session")
                if session_for_count is not None:
                    current_cmd = None
                    for cmd in getattr(session_for_count, 'commands', []):
                        if cmd:
                            current_cmd = cmd
                            break
                    if current_cmd:
                        trial_count_before = sum(
                            1 for t in getattr(session_for_count, 'trials', [])
                            if getattr(t, 'expected_command_id', None) == current_cmd
                        )
                st.session_state["voice_calibration_active_trial_id"] = None
                ct_ui_state = _get_command_trial_ui_state()
                last_trial_id = getattr(last_trial, 'trial_id', None)
                last_session_id = getattr(last_trial, 'expected_command_id', None)
                rejection_reason = None
                if ct_ui_state is not None:
                    if ct_ui_state.status != CommandTrialUIStatus.ARMED:
                        rejection_reason = f"ui_not_armed:{ct_ui_state.status.value if hasattr(ct_ui_state.status, 'value') else ct_ui_state.status}"
                    elif last_trial_id and ct_ui_state.trial_id and last_trial_id != ct_ui_state.trial_id:
                        rejection_reason = "stale_trial_id"
                    elif last_session_id and ct_ui_state.expected_command_id and last_session_id != ct_ui_state.expected_command_id:
                        rejection_reason = "stale_session"
                if rejection_reason:
                    _append_continuous_trace(
                        "calibration_command_trial_result_rejected",
                        (
                            f"session={getattr(last_trial, 'expected_command_id', 'N/A')} "
                            f"trial={last_trial_id[:8] if last_trial_id else 'N/A'} "
                            f"reason={rejection_reason}"
                        ),
                    )
                else:
                    if ct_ui_state is not None and ct_ui_state.status == CommandTrialUIStatus.ARMED:
                        _set_command_trial_ui_state(
                            CommandTrialUIState(
                                status=CommandTrialUIStatus.COMPLETED,
                                calibration_session_id=ct_ui_state.calibration_session_id,
                                trial_id=ct_ui_state.trial_id,
                                expected_command_id=ct_ui_state.expected_command_id,
                                expected_phrase=ct_ui_state.expected_phrase,
                                processor_id=ct_ui_state.processor_id,
                                attempt_index=ct_ui_state.attempt_index,
                            )
                        )
                        _append_continuous_trace(
                            "calibration_command_trial_ui_completed",
                            (
                                f"session={ct_ui_state.calibration_session_id[:8] if ct_ui_state.calibration_session_id else 'N/A'} "
                                f"trial={ct_ui_state.trial_id[:8] if ct_ui_state.trial_id else 'N/A'} "
                                f"classification={getattr(last_trial, 'classification', 'N/A')} "
                                f"trial_count_before={trial_count_before} "
                                f"trial_count_after={trial_count_before + 1}"
                            ),
                        )
                _append_continuous_trace(
                    "calibration_command_trial_result_validated",
                    (
                        f"session={getattr(last_trial, 'expected_command_id', 'N/A')} "
                        f"trial={getattr(last_trial, 'trial_id', 'N/A')[:8] if getattr(last_trial, 'trial_id', None) else 'N/A'} "
                        f"classification={getattr(last_trial, 'classification', 'N/A')}"
                    ),
                )
                _append_continuous_trace(
                    "calibration_command_trial_session_updated",
                    (
                        f"session={updated_session.session_id[:8] if updated_session else 'N/A'} "
                        f"trial_count={len(getattr(updated_session, 'trials', []))}"
                    ),
                )
        except Exception:
            pass

    _reconcile_calibration_measurements(drain_result)

    if drain_result and (drain_result.calibration_negative_trials or drain_result.calibration_tts_echo_transcripts):
        try:
            session = st.session_state.get("voice_calibration_session")
            if session is not None:
                if drain_result.calibration_negative_trials:
                    updated = VoiceCalibrationService().consume_negative_trials(
                        session,
                        tuple(drain_result.calibration_negative_trials),
                    )
                else:
                    updated = session
                if drain_result.calibration_tts_echo_transcripts:
                    updated = VoiceCalibrationService().consume_tts_echo_transcripts(
                        updated,
                        tuple(drain_result.calibration_tts_echo_transcripts),
                    )
                st.session_state["voice_calibration_session"] = updated
        except Exception:
            pass
    
    # ============================================================================
    # PingScore-inspired live scoreboard
    # ============================================================================
    st.divider()
    st.subheader("🏓 Live Scoreboard")
    
    # Match setup (format) - applied on reset
    with st.expander("⚙️ Match Setup", expanded=False):
        _pts = st.session_state.match_manager.engine.points_to_win
        _bo = st.session_state.match_manager.engine.best_of
        _fs = st.session_state.match_manager.engine.first_server
        _sc1, _sc2, _sc3 = st.columns(3)
        with _sc1:
            new_pts = st.selectbox("Points to win", [11, 15, 21], index=[11, 15, 21].index(_pts), key="setup_points")
        with _sc2:
            _g2w = best_of_to_games_to_win(_bo)
            new_games_to_win = st.selectbox("Games to win", [2, 3], index=[2, 3].index(_g2w), key="setup_games_to_win", format_func=lambda x: f"{x} games")
            new_bo = games_to_win_to_best_of(new_games_to_win)
        with _sc3:
            new_fs = st.selectbox("First server", ["A", "B"], index=["A", "B"].index(_fs), key="setup_firstserver")
        if st.button("Apply format (resets match)", key="apply_format", use_container_width=True):
            st.session_state.match_manager.apply_format(new_pts, new_bo, new_fs)
            st.toast(f"Format set: first to {new_pts}, first to {new_games_to_win} games", icon="⚙️")
            st.rerun()
    
    # Three-column scoreboard: Player A | Center | Player B
    score_col1, score_colc, score_col2 = st.columns([1, 1, 1])
    
    with score_col1:
        st.markdown(f"<div style='text-align:center;'><h3>{st.session_state.match_manager.state.player_a}</h3></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='text-align:center; font-size:72px; font-weight:bold; color:#0066FF;'>{st.session_state.match_manager.state.score_a}</div>", unsafe_allow_html=True)
        _b1, _b2 = st.columns(2)
        with _b1:
            if st.button("➕ A", key="add_point_a", use_container_width=True):
                result = apply_manual_score_action(
                    ScoreAction(action_type=ScoreActionType.ADD_POINT_A, match_id=st.session_state.get("voice_selected_match_id")),
                    st.session_state.match_manager,
                    st.session_state,
                )
                if result.success:
                    prev_state = copy.deepcopy(st.session_state.match_manager.state)
                    msg = result.message
                    st.session_state.last_feedback = msg
                    st.toast(msg, icon="✅")
                    play_cue("point")
                    _maybe_speak_tts(msg, "increment")
                    _build_and_store_commentary("point_a", st.session_state.match_manager.state, prev_state)
                    if st.session_state.get("tt_sounds_enabled"):
                        audio_summary = finalize_current_audio_rally(reason="point_scored")
                        st.session_state["_pending_audio_summary_for_commentary"] = audio_summary
                        if audio_summary and audio_summary.confidence >= 0.55:
                            _append_audio_commentary_line(audio_summary)
                    try:
                        _mid = st.session_state.get("voice_selected_match_id")
                        if _mid:
                            persist_voice_match_to_db(_mid, st.session_state.match_manager.engine)
                    except Exception:
                        pass
                st.rerun()
        with _b2:
            if st.button("➖ A", key="sub_point_a", use_container_width=True):
                # Quick undo for Player A
                if st.session_state.match_manager.state.match_history:
                    last = st.session_state.match_manager.state.match_history[-1]
                    if last.get("player") == "A":
                        prev_state = copy.deepcopy(st.session_state.match_manager.state)
                        st.session_state.match_manager.undo_last_point()
                        st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_a}"
                        st.toast(st.session_state.last_feedback, icon="↩️")
                        _maybe_speak_tts(st.session_state.last_feedback, "undo")
                        _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
                        if st.session_state.get("tt_sounds_enabled"):
                            _mark_last_audio_summary_action("undo")
                        try:
                            _mid = st.session_state.get("voice_selected_match_id")
                            if _mid:
                                persist_voice_match_to_db(_mid, st.session_state.match_manager.engine)
                        except Exception:
                            pass
                st.rerun()
    
    with score_colc:
        st.markdown("<div style='text-align:center;'><h4>VS</h4></div>", unsafe_allow_html=True)
        # Serve indicator
        _server = get_serving_player(st.session_state.match_manager.engine)
        _server_name = st.session_state.match_manager.state.player_a if _server == "A" else st.session_state.match_manager.state.player_b
        st.markdown(f"<div style='text-align:center;'>🏓 <b>Serve:</b> {_server_name}</div>", unsafe_allow_html=True)
        _last_server = st.session_state.get("commentary_last_server")
        if _server and _last_server is not None and _server != _last_server:
            _build_and_store_commentary("serve", st.session_state.match_manager.state)
        st.session_state.commentary_last_server = _server
        # Deuce badge
        if is_deuce(st.session_state.match_manager.engine):
            st.markdown("<div style='text-align:center; color:red;'><b>⚡ DEUCE</b></div>", unsafe_allow_html=True)
        # Format + games won (games score derived from actual completed games,
        # never from the raw engine counter, so it can't show phantom games).
        _e = st.session_state.match_manager.engine
        _center_games = compute_completed_games(_e)
        _center_games_a, _center_games_b = compute_match_score(_center_games)
        st.markdown(f"<div style='text-align:center; font-size:13px;'>First to {_e.points_to_win} · {best_of_to_games_to_win(_e.best_of)} games</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='text-align:center; font-size:13px;'>Games: {_center_games_a} – {_center_games_b}</div>", unsafe_allow_html=True)
        # Correction controls
        st.markdown("**Corrections**")
        _cor1, _cor2 = st.columns(2)
        with _cor1:
            if st.button("↩️ Undo Point", key="undo_point_center", use_container_width=True):
                prev_state = copy.deepcopy(st.session_state.match_manager.state)
                success, msg = st.session_state.match_manager.undo_last_point()
                st.session_state.last_feedback = msg
                st.toast(msg, icon="↩️")
                play_cue("undo")
                _maybe_speak_tts(msg, "undo")
                _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
                if st.session_state.get("tt_sounds_enabled"):
                    _mark_last_audio_summary_action("undo")
                st.rerun()
        with _cor2:
            if st.button("↩️ Undo Game", key="undo_game_center", use_container_width=True):
                if st.session_state.match_manager.engine.round_scores:
                    success, msg = st.session_state.match_manager.undo_last_completed_game()
                    st.session_state.last_feedback = msg
                    st.toast(msg, icon="↩️")
                    play_cue("undo")
                    if st.session_state.get("tt_sounds_enabled"):
                        _mark_last_audio_summary_action("undo")
                    st.rerun()
                else:
                    st.warning("No completed games to undo")
    
        _rst1, _rst2 = st.columns(2)
        with _rst1:
            if st.button("🔄 Reset Game", key="reset_game_center", use_container_width=True):
                prev_state = copy.deepcopy(st.session_state.match_manager.state)
                success, msg = st.session_state.match_manager.reset_current_game()
                st.session_state.last_feedback = msg
                st.toast(msg, icon="🔄")
                play_cue("undo")
                _build_and_store_commentary("reset", st.session_state.match_manager.state, prev_state)
                if st.session_state.get("tt_sounds_enabled"):
                    _mark_last_audio_summary_action("reset")
                st.rerun()
        with _rst2:
            if st.button("🗑️ Reset Match", key="reset_match_center", use_container_width=True):
                prev_state = copy.deepcopy(st.session_state.match_manager.state)
                success, msg = st.session_state.match_manager.reset_match()
                clear_result_review_state()
                st.session_state.last_feedback = msg
                st.toast(msg, icon="🔄")
                play_cue("undo")
                _build_and_store_commentary("reset", st.session_state.match_manager.state, prev_state)
                if st.session_state.get("tt_sounds_enabled"):
                    _mark_last_audio_summary_action("reset")
                st.rerun()
        # Voice status
        if st.session_state.get("last_voice_feedback"):
            st.caption(f"🎙️ {st.session_state.last_voice_feedback}")
        # Speaker selection (Phase 2)
        _tagger = st.session_state.voice_speaker_tagger
        if _tagger.mode != "off":
            _speaker_options = [""] + _tagger.allowed_speakers
            _current_speaker = st.session_state.get("voice_current_speaker") or ""
            _speaker_idx = _speaker_options.index(_current_speaker) if _current_speaker in _speaker_options else 0
            _new_speaker = st.selectbox(
                "🎤 Speaker",
                options=_speaker_options,
                index=_speaker_idx,
                key="speaker_select",
                help="Select who is speaking (for audit/logging).",
            )
            if _new_speaker != _current_speaker:
                st.session_state.voice_current_speaker = _new_speaker if _new_speaker else None
                _tagger.set_current_speaker(_new_speaker if _new_speaker else None)
                st.rerun()
        # Audio status indicator (Audio controls moved to Spoken Commentary section).
        _tts_status = ""
        if st.session_state.get("sound_cues_enabled"):
            _tts_status = "🔊 Sound on"
        _tts_adapter = st.session_state.get("voice_tts_adapter")
        if _tts_adapter and _tts_adapter.enabled and _tts_adapter.mode != TTSMode.OFF:
            _tts_status += (" · " if _tts_status else "") + f"TTS: {TTS_FRIENDLY_LABELS.get(_tts_adapter.mode.value, _tts_adapter.mode.value)}"
        if _tts_status:
            st.caption(_tts_status)
    
    with score_col2:
        st.markdown(f"<div style='text-align:center;'><h3>{st.session_state.match_manager.state.player_b}</h3></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='text-align:center; font-size:72px; font-weight:bold; color:#FF6D00;'>{st.session_state.match_manager.state.score_b}</div>", unsafe_allow_html=True)
        _b1, _b2 = st.columns(2)
        with _b1:
            if st.button("➕ B", key="add_point_b", use_container_width=True):
                prev_state = copy.deepcopy(st.session_state.match_manager.state)
                success, msg = st.session_state.match_manager._add_point("B")
                st.session_state.last_feedback = msg
                st.toast(msg, icon="✅")
                play_cue("point")
                _maybe_speak_tts(msg, "increment")
                _build_and_store_commentary("point_b", st.session_state.match_manager.state, prev_state)
                if st.session_state.get("tt_sounds_enabled"):
                    audio_summary = finalize_current_audio_rally(reason="point_scored")
                    st.session_state["_pending_audio_summary_for_commentary"] = audio_summary
                    if audio_summary and audio_summary.confidence >= 0.55:
                        _append_audio_commentary_line(audio_summary)
                try:
                    _mid = st.session_state.get("voice_selected_match_id")
                    if _mid:
                        persist_voice_match_to_db(_mid, st.session_state.match_manager.engine)
                except Exception:
                    pass
                st.rerun()
        with _b2:
            if st.button("➖ B", key="sub_point_b", use_container_width=True):
                # Quick undo for Player B
                if st.session_state.match_manager.state.match_history:
                    last = st.session_state.match_manager.state.match_history[-1]
                    if last.get("player") == "B":
                        prev_state = copy.deepcopy(st.session_state.match_manager.state)
                        st.session_state.match_manager.undo_last_point()
                        st.session_state.last_feedback = f"Point removed from {st.session_state.match_manager.state.player_b}"
                        st.toast(st.session_state.last_feedback, icon="↩️")
                        _maybe_speak_tts(st.session_state.last_feedback, "undo")
                        _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
                        if st.session_state.get("tt_sounds_enabled"):
                            _mark_last_audio_summary_action("undo")
                        try:
                            _mid = st.session_state.get("voice_selected_match_id")
                            if _mid:
                                persist_voice_match_to_db(_mid, st.session_state.match_manager.engine)
                        except Exception:
                            pass
                st.rerun()
    
    # ============================================================================
    # Quick Voice Stats & Feedback (Quick Voice Scoring mode only)
    # ============================================================================
    if st.session_state.get("quick_voice_mode") == "quick":
        _e = st.session_state.match_manager.engine
        _stats = get_live_stats(_e)
        _trail = get_point_log(_e)
        
        st.divider()
        col_trail, col_stats = st.columns([2, 1])
        with col_trail:
            st.markdown("**Point Trail**")
            chips = "".join(
                f"<span style='display:inline-block;width:24px;height:24px;border-radius:50%;"
                f"background:{'#0066FF' if p == 'A' else '#FF6D00'};margin:2px;'></span>"
                for p in _trail[-20:]
            )
            st.markdown(f"<div style='text-align:center;'>{chips}</div>", unsafe_allow_html=True)
        
        with col_stats:
            st.markdown("**Live Stats**")
            streak_text = f"Streak: {_stats['current_streak_player']} ({_stats['current_streak']})"
            max_streak_text = f"Max streak: A={_stats['max_streak_a']}, B={_stats['max_streak_b']}"
            lead_text = f"Biggest lead: {_stats['biggest_lead_player']} by {_stats['biggest_lead_margin']}"
            st.caption(f"{streak_text}\n{max_streak_text}\n{lead_text}")
        
        _last_phrase = st.session_state.quick_voice_last_phrase
        _last_status = st.session_state.quick_voice_last_status
        
        if _last_status == "accepted":
            st.success(f"🎤 **{_last_phrase}** → Point accepted")
        elif _last_status == "duplicate_ignored":
            st.warning(f"🎤 **{_last_phrase}** → Duplicate ignored")
        elif _last_status == "too_soon":
            st.info(f"🎤 **{_last_phrase}** → Too soon, ignored")
        elif _last_status == "rejected":
            st.info(f"🎤 **{_last_phrase}** → Unknown command")
        
        st.caption(
            "Say **Blue / Teal / Green** for Player A  |  "
            "Say **Red / Orange** for Player B  |  "
            "Lithuanian: **Mėlynas** (A), **Žalias** (A), **Raudonas** (B), **Oranžinis** (B)"
        )
    
    # ============================================================================
    # Round / Match Winner Screens (Phase 5 / PingScore port)
    # ============================================================================
    
    _e = st.session_state.match_manager.engine
    _mm = st.session_state.match_manager
    
    # Derive completed games + match score from the engine (single source of truth)
    # and mirror them into session state for the review / submission flow. The
    # engine is never mutated here.
    _completed_games = compute_completed_games(_e)
    st.session_state.completed_games = _completed_games
    _derived_games_a, _derived_games_b = compute_match_score(_completed_games)
    st.session_state.match_complete = _e.match_status == "match_won"
    
    # Reconcile finished games: emit set_win commentary for each completed game
    # exactly once (dedupe prevents re-emission across Streamlit reruns).
    _reconcile_finished_games()
    
    # Completed games review list — always visible once any game is finished so the
    # operator can review the real game-by-game scores (never a silent 0-0).
    if _completed_games:
        st.divider()
        st.markdown("**📋 Completed games**")
        for _g in _completed_games:
            _gw_name = _mm.state.player_a if _g["winner"] == "A" else _mm.state.player_b
            st.caption(
                f"Game {_g['game']}: {_g['player_a_score']}-{_g['player_b_score']} "
                f"({_gw_name})"
            )
        st.caption(f"Match score: {_derived_games_a} – {_derived_games_b}")
    
    if _e.match_status == "game_won":
        # Determine who won the just-completed game
        last_game = _e.round_scores[-1] if _e.round_scores else (0, 0)
        game_winner_name = _mm.state.player_a if last_game[0] > last_game[1] else _mm.state.player_b
        st.success(f"🏆 **Game {len(_completed_games)}** — {game_winner_name} wins {last_game[0]}-{last_game[1]}!")
        st.caption(f"Games: {_derived_games_a} – {_derived_games_b}  |  Next game starting…")
        play_cue("game")
        if st.button("▶️ Next Game", key="next_game_btn", use_container_width=True, type="primary"):
            # The engine is already reset for the next game; just clear the game_won status
            # and rerun to show the live scoreboard again.
            _e.match_status = "in_progress"
            st.rerun()
    
    if st.session_state.match_complete:
        st.divider()
        match_winner_name = _mm.state.player_a if _derived_games_a > _derived_games_b else _mm.state.player_b
        _selected_match_id = st.session_state.get("voice_selected_match_id")
    
        if not _completed_games:
            # Defensive: a legacy/manual path marked the match complete without any
            # recorded games. Never silently persist a 0-0 result.
            st.warning(
                "⚠️ Match is marked complete but no completed games were recorded — "
                "result cannot be submitted."
            )
            st.session_state.pending_result_submission = False
        elif st.session_state.result_submitted:
            st.success(
                f"✅ **Result saved!** {match_winner_name} won "
                f"{_derived_games_a}-{_derived_games_b}."
            )
            st.session_state.pending_result_submission = False
        else:
            st.balloons()
            st.success(
                f"🏅 **Match Complete!** {match_winner_name} wins "
                f"{_derived_games_a}-{_derived_games_b}!"
            )
            st.caption(f"Format: first to {_e.points_to_win}, {best_of_to_games_to_win(_e.best_of)} games")
            st.info("⏳ Pending submission — review the result above before saving.")
            st.session_state.pending_result_submission = True
            play_cue("match")
            if not st.session_state.get("commentary_announced_match_won"):
                _build_and_store_commentary("match_win", st.session_state.match_manager.state)
                st.session_state.commentary_announced_match_won = True
    
        # Submit Result — the DB is written ONLY here, and only when a match is
        # complete, has recorded games, is linked to a tournament match, and has
        # not already been submitted.
        if _completed_games and not st.session_state.result_submitted:
            if _selected_match_id:
                _can_submit = bool(match_winner_name)
                if st.button(
                    "💾 Submit Result",
                    key="submit_result_btn",
                    type="primary",
                    use_container_width=True,
                    disabled=not _can_submit,
                ):
                    finalize_voice_match(_selected_match_id, _e)
                    st.session_state.result_submitted = True
                    st.session_state.pending_result_submission = False
                    if not st.session_state.get("commentary_announced_result_submitted"):
                        _build_and_store_commentary("result_submitted", st.session_state.match_manager.state)
                        st.session_state.commentary_announced_result_submitted = True
                    st.toast("Result submitted!", icon="✅")
                    # Refresh dashboard / recent-results caches so the completed
                    # match becomes visible immediately.
                    st.cache_data.clear()
                    st.rerun()
            else:
                # Free-play (no linked DB match): show a disabled button with an
                # explanation instead of silently hiding the action.
                st.button(
                    "💾 Submit Result",
                    key="submit_result_btn",
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    help="No linked tournament match — result cannot be saved.",
                )
                st.caption(
                    "ℹ️ No linked tournament match — result cannot be saved. "
                    "Select an active match to enable submission."
                )
    else:
        # Match not complete: there is nothing pending to submit.
        st.session_state.pending_result_submission = False
    
    # Rematch / New Match:
    #  - after submission (or when there is nothing to save): shown as normal
    #    next actions,
    #  - before submission of a linked, completed match: shown as secondary
    #    controls behind an explicit "result not saved" warning so they never
    #    mask the Submit Result action.
    _pre_submit_unsaved = (
        st.session_state.match_complete
        and not st.session_state.result_submitted
        and bool(_completed_games)
        and bool(st.session_state.get("voice_selected_match_id"))
    )
    if _pre_submit_unsaved:
        st.caption("⚠️ Result not saved yet — Rematch / New Match will discard it.")
    
    _rem1, _rem2, _rem3 = st.columns(3)
    with _rem1:
        if st.button(
            "🔄 Rematch",
            key="rematch_btn",
            use_container_width=True,
            type="secondary" if _pre_submit_unsaved else "primary",
        ):
            _mm.rematch()
            clear_result_review_state()
            st.toast("Rematch! First server swapped.", icon="🔄")
            st.rerun()
    with _rem2:
        if st.button("🆕 New Match", key="new_match_btn", use_container_width=True):
            _mm.reset_match()
            clear_result_review_state()
            st.toast("New match ready.", icon="🆕")
            st.rerun()
    
    # ============================================================================
    # Voice Scoring Section (WebRTC + Local ASR)
    # ============================================================================
    
    st.divider()
    render_voice_sections(snapshot=_webrtc_snapshot)

    from typing import Any


@dataclass
class CompletedMatchSelection:
    """Shared match-selection boundary between analytics and recap."""

    source: str
    match: Any
    match_id: int



def _render_voice_scoring_settings(snapshot: WebRtcRenderSnapshot | None = None) -> None:
    """Render voice scoring settings."""
    _ss = st.session_state
    
    # Unconditional initialization of key render-local state variables
    # to avoid UnboundLocalError/NameError across all control-flow branches.
    from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
    if snapshot is None:
        snapshot = WebRtcRenderSnapshot.unavailable()
    
    _tracked_factory = _ss.get("voice_webrtc_tracked_factory")
    _current_proc = snapshot.processor
    _streaming_state = _ss.get("voice_streaming_state", "disabled")
    _streaming_ui_state = _ss.get("streaming_ui_state", "disabled")
    _config_frozen = _ss.get("voice_streaming_config_frozen", False)
    _status = _ss.get("voice_streaming_diagnostics", {})
    _desired_playing = bool(_ss.get("desired_mic_playing", False))
    _mount_err = snapshot.mount_error or _ss.get("voice_webrtc_mount_error")
    _webrtc_playing = snapshot.playing
    _webrtc_signalling = snapshot.signalling
    
    st.subheader("🎤 Voice Scoring")

    # Voice scoring toggle
    col_enable, col_status = st.columns([2, 1])
    with col_enable:
        _prev_enabled = st.session_state.get("voice_scoring_enabled", False)
        st.session_state.voice_scoring_enabled = st.toggle(
            "Enable Voice Scoring",
            value=st.session_state.voice_scoring_enabled,
            help="Turn on voice scorekeeping. Push-to-talk is the default reliable mode. "
                 "Continuous listening is optional and experimental.",
        )
        _prev_mode = st.session_state.get("quick_voice_mode", "off")
        st.session_state.quick_voice_mode = st.segmented_control(
            "Voice Mode",
            options=["off", "full", "quick"],
            format_func=lambda x: {"off": "Off", "full": "Full Voice Commands", "quick": "Quick Voice Scoring"}[x],
            default=_prev_mode,
        )
        _new_mode = st.session_state.quick_voice_mode
        if _new_mode != _prev_mode:
            _on_quick_voice_mode_changed(_prev_mode, _new_mode)
        if _new_mode == "quick" and not _quick_voice_asr_ready():
            st.warning(
                "Quick Voice Scoring needs a working transcript provider. "
                "ASR is not ready — see Voice ASR Diagnostics. Use push-to-talk "
                "or manual scoring until ASR loads."
            )
        # Detect transition: ON→OFF clears all pending voice state
        _curr_enabled = st.session_state.voice_scoring_enabled
        if _prev_enabled and not _curr_enabled:
            _stop_streaming_voice_session()
            _disable_continuous_listening()
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
            st.toast("🎤 Voice scoring disabled — all pending voice commands cleared.", icon="ℹ️")
        elif not _prev_enabled and _curr_enabled:
            _increment_voice_session_epoch()
            st.toast("🎤 Voice scoring enabled — new session started.", icon="✅")
    with col_status:
        if not st.session_state.voice_scoring_enabled:
            st.markdown("⚪ **Disabled**")
        elif not WEBRTC_AVAILABLE:
            st.markdown("🔴 **WebRTC unavailable**")
        else:
            _webrtc_playing = snapshot.playing
            _proc = snapshot.processor
            _readiness = resolve_continuous_listening_readiness(
                webrtc_playing=_webrtc_playing,
                processor=_proc,
            )
            if _readiness["ready"]:
                st.markdown("🟢 **Continuous microphone active**")
            elif _readiness["status"] == "WAITING_FOR_FIRST_FRAME":
                st.markdown("🟡 **Microphone connected. Waiting for audio frames...**")
            elif _readiness["status"] == "STALLED":
                st.markdown("🟠 **Microphone connected but no recent frames received.**")
            elif _readiness["status"] == "WAITING_FOR_PROCESSOR":
                st.markdown("🟡 **Waiting for voice processor...**")
            elif _readiness["status"] == "MICROPHONE_STOPPED":
                st.markdown("⚪ **Microphone stopped**")
            else:
                st.markdown("🟡 **Ready**")
    
        # Audio Rally Assistant toggle
        _prev_audio = st.session_state.get("tt_sounds_enabled", False)
        st.session_state.tt_sounds_enabled = st.toggle(
            "Audio Rally Assistant",
            value=st.session_state.get("tt_sounds_enabled", False),
            help="Detects table-tennis impact sounds for commentary enrichment only. "
                 "Does NOT update the score. Disabled by default.",
        )
        if st.session_state.tt_sounds_enabled and not WEBRTC_AVAILABLE:
            st.info("Audio Rally Assistant requires streamlit-webrtc (unavailable in this environment).")
        if _prev_audio and not st.session_state.tt_sounds_enabled:
            _clear_tt_sounds_state()
            st.toast("Audio Rally Assistant disabled.", icon="ℹ️")

    # ------------------------------------------------------------------
    # Step 9: Streaming Voice Scoring (Deepgram or local provider)
    # ------------------------------------------------------------------
    st.subheader("🎙️ Streaming Voice Scoring")

    _streaming_backends = ASRBackendFactory.streaming_backends()
    _streaming_available = bool(_streaming_backends)

    if not _streaming_available:
        st.info(
            "No streaming ASR backend is registered by this build. "
            "Ensure `deepgram-sdk` is installed and `VOICE_ASR_BACKEND=deepgram` is set."
        )
    else:
        _config_frozen = st.session_state.voice_streaming_config_frozen
        _provider_disabled = _config_frozen
        _language_disabled = _config_frozen

        # Resolve provider deterministically before any branch can read it
        _provider_key = "voice_streaming_provider"
        _current_provider = st.session_state.get(_provider_key) or "deepgram"
        _current_language = st.session_state.get("voice_streaming_language") or "lt"

        # Resolve Voice Mode — must be "full" or "quick" to allow streaming
        _resolved_voice_mode = st.session_state.get("quick_voice_mode", "off")
        _voice_mode_allows_streaming = _resolved_voice_mode in ("full", "quick")

        # If Voice Mode is Off and a streaming session is active, stop it
        if not _voice_mode_allows_streaming and _config_frozen:
            _stop_streaming_voice_session()

        # Canonical streaming UI state — always defined, never raises NameError
        _streaming_state = st.session_state.get("voice_streaming_state", "disabled")
        _streaming_ui_state = st.session_state.get("streaming_ui_state", "disabled")
        if _streaming_ui_state not in ("disabled",) and _streaming_state == "disabled":
            _streaming_state = _streaming_ui_state
        if _streaming_state not in (
            "disabled", "connecting", "ready", "listening",
            "reconnecting", "degraded", "failed", "stopping",
            "starting_microphone", "waiting_for_processor",
        ):
            _streaming_state = "failed"

        # Check streaming backend availability via structured status
        # (no live WebSocket connection — only checks env/config)
        _status = ASRBackendFactory.streaming_backend_status(_current_provider)
        _has_active_backend = False
        _current_proc = snapshot.processor
        if _current_proc is not None:
            _existing_backend = getattr(_current_proc, "_streaming_backend", None)
            if _existing_backend is not None and hasattr(_existing_backend, "connection_state"):
                _existing_state = _existing_backend.connection_state()
                if _existing_state in ("connecting", "connected", "reconnecting"):
                    _has_active_backend = True

        _webrtc_playing_now = snapshot.playing
        _desired_mic_now = st.session_state.get("desired_mic_playing", False)
        _ui_state_now = st.session_state.get("streaming_ui_state", "disabled")
        _voice_state_now = st.session_state.get("voice_streaming_state", "disabled")

        _can_start = (
            not _config_frozen
            and _status.available
            and not _has_active_backend
            and _voice_mode_allows_streaming
            and _ui_state_now in ("disabled", "failed", "microphone_stopped")
        )
        _can_stop = (
            _config_frozen
            or _has_active_backend
            or _webrtc_playing_now
            or (_desired_mic_now and _voice_state_now not in ("disabled", "failed"))
            or st.session_state.get("voice_start_requested", False)
            or _ui_state_now in ("starting_microphone", "waiting_for_processor", "connecting")
        )

        # Show Voice Mode info when Off
        if not _voice_mode_allows_streaming and not _config_frozen:
            st.info(
                "Select **Full Voice Commands** or **Quick Voice Scoring** "
                "to start streaming voice scoring.",
                icon="ℹ️",
            )

        # Show precise configuration message when not available
        if not _status.available and not _config_frozen and _voice_mode_allows_streaming:
            if _status.safe_message:
                st.warning(_status.safe_message, icon="⚠️")
        elif not _status.available and _config_frozen:
            st.session_state.voice_streaming_config_frozen = False
            st.session_state.voice_streaming_state = "disabled"
            st.session_state.voice_streaming_error = _status.safe_message
            st.session_state.voice_streaming_last_error_code = _status.reason_code
            st.warning(_status.safe_message, icon="⚠️")

        # Provider selector (frozen when streaming active)
        _available_providers = list(_streaming_backends.keys())
        _selected_provider = st.selectbox(
            "Provider",
            options=_available_providers,
            index=_available_providers.index(_current_provider)
            if _current_provider in _available_providers
            else 0,
            key=f"_stream_provider_sel_{id(st.session_state)}",
            disabled=_provider_disabled,
            help="Streaming ASR provider. Frozen until voice scoring stops.",
        )
        if _selected_provider != _current_provider:
            st.session_state[_provider_key] = _selected_provider
            st.session_state.voice_streaming_config_frozen = False
            st.session_state.voice_streaming_state = "disabled"
            st.session_state.voice_streaming_error = None
            st.rerun()

        # Language selector (frozen when streaming active)
        _language_key = "voice_streaming_language"
        _selected_language = st.segmented_control(
            "Language",
            options=["lt", "en"],
            format_func=lambda x: {"lt": "🇱🇹 Lithuanian", "en": "🇬🇧 English"}[x],
            default=_current_language,
            key=f"_stream_lang_seg_{id(st.session_state)}",
            disabled=_language_disabled,
        )
        if _selected_language != _current_language:
            st.session_state[_language_key] = _selected_language
            st.session_state.voice_streaming_config_frozen = False
            st.session_state.voice_streaming_state = "disabled"
            st.session_state.voice_streaming_error = None
            st.rerun()

        col_start, col_stop = st.columns(2)
        with col_start:
            if st.button(
                "Start Voice Scoring",
                key="stream_start_btn",
                type="primary",
                use_container_width=True,
                disabled=not _can_start,
            ):
                _start_streaming_voice_session()
                _process_streaming_startup()
        with col_stop:
            if st.button(
                "Stop Voice Scoring",
                key="stream_stop_btn",
                type="secondary",
                use_container_width=True,
                disabled=not _can_stop,
            ):
                _stop_streaming_voice_session()
                st.rerun()

        # Connection state badge — must reflect current WebRTC playing state,
        # not stale session state from the previous run.
        _webrtc_playing_now = _get_webrtc_playing_state()
        if not _webrtc_playing_now and _streaming_state in ("ready", "listening"):
            _streaming_state = "microphone_stopped"
        _state_badge = {
            "disabled": "⚪ Disabled",
            "starting_microphone": "🟡 Starting microphone",
            "waiting_for_processor": "🟡 Waiting for processor",
            "connecting": "🔵 Connecting",
            "ready": "🟢 Ready",
            "listening": "🔵 Listening",
            "microphone_stopped": "⚪ Microphone stopped",
            "reconnecting": "🟠 Reconnecting",
            "degraded": "🟠 Degraded",
            "failed": "🔴 Failed",
            "stopping": "⚫ Stopping",
        }.get(_streaming_state, f"❓ {_streaming_state}")
        st.markdown(f"**Connection state:** {_state_badge}")

        if st.session_state.voice_streaming_error:
            st.error(
                f"Streaming error: {st.session_state.voice_streaming_error}",
                icon="⚠️",
            )

        # Latest finalized transcript
        _last_finalized = st.session_state.get("voice_streaming_last_finalized", "")
        if _last_finalized:
            st.markdown(f"**Provider latest final transcript:** {_last_finalized}")
            
        _app_last_continuous = st.session_state.get("last_voice_continuous_transcript", "")
        if _app_last_continuous:
            st.markdown(f"**Application last continuous transcript:** {_app_last_continuous}")

        # Latest interim transcript (clearly marked provisional)
        _last_interim = st.session_state.get("voice_streaming_last_interim", "")
        if _last_interim:
            st.caption(f"**Provisional (interim):** {_last_interim}")
        else:
            st.caption("Provisional (interim): —")

        # Last accepted / rejected command
        _last_accepted = st.session_state.get("voice_last_applied_event_key", "")
        _last_rejected = st.session_state.get("last_voice_rejection_reason", "")
        if _last_accepted:
            st.caption(f"**Last accepted command:** {_last_accepted}")
        if _last_rejected:
            st.caption(f"**Last rejected command:** {_last_rejected}")

        # Session info (frozen config display)
        if _config_frozen:
            with st.expander("📋 Frozen Session Configuration", expanded=False):
                _diag = _ss.get("voice_streaming_diagnostics", {})
                st.markdown(
                    "\n".join(
                        f"- **{k}:** {v}" for k, v in sorted(_diag.items())
                    )
                )

        # State-transition assertions (development only; fail closed in production).
        _webrtc_playing_now = snapshot.playing
        _resolved_state = st.session_state.get("voice_streaming_state", "disabled")
        _proc = snapshot.processor
        _backend = getattr(_proc, "_streaming_backend", None) if _proc else None
        _backend_attached = _backend is not None
        _backend_connected = (
            _backend is not None
            and hasattr(_backend, "connection_state")
            and _backend.connection_state() == "connected"
        )
        if _resolved_state in ("ready", "listening"):
            _invariant_ok = (
                _webrtc_playing_now is True
                and _proc is not None
                and _backend_attached is True
                and _backend_connected is True
            )
            if not _invariant_ok:
                _append_continuous_trace(
                    "voice_state_invariant_violation",
                    f"state={_resolved_state} playing={_webrtc_playing_now} "
                    f"processor={_proc is not None} backend_attached={_backend_attached} "
                    f"backend_connected={_backend_connected}",
                )
                st.session_state.voice_streaming_state = "failed"
                st.session_state.streaming_ui_state = "failed"
                st.session_state.voice_streaming_config_frozen = False
                _set_desired_mic_playing(False, reason="state_invariant_violation", caller="_assert_voice_state_invariants")

    # Voice Calibration Wizard
    if render_voice_calibration is not None and VoiceCalibrationService is not None:
        try:
            render_voice_calibration(
                calibration_service=VoiceCalibrationService(),
            )
        except Exception as exc:
            logger.exception("Calibration wizard failed")
            st.warning(f"Calibration wizard unavailable: {exc}")

    # Noise Robustness
    with st.expander("🎛 Noise Robustness", expanded=False):
        st.caption("Tune speech-energy gating for tournament environments. "
                   "Changes apply to this session without code edits.")
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.voice_noise_filtering = st.checkbox(
                "Enable noise gate",
                value=st.session_state.voice_noise_filtering,
                help="Reject chunks whose energy is below the threshold.",
            )
        with c2:
            st.session_state.voice_strict_mode = st.checkbox(
                "Strict mode (require confirmation)",
                value=st.session_state.voice_strict_mode,
                help="Flag score events for confirmation in noisy venues.",
            )
        st.session_state.voice_noise_threshold = st.number_input(
            "Noise threshold (RMS)",
            min_value=0.0, max_value=1.0, step=0.001,
            value=float(st.session_state.voice_noise_threshold),
            help="Minimum speech energy. Chunks below this are ignored.",
        )
        st.metric("Last chunk RMS", round(st.session_state.voice_last_chunk_rms or 0.0, 4))
        if st.button("📊 Recommend threshold from samples", key="noise_recommend_btn"):
            samples = st.session_state.voice_rms_samples
            if samples:
                profiler = NoiseProfiler(ambient_samples=list(samples))
                rec = profiler.recommend_threshold()
                st.session_state.voice_noise_threshold = rec
                st.success(
                    f"Recommended threshold: {rec} (from {len(samples)} samples, "
                    f"ambient mean {round(profiler.ambient_stats().mean, 4)})"
                )
            else:
                st.info("No RMS samples yet. Start listening and let some audio through first.")
        st.caption("Tip: sample ambient hall noise, then set the threshold a bit above it. "
                   "Directional/close microphones improve accuracy.")

        recommendation = st.session_state.get("voice_live_profile_recommendation")
        activation_status = st.session_state.get("voice_live_profile_activation_status")

        if recommendation is not None and _render_live_profile_recommendation is not None:
            st.markdown("---")
            st.caption("Calibrated voice profile recommendation:")
            _render_live_profile_recommendation(recommendation)

            st.session_state["voice_calibration_auto_apply"] = st.checkbox(
                "Apply safe recommendations after successful calibration",
                value=st.session_state.get("voice_calibration_auto_apply", False),
                key="noise_auto_apply_cb",
            )

            rec_available = recommendation.status in {RecommendationStatus.AVAILABLE, RecommendationStatus.WARNING} if RecommendationStatus is not None else True
            if activation_status is None and rec_available and (
                st.session_state.get("voice_calibration_auto_apply", False)
                or st.button("Activate calibrated voice profile", key="noise_activate_btn", type="primary")
            ):
                from tournament_platform.app.services.voice_calibration.models import LiveVoiceSettingsSnapshot
                current_snapshot = LiveVoiceSettingsSnapshot(
                    noise_gate_enabled=st.session_state.voice_noise_filtering,
                    noise_threshold_rms=st.session_state.voice_noise_threshold,
                    strict_mode_enabled=st.session_state.voice_strict_mode,
                    asr_config_id=None,
                    aliases=(),
                    preferred_phrases=(),
                    config_revision=st.session_state.get("voice_live_profile_config_revision", 0),
                )
                previous = _activate_calibrated_voice_profile(recommendation, current_snapshot)
                if previous is not None:
                    st.session_state.voice_live_profile_settings_snapshot = previous
                    st.session_state.voice_live_profile_activation_status = VoiceProfileActivationStatus.ACTIVE
                    st.session_state.voice_live_profile_config_revision += 1
                    st.rerun()
                else:
                    st.error("Could not activate calibrated profile.")

            if activation_status is not None and _undo_calibrated_settings is not None:
                if st.button("Undo calibrated settings", key="noise_undo_btn", type="secondary"):
                    _undo_calibrated_settings()
                    st.session_state.voice_live_profile_activation_status = VoiceProfileActivationStatus.INACTIVE
                    st.rerun()

            if _render_post_activation_verification is not None:
                _render_post_activation_verification()

            if activation_status is not None and _render_effective_configuration is not None:
                st.markdown("---")
                _render_effective_configuration()

    if st.session_state.voice_scoring_enabled or st.session_state.get("tt_sounds_enabled", False):
        if st.session_state.voice_scoring_enabled:
            st.markdown("**Push-to-Talk** (recommended)")
            st.caption("Click the microphone, speak your command, and release to send.")
    
        # Continuous listening is optional.
        with st.expander("🎙 Full Voice Commands", expanded=True):
            st.caption(
                "Uses streamlit-webrtc for hands-free continuous voice capture. "
                "This mode is experimental and may miss commands in noisy environments. "
                "Push-to-talk remains the default reliable mode."
            )
            # WebRTC mount error display
            _mount_err = st.session_state.get("voice_webrtc_mount_error")
            if _mount_err:
                st.error(f"WebRTC mount failed: {_mount_err}")

            if not WEBRTC_AVAILABLE:
                st.info("Continuous listening requires streamlit-webrtc. Use Push-to-Talk instead.")
                st.caption("You can still use the push-to-talk voice input below.")
            else:
                _tracked_factory = st.session_state.get("voice_webrtc_tracked_factory")
                st.caption(
                    "Click **Start Voice Scoring** and allow browser microphone permission. "
                    "Stop Voice Scoring ends both Deepgram and microphone capture. "
                    "Voice commands are processed only while the microphone is active."
                )
            
                # Point 5: authoritative snapshot display
                if snapshot.playing:
                    st.success("🟢 **Microphone active** (Continuous capture)")
                elif st.session_state.get("desired_mic_playing"):
                    st.info("🟡 **Starting microphone...**")
                else:
                    st.info("⚪ **Microphone stopped**")

                if snapshot.processor:
                    _frames = snapshot.audio_frames_received
                    if _frames > 0:
                        st.caption(f"✓ Voice processor connected ({_frames} frames received)")
                    else:
                        st.caption("✓ Voice processor connected (Waiting for audio...)")

                # Snapshot factory diagnostics to session_state from the main thread.
                # Use factory.get_diagnostics() — the factory owns its lock.
                try:
                    _factory_diag = _tracked_factory.get_diagnostics()
                    if _factory_diag["call_count"] > 0:
                        _ss._voice_factory_call_count = _factory_diag["call_count"]
                    if _factory_diag["callback_count"] > 0:
                        _ss._voice_processor_callback_count = _factory_diag["callback_count"]
                    if _factory_diag["last_error"] is not None:
                        _ss._voice_factory_last_error = _factory_diag["last_error"]
                    if _factory_diag["last_processor_id"] is not None:
                        _ss._voice_last_processor_id = _factory_diag["last_processor_id"]
                    if _factory_diag["last_processor_class"] is not None:
                        _ss._voice_last_processor_class = _factory_diag["last_processor_class"]
                    if _factory_diag["last_exception"] is not None:
                        _ss._voice_last_processor_exception = _factory_diag["last_exception"]
                except Exception:
                    pass
            
                # Snapshot audio callback diagnostics (fallback path).
                with _audio_callback_lock:
                    _ss._voice_audio_callback_count = _audio_callback_count
                    _ss._voice_last_audio_frame_timestamp = _last_audio_frame_timestamp
                    _ss._voice_last_audio_frame_rms = _last_audio_frame_rms
                    _ss._voice_last_audio_frame_shape = _last_audio_frame_shape
                    _ss._voice_last_audio_frame_sample_rate = _last_audio_frame_sample_rate
                    _ss._voice_last_audio_frame_method = _last_audio_frame_method
            
                # Main-thread frame audit: emit trace events for first frame and
                # every 100th frame without flooding the audit log.
                _audit_proc = get_active_voice_processor()
                if _audit_proc is not None:
                    _frames = getattr(_audit_proc, "_audio_frames_received", 0)
                    _last_audit = st.session_state.get("_voice_main_thread_frame_audit_count", 0)
                    if _frames > 0 and _last_audit != _frames:
                        if _last_audit == 0:
                            _append_continuous_trace("continuous_audio_frame_received", "first_frame")
                        elif _frames - _last_audit >= 100:
                            _append_continuous_trace("continuous_audio_frame_received", f"frame_{_frames}")
                        st.session_state._voice_main_thread_frame_audit_count = _frames

                if snapshot.context is not None:
                    _ss.voice_webrtc_streamer_state = {
                        "playing": snapshot.playing,
                        "signalling": snapshot.signalling,
                    }
                else:
                    _ss.voice_webrtc_streamer_state = {
                        "playing": False,
                        "signalling": False,
                    }

                # Detect WebRTC state transitions for trace events
                _current_playing = st.session_state.voice_webrtc_streamer_state.get("playing", False)
                _prev_playing = st.session_state.get("_voice_prev_webrtc_playing", False)
                if _current_playing and not _prev_playing:
                    _append_continuous_trace("webrtc_playing", "microphone_stream_started")
                    # Auto-create continuous session on WebRTC play transition
                    st.session_state.voice_continuous_session_id = str(uuid.uuid4())
                    st.session_state.voice_continuous_session_start = time.time()
                    st.session_state.voice_continuous_requested = True
                    st.session_state.voice_events_enabled = True
                    st.session_state.voice_listening = True
                    st.session_state.voice_stale_events_ignored = 0
                    st.session_state.last_voice_continuous_transcript = ""
                    st.session_state.last_voice_push_to_talk_transcript = ""
                    st.session_state.last_voice_debug_transcript = ""
                    _append_continuous_trace("continuous_session_started", f"session={st.session_state.voice_continuous_session_id[:8]}")
                    # Reset processor audio buffer if it exists
                    _proc = _get_current_webrtc_processor()
                    if _proc is not None:
                        try:
                            if hasattr(_proc, 'audio_buffer') and _proc.audio_buffer is not None:
                                _proc.audio_buffer.reset()
                        except Exception:
                            pass
                elif not _current_playing and _prev_playing:
                    _append_continuous_trace("webrtc_not_playing", "microphone_stream_stopped")
                    st.session_state.voice_continuous_requested = False
                    st.session_state.voice_events_enabled = False
                    st.session_state.voice_listening = False
                    st.session_state.voice_continuous_session_id = None
                    st.session_state.voice_continuous_session_start = 0.0
                    _append_continuous_trace("continuous_session_stopped", "microphone_stream_stopped")

                    # Do NOT immediately clear the backend on a single not-playing frame.
                    # Record the timestamp and let _refresh_streaming_diagnostics handle
                    # confirmed unexpected-stop cleanup after a grace period.
                    if st.session_state.get("desired_mic_playing", False):
                        st.session_state.unexpected_webrtc_stop_ts = time.time()
                        _append_continuous_trace(
                            "unexpected_webrtc_stop_candidate",
                            f"desired_mic_playing=True stop_ts={st.session_state.unexpected_webrtc_stop_ts}",
                        )
                st.session_state._voice_prev_webrtc_playing = _current_playing

                # Store processor reference in session state and emit precise stage
                # Use the LIVE snapshot, not a stale cache. The voice_webrtc_ctx
                # dict is only for cross-thread access by the event-draining thread.
                _processor_stage = "component_not_mounted"
                _current_proc = snapshot.processor
                _current_processor_id = snapshot.processor_id

                if snapshot.context is not None:
                    if not snapshot.playing:
                        _processor_stage = "webrtc_not_playing"
                    elif snapshot.processor is None:
                        # playing=True but processor=None — this is a transient
                        # reference gap during worker/context transitions, NOT
                        # a processor replacement. Do NOT close the backend.
                        # _refresh_streaming_diagnostics handles transient state.
                        _processor_stage = "processor_reference_temporarily_unavailable"
                    else:
                        _frames = snapshot.audio_frames_received
                        _processor_stage = "audio_frames_received" if _frames > 0 else "processor_created_no_frames"

                    if st.session_state.voice_webrtc_ctx is None:
                        st.session_state.voice_webrtc_ctx = {}
                    st.session_state.voice_webrtc_ctx["processor"] = _current_proc
                    if _current_proc is not None:
                        _current_proc._session_id = st.session_state.get("voice_continuous_session_id")
                        _current_proc._session_state_ref = st.session_state
                        logger.info("Stored audio processor in session state (session=%s)", _current_proc._session_id[:8] if _current_proc._session_id else "none")

                    _prev_processor_stage = st.session_state.get("_voice_prev_processor_stage")
                    if _processor_stage != _prev_processor_stage:
                        if _processor_stage == "processor_reference_temporarily_unavailable":
                            _append_continuous_trace(
                                _processor_stage,
                                f"webrtc_playing_but_no_processor "
                                f"last_frame_age_ms=recent "
                                f"desired_mic_playing={bool(st.session_state.get('desired_mic_playing', False))}",
                            )
                        else:
                            _append_continuous_trace(_processor_stage)
                        st.session_state._voice_prev_processor_stage = _processor_stage

                    # Emit processor replacement audit events ONLY when a DIFFERENT
                    # processor is confirmed (not when processor is temporarily None).
                    _prev_id = st.session_state.get("_voice_prev_processor_id_audit")
                    if _prev_id is not None and _current_proc is not None:
                        _new_id = id(_current_proc)
                        if _new_id != _prev_id:
                            _append_continuous_trace(
                                "processor_mounted",
                                f"old_processor_id={_prev_id} "
                                f"new_processor_id={_new_id} "
                                f"new_generation={getattr(_current_proc, '_processor_generation', '—')} "
                                f"webrtc_playing={_current_playing} "
                                f"desired_mic_playing={bool(st.session_state.get('desired_mic_playing', False))} "
                                f"factory_object_id={id(_tracked_factory)} "
                                f"factory_type={type(_tracked_factory).__name__}",
                            )
                    elif _current_proc is not None:
                        _append_continuous_trace(
                            "processor_created",
                            f"processor_id={id(_current_proc)} "
                            f"generation={getattr(_current_proc, '_processor_generation', '—')} "
                            f"factory_object_id={id(_tracked_factory)} "
                            f"factory_type={type(_tracked_factory).__name__} "
                            f"voice_session_id={st.session_state.get('voice_continuous_session_id', '—')}",
                        )
                    if _current_proc is not None:
                        st.session_state._voice_prev_processor_id_audit = id(_current_proc)

                    # --- Unthrottled ownership mismatch check (runs every render) ---
                    # CONFIRMED replacement only: when a DIFFERENT processor object
                    # is present (not just None). `processor=None` during
                    # `playing=True` is a transient reference gap, NOT a replacement.
                    _streaming_proc_id = st.session_state.get("streaming_processor_id")
                    if _streaming_proc_id is not None and _current_proc is not None:
                        if _streaming_proc_id != id(_current_proc):
                            _append_continuous_trace(
                                "processor_replacement_confirmed",
                                f"old_processor_id={_streaming_proc_id} "
                                f"new_processor_id={id(_current_proc)} "
                                f"webrtc_playing={snapshot.playing} "
                                f"desired_mic_playing={bool(st.session_state.get('desired_mic_playing', False))}",
                            )
                            st.session_state.processor_ownership_mismatch = True
                            _terminate_streaming_voice_session(
                                reason="processor_replacement_detected",
                                final_state="failed",
                            )
                            _append_continuous_trace(
                                "processor_replacement_recovery",
                                f"old_processor_id={_streaming_proc_id} "
                                f"new_processor_id={id(_current_proc)} "
                                f"backend_closed=True session_unfrozen=True "
                                f"desired_mic_playing=False",
                            )
                            _request_voice_rerun("processor_replacement_recovered")
                            return

                    # Show mount error if any
                    if snapshot.mount_error:
                        st.error(f"🔴 WebRTC component render failed: {snapshot.mount_error}")
                        st.caption("Push-to-talk and debug text scoring remain available.")
                    elif snapshot.context is None:
                        st.warning("🟡 WebRTC component did not return a context. The component may still be loading.")
                    elif not snapshot.playing:
                        st.info("⚪ Continuous mode is not active. Click Start Voice Scoring. Your browser may ask for microphone permission.")
                    else:
                        st.success("🟢 Continuous microphone active. Speak a score command.")

                    # Mic status panel — always show when component is rendered
                    _webrtc_mounted = _current_proc is not None
                    _webrtc_state = str(getattr(snapshot.context, "state", "unknown")) if snapshot.context else "unknown"
                    _audio_processor_created = "yes" if _webrtc_mounted else "no"
                    _last_speech_ts = getattr(getattr(_current_proc, 'audio_buffer', None), '_last_speech_time', None) if _current_proc else None
                    _last_audio_frame_ts = f"{_last_speech_ts:.3f}" if _last_speech_ts is not None else "N/A"
                    _queued_chunks = _safe_queue_size(getattr(_current_proc, "_chunk_queue", None)) if _current_proc else 0
                    _last_asr = st.session_state.get("last_voice_transcript", "—") or "—"
                    _seg_duration = getattr(getattr(_current_proc, 'audio_buffer', None), 'get_speech_segment_duration_ms', lambda: 0.0)() if _current_proc else 0.0
                    _seg_reset_reason = getattr(getattr(_current_proc, 'audio_buffer', None), 'get_segment_reset_reason', lambda: "")() if _current_proc else ""
                    _buffer_duration = getattr(getattr(_current_proc, 'audio_buffer', None), 'get_buffer_duration_ms', lambda: 0.0)() if _current_proc else 0.0

                    _streaming_proc_id = st.session_state.get("streaming_processor_id")
                    _streaming_proc_gen = st.session_state.get("streaming_processor_generation")
                    _backend_attached = getattr(_current_proc, "_streaming_backend", None) is not None
                    _has_active_backend = _backend_attached
                    _stream_stats = _current_proc.get_streaming_transport_stats() if _current_proc and hasattr(_current_proc, "get_streaming_transport_stats") else {}

                    _mic_status_items = [
                        ("WebRTC component mounted", "yes" if _webrtc_mounted else "no"),
                        ("WebRTC state", _webrtc_state),
                        ("audio processor created", _audio_processor_created),
                        ("last audio frame timestamp", _last_audio_frame_ts),
                        ("queued chunks count", str(_queued_chunks)),
                        ("last ASR result", _last_asr),
                        ("speech segment duration", f"{_seg_duration:.1f} ms"),
                        ("buffer duration", f"{_buffer_duration:.1f} ms"),
                        ("segment reset reason", _seg_reset_reason or "—"),
                        ("resolved_connection_state", st.session_state.get("voice_streaming_state", "disabled")),
                        ("desired_mic_playing", "yes" if st.session_state.get("desired_mic_playing", False) else "no"),
                        ("webrtc_playing", "yes" if _get_webrtc_playing_state() else "no"),
                        ("webrtc_signalling", "yes" if snapshot.signalling else "no"),
                        ("microphone_confirmed_at", str(st.session_state.get("streaming_start_microphone_confirmed_at") or "—")),
                        ("audio_processor_created", _audio_processor_created),
                        ("current_processor_id", str(id(_current_proc)) if _current_proc else "none"),
                        ("current_processor_generation", str(getattr(_current_proc, "_processor_generation", "—")) if _current_proc else "—"),
                        ("streaming_backend_attached", "yes" if _has_active_backend else "no"),
                        ("backend_connection_state", _stream_stats.get("backend_connection_state", "—")),
                        ("provider_connected", "yes" if _stream_stats.get("provider_connected") else "no"),
                        ("voice_scoring_ready", "yes" if _stream_stats.get("voice_scoring_ready") else "no"),
                        ("streaming_processor_id", str(_streaming_proc_id or "—")),
                        ("streaming_generation", str(_streaming_proc_gen or "—")),
                        ("backend_identity_matches_current_processor", "yes" if _streaming_proc_id == id(_current_proc) and _streaming_proc_gen == getattr(_current_proc, "_streaming_generation", None) else "no" if _current_proc else "n/a"),
                        ("audio_enqueued", str(_stream_stats.get("audio_enqueued", 0))),
                        ("audio_send_success", str(_stream_stats.get("audio_send_success", 0))),
                        ("provider_messages", str(_stream_stats.get("provider_messages_received", 0))),
                        ("results_with_text", str(_stream_stats.get("provider_results_with_text", 0))),
                        ("factory_object_id", str(id(_tracked_factory))),
                        ("factory_creation_count", str(st.session_state.get("_voice_factory_creation_count", "—"))),
                    ]
                    st.markdown(
                        "\n".join(
                            f"- {label}: **{_debug_value(value)}"
                            for label, value in _mic_status_items
                        )
                    )
                    # Show last heard phrase
                    if st.session_state.last_voice_transcript:
                        st.info(f"Last heard: **{st.session_state.last_voice_transcript}**")
            
                    # Show parsed interpretation
                    if st.session_state.last_voice_event:
                        event = st.session_state.last_voice_event
                        if event.type == "set_score":
                            st.success(f"Parsed: Set score to {event.score_a}-{event.score_b}")
                        elif event.type == "increment":
                            st.success(f"Parsed: Point to Player {event.player}")
                        elif event.type == "undo":
                            st.success("Parsed: Undo last point")
                        else:
                            st.warning(f"Parsed: Unknown command (confidence: {event.confidence:.0%})")
            
                    # Show last accepted update
                    if st.session_state.last_voice_feedback:
                        st.caption(f"Last update: {st.session_state.last_voice_feedback}")
            
                    # Warn if last accepted command came from debug while continuous is requested
                    _last_event_source = getattr(
                        st.session_state.get("last_voice_event"),
                        "source",
                        None,
                    )
                    if _last_event_source == "debug":
                        st.warning(
                            "Last accepted command came from debug input, not continuous listening. "
                            "Use the debug panel or speak into the microphone for continuous commands."
                        )

            # Advance startup state machine while a start request is pending.
            # This runs after webrtc_streamer() has rendered and updated
            # voice_webrtc_streamer_state, so the processor and playing state
            # are visible to the state machine.
            if st.session_state.get("streaming_start_request_id"):
                _process_streaming_startup()
                _ui_state = st.session_state.get("streaming_ui_state", "disabled")
                if _ui_state in ("starting_microphone", "waiting_for_processor", "connecting"):
                    _request_voice_rerun("startup_poll")


            # Debug voice panel (developer helper)
            if st.session_state.voice_scoring_enabled:
                _render_confirm_panel(st.session_state.get("pending_confirmations", []))

            # Debug voice panel (developer helper)
            if st.session_state.voice_scoring_enabled:
                with st.expander("🔧 Debug Voice Pipeline", expanded=False):
                    _debug_col1, _debug_col2 = st.columns(2)
                    with _debug_col1:
                        _debug_transcript = st.text_input(
                            "Debug transcript",
                            key="voice_debug_transcript",
                            placeholder="e.g. point red, point blue, undo",
                        )
                    with _debug_col2:
                        if st.button("Process debug command", key="voice_debug_process_btn", use_container_width=True):
                            if _debug_transcript.strip():
                                _debug_res_obj = apply_score_event_and_refresh_ui(
                                    _debug_transcript.strip(),
                                    source="debug",
                                )
                                # Convert back to dict for legacy UI compatibility
                                _debug_result = {
                                    "success": _debug_res_obj.success,
                                    "reason": _debug_res_obj.reason,
                                    "previous_score": _debug_res_obj.previous_score,
                                    "new_score": _debug_res_obj.new_score,
                                    "parsed": _debug_res_obj.parsed,
                                    "route_result": _debug_res_obj.route_result,
                                }
                                st.session_state["_voice_debug_last_result"] = _debug_result
                                st.rerun()
                            else:
                                st.warning("Enter a transcript first.")

                    _last_debug = st.session_state.get("_voice_debug_last_result")
                    if _last_debug:
                        st.markdown("**Last debug result**")
                        st.json({
                            "success": _last_debug.get("success"),
                            "reason": _last_debug.get("reason"),
                            "previous_score": _last_debug.get("previous_score"),
                            "new_score": _last_debug.get("new_score"),
                            "intent": _last_debug.get("parsed").intent if _last_debug.get("parsed") else None,
                            "confidence": _last_debug.get("parsed").confidence if _last_debug.get("parsed") else None,
                            "rerun_requested": bool(st.session_state.get(_VOICE_RERUN_KEY)),
                        })

            # =====================================================================
            # Phase 9: Admin / Observability Screen
            # =====================================================================
            with st.expander("📊 Voice Observability & Operations", expanded=False):
                st.caption(
                    "Unified audit log for voice scoring events. "
                    "All sources (debug, push-to-talk, continuous) append here. "
                    "Exportable per match."
                )
                _audit_events = st.session_state.get("voice_audit_events", [])
                if _audit_events:
                    st.markdown(f"**Recent events (showing last {min(len(_audit_events), 50)} of {len(_audit_events)} retained)**")
                    for entry in reversed(_audit_events[-50:]):
                        status_icon = "✅" if entry.get("accepted") else "❌"
                        source = entry.get("source", "?")
                        note = entry.get("note", "")
                        st.markdown(
                            f"{status_icon} **{entry.get('event_type', '?')}** "
                            f"`{entry.get('previous_score', '?')}` → `{entry.get('new_score', '?')}` "
                            f"| source: {source} "
                            f"| conf: {entry.get('confidence', 0):.0%} "
                            f"| {note}"
                        )
                        with st.popover("Details"):
                            st.json(entry)
                else:
                    st.caption("No events recorded yet. Run a voice command to start logging.")
    
                col_export, col_clear, col_info = st.columns(3)
                with col_export:
                    if st.button("📥 Export Audit Log (JSON)", key="export_audit_log"):
                        import json
                        export_data = _audit_events
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"voice_audit_{timestamp}.json"
                        st.download_button(
                            label=f"Download {filename}",
                            data=json.dumps(export_data, indent=2, default=str),
                            file_name=filename,
                            mime="application/json",
                            key="download_audit",
                        )
                with col_clear:
                    if st.button("🗑️ Clear Audit Log", key="clear_audit_log"):
                        st.session_state.voice_audit_events = []
                        st.session_state.voice_event_log = []
                        if st.session_state.get("voice_event_logger"):
                            st.session_state.voice_event_logger.clear()
                        st.success("Audit log cleared.")
                        st.rerun()
                with col_info:
                    st.caption(f"Retention: up to 1000 events in memory")

                # Voice diagnostics
                with st.expander("🩺 Voice diagnostics", expanded=False):
                    _hf_token = get_hf_token()
                    _hf_configured = "yes" if _hf_token else "no"
                    _asr_status = _normalize_status_dict(
                        st.session_state.get("voice_asr_status"),
                        default_reason="ASR status unavailable",
                    )
                    _asr_loaded = "yes" if bool(_asr_status.get("available", False)) else "no"
                    _proc = get_active_voice_processor()
                    _proc_id = id(_proc) if _proc else "none"
                    _proc_class = type(_proc).__name__ if _proc else "—"
                    _session_id = st.session_state.get("voice_continuous_session_id", "none")
                    _session_start = st.session_state.get("voice_continuous_session_start", 0.0)
                    _stale_ignored = st.session_state.get("voice_stale_events_ignored", 0)
                    _factory_calls = st.session_state.get("_voice_factory_call_count", 0)
                    _factory_last_error = st.session_state.get("_voice_factory_last_error")
                    _proc_callback_count = st.session_state.get("_voice_processor_callback_count", 0)
                    _last_proc_exception = st.session_state.get("_voice_last_processor_exception")
                    _proc_diag = _proc.get_diagnostics() if _proc and hasattr(_proc, "get_diagnostics") else {}
                    _worker_diag = _proc.get_worker_diagnostics() if _proc and hasattr(_proc, "get_worker_diagnostics") else {}

                    _q_size = _safe_queue_size(getattr(_proc, "_chunk_queue", None)) if _proc else 0
                    _dropped = int(getattr(_proc, "_dropped_chunks", 0) or 0) if _proc else 0
                    _evt_q = _safe_queue_size(getattr(_proc, "event_queue", None)) if _proc else 0
                    _last_rms = st.session_state.get("voice_last_chunk_rms", 0.0)
                    _seg_ms = getattr(getattr(_proc, 'audio_buffer', None), 'get_speech_segment_duration_ms', lambda: 0.0)() if _proc else 0.0
                    _seg_reset_reason = getattr(getattr(_proc, 'audio_buffer', None), 'get_segment_reset_reason', lambda: "")() if _proc else ""
                    _buffer_duration = getattr(getattr(_proc, 'audio_buffer', None), 'get_buffer_duration_ms', lambda: 0.0)() if _proc else 0.0
                    _last_transcript = st.session_state.get("last_voice_transcript", "")
                    _last_accepted = st.session_state.get("voice_last_applied_event_key")
                    _last_rejected_reason = st.session_state.get("last_voice_rejection_reason", "")
                    _last_success_message = st.session_state.get("last_voice_success_message", "")
                    _last_action_taken = st.session_state.get("last_voice_action_taken", "")
                    _last_continuous_transcript = st.session_state.get("last_voice_continuous_transcript", "")
                    _last_push_to_talk_transcript = st.session_state.get("last_voice_push_to_talk_transcript", "")
                    _last_debug_transcript = st.session_state.get("last_voice_debug_transcript", "")
                    _last_source = getattr(
                        st.session_state.get("last_voice_event"),
                        "source",
                        "unknown",
                    ) if st.session_state.get("last_voice_event") else "—"
                    _proc_status = getattr(_proc, "_status", "n/a") if _proc else "no processor"
                    _asr_ready = "yes" if (_proc and getattr(_proc, "_asr_ready", False)) else "no"
                    _asr_latency = getattr(st.session_state.get("last_voice_event"), "asr_latency_ms", None)
                    _webrtc_playing = _get_webrtc_playing_state()
                    _has_pending = bool(_proc.has_pending_events()) if _proc else False
                    _continuous_requested = bool(
                        st.session_state.get("voice_listening")
                        or _webrtc_playing
                        or (_has_pending and st.session_state.get("voice_selected_match_id") and not st.session_state.get("match_complete"))
                    )
                    _voice_diag_items = [
                        ("continuous mode requested (canonical)", "yes" if _continuous_requested else "no"),
                        ("voice_listening flag", "yes" if st.session_state.get("voice_listening") else "no"),
                        ("WebRTC playing", "yes" if _webrtc_playing else "no"),
                        ("WebRTC signalling", st.session_state.get("voice_webrtc_streamer_state", {}).get("signalling", False)),
                        ("processor created", "yes" if _proc else "no"),
                        ("processor ID", str(_proc_id)),
                        ("processor class", _proc_class),
                        ("processor callback count", str(_proc_callback_count)),
                        ("audio_frame_callback count", str(_audio_callback_count)),
                        ("factory call count", str(_factory_calls)),
                        ("factory last error", _factory_last_error or "none"),
                        ("last processor exception", str(_last_proc_exception) if _last_proc_exception else "none"),
                        ("audio frames received", str(_proc_diag.get("audio_frames_received", 0))),
                        ("chunks created", str(_proc_diag.get("chunks_created", 0))),
                        ("ASR events enqueued", str(_proc_diag.get("asr_events_enqueued", 0))),
                        ("current continuous session ID", _session_id[:8] + "..." if isinstance(_session_id, str) and len(_session_id) > 8 else _session_id),
                        ("session start", f"{_session_start:.1f}" if _session_start else "—"),
                        ("stale events ignored", str(_stale_ignored)),
                        ("audio queue size", str(_q_size)),
                        ("event queue size", str(_evt_q)),
                        ("event queue peek", str(_peek_evt)[:200] if (_peek_evt := _proc.peek_events(max_items=3) if _proc and hasattr(_proc, "peek_events") else []) else "empty"),
                        ("chunk queue peek", str(_peek_chk)[:200] if (_peek_chk := _proc.peek_chunks(max_items=3) if _proc and hasattr(_proc, "peek_chunks") else []) else "empty"),
                        ("dropped audio frames", str(_dropped)),
                        ("VAD RMS latest", f"{_last_rms:.4f}"),
                        ("speech segment duration", f"{_seg_ms:.1f} ms" if _seg_ms else "0.0 ms"),
                        ("buffer duration", f"{_buffer_duration:.1f} ms" if _buffer_duration else "0.0 ms"),
                        ("segment reset reason", _seg_reset_reason or "—"),
                        ("last continuous transcript", _last_continuous_transcript or "—"),
                        ("last push-to-talk transcript", _last_push_to_talk_transcript or "—"),
                        ("last debug transcript", _last_debug_transcript or "—"),
                        ("last command source", _last_source),
                        ("last transcript", _last_transcript or "—"),
                        ("last accepted command", _last_accepted or "—"),
                        ("last rejected command reason", _last_rejected_reason or "—"),
                        ("last success message", _last_success_message or "—"),
                        ("last action taken", _last_action_taken or "—"),
                        ("ASR model loaded", "yes" if (_proc and getattr(_proc, "_asr", None) is not None) else "no"),
                        ("processor active", _asr_ready),
                        ("processor status", _proc_status),
                        ("worker started", "yes" if _worker_diag.get("worker_started") else "no"),
                        ("worker thread alive", "yes" if _worker_diag.get("worker_thread_alive") else "no"),
                        ("worker thread name", _worker_diag.get("worker_thread_name") or "—"),
                        ("worker stop event set", "yes" if _worker_diag.get("worker_stop_event_set") else "no"),
                        ("audio queue size", str(_worker_diag.get("audio_queue_size", 0))),
                        ("work items enqueued", str(_worker_diag.get("total_work_items_enqueued", 0))),
                        ("work items dequeued", str(_worker_diag.get("total_work_items_dequeued", 0))),
                        ("transcription calls started", str(_worker_diag.get("transcription_calls_started", 0))),
                        ("transcription calls completed", str(_worker_diag.get("transcription_calls_completed", 0))),
                        ("blank transcription count", str(_worker_diag.get("blank_transcription_count", 0))),
                        ("last worker exception", _worker_diag.get("last_worker_exception") or "none"),
                        ("last work item timestamp", f"{_worker_diag.get('last_work_item_timestamp', 0.0):.1f}" if _worker_diag.get("last_work_item_timestamp") else "—"),
                        ("last ASR latency", f"{_asr_latency:.1f} ms" if _asr_latency else "—"),
                    ]

                    # Drain-path diagnostics
                    _drain_diag = get_drain_diagnostics()
                    _stream_diag = _proc.get_streaming_transport_stats() if _proc and hasattr(_proc, "get_streaming_transport_stats") else {}
                    
                    _stream_diag_items = [
                        ("backend connection state", _stream_diag.get("backend_connection_state", "—")),
                        ("provider connected", "yes" if _stream_diag.get("provider_connected") else "no"),
                        ("voice scoring ready", "yes" if _stream_diag.get("voice_scoring_ready") else "no"),
                        ("streaming frames received", str(_stream_diag.get("streaming_frames_received", 0))),
                        ("streaming frames converted", str(_stream_diag.get("streaming_frames_converted", 0))),
                        ("audio enqueued to backend", str(_stream_diag.get("audio_enqueued", 0))),
                        ("audio send attempts", str(_stream_diag.get("audio_send_attempts", 0))),
                        ("audio send success", str(_stream_diag.get("audio_send_success", 0))),
                        ("audio send failed", str(_stream_diag.get("audio_send_failed", 0))),
                        ("audio bytes sent", str(_stream_diag.get("audio_bytes_sent", 0))),
                        ("audio duration sent", f"{_stream_diag.get('audio_duration_sent_ms', 0.0) / 1000.0:.1f}s"),
                        ("send loop started", "yes" if _stream_diag.get("send_loop_started") else "no"),
                        ("send loop alive", "yes" if _stream_diag.get("send_loop_alive") else "no"),
                        ("keepalive loop started", "yes" if _stream_diag.get("keepalive_loop_started") else "no"),
                        ("keepalive loop alive", "yes" if _stream_diag.get("keepalive_loop_alive") else "no"),
                        ("provider messages received", str(_stream_diag.get("provider_messages_received", 0))),
                        ("provider results received", str(_stream_diag.get("provider_results_received", 0))),
                        ("results with text", str(_stream_diag.get("provider_results_with_text", 0))),
                        ("results empty", str(_stream_diag.get("provider_results_empty", 0))),
                        ("results interim", str(_stream_diag.get("provider_results_interim", 0))),
                        ("results final", str(_stream_diag.get("provider_results_final", 0))),
                        ("results speech_final", str(_stream_diag.get("provider_results_speech_final", 0))),
                        ("last interim text", _stream_diag.get("last_interim_text", "—")),
                        ("last final text", _stream_diag.get("last_final_text", "—")),
                        ("provider metadata count", str(_stream_diag.get("provider_metadata_count", 0))),
                        ("provider utterance end count", str(_stream_diag.get("provider_utterance_end_count", 0))),
                        ("provider speech started count", str(_stream_diag.get("provider_speech_started_count", 0))),
                        ("provider error count", str(_stream_diag.get("provider_error_count", 0))),
                        ("provider close count", str(_stream_diag.get("provider_close_count", 0))),
                        ("provider unknown messages", str(_stream_diag.get("provider_unknown_message_count", 0))),
                    ]

                    _drain_diag_items = [
                        ("drain invocation count", str(_drain_diag.get("invocation_count", 0))),
                        ("drain last timestamp", f"{_drain_diag.get('last_timestamp', 0.0):.1f}" if _drain_diag.get("last_timestamp") else "—"),
                        ("drain last processor ID", str(_drain_diag.get("last_processor_id", "none"))),
                        ("drain last queue ID", str(_drain_diag.get("last_queue_id", "none"))),
                        ("drain queue size before", str(_drain_diag.get("last_queue_size_before", 0))),
                        ("drain queue size after", str(_drain_diag.get("last_queue_size_after", 0))),
                        ("drain last skipped reason", _drain_diag.get("last_skipped_reason", "none") or "none"),
                        ("drain last exception", str(_drain_diag.get("last_exception", "none")) if _drain_diag.get("last_exception") else "none"),
                    ]

                    st.markdown("**Event Drain Diagnostics**")
                    st.markdown(
                        "\n".join(
                            f"- {label}: **{_debug_value(value)}"
                            for label, value in _drain_diag_items
                        )
                    )

                    st.markdown("**Streaming Transport Diagnostics**")
                    st.markdown(
                        "\n".join(
                            f"- {label}: **{_debug_value(value)}"
                            for label, value in _stream_diag_items
                        )
                    )

                    st.markdown(
                        "\n".join(
                            f"- {label}: **{_debug_value(value)}"
                            for label, value in _voice_diag_items
                        )
                    )

                    # Runtime / Ollama bridge diagnostics
                    try:
                        from tournament_platform.app.components.runtime_diagnostics import render_runtime_diagnostics

                        render_runtime_diagnostics()
                    except Exception:
                        pass

                    if st.session_state.voice_listening:
                        # Confidence indicator
                        if st.session_state.last_voice_event:
                            _conf = getattr(st.session_state.last_voice_event, "confidence", 0.0)
                            _conf_pct = int(_conf * 100)
                            _color = "🔴" if _conf_pct < 50 else ("🟡" if _conf_pct < 80 else "🟢")
                            st.progress(_conf, text=f"{_color} Confidence: {_conf_pct:.0f}%")
            
                        # Voice ASR Diagnostics expander (precise status + test buttons)
                        with st.expander("🩺 Voice ASR Diagnostics", expanded=False):
                            _diag = get_asr_diagnostic()
                            _asr_state = _diag.get("state") or _diag.get("reason") or "not_configured"
                            _asr_diag_items = [
                                ("ASR provider", _diag.get("provider", "faster_whisper")),
                                ("ASR ready", "yes" if _diag.get("available") else "no"),
                                ("State", _asr_state),
                                ("Model", _diag.get("model_size", "—")),
                                ("Device", _diag.get("device", "—")),
                                ("Compute type", _diag.get("compute_type", "—")),
                                ("Last ASR error", _diag.get("reason") or "none"),
                            ]
                            st.markdown(
                                "\n".join(
                                    f"**{label}:** {_debug_value(value)}"
                                    for label, value in _asr_diag_items
                                )
                            )

                            st.divider()
                            c_left, c_mid, c_right = st.columns(3)
                            with c_left:
                                if st.button("Test imports", key="asr_test_imports"):
                                    st.json(_diag.get("imports", {}))
                            with c_mid:
                                if st.button("Load ASR model", key="asr_test_load"):
                                    _asr = get_asr()
                                    if _asr is None:
                                        st.error("No ASR backend available.")
                                    else:
                                        st.json(_asr.get_status().__dict__ if hasattr(_asr.get_status(), "__dict__") else _asr.get_status())
                            with c_right:
                                if st.button("Refresh status", key="asr_refresh"):
                                    st.session_state.voice_asr_status = None
                                    st.rerun()

                            st.caption(
                                "Import probe shows exactly which ASR packages are "
                                "present on this runtime. 'Load ASR model' attempts to "
                                "instantiate the model and reports the precise outcome."
                            )

                        # Debug expander
                        with st.expander("🔍 Voice Debug", expanded=False):
                            st.markdown("**Recent Voice Events (unified audit)**")
                            _audit_events = st.session_state.get("voice_audit_events", [])
                            if _audit_events:
                                for entry in _audit_events[-10:]:
                                    st.json(entry)
                            else:
                                st.caption("No events yet.")
                        
                            if st.button("Clear Event Log", key="clear_voice_log"):
                                st.session_state.voice_audit_events = []
                                st.session_state.voice_event_log = []
                                if st.session_state.get("voice_event_logger"):
                                    st.session_state.voice_event_logger.clear()
                                st.rerun()

                    if st.session_state.voice_listening:
                        # Voice scoring debug expander
                        with st.expander("🩺 Voice scoring debug", expanded=False):
                            _mm = st.session_state.get("match_manager")
                            _eng = getattr(_mm, "engine", None)
                            _quick_mode = st.session_state.get("quick_voice_mode", "off")
                            _last_accepted = st.session_state.get("voice_last_applied_event_key")
                            _last_rejected = st.session_state.get("last_voice_rejection_reason", "")
                            _last_success = st.session_state.get("last_voice_success_message", "")
                            _last_action = st.session_state.get("last_voice_action_taken", "")
                            _q_last_player = st.session_state.get("quick_voice_last_player")
                            _q_last_ts = st.session_state.get("quick_voice_last_ts", 0.0)
                            _rerun_req = bool(st.session_state.get(_VOICE_RERUN_KEY))
                            _last_source = getattr(
                                st.session_state.get("last_voice_event"),
                                "source",
                                "unknown",
                            ) if st.session_state.get("last_voice_event") else "—"
                            _voice_debug_items = [
                                ("voice mode", _quick_mode),
                                ("voice enabled", "yes" if st.session_state.get("voice_scoring_enabled") else "no"),
                                ("last transcript", st.session_state.get("last_voice_transcript", "—") or "—"),
                                ("last command source", _last_source),
                                ("last continuous transcript", st.session_state.get("last_voice_continuous_transcript", "—") or "—"),
                                ("last push-to-talk transcript", st.session_state.get("last_voice_push_to_talk_transcript", "—") or "—"),
                                ("last debug transcript", st.session_state.get("last_voice_debug_transcript", "—") or "—"),
                                (
                                    "last parsed intent",
                                    (
                                        st.session_state.get("last_voice_event").type
                                        if st.session_state.get("last_voice_event") else "—"
                                    ),
                                ),
                                ("last accepted command", _last_accepted or "—"),
                                ("last rejected reason", _last_rejected or "—"),
                                ("last success message", _last_success or "—"),
                                ("last action taken", _last_action or "—"),
                                (
                                    "current score",
                                    f"{_eng.score_a}-{_eng.score_b}" if _eng else "n/a",
                                ),
                                (
                                    "games won",
                                    f"{_eng.games_won_a}-{_eng.games_won_b}" if _eng else "n/a",
                                ),
                                (
                                    "completed games",
                                    len(_eng.round_scores) if _eng else 0,
                                ),
                                (
                                    "game_won flag",
                                    _eng.match_status == "game_won" if _eng else "n/a",
                                ),
                                (
                                    "match_complete flag",
                                    _eng.match_status == "match_won" if _eng else "n/a",
                                ),
                                ("last applied event id", _last_accepted or "—"),
                                (
                                    "quick voice last player/time",
                                    f"{_q_last_player} / {_q_last_ts:.0f}" if _q_last_player else "—",
                                ),
                                ("rerun requested", _rerun_req),
                            ]
                            st.markdown(
                                "\n".join(
                                    f"- {label}: **{_debug_value(value)}"
                                    for label, value in _voice_debug_items
                                )
                            )
        # Voice diagnostics — always visible, regardless of WebRTC availability
        with st.expander("🩺 Voice diagnostics", expanded=False):
            _hf_token = get_hf_token()
            _hf_configured = "yes" if _hf_token else "no"
            _asr_status = _normalize_status_dict(
                st.session_state.get("voice_asr_status"),
                default_reason="ASR status unavailable",
            )
            _asr_loaded = "yes" if bool(_asr_status.get("available", False)) else "no"
            _proc = get_active_voice_processor()
            _proc_id = id(_proc) if _proc else "none"
            _proc_class = type(_proc).__name__ if _proc else "—"
            _session_id = st.session_state.get("voice_continuous_session_id", "none")
            _session_start = st.session_state.get("voice_continuous_session_start", 0.0)
            _stale_ignored = st.session_state.get("voice_stale_events_ignored", 0)
            _factory_calls = st.session_state.get("_voice_factory_call_count", 0)
            _factory_last_error = st.session_state.get("_voice_factory_last_error")
            _proc_callback_count = st.session_state.get("_voice_processor_callback_count", 0)
            _last_proc_exception = st.session_state.get("_voice_last_processor_exception")
            _proc_diag = _proc.get_diagnostics() if _proc and hasattr(_proc, "get_diagnostics") else {}
            _worker_diag = _proc.get_worker_diagnostics() if _proc and hasattr(_proc, "get_worker_diagnostics") else {}

            _q_size = _safe_queue_size(getattr(_proc, "_chunk_queue", None)) if _proc else 0
            _dropped = int(getattr(_proc, "_dropped_chunks", 0) or 0) if _proc else 0
            _evt_q = _safe_queue_size(getattr(_proc, "event_queue", None)) if _proc else 0
            _last_rms = st.session_state.get("voice_last_chunk_rms", 0.0)
            _seg_ms = getattr(getattr(_proc, 'audio_buffer', None), 'get_speech_segment_duration_ms', lambda: 0.0)() if _proc else 0.0
            _seg_reset_reason = getattr(getattr(_proc, 'audio_buffer', None), 'get_segment_reset_reason', lambda: "")() if _proc else ""
            _buffer_duration = getattr(getattr(_proc, 'audio_buffer', None), 'get_buffer_duration_ms', lambda: 0.0)() if _proc else 0.0
            _last_transcript = st.session_state.get("last_voice_transcript", "")
            _last_accepted = st.session_state.get("voice_last_applied_event_key")
            _last_rejected_reason = st.session_state.get("last_voice_rejection_reason", "")
            _last_success_message = st.session_state.get("last_voice_success_message", "")
            _last_action_taken = st.session_state.get("last_voice_action_taken", "")
            _last_continuous_transcript = st.session_state.get("last_voice_continuous_transcript", "")
            _last_push_to_talk_transcript = st.session_state.get("last_voice_push_to_talk_transcript", "")
            _last_debug_transcript = st.session_state.get("last_voice_debug_transcript", "")

            _webrtc_state = st.session_state.get("voice_webrtc_streamer_state", {"playing": False, "signalling": False})
            _webrtc_playing = _webrtc_state.get("playing", False) if isinstance(_webrtc_state, dict) else getattr(_webrtc_state, "playing", False)
            _webrtc_signalling = _webrtc_state.get("signalling", False) if isinstance(_webrtc_state, dict) else getattr(_webrtc_state, "signalling", False)
            _mount_error = st.session_state.get("voice_webrtc_mount_error")

            _streaming_state = st.session_state.get("voice_streaming_state", "disabled")
            _streaming_ui_state = st.session_state.get("streaming_ui_state", "disabled")
            _config_frozen = st.session_state.get("voice_streaming_config_frozen", False)
            _start_requested = st.session_state.get("voice_start_requested", False)
            _desired_playing = st.session_state.get("desired_mic_playing", False)

            _backend = getattr(_proc, "_streaming_backend", None) if _proc else None
            _backend_attached = _backend is not None
            _backend_state = getattr(_backend, "connection_state", lambda: "none")() if _backend else "none"
            _streaming_gen = getattr(_proc, "_streaming_generation", 0) if _proc else 0
            _streaming_session = getattr(_proc, "_streaming_voice_session_id", None) if _proc else None
            _streaming_match = getattr(_proc, "_streaming_match_id", None) if _proc else None

            _streaming_diag = _proc.get_streaming_diagnostics() if _proc and hasattr(_proc, "get_streaming_diagnostics") else {}

            _last_audio_frame_ts = getattr(_proc, '_last_recv_timestamp', 0.0) if _proc else 0.0
            _last_audio_frame_age_ms = f"{(time.time() - _last_audio_frame_ts) * 1000:.0f} ms" if _last_audio_frame_ts else "N/A"
            _mounted_processor_id = id(snapshot.processor) if snapshot.processor else "none"

            _voice_diag_items = [
                ("HF token configured", _hf_configured),
                ("Batch ASR loaded", _asr_loaded),
                ("Batch ASR provider", _asr_status.get("provider", "—")),
                ("Batch ASR state", _asr_status.get("state", "—")),
                ("Processor class", _proc_class),
                ("Processor ID", str(_proc_id)),
                ("Mounted processor ID", str(_mounted_processor_id)),
                ("Callback count", str(_proc_callback_count)),
                ("Batch ASR worker alive", "yes" if _proc_diag.get("worker_thread_alive") else "no"),
                ("Session ID", _session_id[:8] + "..." if _session_id else "none"),
                ("Session start", datetime.fromtimestamp(_session_start).strftime("%H:%M:%S") if _session_start else "—"),
                ("Stale events ignored", str(_stale_ignored)),
                ("Factory calls", str(_factory_calls)),
                ("Factory last error", str(_factory_last_error) if _factory_last_error else "—"),
                ("Last processor exception", str(_last_proc_exception) if _last_proc_exception else "—"),
                ("Chunk queue size", str(_q_size)),
                ("Dropped chunks", str(_dropped)),
                ("Event queue size", str(_evt_q)),
                ("Last frame RMS", f"{_last_rms:.4f}"),
                ("Speech segment", f"{_seg_ms:.1f} ms"),
                ("Segment reset reason", _seg_reset_reason or "—"),
                ("Buffer duration", f"{_buffer_duration:.1f} ms"),
                ("Last transcript", _last_transcript or "—"),
                ("Last accepted event", _last_accepted or "—"),
                ("Last rejected reason", _last_rejected_reason or "—"),
                ("Last streaming rejection", st.session_state.get("last_streaming_event_rejection_reason", "—")),
                ("Last success message", _last_success_message or "—"),
                ("Last action taken", _last_action_taken or "—"),
                ("Last continuous transcript", _last_continuous_transcript or "—"),
                ("Last streaming skip: listening", str(_ss.get("voice_events_skip_listening", 0))),
                ("Last streaming skip: match_won", str(_ss.get("voice_events_skip_match_won", 0))),
                ("Last streaming skip: unknown_type", str(_ss.get("voice_events_skip_unknown_type", 0))),
                ("Parser last result", st.session_state.get("voice_parser_last_result", "—")),
                ("Score application last result", st.session_state.get("voice_score_application_last_result", "—")),
                ("Confidence", f"{st.session_state.get('voice_last_confidence', 0.0):.4f}"),
                ("Confidence threshold", f"{st.session_state.get('voice_confidence_threshold', 0.5):.4f}"),
                ("Voice MatchManager ID", str(id(st.session_state.get("match_manager")))),
                ("Session MatchManager ID", str(id(st.session_state.get("match_manager")))),
                ("Scoreboard rendered score", st.session_state.match_manager.state.get_score_string()),
                ("Last push-to-talk transcript", _last_push_to_talk_transcript or "—"),
                ("Last debug transcript", _last_debug_transcript or "—"),
                ("WebRTC playing", "yes" if _webrtc_playing else "no"),
                ("WebRTC signalling", "yes" if _webrtc_signalling else "no"),
                ("Mount error", str(_mount_error) if _mount_error else "—"),
                ("Streaming UI state", _streaming_ui_state),
                ("Streaming state", _streaming_state),
                ("Config frozen", "yes" if _config_frozen else "no"),
                ("Start requested", "yes" if _start_requested else "no"),
                ("Stop requested", "yes" if st.session_state.get("voice_stop_requested", False) else "no"),
                ("Desired mic playing", "yes" if _desired_playing else "no"),
                ("Last desired mic writer", str(st.session_state.get("last_desired_mic_writer") or "—")),
                ("Last desired mic reason", str(st.session_state.get("last_desired_mic_reason") or "—")),
                ("Streaming backend attached", "yes" if _backend_attached else "no"),
                ("Streaming backend state", _backend_state),
                ("Streaming generation", str(_streaming_gen)),
                ("Streaming session ID", _streaming_session[:8] + "..." if _streaming_session else "none"),
                ("Streaming match ID", str(_streaming_match) if _streaming_match else "none"),
                ("Backend object ID", str(_streaming_diag.get("backend_object_id", "none"))),
                ("Finalized emitted", str(_streaming_diag.get("finalized_utterances_emitted", 0))),
                ("Finalized queue depth", str(_streaming_diag.get("finalized_queue_depth", 0))),
                ("Finalized processed", str(_streaming_diag.get("streaming_finalized_count", 0))),
                ("Finalized stale", str(_streaming_diag.get("streaming_stale_count", 0))),
                ("Finalized duplicate", str(_streaming_diag.get("streaming_duplicate_count", 0))),
                ("Finalized mismatch", str(_streaming_diag.get("streaming_match_mismatch_count", 0))),
                ("Finalized invalid", str(_streaming_diag.get("streaming_invalid_count", 0))),
                ("Finalized failed", str(_streaming_diag.get("streaming_failed_count", 0))),
                ("Streaming drain calls", str(_streaming_diag.get("streaming_drain_calls", 0))),
                ("Streaming events drained", str(_streaming_diag.get("streaming_events_drained", 0))),
                ("Audio delivery mode", _streaming_diag.get("audio_delivery_mode", "—")),
                ("Audio enqueued", str(_streaming_diag.get("audio_enqueued", 0))),
                ("Audio sent", str(_streaming_diag.get("audio_sent", 0))),
                ("Audio queue full", str(_streaming_diag.get("audio_queue_full", 0))),
                ("Audio provider unavailable", str(_streaming_diag.get("audio_provider_unavailable", 0))),
                ("Audio stale", str(_streaming_diag.get("audio_stale", 0))),
                ("Chunks created", str(_proc_diag.get("chunks_created", 0))),
                ("Chunks enqueued", str(_proc_diag.get("chunks_enqueued", 0))),
                ("Chunks rejected", str(_proc_diag.get("chunks_rejected", 0))),
                ("Last chunk rejection reason", _proc_diag.get("last_chunk_rejection_reason", "—")),
                ("Runtime mode", _proc_diag.get("runtime_mode", "—")),
                ("Last audio frame age", _last_audio_frame_age_ms),
                ("Unexpected stop count", str(st.session_state.get("unexpected_webrtc_stop_count", 0))),
                ("Last unexpected stop TS", str(st.session_state.get("unexpected_webrtc_stop_ts", "—"))),
                ("Last session termination reason", str(st.session_state.get("last_session_termination_reason") or "—")),
                ("Streaming config frozen", "yes" if st.session_state.get("streaming_config_frozen", False) else "no"),
                ("Start button allowed", "yes" if _can_start else "no"),
                ("Start button block reason", _get_start_block_reason(_can_start, _config_frozen, _status, _has_active_backend, _ui_state_now, _voice_mode_allows_streaming)),
                ("Stop button allowed", "yes" if _can_stop else "no"),
            ]
            st.markdown(
                "\n".join(
                    f"- **{label}:** {_debug_value(value)}"
                    for label, value in _voice_diag_items
                )
            )

            if _backend is not None and hasattr(_backend, "get_connection_info"):
                try:
                    _conn_info = _backend.get_connection_info()
                    _conn_items = [
                        ("Connection state", _conn_info.get("connection_state", "—")),
                        ("Connection attempt", str(_conn_info.get("connection_attempt", "—"))),
                        ("Connection started at", str(_conn_info.get("connection_started_at", "—"))),
                        ("Connection opened at", str(_conn_info.get("connection_opened_at", "—"))),
                        ("Connection failed at", str(_conn_info.get("connection_failed_at", "—"))),
                        ("Last error category", str(_conn_info.get("last_error_category", "—"))),
                        ("Last error code", str(_conn_info.get("last_error_code", "—"))),
                        ("Last error message", str(_conn_info.get("last_error_message_safe", "—"))),
                        ("Last close code", str(_conn_info.get("last_close_code", "—"))),
                        ("Last close reason", str(_conn_info.get("last_close_reason_safe", "—"))),
                        ("Reconnect attempt", str(_conn_info.get("reconnect_attempt", "—"))),
                        ("Credentials configured", "yes" if _conn_info.get("credentials_configured") else "no"),
                        ("Message index", str(_conn_info.get("provider_message_index", 0))),
                        ("Last message type", _conn_info.get("last_provider_message_type") or "—"),
                        ("Last message summary", _conn_info.get("last_provider_message_summary") or "—"),
                    ]
                    st.markdown("**Backend connection diagnostics (incl. provider messages)**")
                    st.markdown(
                        "\n".join(
                            f"- **{label}:** {_debug_value(value)}"
                            for label, value in _conn_items
                        )
                    )
                except Exception:
                    st.caption("Backend connection diagnostics unavailable.")

            if _backend is not None and hasattr(_backend, "metrics"):
                try:
                    _metrics = _backend.metrics()
                    _metrics_dict = _metrics.to_dict() if hasattr(_metrics, "to_dict") else _metrics.__dict__ if hasattr(_metrics, "__dict__") else _metrics._asdict() if hasattr(_metrics, "_asdict") else {}
                    _metrics_items = [
                        ("Provider messages received", str(_metrics_dict.get("provider_messages_received", 0))),
                        ("Results received", str(_metrics_dict.get("provider_results_received", 0))),
                        ("Results empty", str(_metrics_dict.get("provider_results_empty", 0))),
                        ("Results with text", str(_metrics_dict.get("provider_results_with_text", 0))),
                        ("Results interim", str(_metrics_dict.get("provider_results_interim", 0))),
                        ("Results final", str(_metrics_dict.get("provider_results_final", 0))),
                        ("Results speech_final", str(_metrics_dict.get("provider_results_speech_final", 0))),
                        ("Transcript text extracted", str(_metrics_dict.get("transcript_text_extracted", 0))),
                        ("Provider metadata count", str(_metrics_dict.get("provider_metadata_count", 0))),
                        ("Provider unknown msg count", str(_metrics_dict.get("provider_unknown_message_count", 0))),
                        ("Provider speech_started", str(_metrics_dict.get("provider_speech_started_count", 0))),
                        ("Provider utterance_end", str(_metrics_dict.get("provider_utterance_end_count", 0))),
                        ("Audio bytes sent", str(_metrics_dict.get("audio_bytes_sent", 0))),
                        ("Audio send attempts", str(_metrics_dict.get("audio_send_attempts", 0))),
                        ("Audio send failed", str(_metrics_dict.get("audio_send_failed", 0))),
                        ("Audio send success", str(_metrics_dict.get("audio_send_success", 0))),
                        ("Audio duration sent (ms)", str(round(_metrics_dict.get("audio_duration_sent_ms", 0.0), 1))),
                        ("Output frame bytes", str(_metrics_dict.get("output_frame_bytes", "—"))),
                        ("Output frame duration (ms)", str(_metrics_dict.get("output_frame_duration_ms", "—"))),
                        ("Interim transcript", str(_metrics_dict.get("last_interim_text", "") or "—")),
                        ("Final transcript", str(_metrics_dict.get("last_final_text", "") or "—")),
                    ]
                    st.markdown("**Provider pipeline metrics**")
                    st.markdown(
                        "\n".join(
                            f"- **{label}:** {_debug_value(value)}"
                            for label, value in _metrics_items
                        )
                    )
                except Exception:
                    st.caption("Provider pipeline metrics unavailable.")

            if _proc_diag:
                st.markdown("**Processor diagnostics**")
                st.json(_proc_diag)


    if st.session_state.get("tt_sounds_enabled", False):
        with st.expander("🔬 Audio Rally Debug", expanded=False):
            _dims = st.session_state.get("tt_sounds_recent_events", [])
            if _dims:
                for ev in _dims[-10:]:
                    st.caption(f"{ev.timestamp:.2f}s — {ev.event_type} energy={ev.energy:.3f} conf={ev.confidence:.2f}")
            else:
                st.caption("No impacts detected yet.")
    
        _ctx = st.session_state.get("tt_sounds_rally_context")
        if _ctx and _ctx.impacts:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Impacts", len(_ctx.impacts))
            with c2:
                dur = (_ctx.impacts[-1].timestamp - _ctx.impacts[0].timestamp) if len(_ctx.impacts) > 1 else 0.0
                st.metric("Rally duration", f"{dur:.1f}s")
            with c3:
                intervals = [
                    _ctx.impacts[i+1].timestamp - _ctx.impacts[i].timestamp
                    for i in range(len(_ctx.impacts)-1)
                ]
                avg = sum(intervals)/len(intervals) if intervals else 0.0
                st.metric("Avg interval", f"{avg*1000:.0f} ms")
            with c4:
                strongest = max(e.energy for e in _ctx.impacts)
                st.metric("Strongest impact", f"{strongest:.3f}")
        else:
            st.caption("Start a rally to see audio summary.")

    # ============================================================================
    # Voice Input Section
    # ============================================================================

    st.divider()

def _render_voice_input() -> None:
    """Render voice input controls."""
    st.subheader("🎤 Voice Input")

    # Push-to-talk via st.audio_input (Phase 3)
    if st.session_state.voice_scoring_enabled:
        audio_file = st.audio_input("🎙️ Push to Talk", key="voice_push_to_talk_input")
        if audio_file is not None:
            _file_fingerprint = getattr(audio_file, "name", "") + str(getattr(audio_file, "size", 0))
            _voice_p2p_cache = st.session_state.get("_voice_p2p_cache") or {}
            _cached_event = _voice_p2p_cache.get(_file_fingerprint)
            if _cached_event is None:
                if st.session_state.get("quick_voice_mode") == "quick":
                    # Quick Voice depends on the active transcript provider.
                    # Do not silently process when ASR is not ready.
                    if not _quick_voice_asr_ready():
                        st.warning(
                            "Quick Voice Scoring needs a working transcript "
                            "provider. ASR is not ready — see Voice ASR Diagnostics. "
                            "Manual scoring still works."
                        )
                        _cached_event = None
                    else:
                        pcm_bytes = _audio_input_to_pcm(audio_file)
                        if pcm_bytes:
                            if "voice_asr" not in st.session_state:
                                st.session_state.voice_asr = LocalASR(vocabulary=VoiceVocabulary.load())
                            try:
                                raw_text = st.session_state.voice_asr.transcribe_chunk(pcm_bytes)
                            except Exception:
                                raw_text = ""
                            if raw_text and raw_text.strip():
                                _process_quick_voice_event(raw_text.strip())
                        _cached_event = None
                else:
                    _cached_event = _process_push_to_talk_audio(audio_file)
                    if _cached_event is not None:
                        st.session_state.setdefault("_voice_p2p_cache", {})[_file_fingerprint] = _cached_event
            event = _cached_event
            if event is not None:
                st.session_state.last_voice_transcript = event.raw_text
                st.session_state.last_voice_event = event
                st.session_state.last_voice_raw_transcript = event.raw_text
                if event.type == "unknown":
                    st.warning(f"🎤 Voice: Unknown command (transcript: {event.raw_text})")
                else:
                    st.success(f"🎤 Parsed: {event.type} (confidence: {event.confidence:.0%})")

    # Legacy real-time mode controls (deprecated — use continuous listening expander above).
    with st.expander("⚙️ Legacy Audio Controls", expanded=False):
        st.caption("These controls are deprecated. Use the continuous listening expander above for WebRTC mode.")
        col_mode1, col_mode2 = st.columns(2)
        with col_mode1:
            if st.button("🎙️ Start Continuous", key="push_to_talk_btn", use_container_width=True, type="primary"):
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

    # ============================================================================
    # Dataset Recorder Panel (Phase 4)
    # ============================================================================

    if VOICE_DATASET_OPT_IN:
        _render_dataset_panel()

    # Display last feedback
    if st.session_state.last_feedback:
        st.info(f"Last action: {st.session_state.last_feedback}")

    # Render pending commentary (speech + text preview)
    render_pending_commentary()

    # ============================================================================
    # Phase 4: Match Summary, Export, and Announcements
    # ============================================================================
    st.divider()

def _render_match_analytics() -> CompletedMatchSelection:
    """Render match analytics."""
    _sel_source = 'live'
    _sel_id = ''
    _sel_match = None
    st.subheader("📊 Match Analytics")

    _match_id = st.session_state.get("voice_selected_match_id")
    _engine = st.session_state.match_manager.engine
    _p1 = st.session_state.voice_selected_player1_name or "Player A"
    _p2 = st.session_state.voice_selected_player2_name or "Player B"

    _options = []
    _render_match_id = None
    _render_engine = None
    _render_service = None
    _render_formatted = None

    if _match_id:
        _live_score = f"{_engine.score_a}-{_engine.score_b}"
        _live_label = f"Current live match — {_p1} vs {_p2} ({_live_score})"
        _options.append({
            "id": "live",
            "label": _live_label,
            "player_a_name": _p1,
            "player_b_name": _p2,
            "winner_name": None,
            "match_score": _live_score,
            "game_scores": None,
            "source": "live",
        })

    _current_tournament_id = st.session_state.get("voice_selected_tournament_id")
    if _current_tournament_id is not None:
        _db = SessionLocal()
        try:
            from tournament_platform.app.services.match_analytics import load_completed_match_options
            _completed_opts = load_completed_match_options(_db, tournament_id=_current_tournament_id, limit=100)
            _options.extend([
                {
                    "id": opt.id,
                    "label": opt.label,
                    "player_a_name": opt.player_a_name,
                    "player_b_name": opt.player_b_name,
                    "winner_name": opt.winner_name,
                    "match_score": opt.match_score,
                    "game_scores": opt.game_scores,
                    "source": "database",
                }
                for opt in _completed_opts
            ])
        finally:
            _db.close()
    else:
        _db_all = SessionLocal()
        try:
            from tournament_platform.app.services.match_analytics import load_completed_match_options
            _completed_opts = load_completed_match_options(_db_all, tournament_id=None, limit=100)
            _options.extend([
                {
                    "id": opt.id,
                    "label": opt.label,
                    "player_a_name": opt.player_a_name,
                    "player_b_name": opt.player_b_name,
                    "winner_name": opt.winner_name,
                    "match_score": opt.match_score,
                    "game_scores": opt.game_scores,
                    "source": "database",
                }
                for opt in _completed_opts
            ])
        finally:
            _db_all.close()

    if not _options:
        _empty_msg = "No completed matches available yet. Complete or submit a match to see analytics."
        if _current_tournament_id is not None:
            _tdb = SessionLocal()
            try:
                _tournament = _tdb.query(Tournament).filter(Tournament.id == _current_tournament_id).first()
                if _tournament and _tournament.name:
                    _empty_msg = f"No completed matches found for {_tournament.name}. Complete and submit a match to see analytics."
            finally:
                _tdb.close()
        st.info(_empty_msg)
    else:
        _db_ids = [o["id"] for o in _options if o["source"] == "database"]
        _stored_id = st.session_state.get("analytics_selected_match_id")
        if _stored_id is not None and str(_stored_id) in _db_ids:
            _default_idx = _db_ids.index(str(_stored_id))
        elif _db_ids:
            _default_idx = 0
            st.session_state["analytics_selected_match_id"] = int(_db_ids[0].split(":")[-1]) if ":" in _db_ids[0] else int(_db_ids[0])
        else:
            _default_idx = 0

        _labels = [o["label"] for o in _options]
        _selected_label = st.selectbox("Analyze completed match", _labels, index=_default_idx, key="match_analytics_select")
        _selected_idx = _labels.index(_selected_label)
        _selected = _options[_selected_idx]

        _sel_id = _selected["id"]
        _sel_source = _selected["source"]
        _sel_p1 = _selected["player_a_name"]
        _sel_p2 = _selected["player_b_name"]

        if _sel_source == "database":
            st.session_state["analytics_selected_match_id"] = int(_sel_id)
            _db2 = SessionLocal()
            try:
                _match = _db2.query(Match).filter(Match.id == int(_sel_id)).first()
                if _match:
                    from tournament_platform.app.services.match_analytics import build_synthetic_engine_from_match
                    _synthetic_engine = build_synthetic_engine_from_match(_match)
                    _render_service = MatchAnalyticsService(player_a_name=_sel_p1, player_b_name=_sel_p2)
                    _render_insight = _render_service.analyze(_synthetic_engine, match_id=_match.id)
                    _render_formatted = _render_service.format(_render_insight)
                    _render_match_id = _match.id
                    _render_engine = _synthetic_engine
                else:
                    st.warning("Selected match not found.")
            finally:
                _db2.close()
        else:
            _render_service = MatchAnalyticsService(player_a_name=_p1, player_b_name=_p2)
            _render_insight = _render_service.analyze(_engine, match_id=_match_id)
            _render_formatted = _render_service.format(_render_insight)
            _render_match_id = _match_id
            _render_engine = _engine

        if _render_match_id is not None and _render_formatted is not None:
            if st.session_state.get("voice_debug_mode", False):
                st.caption(f"Analytics selected match ID: {_render_match_id} | Completed matches loaded: {len(_db_ids)} | Selected tournament ID: {_current_tournament_id}")
        
            with st.expander("📋 Summary", expanded=True):
                st.markdown(f"**{_render_formatted.get('title', 'Match Analytics')}**\n\n{_render_formatted.get('summary', 'No summary available.')}")

            if _render_formatted.get("game_by_game"):
                with st.expander("🎮 Game by game"):
                    for g in _render_formatted["game_by_game"]:
                        st.markdown(f"- Game {g['game']}: **{g['winner']}** won {g['score']} — {g['summary']}")

            if _render_formatted.get("momentum"):
                with st.expander("⚡ Momentum"):
                    for m in _render_formatted["momentum"]:
                        size = "Major" if m["is_major"] else "Scoring"
                        st.markdown(f"- **{m['player']}**: {size} run of {m['points']} points ({m['start_score']} → {m['end_score']})")

            if _render_formatted.get("key_events"):
                with st.expander("🔑 Key moments"):
                    for ke in _render_formatted["key_events"]:
                        st.markdown(f"- [{ke['event_type']}] {ke['text']}")

            col_sum, col_exp = st.columns(2)
            with col_sum:
                if st.button("🤖 Generate AI Summary", key="generate_ai_summary_btn", use_container_width=True):
                    try:
                        _ai_text = _render_service.generate_ai_summary(_render_insight, _render_match_id, _render_engine)
                        st.session_state.voice_ai_summary = _ai_text
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI summary failed: {e}")
            with col_exp:
                if st.button("📤 Export Report", key="export_report_btn", use_container_width=True):
                    from tournament_platform.app.services.voice.report_exporter import MatchReportExporter
                    exporter = MatchReportExporter()
                    _meta_base = {
                        "players": [
                            st.session_state.voice_selected_player1_name or "Player A",
                            st.session_state.voice_selected_player2_name or "Player B",
                        ],
                        "tournament": "Current Tournament",
                    }
                    _persisted = _get_persisted_match_meta(_render_match_id, _render_engine)
                    _meta = {
                        **_meta_base,
                        "score": _persisted["score"],
                        "winner": _persisted["winner"],
                        "game_scores": _persisted["game_scores"],
                    }
                    _report = exporter.export_match_report(_render_match_id, _meta, include_summary=True, include_commentary=False)
                    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.download_button(
                        label=f"Download report_{timestamp}.md",
                        data=_report,
                        file_name=f"match_report_{_render_match_id}_{timestamp}.md",
                        mime="text/markdown",
                        key="download_match_report",
                    )

            if "voice_ai_summary" in st.session_state and st.session_state.voice_ai_summary:
                st.markdown(f"**🤖 AI Summary:**\n\n{st.session_state.voice_ai_summary}")

            st.divider()
    return CompletedMatchSelection(
        source=_sel_source,
        match=_sel_match,
        match_id=int(_sel_id) if _sel_source == 'database' else _match_id,
    )


def _render_teams_recap(selection) -> None:
    """Render teams recap."""
    _match_id = st.session_state.get("voice_selected_match_id")
    _engine = st.session_state.match_manager.engine
    _sel_p1 = st.session_state.voice_selected_player1_name or "Player A"
    _sel_p2 = st.session_state.voice_selected_player2_name or "Player B"
    _current_tournament_id = st.session_state.get("voice_selected_tournament_id")
    _sel_source = selection.source if selection else 'live'
    _match = selection.match if selection else None
    _render_match_id = selection.match_id if selection else _match_id

    st.subheader("📣 Teams Recap")
    from tournament_platform.app.services.match_facts import MatchFacts
    from tournament_platform.app.services.recap_templates import build_recap
    from tournament_platform.app.services.teams_publisher import TeamsEvent, TeamsPublisher

    _facts = None
    if _sel_source == "database" and _match:
        _facts = MatchFacts(
            match_id=_match.id,
            tournament_id=_match.tournament_id,
            player_a=_sel_p1,
            player_b=_sel_p2,
            winner=_match.winner or _sel_p1,
            final_score=_match.score or "TBD",
            game_scores=_match.game_scores.split(",") if _match.game_scores else [],
            completed_at=_match.completed_at,
            tags=[],
        )
    else:
        _facts = MatchFacts(
            match_id=_render_match_id,
            tournament_id=_current_tournament_id or 0,
            player_a=_sel_p1,
            player_b=_sel_p2,
            winner=_sel_p1 or "Player A",
            final_score=f"{_engine.score_a}-{_engine.score_b}" if _engine else "TBD",
            game_scores=[],
            completed_at=None,
            tags=[],
        )

    if "recap_tone" not in st.session_state:
        st.session_state["recap_tone"] = "neutral"

    ton_opts = ["neutral", "professional", "fun_office_banter", "sport_commentator", "short_teams_update"]
    tone_labels = {
        "neutral": "Neutral / No-roast",
        "professional": "Professional",
        "fun_office_banter": "Fun office banter",
        "sport_commentator": "Sport commentator",
        "short_teams_update": "Short Teams update",
    }
    cur_tone_idx = ton_opts.index(st.session_state["recap_tone"])
    sel_tone = st.selectbox(
        "Recap tone",
        options=ton_opts,
        index=cur_tone_idx,
        format_func=lambda t: tone_labels.get(t, t),
        key="recap_tone_select",
    )
    st.session_state["recap_tone"] = sel_tone

    _recap_text = build_recap(_facts, tone=sel_tone)

    if "teams_recap_pending" in st.session_state:
        st.session_state["teams_recap_preview"] = st.session_state["teams_recap_pending"]
        del st.session_state["teams_recap_pending"]
    elif "teams_recap_preview" not in st.session_state:
        st.session_state["teams_recap_preview"] = _recap_text

    _preview_area = st.text_area("Recap preview", value=_recap_text, height=120, key="teams_recap_preview", label_visibility="collapsed")

    col_gen, col_reg = st.columns(2)
    with col_gen:
        if st.button("🔄 Regenerate", key="regenerate_recap", use_container_width=True):
            st.session_state["teams_recap_pending"] = build_recap(_facts, tone=st.session_state["recap_tone"])
            st.rerun()
    with col_reg:
        if st.button("📤 Post to Teams", key="post_recap_to_teams", use_container_width=True):
            publisher = TeamsPublisher()
            event = TeamsEvent(
                event_type="match_completed",
                tournament_id=_facts.tournament_id,
                match_id=_facts.match_id,
                title=f"Match Recap: {_facts.player_a} vs {_facts.player_b}",
                body=st.session_state.get("teams_recap_preview", _recap_text),
                facts={},
                created_at=datetime.now(timezone.utc),
            )
            result = publisher.post_plain_text(event, actor="operator")
            if result.success:
                st.success(result.message)
            else:
                st.warning(result.message)
                if st.button("📋 Copy Message", key="copy_recap_message"):
                    st.session_state["teams_copied_recap"] = st.session_state.get("teams_recap_preview", _recap_text)
                    st.toast("Message copied!", icon="✅")
    

def render_voice_sections(snapshot: WebRtcRenderSnapshot | None = None) -> None:
    """Compose the voice scoring UI block."""
    _match_complete = bool(st.session_state.get("match_complete", False))
    _has_valid_match = bool(st.session_state.get("voice_selected_match_id"))

    # Voice Scoring settings
    try:
        _render_voice_scoring_settings(snapshot=snapshot)
    except Exception as exc:
        logger.exception("Voice Scoring settings failed")
        st.error(f"Voice Scoring settings error: {exc}")

    # Voice Input — disable when match is complete or no match selected
    voice_input_enabled = _has_valid_match and not _match_complete
    if voice_input_enabled:
        try:
            _render_voice_input()
        except Exception as exc:
            logger.exception("Voice Input failed")
            st.warning(f"Voice Input unavailable: {exc}")
    else:
        if not _has_valid_match:
            st.info("Select a match to enable voice scoring.")
        elif _match_complete:
            st.info("Voice input is disabled for completed matches.")

    # Match Analytics
    _analytics_selection = None
    try:
        _analytics_selection = _render_match_analytics()
    except Exception as exc:
        logger.exception("Match Analytics failed")
        st.warning(f"Match Analytics unavailable: {exc}")

    # Teams Recap
    try:
        _render_teams_recap(_analytics_selection)
    except Exception as exc:
        logger.exception("Teams Recap failed")
        st.warning(f"Teams Recap unavailable: {exc}")

    if st.session_state.get("tt_sounds_enabled", False):
        _summaries = st.session_state.get("tt_sounds_audio_summaries", [])
        if _summaries:
            with st.expander("🏓 Audio Rally Insights (experimental)", expanded=False):
                _render_audio_rally_insights(_summaries)

    st.divider()
    st.subheader("📢 Announcements")
    _ann_enabled = st.toggle("Enable automatic announcements", value=False, key="voice_announcements_toggle")
    if _ann_enabled:
        st.caption("Automatic match/game announcements are enabled.")

    _maybe_voice_rerun()

    _maybe_voice_heartbeat(snapshot=snapshot)
    _maybe_tt_sounds_heartbeat(snapshot=snapshot)
    st.divider()
    st.subheader("Voice Commands")
    st.markdown("""
    **Supported commands:**
    - "Point to [Player Name]" - Add a point
    - "Player A scored" / "Player B scored" - Add a point
    - "Undo last point" - Remove the last point
    - "What's the score?" - Hear the current score
    - "Alice beat Bob 3-1" - Report a match result

    **PingScore-style color aliases (Phase 4):**
    - "Blue" / "Teal" / "Green" — point to Player A
    - "Red" / "Orange" / "Read" — point to Player B

    **Tips:**
    - Speak clearly and at a normal volume
    - The system works best in a quiet environment
    - Use the +/− buttons for quick manual corrections
    - Duplicate voice commands within 1.2 seconds are automatically suppressed
    """)



if __name__ == "__main__":
    _render_ui()