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
from datetime import datetime
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
from tournament_platform.app.services.voice.dataset_recorder import VoiceDatasetRecorder, VoiceDatasetSample
from tournament_platform.app.services.voice.quick_voice import QuickVoiceScoringEngine
from tournament_platform.app.services.voice_audio import VoiceAudioBuffer, AudioChunk
from tournament_platform.app.services.voice_asr import LocalASR, LocalASRError
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice_audit import EventLogger
from tournament_platform.app.services.voice_noise import NoiseFilter, NoiseProfiler
from tournament_platform.app.services.voice.runtime_state import migrate_from_session_state, get_state, set_state, sync_legacy_keys
from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
from tournament_platform.app.services.voice.confirmation import VoiceConfirmationStateMachine
from tournament_platform.app.api_client import api_client
from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.app.components.tour import render_tour
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
from tournament_platform.app.services.commentary_voice.piper_voice import get_piper_engine, PiperTTSEngine, PiperTTSError
from tournament_platform.app.services.commentary_voice.piper_runtime import find_piper_voices, PiperVoice, is_piper_available


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
if 'last_voice_transcript' not in st.session_state:
    st.session_state.last_voice_transcript = ""
if 'last_voice_event' not in st.session_state:
    st.session_state.last_voice_event = None
if 'last_voice_feedback' not in st.session_state:
    st.session_state.last_voice_feedback = ""
if 'voice_event_log' not in st.session_state:
    st.session_state.voice_event_log = []

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
if 'voice_asr_status' not in st.session_state:
    st.session_state.voice_asr_status = None
if 'voice_webrtc_ctx' not in st.session_state:
    st.session_state.voice_webrtc_ctx = None

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
# Every accepted voice command gets a stable event ID. After applying, we
# request a single scoreboard rerun. This prevents the live scoreboard from
# showing stale state until the user manually interacts.
if 'voice_scoreboard_rerun_requested' not in st.session_state:
    st.session_state.voice_scoreboard_rerun_requested = False
if 'voice_scoreboard_rerun_reason' not in st.session_state:
    st.session_state.voice_scoreboard_rerun_reason = ""
if 'voice_scoreboard_rerun_event_id' not in st.session_state:
    st.session_state.voice_scoreboard_rerun_event_id = None
if 'voice_scoreboard_rerun_consumed_at' not in st.session_state:
    st.session_state.voice_scoreboard_rerun_consumed_at = 0.0
if 'last_applied_voice_event_ids' not in st.session_state:
    st.session_state.last_applied_voice_event_ids = []

# Confirmation panel state (Phase 1)
if 'pending_confirmations' not in st.session_state:
    st.session_state.pending_confirmations = []

# VoiceConfirmationStateMachine singleton (Phase 1 / Phase 2 integration)
if 'voice_confirmation_machine' not in st.session_state:
    st.session_state.voice_confirmation_machine = VoiceConfirmationStateMachine(ttl_seconds=8.0)

# Migrate legacy scattered keys to VoiceRuntimeState (Phase 1 / Phase 2)
migrate_from_session_state()

# Dataset recorder state (Phase 4)
if 'voice_dataset_recorder' not in st.session_state:
    st.session_state.voice_dataset_recorder = VoiceDatasetRecorder(enabled=VOICE_DATASET_OPT_IN)
if 'voice_dataset_samples' not in st.session_state:
    st.session_state.voice_dataset_samples = []

# Quick Voice Scoring state
if 'quick_voice_mode' not in st.session_state:
    st.session_state.quick_voice_mode = "off"
if 'quick_voice_last_player' not in st.session_state:
    st.session_state.quick_voice_last_player = None
if 'quick_voice_last_ts' not in st.session_state:
    st.session_state.quick_voice_last_ts = 0.0
if 'quick_voice_last_phrase' not in st.session_state:
    st.session_state.quick_voice_last_phrase = ""
if 'quick_voice_last_status' not in st.session_state:
    st.session_state.quick_voice_last_status = "idle"
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

# ============================================================================
# Voice rerun helpers (one-shot flags)
# ============================================================================
_VOICE_RERUN_KEY = "_voice_needs_rerun"
_VOICE_RERUN_REASON_KEY = "_voice_rerun_reason"


def _request_voice_rerun(reason: str = "") -> None:
    st.session_state[_VOICE_RERUN_KEY] = True
    st.session_state[_VOICE_RERUN_REASON_KEY] = reason


def _maybe_voice_rerun() -> None:
    if st.session_state.get(_VOICE_RERUN_KEY):
        st.session_state[_VOICE_RERUN_KEY] = False
        st.rerun()


# ============================================================================
# Voice Scoring Gate Helpers
# ============================================================================

def is_voice_scoring_enabled() -> bool:
    """Single source of truth for whether voice scoring is enabled."""
    return bool(st.session_state.get("voice_scoring_enabled", False))


def reject_if_voice_disabled(source: str) -> bool:
    """Return True if the given voice source should be rejected because voice scoring is disabled."""
    if source in {"voice", "continuous", "push_to_talk", "asr", "debug_voice"}:
        return not is_voice_scoring_enabled()
    return False


# ============================================================================
# Voice Session Epoch
# ============================================================================

def _get_voice_session_epoch() -> int:
    """Get current voice session epoch, initializing if needed."""
    if "voice_session_epoch" not in st.session_state:
        st.session_state.voice_session_epoch = 1
    return st.session_state.voice_session_epoch


def _increment_voice_session_epoch() -> None:
    """Bump epoch to invalidate any queued/stale voice events."""
    current = st.session_state.get("voice_session_epoch", 1)
    st.session_state.voice_session_epoch = current + 1


def disable_voice_scoring_and_clear_pending_state(reason: str = "voice_toggle_off") -> None:
    """Disable voice scoring and clear all pending voice state."""
    # Stop continuous listening if active
    if st.session_state.get("voice_listening"):
        st.session_state.voice_listening = False
        ctx = st.session_state.get("voice_webrtc_ctx")
        if ctx and ctx.get("processor"):
            try:
                ctx["processor"].stop()
            except Exception:
                pass
    
    # Clear processor queues explicitly
    if ctx and ctx.get("processor"):
        try:
            proc = ctx["processor"]
            with proc._lock:
                while not proc._chunk_queue.empty():
                    try:
                        proc._chunk_queue.get_nowait()
                    except queue.Empty:
                        break
                while not proc.event_queue.empty():
                    try:
                        proc.event_queue.get_nowait()
                    except queue.Empty:
                        break
        except Exception:
            pass
    
    # Clear all pending voice state
    st.session_state.pending_confirmations = []
    st.session_state.last_voice_transcript = ""
    st.session_state.last_voice_event = None
    st.session_state.last_voice_feedback = ""
    st.session_state.voice_event_log = []
    st.session_state.voice_scoreboard_rerun_requested = False
    st.session_state.voice_scoreboard_rerun_reason = ""
    st.session_state.voice_scoreboard_rerun_event_id = None
    st.session_state.voice_scoreboard_rerun_consumed_at = 0.0
    st.session_state.last_applied_voice_event_ids = []
    st.session_state.voice_last_applied_event_key = None
    st.session_state.voice_last_applied_event_ts = 0.0
    st.session_state.voice_last_heartbeat = 0.0
    
    # Increment epoch to invalidate any queued events
    _increment_voice_session_epoch()
    
    # Reset confirmation machine
    machine = st.session_state.get("voice_confirmation_machine")
    if machine:
        machine.reset()


# ============================================================================
# Quick Voice Scoring helpers
# ============================================================================

def _on_quick_voice_mode_changed(old_mode: str, new_mode: str) -> None:
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
        _request_voice_rerun("quick_voice_accepted")


def _process_quick_voice_event(transcript: str) -> None:
    if st.session_state.get("quick_voice_mode") != "quick":
        return

    mm = st.session_state.match_manager
    engine = QuickVoiceScoringEngine()
    result = engine.process(
        transcript=transcript,
        current_score_a=mm.state.score_a,
        current_score_b=mm.state.score_b,
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

def _maybe_voice_heartbeat() -> None:
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
        if hasattr(processor, 'get_events'):
            has_pending = len(processor.get_events()) > 0
    
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


# ============================================================================
# Canonical Score Apply Function
# ============================================================================

@dataclass
class ScoreApplyResult:
    """Outcome of applying a voice score event through the canonical pipeline."""
    success: bool
    reason: str
    previous_score: str
    new_score: str
    parsed: Any  # VoiceParseResult
    route_result: Any  # RouteResult
    event_key: Optional[str] = None
    event_ts: float = 0.0


def apply_score_event_and_refresh_ui(
    transcript: str,
    source: str = "asr",
    enable_confirmation: bool = VOICE_ENABLE_CONFIRMATION,
    current_score_a: Optional[int] = None,
    current_score_b: Optional[int] = None,
) -> ScoreApplyResult:
    """Canonical function for all voice scoring paths.

    Single pipeline: normalize → parse → route → apply → refresh UI.

    1. Normalize transcript (TranscriptPostProcessor)
    2. Parse to VoiceParseResult (commands.parse())
    3. Route through RouteContext (cooldown, confidence, policy)
    4. If APPLY: convert to VoiceScoreEvent via parsed.to_score_event()
    5. Call match_manager.apply_voice_event()
    6. Update cooldown tracking in session state
    7. Play sound cues
    8. Speak TTS
    9. Request rerun
    10. Return ScoreApplyResult
    """
    # HARD GATE: reject all voice commands when voice scoring is disabled
    if reject_if_voice_disabled(source):
        return ScoreApplyResult(
            success=False,
            reason="voice_scoring_disabled",
            previous_score=st.session_state.match_manager.state.get_score_string(),
            new_score=st.session_state.match_manager.state.get_score_string(),
            parsed=None,
            route_result=None,
        )

    mm = st.session_state.match_manager
    if current_score_a is None:
        current_score_a = mm.state.score_a
    if current_score_b is None:
        current_score_b = mm.state.score_b

    # 1. Normalize
    processed = TranscriptPostProcessor(VoiceVocabulary.load()).process(transcript)

    # 2. Parse
    parsed = parse_command(
        processed,
        current_score_a=current_score_a,
        current_score_b=current_score_b,
    )
    parsed.source = source

    # 3. Route
    _route_ctx = RouteContext(
        current_score_a=current_score_a,
        current_score_b=current_score_b,
        strict_mode=st.session_state.get("voice_strict_mode", False),
        enable_confirmation=enable_confirmation,
        last_applied_event_key=st.session_state.get("voice_last_applied_event_key"),
        last_applied_event_ts=st.session_state.get("voice_last_applied_event_ts", 0.0),
    )
    route_result = route_and_update_context(parsed, _route_ctx)

    prev_score = mm.state.get_score_string()

    # REJECT
    if route_result.decision == RouteDecision.REJECT:
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
        else:
            st.session_state.last_voice_feedback = "Confirmation busy — try again"
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
        st.toast(f"🎤 {_phase3_result.get('message', '')}", icon="✅")
        if VOICE_DEBUG_EVENTS:
            st.session_state.voice_event_logger.record(
                _score_event,
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
        new_score = mm.state.get_score_string()
        note = "" if success else msg

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

            st.session_state.last_voice_feedback = msg
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
                _build_local_commentary("voice_score_confirmed", state, None, settings, str(uuid.uuid4()))

            # Immediately re-derive UI state so it's available on next render.
            # This ensures completed_games and match_complete are never stale.
            st.session_state.completed_games = compute_completed_games(mm.engine)
            st.session_state.match_complete = (mm.engine.match_status == "match_won")
            if mm.engine.match_status == "match_won":
                st.session_state.pending_result_submission = True

            _request_voice_rerun("applied")
        else:
            st.session_state.last_voice_feedback = msg
            st.warning(f"🎤 Voice: {msg}")
            play_cue("reject")
            if st.session_state.get("commentary_engine") == "local":
                _build_local_commentary("voice_score_rejected", state, None, settings, str(uuid.uuid4()))
    else:
        success = False
        msg = "Unknown command"
        st.session_state.last_voice_feedback = msg
        new_score = prev_score
        note = "unrecognized transcript"

    # Structured event logging
    if VOICE_DEBUG_EVENTS:
        st.session_state.voice_event_logger.record(
            _score_event,
            accepted=success,
            previous_score=prev_score,
            new_score=new_score,
            note=note,
        )

    # Backward-compatible UI log entry
    log_entry = {
        "timestamp": getattr(_score_event, 'timestamp', time.time()),
        "event_id": getattr(_score_event, 'event_id', ''),
        "transcript": transcript,
        "event_type": _score_event.type if hasattr(_score_event, 'type') else 'unknown',
        "score_a": getattr(_score_event, 'score_a', None),
        "score_b": getattr(_score_event, 'score_b', None),
        "player": getattr(_score_event, 'player', None),
        "confidence": getattr(_score_event, 'confidence', 0.0),
        "source": source,
        "speaker_label": getattr(_score_event, 'speaker_label', None),
        "language": getattr(_score_event, 'language', 'en'),
        "asr_latency_ms": getattr(_score_event, 'asr_latency_ms', None),
        "noise_rms": getattr(_score_event, 'noise_rms', None),
        "accepted": success,
        "previous_score": prev_score,
        "new_score": new_score,
    }
    st.session_state.voice_event_log.append(log_entry)
    if len(st.session_state.voice_event_log) > 50:
        st.session_state.voice_event_log = st.session_state.voice_event_log[-50:]

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
) -> Dict[str, Any]:
    """Shared transcript processing for push-to-talk, continuous, and debug.

    Delegates to the canonical ``apply_score_event_and_refresh_ui`` and wraps
    the result in the legacy dict format for backward compatibility.

    Returns a dict with keys:
        success, reason, previous_score, new_score, parsed, route_result
    """
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


# ============================================================================
# Commentary Settings Initialization
# ============================================================================
if 'commentary_enabled' not in st.session_state:
    st.session_state.commentary_enabled = False
if 'commentary_style' not in st.session_state:
    st.session_state.commentary_style = normalize_commentary_style(CommentaryStyle.NEUTRAL.value)
# Normalize any legacy/typo style value (e.g. "couch") stored in the session so
# later CommentaryStyle(...) construction never raises.
elif st.session_state.commentary_style not in COMMENTARY_STYLE_OPTIONS:
    st.session_state.commentary_style = normalize_commentary_style(st.session_state.commentary_style)
if 'commentary_verbosity' not in st.session_state:
    st.session_state.commentary_verbosity = CommentaryVerbosity.STANDARD.value
if 'commentary_voice' not in st.session_state:
    st.session_state.commentary_voice = "default"
if 'commentary_language' not in st.session_state:
    st.session_state.commentary_language = "en"
if 'commentary_muted' not in st.session_state:
    st.session_state.commentary_muted = False
if 'commentary_mode' not in st.session_state:
    st.session_state.commentary_mode = CommentaryMode.EVERY_POINT.value
if 'commentary_intensity' not in st.session_state:
    st.session_state.commentary_intensity = CommentaryIntensity.MEDIUM.value
if 'commentary_speak_generated' not in st.session_state:
    st.session_state.commentary_speak_generated = True
if 'commentary_ollama_rewrite_enabled' not in st.session_state:
    st.session_state.commentary_ollama_rewrite_enabled = False
if 'commentary_ollama_model' not in st.session_state:
    st.session_state.commentary_ollama_model = ""
if 'commentary_ollama_timeout' not in st.session_state:
    st.session_state.commentary_ollama_timeout = 2.0
if 'commentary_announced_game_won' not in st.session_state:
    st.session_state.commentary_announced_game_won = False
if 'commentary_announced_match_won' not in st.session_state:
    st.session_state.commentary_announced_match_won = False
if 'commentary_announced_result_submitted' not in st.session_state:
    st.session_state.commentary_announced_result_submitted = False
if 'commentary_voice_profile' not in st.session_state:
    st.session_state.commentary_voice_profile = "browser_default"
if 'commentary_rate' not in st.session_state:
    st.session_state.commentary_rate = 1.0
if 'commentary_pitch' not in st.session_state:
    st.session_state.commentary_pitch = 1.0
if 'commentary_volume' not in st.session_state:
    st.session_state.commentary_volume = 1.0
if 'commentary_engine' not in st.session_state:
    st.session_state.commentary_engine = "legacy"
if 'commentary_detail' not in st.session_state:
    st.session_state.commentary_detail = "standard"
if 'commentary_browser_voice_name' not in st.session_state:
    st.session_state.commentary_browser_voice_name = None
if 'commentary_emitted_game_keys' not in st.session_state:
    st.session_state.commentary_emitted_game_keys = []
if 'commentary_last_server' not in st.session_state:
    st.session_state.commentary_last_server = None
if 'commentary_last_critical_moment' not in st.session_state:
    st.session_state.commentary_last_critical_moment = None
if 'commentary_last_critical_moment_ts' not in st.session_state:
    st.session_state.commentary_last_critical_moment_ts = 0.0
if 'pending_local_audio' not in st.session_state:
    st.session_state.pending_local_audio = None
if 'last_commentary_event_id' not in st.session_state:
    st.session_state.last_commentary_event_id = None
if 'pending_commentary' not in st.session_state:
    st.session_state.pending_commentary = None
if 'last_commentary_text' not in st.session_state:
    st.session_state.last_commentary_text = None
if 'commentary_tts_engine' not in st.session_state:
    st.session_state.commentary_tts_engine = "browser"
if 'commentary_piper_voice_id' not in st.session_state:
    st.session_state.commentary_piper_voice_id = None
if 'last_commentary_engine' not in st.session_state:
    st.session_state.last_commentary_engine = None
if 'last_commentary_voice_id' not in st.session_state:
    st.session_state.last_commentary_voice_id = None
if 'last_commentary_audio_path' not in st.session_state:
    st.session_state.last_commentary_audio_path = None


# ============================================================================
# Voice Scoring (WebRTC) Audio Processor
# ============================================================================

class VoiceAudioProcessor(AudioProcessorBase):
    """
    Audio processor for streamlit-webrtc voice scoring.

    Receives audio frames, buffers them into chunks, and queues them for
    background transcription. A single worker thread handles all transcription
    to avoid thread explosion. The worker emits plain data tuples into
    ``event_queue``; the main Streamlit loop consumes and mutates session state.

    Inherits from ``AudioProcessorBase`` so streamlit-webrtc actually invokes
    ``recv`` / ``recv_queued`` (it never calls a custom ``recv_audio`` method).
    """

    # Class-level worker control: one worker thread per processor instance,
    # started on first chunk and stopped on ``stop()``.
    _worker_started: bool = False

    def __init__(
        self,
        noise_gate_rms: float = 0.0,
        sample_format: str = SAMPLE_FORMAT_FLOAT32,
        voice_strict_mode: bool = False,
        vad: Optional[VoiceActivityDetector] = None,
    ):
        """
        Initialize the audio processor.

        Args:
            noise_gate_rms: Minimum speech-energy floor. 0.0 disables the gate.
            sample_format: Audio sample format ("float32" or "int16").
            voice_strict_mode: If True, flag score events for confirmation.
            vad: Optional VoiceActivityDetector for improved speech detection.
        """
        # Detect sample format from WebRTC frames (default to float32 for safety)
        self._sample_format = getattr(self, '_sample_format', sample_format)
        self.audio_buffer = VoiceAudioBuffer(
            noise_gate_rms=noise_gate_rms,
            sample_format=self._sample_format,
            vad=vad,
        )
        # Phase 6: Load vocabulary for ASR biasing and post-processing
        self.vocabulary = VoiceVocabulary.load()
        self.parser = VoiceParser()
        self.post_processor = TranscriptPostProcessor(self.vocabulary)
        self.event_queue: queue.Queue = queue.Queue(maxsize=50)
        self._processing = False
        self._lock = threading.Lock()
        # Configuration passed from main thread (not read from session state
        # here to keep __init__ safe for any calling thread).
        self._voice_strict_mode = voice_strict_mode
        # Single worker thread for all chunks (avoids thread explosion)
        self._worker_thread: Optional[threading.Thread] = None
        self._chunk_queue: queue.Queue = queue.Queue(maxsize=20)
        self._stop_worker = threading.Event()
        self._dropped_chunks = 0

    def _get_asr(self):
        """Lazy-load the ASR backend to keep processor initialization lightweight."""
        if self._asr is None:
            self._asr = ASRBackendFactory.create(vocabulary=self.vocabulary)
        return self._asr

    def _start_worker(self) -> None:
        """Start the single background transcription worker if not already running."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        def _worker_loop() -> None:
            """Consume chunks from _chunk_queue and transcribe them."""
            while not self._stop_worker.is_set():
                try:
                    chunk = self._chunk_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._transcribe_chunk(chunk)

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        self._worker_thread.start()

    def _ingest_frame(self, frame) -> None:
        """
        Process a single WebRTC audio frame: detect its sample format, buffer
        it, and (when a complete utterance chunk is detected) queue it for the
        background transcription worker.
        """
        import numpy as np
        
        # Detect format from frame and update buffer accordingly.
        # If incoming format differs from the current buffer state, flush the
        # current buffer first so a chunk never contains mixed-format frames.
        fmt_name = getattr(getattr(frame, 'format', None), 'name', None)
        sample_rate = getattr(frame, 'sample_rate', None)
        channels = getattr(frame, 'channels', None)
        
        detected_format = None
        if fmt_name in ('s16', 's16p'):
            detected_format = SAMPLE_FORMAT_INT16
        elif fmt_name in ('flt', 'fltp', 'f32', 'f32p'):
            detected_format = SAMPLE_FORMAT_FLOAT32
        
        # Flush if any format parameter changed
        needs_flush = False
        if detected_format is not None and detected_format != self._sample_format:
            needs_flush = True
        if sample_rate is not None and sample_rate != self.audio_buffer.sample_rate:
            needs_flush = True
        if channels is not None and channels != self.audio_buffer.channels:
            needs_flush = True
        
        if needs_flush:
            with self.audio_buffer._lock:
                buffered = len(self.audio_buffer._buffer)
            if buffered > 0:
                flushed = self.audio_buffer.flush()
                if flushed:
                    logger.debug(
                        "VoiceAudioProcessor: flushed chunk on format change "
                        "(old_format=%s, new_format=%s, old_rate=%d, new_rate=%s, old_channels=%d, new_channels=%s)",
                        self._sample_format, detected_format or self._sample_format,
                        self.audio_buffer.sample_rate, sample_rate,
                        self.audio_buffer.channels, channels,
                    )
                    self._enqueue_chunk(flushed)
        
        if detected_format is not None and detected_format != self._sample_format:
            self._sample_format = detected_format
            if self.audio_buffer.sample_format != self._sample_format:
                self.audio_buffer.update_format(sample_format=self._sample_format)
        
        if sample_rate is not None and sample_rate != self.audio_buffer.sample_rate:
            self.audio_buffer.update_format(sample_rate=sample_rate)
        
        if channels is not None and channels != self.audio_buffer.channels:
            self.audio_buffer.update_format(channels=channels)
        
        # Fallback: detect from numpy array dtype if format name was not available
        if detected_format is None:
            try:
                array = frame.to_ndarray()
                if array.dtype == np.int16:
                    fallback_format = SAMPLE_FORMAT_INT16
                else:
                    fallback_format = SAMPLE_FORMAT_FLOAT32
                if fallback_format != self._sample_format:
                    needs_flush = True
                    with self.audio_buffer._lock:
                        buffered = len(self.audio_buffer._buffer)
                    if buffered > 0:
                        flushed = self.audio_buffer.flush()
                        if flushed:
                            logger.debug(
                                "VoiceAudioProcessor: flushed chunk on fallback format change "
                                "(old_format=%s, new_format=%s)",
                                self._sample_format, fallback_format,
                            )
                            self._enqueue_chunk(flushed)
                    self._sample_format = fallback_format
                    if self.audio_buffer.sample_format != self._sample_format:
                        self.audio_buffer.update_format(sample_format=self._sample_format)
            except Exception:
                pass
        
        frame_bytes = frame.to_ndarray().tobytes()
        chunk = self.audio_buffer.push_frame(frame_bytes)

        if chunk is not None:
            logger.debug(
                "VoiceAudioProcessor: emitted chunk %.1f ms, RMS=%.4f, frames=%d, "
                "format=%s, sample_rate=%d, channels=%d",
                chunk.duration_ms, chunk.rms, len(chunk.frames),
                chunk.sample_format, chunk.sample_rate, chunk.channels,
            )
            self._enqueue_chunk(chunk)

    def _enqueue_chunk(self, chunk: AudioChunk) -> None:
        """Enqueue a chunk with bounded queue and drop-oldest policy."""
        self._start_worker()
        try:
            self._chunk_queue.put_nowait(chunk)
        except queue.Full:
            # Drop oldest to keep real-time behavior
            try:
                self._chunk_queue.get_nowait()
                self._dropped_chunks += 1
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait(chunk)
            except queue.Full:
                pass  # Queue still full; drop this chunk too

    def recv(self, frame):
        """
        streamlit-webrtc callback (sync / non-async mode).

        Receives a single audio frame, buffers it, and returns it unchanged so
        the audio stream continues to flow in SENDONLY mode.
        """
        self._ingest_frame(frame)
        return frame

    async def recv_queued(self, frames):
        """
        streamlit-webrtc callback (async mode — the default).

        Receives a batch of audio frames, buffers each one, and returns the
        batch so the audio stream continues to flow in SENDONLY mode.
        """
        for frame in frames:
            self._ingest_frame(frame)
        return frames

    def _transcribe_chunk(self, chunk: AudioChunk) -> None:
        """Transcribe an audio chunk in the background worker thread.

        NOTE: This runs in a background thread. Do NOT access st.session_state
        here. Pass any needed context (e.g., current scores) from the main
        Streamlit loop via method parameters or instance attributes set by
        the main thread.
        """
        try:
            pcm_bytes = chunk.to_pcm_bytes()
            if not pcm_bytes:
                logger.debug("Empty PCM bytes, skipping transcription")
                return

            if chunk.rms < 0.01:
                logger.debug(
                    "Chunk RMS %.4f below floor, skipping transcription",
                    chunk.rms,
                )
                return

            logger.debug(
                "Transcribing chunk: pcm_len=%d, chunk_format=%s, chunk_rate=%d, "
                "chunk_channels=%d, chunk_rms=%.4f",
                len(pcm_bytes), chunk.sample_format, chunk.sample_rate,
                chunk.channels, chunk.rms,
            )

            # Measure ASR latency for observability (Phase 1/5).
            start = time.time()
            raw_text = self._get_asr().transcribe_pcm(pcm_bytes)
            latency_ms = (time.time() - start) * 1000.0
            logger.debug("ASR raw result: '%s' (latency: %.1f ms)", raw_text, latency_ms)
            if not raw_text:
                return

            # Phase 6: Post-process transcript with vocabulary corrections
            text = self.post_processor.process(raw_text)
            logger.debug("Post-processed text: '%s'", text)

            # Parse the transcript without current scores (deuce validation
            # is deferred to the main Streamlit loop where session state is safe).
            event = self.parser.parse(text)
            event.noise_rms = chunk.rms
            event.asr_latency_ms = latency_ms
            # Strict mode (Phase 5): flag score events for confirmation.
            # NOTE: We read voice_strict_mode from the instance attribute that
            # the main thread updates, not from st.session_state directly.
            if getattr(self, '_voice_strict_mode', False) and event.type != "unknown":
                event.requires_confirmation = True

            # Put event in queue for the main Streamlit loop to consume
            try:
                self.event_queue.put_nowait((raw_text, text, event))
            except queue.Full:
                pass  # Drop event if main thread is too far behind
            logger.debug("Voice event queued: type=%s, text='%s'", event.type, text)

        except Exception as e:
            logger.error("Error in voice transcription thread: %s", e)

    def get_events(self) -> List[Tuple[str, str, VoiceScoreEvent]]:
        """Drain all pending events from the queue.

        Returns a list of (raw_transcript, processed_transcript, event) tuples.
        """
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def stop(self) -> None:
        """Stop processing and flush remaining audio."""
        self._stop_worker.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self.audio_buffer.reset()
        # Clear pending queues to release memory and stop stale processing
        with self._lock:
            while not self._chunk_queue.empty():
                try:
                    self._chunk_queue.get_nowait()
                except queue.Empty:
                    break
            while not self.event_queue.empty():
                try:
                    self.event_queue.get_nowait()
                except queue.Empty:
                    break


def persist_voice_match_to_db(match_id: int, engine) -> None:
    """
    Persist the current voice MatchManager engine state to the DB ``Match`` row.

    The ``score`` column follows the app-wide convention of "gamesWonA-gamesWonB"
    (the match result). While the match is in progress the row is marked
    ``active`` and the running games-won tally is stored; when the match is won
    the row is marked ``completed`` with ``winner``/``winner_id``/``completed_at``
    so completed games/matches survive session restarts.
    """
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
            winner_label = "A" if engine.games_won_a > engine.games_won_b else "B"
            match.winner = (
                engine.player_a_name if winner_label == "A" else engine.player_b_name
            )
            match.winner_id = (
                engine.player_a_id if winner_label == "A" else engine.player_b_id
            )
            if match.completed_at is None:
                match.completed_at = datetime.now(timezone.utc)
        else:
            match.status = MatchStatus.active
            match.winner = None
            match.winner_id = None

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


def _audio_input_to_pcm(audio_file: Any) -> bytes:
    """Convert st.audio_input bytes (WebM/Opus) to mono PCM 16kHz int16."""
    try:
        import av
        container = av.open(audio_file)
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000,
        )
        pcm_frames = []
        for packet in container.demux(stream):
            for frame in packet.decode():
                resampled = resampler.resample(frame)
                pcm_frames.append(resampled.to_ndarray().tobytes())
        return b"".join(pcm_frames)
    except Exception as exc:
        logger.error("Failed to convert audio input to PCM: %s", exc)
        return b""


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

    result = _process_voice_transcript(raw_text, source="push_to_talk")

    if VOICE_DEBUG_EVENTS:
        try:
            _e = VoiceParser().parse(
                TranscriptPostProcessor(VoiceVocabulary.load()).process(raw_text),
                current_score_a=st.session_state.match_manager.state.score_a,
                current_score_b=st.session_state.match_manager.state.score_b,
            )
            st.session_state.voice_event_logger.record(
                _e,
                accepted=result.get("success", False),
                previous_score=result.get("previous_score", ""),
                new_score=result.get("new_score", ""),
                note="push_to_talk",
            )
        except Exception:
            pass

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


def _render_confirm_panel() -> None:
    pending = st.session_state.get("pending_confirmations", [])
    if not pending:
        _machine = st.session_state.get("voice_confirmation_machine")
        if _machine and not _machine.is_idle():
            _machine.reset()
        return

    st.markdown("### ⏳ Pending Voice Confirmations")
    for idx, item in enumerate(pending):
        with st.container(border=True):
            col_a, col_b, col_c = st.columns([2, 1, 1])
            with col_a:
                st.markdown(f"**Intent:** {item['intent']}")
                st.caption(f"Transcript: {item['raw_transcript']}")
                st.caption(f"Confidence: {item['confidence']:.0%}")
                st.caption(f"{item['predicted_score_before']} → {item['predicted_score_after']}")
            with col_b:
                if st.button("✅ Confirm", key=f"confirm_voice_{idx}", use_container_width=True):
                    _apply_pending(idx)
            with col_c:
                if st.button("✖ Cancel", key=f"cancel_voice_{idx}", use_container_width=True):
                    _machine = st.session_state.get("voice_confirmation_machine")
                    if _machine:
                        _machine.cancel()
                        _machine.reset()
                    st.session_state.pending_confirmations.pop(idx)
                    st.session_state.last_voice_feedback = "Cancelled"
                    _request_voice_rerun("cancel")


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
        if VOICE_DEBUG_EVENTS:
            st.session_state.voice_event_logger.record(
                VoiceScoreEvent(type=intent_str, raw_text=raw, confidence=item.get("confidence", 0.0)),
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


def _process_voice_events() -> None:
    """Process pending voice events from the WebRTC audio processor.

    Runs in the main Streamlit thread. Reads events from the processor's
    queue and delegates to the canonical ``apply_score_event_and_refresh_ui``.

    The continuous listening loop calls ``st.rerun()`` at the end to drain
    queued events promptly (streamlit-webrtc does not rerun on audio data).
    """
    if not st.session_state.voice_listening:
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
        return

    # If the match is already won, stop listening and disable voice updates.
    _engine = st.session_state.match_manager.engine
    if _engine.match_status == "match_won":
        st.session_state.voice_listening = False
        st.session_state.last_voice_feedback = "Match complete — voice listening stopped"
        if ctx and ctx.get("processor"):
            ctx["processor"].stop()
        return

    _current_score_a = st.session_state.match_manager.state.score_a
    _current_score_b = st.session_state.match_manager.state.score_b

    # Expire stale pending confirmations (> 8 s old).
    _now = time.time()
    _stale_idx = []
    for _idx, _pending in enumerate(st.session_state.pending_confirmations):
        if _now - _pending.get("received_at", _now) > 8.0:
            _stale_idx.append(_idx)
    for _idx in reversed(_stale_idx):
        st.session_state.pending_confirmations.pop(_idx)

    logger.info("_process_voice_events: processing %d events", len(events))
    for raw_text, text, event in events:
        if st.session_state.get("quick_voice_mode") == "quick":
            _process_quick_voice_event(text)
        else:
            # Preserve noise/latency metadata on the text for the canonical function
            metadata_prefix = ""
            if getattr(event, 'noise_rms', None) is not None:
                metadata_prefix = f"[noise_rms={event.noise_rms}]"
            if getattr(event, 'asr_latency_ms', None) is not None:
                metadata_prefix += f"[latency={event.asr_latency_ms}]"

            # Use the canonical function for ALL scoring logic
            result = apply_score_event_and_refresh_ui(
                transcript=text,
                source="webrtc",
                enable_confirmation=VOICE_ENABLE_CONFIRMATION,
                current_score_a=_current_score_a,
                current_score_b=_current_score_b,
            )

            # Log result for observability
            logger.debug(
                "Voice event processed: transcript='%s', success=%s, reason='%s', "
                "prev='%s' -> new='%s'",
                text, result.success, result.reason,
                result.previous_score, result.new_score,
            )

    # Note: We do NOT call st.rerun() here anymore. The heartbeat at the end
    # of the page handles rerunning while continuous listening is active.
    # This avoids conflicting rerun calls from both the event processor and
    # the heartbeat.


def _render_dataset_panel() -> None:
    """Render the opt-in dataset recorder panel (Phase 4)."""
    if not VOICE_DATASET_OPT_IN:
        st.caption("Dataset recorder is disabled. Set VOICE_DATASET_OPT_IN=1 to enable.")
        return

    recorder: VoiceDatasetRecorder = st.session_state.get("voice_dataset_recorder")
    if recorder is None:
        return

    st.markdown("### 🧪 Voice Dataset Recorder")
    st.caption(
        "Opt-in capture of transcripts, parsed intents, and operator corrections "
        "for grammar evaluation. No audio is stored unless explicitly enabled below."
    )

    col_opt1, col_opt2, col_opt3 = st.columns(3)
    with col_opt1:
        st.session_state.voice_dataset_record_audio = st.checkbox(
            "Record audio",
            value=st.session_state.get("voice_dataset_record_audio", False),
            help="Store audio samples (privacy-sensitive). Disabled by default.",
        )
    with col_opt2:
        match_id = st.session_state.get("voice_selected_match_id")
        st.caption(f"Match ID: {match_id if match_id else 'None'}")
    with col_opt3:
        if st.button("🔄 Refresh samples", key="refresh_dataset_samples"):
            st.rerun()

    samples = recorder.get_samples(match_id=match_id, limit=200)
    st.session_state.voice_dataset_samples = samples

    if samples:
        st.markdown(f"**Recent samples ({len(samples)} shown)**")
        for idx, sample in enumerate(samples):
            with st.container(border=True):
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.markdown(f"`{sample.transcript}`")
                    st.caption(f"Parsed: {sample.parsed_intent} | Expected: {sample.expected_intent or '—'}")
                    if sample.matched is False:
                        st.warning(f"Correction: {sample.correction}")
                with col_b:
                    expected = st.text_input(
                        "Expected intent",
                        value=sample.expected_intent or "",
                        key=f"dataset_expected_{sample.id}_{idx}",
                    )
                    if st.button("💾 Save", key=f"dataset_save_{sample.id}_{idx}", use_container_width=True):
                        from tournament_platform.app.services.voice.event_log import VoiceCommandRepository
                        db = VoiceCommandRepository._session()
                        try:
                            row = db.query(VoiceCommand).filter(VoiceCommand.id == sample.id).first()
                            if row:
                                row.expected_intent = expected
                                row.matched = expected == sample.parsed_intent
                                row.correction = expected if sample.parsed_intent != expected else None
                                db.commit()
                                st.success("Saved")
                                st.rerun()
                        except Exception as exc:
                            db.rollback()
                            st.error(f"Save failed: {exc}")
                        finally:
                            db.close()
                with col_c:
                    st.caption(f"Matched: {sample.matched}")
                    st.caption(f"Mic: {sample.mic_type or '—'}")

        col_jsonl, col_csv, col_summary = st.columns(3)
        with col_jsonl:
            if st.button("📥 Export JSONL", key="export_dataset_jsonl"):
                jsonl = recorder.export_jsonl(samples=samples)
                timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    label=f"Download voice_dataset_{timestamp}.jsonl",
                    data=jsonl,
                    file_name=f"voice_dataset_{timestamp}.jsonl",
                    mime="application/x-ndjson",
                    key="download_dataset_jsonl",
                )
        with col_csv:
            if st.button("📊 Export CSV", key="export_dataset_csv"):
                csv_data = recorder.export_csv(samples=samples)
                timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    label=f"Download voice_dataset_{timestamp}.csv",
                    data=csv_data,
                    file_name=f"voice_dataset_{timestamp}.csv",
                    mime="text/csv",
                    key="download_dataset_csv",
                )
        with col_summary:
            summary = recorder.accuracy_summary(samples=samples)
            st.markdown(
                f"**Accuracy:** {summary['accuracy']:.0%}  \n"
                f"Matched: {summary['matched']} / {summary['total']}"
            )
    else:
        st.caption("No dataset samples recorded yet. Enable VOICE_DATASET_OPT_IN and use voice commands to start collecting.")


# ============================================================================
# Commentary Helpers
# ============================================================================

_commentary_service = CommentaryService()


def _get_commentary_settings() -> CommentarySettings:
    """Build CommentarySettings from current session state."""
    # Normalize the style so legacy/typo values ("couch", "commentator") never
    # raise ValueError when constructing the CommentaryStyle enum.
    style_value = normalize_commentary_style(
        st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)
    )
    return CommentarySettings(
        enabled=st.session_state.get("commentary_enabled", False),
        style=CommentaryStyle(style_value),
        verbosity=CommentaryVerbosity(st.session_state.get("commentary_verbosity", CommentaryVerbosity.STANDARD.value)),
        voice=st.session_state.get("commentary_voice", "default"),
        language=st.session_state.get("commentary_language", "en"),
        muted=st.session_state.get("commentary_muted", False),
        mode=CommentaryMode(st.session_state.get("commentary_mode", CommentaryMode.EVERY_POINT.value)),
        intensity=CommentaryIntensity(st.session_state.get("commentary_intensity", CommentaryIntensity.MEDIUM.value)),
        speak_generated=st.session_state.get("commentary_speak_generated", True),
        ollama_rewrite_enabled=st.session_state.get("commentary_ollama_rewrite_enabled", False),
        ollama_model=st.session_state.get("commentary_ollama_model", ""),
        ollama_timeout=float(st.session_state.get("commentary_ollama_timeout", 2.0)),
        voice_profile_id=st.session_state.get("commentary_voice_profile", "browser_default"),
        rate=float(st.session_state.get("commentary_rate", 1.0)),
        pitch=float(st.session_state.get("commentary_pitch", 1.0)),
        volume=float(st.session_state.get("commentary_volume", 1.0)),
    )


_CRITICAL_COOLDOWN_S = 10.0


def _is_critical_moment(moment: ScoreMoment) -> bool:
    return moment in (
        ScoreMoment.DEUCE,
        ScoreMoment.ADVANTAGE_A,
        ScoreMoment.ADVANTAGE_B,
        ScoreMoment.GAME_POINT_A,
        ScoreMoment.GAME_POINT_B,
        ScoreMoment.GAME_WON_A,
        ScoreMoment.GAME_WON_B,
        ScoreMoment.MATCH_WON_A,
        ScoreMoment.MATCH_WON_B,
        ScoreMoment.COMEBACK_A,
        ScoreMoment.COMEBACK_B,
    )


def _apply_critical_cooldown(settings: CommentarySettings, moment: ScoreMoment) -> CommentarySettings:
    if not _is_critical_moment(moment):
        return settings
    last_moment = st.session_state.get("commentary_last_critical_moment")
    last_ts = st.session_state.get("commentary_last_critical_moment_ts", 0.0)
    now = time.time()
    if last_moment == moment and (now - last_ts) < _CRITICAL_COOLDOWN_S:
        return CommentarySettings(
            enabled=settings.enabled,
            style=settings.style,
            verbosity=CommentaryVerbosity.MINIMAL,
            voice=settings.voice,
            language=settings.language,
            muted=settings.muted,
            mode=settings.mode,
            intensity=CommentaryIntensity.LOW,
            speak_generated=settings.speak_generated,
            ollama_rewrite_enabled=settings.ollama_rewrite_enabled,
            ollama_model=settings.ollama_model,
            ollama_timeout=settings.ollama_timeout,
            voice_profile_id=settings.voice_profile_id,
            rate=settings.rate,
            pitch=settings.pitch,
            volume=settings.volume,
        )
    st.session_state.commentary_last_critical_moment = moment
    st.session_state.commentary_last_critical_moment_ts = now
    return settings


def _synthesize_piper_audio(text: str, voice_profile_id: str) -> Optional[str]:
    from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile
    profile = get_profile(voice_profile_id)
    if not profile or profile.engine != "piper":
        return None
    engine = get_piper_engine()
    if not engine.available:
        return None
    voices = engine.list_voices()
    if not voices:
        return None
    voice_map = {v.id: v for v in voices}
    piper_voice = voice_map.get(profile.voice_id or profile.id)
    if not piper_voice:
        piper_voice = next(iter(voices), None)
    if not piper_voice:
        return None
    try:
        result = engine.synthesize(text, piper_voice, rate=float(st.session_state.get("commentary_rate", 1.0)), volume=float(st.session_state.get("commentary_volume", 1.0)))
        return str(result.audio_path)
    except Exception:
        return None


def play_commentary(
    text: str,
    settings: CommentarySettings,
    event_id: str | None = None,
    importance: str | None = None,
) -> None:
    """Route commentary playback to the selected engine with fallback."""
    if settings.mode == CommentaryMode.VISUAL_ONLY:
        return
    if not text:
        return

    engine_name = st.session_state.get("commentary_tts_engine", "browser")
    if engine_name != "piper":
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        speak_commentary(
            text=text,
            key=f"commentary_{event_id or uuid.uuid4()}",
            voice=settings.voice,
            lang=tts_lang,
            rate=settings.rate,
            pitch=settings.pitch,
            volume=settings.volume,
            voice_profile_id=settings.voice_profile_id,
        )
        return

    piper_voice_id = st.session_state.get("commentary_piper_voice_id")
    if not piper_voice_id:
        notify_piper_unavailable_once(
            "No Piper voice selected. Choose a Piper voice in commentary settings, "
            "or use Browser speech.",
            level="info",
        )
        return

    from tournament_platform.app.services.commentary_voice.voice_catalog import get_profile
    profile = get_profile(piper_voice_id)
    if not profile or profile.engine != "piper":
        notify_piper_unavailable_once(
            "Piper voice not found. Browser speech is available as a fallback.",
            level="info",
        )
        return

    engine = get_piper_engine()
    if not engine.available:
        notify_piper_unavailable_once(
            "Piper local TTS is not available in this environment. "
            "Browser speech is available as a fallback.",
            level="info",
        )
        return

    voices = engine.list_voices()
    voice_map = {v.id: v for v in voices}
    piper_voice = voice_map.get(piper_voice_id)
    if not piper_voice:
        notify_piper_unavailable_once(
            "Piper voice model not found. Browser speech is available as a fallback.",
            level="info",
        )
        return

    try:
        result = engine.synthesize(
            text,
            piper_voice,
            rate=float(settings.rate),
            volume=float(settings.volume),
        )
        speak_commentary_audio_file(result.audio_path, key=f"piper_{event_id or uuid.uuid4()}")
        st.session_state.last_commentary_engine = "piper"
        st.session_state.last_commentary_voice_id = piper_voice_id
        st.session_state.last_commentary_audio_path = str(result.audio_path)
    except PiperTTSError as exc:
        st.warning(f"Piper synthesis failed: {exc}. Falling back to browser speech.")
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        speak_commentary(
            text=text,
            key=f"commentary_{event_id or uuid.uuid4()}",
            voice=settings.voice,
            lang=tts_lang,
            rate=settings.rate,
            pitch=settings.pitch,
            volume=settings.volume,
            voice_profile_id=settings.voice_profile_id,
        )
        st.session_state.last_commentary_engine = "browser"
        st.session_state.last_commentary_voice_id = None
        st.session_state.last_commentary_audio_path = None


def _event_type_to_tt(event_type: str, state: Any) -> TTEventType:
    if event_type in ("point_a", "point_b", "point_scored"):
        return TTEventType.POINT_WON
    if event_type == "undo":
        return TTEventType.POINT_LOST
    if event_type == "serve":
        return TTEventType.SERVE_POINT
    if event_type == "deuce":
        return TTEventType.DEUCE
    if event_type == "advantage":
        return TTEventType.ADVANTAGE
    if event_type == "game_point":
        return TTEventType.GAME_POINT
    if event_type == "match_point":
        return TTEventType.MATCH_POINT
    if event_type == "set_win":
        return TTEventType.GAME_WON
    if event_type == "match_win":
        return TTEventType.MATCH_WON
    if event_type == "manual_score_change":
        return TTEventType.MANUAL_SCORE_CHANGE
    if event_type == "voice_score_confirmed":
        return TTEventType.VOICE_SCORE_CONFIRMED
    if event_type == "voice_score_rejected":
        return TTEventType.VOICE_SCORE_REJECTED
    return TTEventType.POINT_WON


def _build_local_commentary(
    event_type: str,
    state: Any,
    previous_state: Optional[Any],
    settings: Any,
    event_id: str,
) -> CommentaryLine:
    """Generate commentary using the local template engine and wrap it in a CommentaryLine."""
    tt_evt = _event_type_to_tt(event_type, state)
    player_a = getattr(state, "player_a", "Player A")
    player_b = getattr(state, "player_b", "Player B")
    player = player_a
    opponent = player_b
    if event_type in ("point_b",):
        player = player_b
        opponent = player_a

    serving_player = getattr(state, "serving_player", "") or player_a

    evt_data = CommentaryEventData(
        event_type=tt_evt,
        player=player,
        opponent=opponent,
        serving_player=serving_player,
        language=str(settings.language or "en"),
        style=normalize_commentary_style(getattr(settings, "style", CommentaryStyle.NEUTRAL.value)),
        score=f"{getattr(state, 'score_a', 0)} to {getattr(state, 'score_b', 0)}",
        game_score=f"{getattr(state, 'score_a', 0)}–{getattr(state, 'score_b', 0)}",
        match_score=f"{getattr(state, 'sets_a', 0)} to {getattr(state, 'sets_b', 0)}",
    )

    ctx = MatchContextBuilder.from_spoken_score_state(state)
    detail = st.session_state.get("commentary_detail", "standard")
    fast_score_change = False  # could be set externally when rapid scoring is detected

    engine = CommentaryEngine()
    generated = engine.generate_commentary(
        evt_data,
        ctx,
        spoken_enabled=bool(getattr(settings, "enabled", False)),
        fast_score_change=fast_score_change,
        detail=detail,
    )

    text = generated.final_text or generated.text or ""
    should_speak = generated.should_speak
    priority = 2
    if tt_evt in (TTEventType.GAME_WON, TTEventType.MATCH_WON, TTEventType.DEUCE, TTEventType.ADVANTAGE, TTEventType.GAME_POINT, TTEventType.MATCH_POINT):
        priority = 3

    line = CommentaryLine(
        text=text,
        event_type=event_type,
        priority=priority,
        should_speak=should_speak,
        dedupe_key=f"{event_type}:{event_id}",
        event_id=event_id,
        generated_text=generated.generated_text,
        final_text=generated.final_text,
        template_language=generated.language,
        template_style=generated.style,
        base_template=generated.base_template,
        used_fallback=generated.used_fallback,
        fallback_reason=None,
        mixed_language_detected=generated.mixed_language_detected,
        used_ollama=False,
        ollama_rejected_reason=None,
        tts_language_code=generated.tts_language_code,
        cache_key=None,
        cache_hit=False,
        selected_language=evt_data.language,
        normalized_language=generated.language,
        event_id_str=tt_evt.value,
    )
    line._local_commentary = generated
    return line


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

    engine_choice = st.session_state.get("commentary_engine", "legacy")

    if engine_choice == "local":
        line = _build_local_commentary(
            event_type=event_type,
            state=state,
            previous_state=previous_state,
            settings=settings,
            event_id=event_id,
        )
    else:
        moment = _commentary_service.classify_score_moment(spoken_state, prev_spoken)
        settings = _apply_critical_cooldown(settings, moment)

        line = _commentary_service.build_score_commentary(
            event_type=event_type,
            state=spoken_state,
            settings=settings,
            event_id=event_id,
            previous_state=prev_spoken,
        )

    if line.final_text and settings.language != "en":
        tts_lang = "lt-LT" if settings.language == "lt" else "en-US"
        line.tts_language_code = tts_lang

    should_speak = _commentary_service.should_speak_commentary(
        last_event_id=st.session_state.get("last_commentary_event_id"),
        current_event_id=event_id,
        settings=settings,
    )
    if not should_speak and engine_choice == "local":
        # Local engine already encodes speak intent in GeneratedCommentary.should_speak,
        # but we still gate with the legacy dedupe/disabled checks.
        local_line = getattr(line, "_local_commentary", None)
        if local_line is not None:
            should_speak = local_line.should_speak

    if should_speak:
        st.session_state.pending_commentary = line
        st.session_state.last_commentary_event_id = event_id
        st.session_state.last_commentary_text = line.text
        st.session_state.pending_local_audio = None
        st.session_state.last_commentary_debug = {
            "selected_language": getattr(line, "selected_language", settings.language),
            "normalized_language": getattr(line, "normalized_language", settings.language),
            "event_id": getattr(line, "event_id", event_id),
            "event_id_str": getattr(line, "event_id_str", event_type),
            "template_language": getattr(line, "template_language", ""),
            "template_style": getattr(line, "template_style", ""),
            "base_template": getattr(line, "base_template", ""),
            "generated_text": getattr(line, "generated_text", ""),
            "final_text": getattr(line, "final_text", ""),
            "used_fallback": getattr(line, "used_fallback", False),
            "fallback_reason": getattr(line, "fallback_reason", None),
            "mixed_language_detected": getattr(line, "mixed_language_detected", False),
            "used_ollama": getattr(line, "used_ollama", False),
            "ollama_rejected_reason": getattr(line, "ollama_rejected_reason", None),
            "spoken": getattr(line, "should_speak", True),
            "tts_language_code": getattr(line, "tts_language_code", "en-US"),
            "cache_key": getattr(line, "cache_key", None),
            "cache_hit": getattr(line, "cache_hit", False),
        }
    else:
        st.session_state.pending_commentary = None
        st.session_state.pending_local_audio = None


def _emit_set_win_commentary(game_event: dict, *, speak: bool) -> bool:
    """Emit set_win commentary for a finished game with dedupe and mode gating.

    Returns True if commentary was emitted, False otherwise.
    """
    match_id = str(st.session_state.get("voice_selected_match_id") or "none")
    game_number = int(game_event.get("game_number", 1))
    winner = game_event.get("winner", "")
    game_score = game_event.get("game_score", "")
    dedupe_key = f"{match_id}:set_win:{game_number}:{winner}:{game_score}"

    emitted_keys = st.session_state.get("commentary_emitted_game_keys", [])
    if dedupe_key in emitted_keys:
        return False

    settings = _get_commentary_settings()
    if not settings.enabled or settings.muted:
        return False

    engine_choice = st.session_state.get("commentary_engine", "legacy")

    if engine_choice == "local":
        from tournament_platform.app.services.commentary.event_schema import CommentaryEventData, TTEventType
        from tournament_platform.app.services.commentary.match_context import MatchContextBuilder

        player_a = game_event.get("player_a", winner)
        player_b = game_event.get("loser", player_a)
        serving_player = player_a

        evt_data = CommentaryEventData(
            event_type=TTEventType.GAME_WON,
            player=winner,
            opponent=player_b,
            serving_player=serving_player,
            language=str(settings.language or "en"),
            style=normalize_commentary_style(getattr(settings, "style", CommentaryStyle.NEUTRAL.value)),
            game_score=game_score,
            match_score=game_event.get("match_score", ""),
            completed_games=game_event.get("completed_games", []),
        )

        state = st.session_state.match_manager.state
        ctx = MatchContextBuilder.from_spoken_score_state(state)
        if ctx.completed_games:
            ctx.current_game = len(ctx.completed_games) + 1

        detail = st.session_state.get("commentary_detail", "standard")
        engine = CommentaryEngine()
        generated = engine.generate_commentary(
            evt_data,
            ctx,
            spoken_enabled=settings.enabled and not settings.muted,
            detail=detail,
        )

        text = generated.final_text or generated.text or ""
        priority = 3
        should_speak = speak and generated.should_speak

        line = CommentaryLine(
            text=text,
            event_type="set_win",
            priority=priority,
            should_speak=should_speak,
            dedupe_key=dedupe_key,
            event_id=str(uuid.uuid4()),
            generated_text=generated.generated_text,
            final_text=generated.final_text,
            template_language=generated.language,
            template_style=generated.style,
            base_template=generated.base_template,
            used_fallback=generated.used_fallback,
            fallback_reason=None,
            mixed_language_detected=generated.mixed_language_detected,
            used_ollama=False,
            ollama_rejected_reason=None,
            tts_language_code=generated.tts_language_code,
            cache_key=None,
            cache_hit=False,
            selected_language=evt_data.language,
            normalized_language=generated.language,
            event_id_str="game_won",
        )
        line._local_commentary = generated
    else:
        should_gen = _commentary_service.should_generate(
            "set_win",
            ImportanceLevel.CRITICAL,
            settings.mode,
            settings.intensity,
        )
        if not should_gen:
            return False

        line = _commentary_service.build_set_win_commentary(game_event, settings)
        line.should_speak = speak and settings.mode not in (CommentaryMode.OFF, CommentaryMode.VISUAL_ONLY)

    debug_info = {
        "game_number": game_number,
        "winner": winner,
        "loser": game_event.get("loser", ""),
        "game_score": game_score,
        "match_score": game_event.get("match_score", ""),
        "completed_games": game_event.get("completed_games", []),
        "dedupe_key": dedupe_key,
        "event_id": getattr(line, "event_id", ""),
        "event_id_str": getattr(line, "event_id_str", "set_win"),
        "selected_language": getattr(line, "selected_language", settings.language),
        "normalized_language": getattr(line, "normalized_language", ""),
        "template_language": getattr(line, "template_language", ""),
        "template_style": getattr(line, "template_style", ""),
        "base_template": getattr(line, "base_template", ""),
        "generated_text": getattr(line, "generated_text", ""),
        "final_text": getattr(line, "final_text", ""),
        "used_fallback": getattr(line, "used_fallback", False),
        "fallback_reason": getattr(line, "fallback_reason", None),
        "mixed_language_detected": getattr(line, "mixed_language_detected", False),
        "used_ollama": getattr(line, "used_ollama", False),
        "ollama_rejected_reason": getattr(line, "ollama_rejected_reason", None),
        "spoken": getattr(line, "should_speak", True),
        "tts_language_code": getattr(line, "tts_language_code", "en-US"),
        "cache_key": getattr(line, "cache_key", None),
        "cache_hit": getattr(line, "cache_hit", False),
    }

    try:
        from tournament_platform.models import SessionLocal
        db = SessionLocal()
        log_commentary_event(
            db_session=db,
            tournament_id=st.session_state.get("voice_selected_tournament_id"),
            match_id=int(match_id) if match_id != "none" else None,
            player_a=game_event.get("player_a"),
            player_b=game_event.get("player_b"),
            event_type="set_win",
            source_event_json=json.dumps({
                "game_number": game_number,
                "winner": winner,
                "loser": game_event.get("loser", ""),
                "game_score": game_score,
                "match_score": game_event.get("match_score", ""),
                "completed_games": game_event.get("completed_games", []),
                "language": getattr(line, "normalized_language", settings.language),
                "style": getattr(line, "template_style", "neutral"),
                "dedupe_key": dedupe_key,
            }, default=str),
            score_before_json=None,
            score_after_json=None,
            style=getattr(line, "template_style", "neutral") or "neutral",
            language=getattr(line, "normalized_language", "en") or "en",
            commentary_mode=settings.mode.value,
            intensity=settings.intensity.value,
            template_id=getattr(line, "base_template", None),
            generated_text=getattr(line, "generated_text", "") or "",
            final_text=getattr(line, "final_text", "") or "",
            used_ollama=getattr(line, "used_ollama", False),
            ollama_model=getattr(_commentary_service.rewriter, "model", None) if _commentary_service.rewriter else None,
            ollama_cache_hit=getattr(line, "cache_hit", False),
            spoken=getattr(line, "should_speak", True),
            tts_mode="browser",
            latency_ms=None,
            error=None,
            cache_key=getattr(line, "cache_key", None),
        )
    except Exception:
        pass

    st.session_state.pending_commentary = line
    st.session_state.last_commentary_event_id = getattr(line, "event_id", "")
    st.session_state.last_commentary_text = line.text
    st.session_state.last_set_win_text = getattr(line, "final_text", "")
    st.session_state.last_commentary_debug = debug_info
    st.session_state.commentary_emitted_game_keys = emitted_keys + [dedupe_key]
    return True


def _reconcile_finished_games() -> None:
    """Emit set_win commentary for every finished game exactly once per game."""
    _e = st.session_state.match_manager.engine
    games = list(_e.round_scores)
    mid = st.session_state.get("voice_selected_match_id")
    match_id = str(mid) if mid else "none"
    _mm = st.session_state.match_manager

    for i, (a, b) in enumerate(games):
        game_number = i + 1
        winner_label = "A" if a > b else "B"
        winner_name = _mm.state.player_a if winner_label == "A" else _mm.state.player_b
        loser_name = _mm.state.player_b if winner_label == "A" else _mm.state.player_a
        game_score = f"{a}\u2013{b}"
        match_score = f"{_e.games_won_a}\u2013{_e.games_won_b}"
        completed_games = [f"{x}\u2013{y}" for x, y in games]

        _emit_set_win_commentary({
            "event_id": "set_win",
            "game_number": game_number,
            "winner": winner_name,
            "loser": loser_name,
            "game_score": game_score,
            "match_score": match_score,
            "completed_games": completed_games,
            "language": st.session_state.get("commentary_language", "en"),
            "style": normalize_commentary_style(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
            "match_id": match_id,
            "player_a": _mm.state.player_a,
            "player_b": _mm.state.player_b,
        }, speak=True)

    # Emit match_won commentary when the match is complete.
    if _e.match_status == "match_won":
        winner_name = _mm.state.player_a if _e.games_won_a > _e.games_won_b else _mm.state.player_b
        loser_name = _mm.state.player_b if _e.games_won_a > _e.games_won_b else _mm.state.player_a
        match_score = f"{_e.games_won_a}\u2013{_e.games_won_b}"
        completed_games = [f"{x}\u2013{y}" for x, y in games]
        dedupe_key = f"{match_id}:match_won:{winner_name}:{match_score}"

        emitted_keys = st.session_state.get("commentary_emitted_game_keys", [])
        if dedupe_key not in emitted_keys:
            if st.session_state.get("commentary_engine") == "local":
                from tournament_platform.app.services.commentary.event_schema import CommentaryEventData, TTEventType
                from tournament_platform.app.services.commentary.match_context import MatchContextBuilder

                evt_data = CommentaryEventData(
                    event_type=TTEventType.MATCH_WON,
                    player=winner_name,
                    opponent=loser_name,
                    serving_player=winner_name,
                    language=str(st.session_state.get("commentary_language", "en")),
                    style=normalize_commentary_style(st.session_state.get("commentary_style", CommentaryStyle.NEUTRAL.value)),
                    match_score=match_score,
                    completed_games=completed_games,
                )
                state = _mm.state
                ctx = MatchContextBuilder.from_spoken_score_state(state)
                ctx.games_won_a = _e.games_won_a
                ctx.games_won_b = _e.games_won_b
                ctx.completed_games = completed_games

                engine = CommentaryEngine()
                generated = engine.generate_commentary(
                    evt_data,
                    ctx,
                    spoken_enabled=True,
                    detail=st.session_state.get("commentary_detail", "standard"),
                )
                text = generated.final_text or generated.text or ""
                line = CommentaryLine(
                    text=text,
                    event_type="match_won",
                    priority=3,
                    should_speak=True,
                    dedupe_key=dedupe_key,
                    event_id=str(uuid.uuid4()),
                    generated_text=generated.generated_text,
                    final_text=generated.final_text,
                    template_language=generated.language,
                    template_style=generated.style,
                    base_template=generated.base_template,
                    used_fallback=generated.used_fallback,
                    fallback_reason=None,
                    mixed_language_detected=generated.mixed_language_detected,
                    used_ollama=False,
                    ollama_rejected_reason=None,
                    tts_language_code=generated.tts_language_code,
                    cache_key=None,
                    cache_hit=False,
                    selected_language=evt_data.language,
                    normalized_language=generated.language,
                    event_id_str="match_won",
                )
                line._local_commentary = generated
                st.session_state.pending_commentary = line
                st.session_state.last_commentary_event_id = line.event_id
                st.session_state.last_commentary_text = line.text
            st.session_state.commentary_emitted_game_keys = emitted_keys + [dedupe_key]


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
            _current_style = normalize_commentary_style(st.session_state.commentary_style)
            if _current_style not in COMMENTARY_STYLE_OPTIONS:
                _current_style = COMMENTARY_STYLE_OPTIONS[0]
            st.session_state.commentary_style = st.selectbox(
                "Voice style",
                options=COMMENTARY_STYLE_OPTIONS,
                index=COMMENTARY_STYLE_OPTIONS.index(_current_style),
            )
            _engine_options = ["legacy", "local"]
            _engine_labels = {"legacy": "Legacy", "local": "Local template engine"}
            _current_engine = st.session_state.get("commentary_engine", "legacy")
            _engine_idx = _engine_options.index(_current_engine) if _current_engine in _engine_options else 0
            st.session_state.commentary_engine = st.selectbox(
                "Commentary engine",
                options=_engine_options,
                format_func=lambda k: _engine_labels.get(k, k),
                index=_engine_idx,
                help="Choose the commentary generation path. Legacy uses the existing templates; Local uses the new TT template bank.",
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
            _detail_options = ["short", "standard", "tactical"]
            _detail_labels = {"short": "Short", "standard": "Standard", "tactical": "Tactical"}
            _current_detail = st.session_state.get("commentary_detail", "standard")
            _detail_idx = _detail_options.index(_current_detail) if _current_detail in _detail_options else 1
            st.session_state.commentary_detail = st.selectbox(
                "Commentary detail",
                options=_detail_options,
                format_func=lambda k: _detail_labels.get(k, k),
                index=_detail_idx,
                help="Short = minimal output. Standard = normal play-by-play. Tactical = include tactical commentary when available.",
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
                last_engine = st.session_state.get("last_commentary_engine")
                last_voice_id = st.session_state.get("last_commentary_voice_id")
                last_audio_path = st.session_state.get("last_commentary_audio_path")
                if last_text:
                    if last_engine == "piper" and last_audio_path and Path(last_audio_path).exists():
                        speak_commentary_audio_file(Path(last_audio_path), key=f"replay_{uuid.uuid4()}")
                    else:
                        settings = _get_commentary_settings()
                        play_commentary(text=last_text, settings=settings, event_id=str(uuid.uuid4()))
                    st.rerun()

        st.divider()
        st.markdown("**Commentary behavior**")

        _lang_col, _mode_col = st.columns(2)
        with _lang_col:
            _lang_options = {
                "English": "en",
                "Lithuanian": "lt",
            }
            _current_lang = st.session_state.get("commentary_language", "en")
            _normalized_current = CommentaryService._normalize_language(_current_lang)
            _lang_values = list(_lang_options.values())
            _selected_idx = _lang_values.index(_normalized_current) if _normalized_current in _lang_values else 0
            _selected_label = st.selectbox(
                "Commentary language",
                options=list(_lang_options.keys()),
                index=_selected_idx,
                key="commentary_language_select",
            )
            st.session_state.commentary_language = _lang_options[_selected_label]
        with _mode_col:
            _mode_options = [m.value for m in CommentaryMode]
            _mode_labels = {
                "off": "Off",
                "visual_only": "Visual only",
                "important_only": "Important events only",
                "after_every_game": "After every game",
                "every_point": "Every point",
                "spoken": "Spoken commentary",
            }
            _mode_display = [_mode_labels.get(v, v) for v in _mode_options]
            _current_mode = st.session_state.get("commentary_mode", CommentaryMode.EVERY_POINT.value)
            _mode_idx = _mode_options.index(_current_mode) if _current_mode in _mode_options else 0
            _new_mode_label = st.selectbox(
                "Mode",
                options=_mode_display,
                index=_mode_idx,
                key="commentary_mode_select",
            )
            _new_mode = _mode_options[_mode_display.index(_new_mode_label)]
            if _new_mode != _current_mode:
                st.session_state.commentary_mode = _new_mode
                st.rerun()

        _int_col, _speak_col = st.columns(2)
        with _int_col:
            _int_options = [i.value for i in CommentaryIntensity]
            _current_int = st.session_state.get("commentary_intensity", CommentaryIntensity.MEDIUM.value)
            _int_idx = _int_options.index(_current_int) if _current_int in _int_options else 1
            st.session_state.commentary_intensity = st.selectbox(
                "Intensity",
                options=_int_options,
                index=_int_idx,
                key="commentary_intensity_select",
            )
        with _speak_col:
            st.session_state.commentary_speak_generated = st.checkbox(
                "Speak generated commentary",
                value=st.session_state.get("commentary_speak_generated", True),
                key="commentary_speak_generated_checkbox",
            )

        with st.expander("🎙️ Voice profile", expanded=False):
            from tournament_platform.app.services.commentary_voice.voice_catalog import profile_choices
            from tournament_platform.app.services.commentary_voice.voice_settings import init_voice_session_state

            init_voice_session_state()

            _profile_choices = profile_choices()
            _profile_ids = [c[0] for c in _profile_choices]
            _profile_labels = [c[1] for c in _profile_choices]
            _current_profile = st.session_state.get("commentary_voice_profile", "browser_default")
            _profile_idx = _profile_ids.index(_current_profile) if _current_profile in _profile_ids else 0
            _new_profile_id = st.selectbox(
                "Profile",
                options=_profile_ids,
                format_func=lambda pid: next((c[1] for c in _profile_choices if c[0] == pid), pid),
                index=_profile_idx,
                key="commentary_voice_profile_select",
            )
            st.session_state.commentary_voice_profile = _new_profile_id

            _profile_sync_applied = False
            # Only sync when the profile *selection actually changed* (tracked
            # via commentary_voice_profile_applied). This avoids an unconditional
            # st.rerun() every render that would fight the user's style choice
            # and could make the page appear frozen.
            _applied_profile = st.session_state.get("commentary_voice_profile_applied")
            if _new_profile_id != _applied_profile:
                if _new_profile_id == "sport_commentator":
                    st.session_state.commentary_style = CommentaryStyle.ANNOUNCER.value
                    st.session_state.commentary_intensity = CommentaryIntensity.MEDIUM.value
                    _profile_sync_applied = True
                elif _new_profile_id == "coach":
                    st.session_state.commentary_style = CommentaryStyle.COACH.value
                    _profile_sync_applied = True
                elif _new_profile_id in ("lt_browser_default",):
                    st.session_state.commentary_language = "lt"
                    _profile_sync_applied = True
                elif _new_profile_id in ("en_browser_default",):
                    st.session_state.commentary_language = "en"
                    _profile_sync_applied = True
                if _profile_sync_applied:
                    st.session_state.commentary_voice_profile_applied = _new_profile_id

            if _profile_sync_applied:
                st.rerun()

            _rate_col, _pitch_col = st.columns(2)
            with _rate_col:
                st.session_state.commentary_rate = st.slider(
                    "Rate",
                    min_value=0.5,
                    max_value=2.0,
                    step=0.05,
                    value=float(st.session_state.get("commentary_rate", 1.0)),
                    key="commentary_rate_slider",
                )
            with _pitch_col:
                st.session_state.commentary_pitch = st.slider(
                    "Pitch",
                    min_value=0.5,
                    max_value=2.0,
                    step=0.05,
                    value=float(st.session_state.get("commentary_pitch", 1.0)),
                    key="commentary_pitch_slider",
                )
            st.session_state.commentary_volume = st.slider(
                "Volume",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                value=float(st.session_state.get("commentary_volume", 1.0)),
                key="commentary_volume_slider",
            )
            if st.button("🔊 Test voice", use_container_width=True, key="test_voice_button"):
                settings = _get_commentary_settings()
                play_commentary(
                    text="Game point for Red. 10 to 8.",
                    settings=settings,
                    event_id=str(uuid.uuid4()),
                )

        with st.expander("🔧 Advanced spoken commentary", expanded=False):
            _piper_ok = is_piper_available()
            _engine_options = ["browser", "piper"]
            _engine_labels = {
                "browser": "Browser speech",
                "piper": "Piper local voices" + ("" if _piper_ok else " (unavailable)"),
            }
            _current_engine = st.session_state.get("commentary_tts_engine", "browser")
            _engine_idx = _engine_options.index(_current_engine) if _current_engine in _engine_options else 0
            _new_engine = st.selectbox(
                "TTS engine",
                options=_engine_options,
                format_func=lambda e: _engine_labels.get(e, e),
                index=_engine_idx,
                key="commentary_tts_engine_select",
                help=(
                    "Browser speech is recommended for Streamlit Cloud. "
                    "Piper local is optional for local desktop use."
                ),
            )
            st.session_state.commentary_tts_engine = _new_engine

            if _new_engine == "piper":
                if not _piper_ok:
                    st.info(
                        "Piper local TTS is not available in this environment. "
                        "Browser speech is available as a fallback."
                    )
                else:
                    piper_voices = find_piper_voices()
                    if not piper_voices:
                        st.info(
                            "No Piper voices found. Add `.onnx` and `.onnx.json` files to "
                            "`tournament_platform/assets/tts/piper/voices/` to enable local voices."
                        )
                    else:
                        _piper_voice_options = [v.id for v in piper_voices]
                        _piper_voice_labels = {v.id: v.label for v in piper_voices}
                        _current_piper_voice = st.session_state.get("commentary_piper_voice_id")
                        _pv_idx = _piper_voice_options.index(_current_piper_voice) if _current_piper_voice in _piper_voice_options else 0
                        _new_pv = st.selectbox(
                            "Piper voice",
                            options=_piper_voice_options,
                            format_func=lambda vid: _piper_voice_labels.get(vid, vid),
                            index=_pv_idx,
                            key="commentary_piper_voice_select",
                        )
                        st.session_state.commentary_piper_voice_id = _new_pv

                        _speed_col, _vol_col = st.columns(2)
                        with _speed_col:
                            st.session_state.commentary_rate = st.slider(
                                "Piper speed",
                                min_value=0.8,
                                max_value=1.2,
                                step=0.05,
                                value=float(st.session_state.get("commentary_rate", 1.0)),
                                key="piper_rate_slider",
                            )
                        with _vol_col:
                            st.session_state.commentary_volume = st.slider(
                                "Piper volume",
                                min_value=0.0,
                                max_value=1.0,
                                step=0.05,
                                value=float(st.session_state.get("commentary_volume", 1.0)),
                                key="piper_volume_slider",
                            )
                        if st.button("🔊 Test Piper voice", use_container_width=True, key="test_piper_voice_button"):
                            settings = _get_commentary_settings()
                            play_commentary(
                                text="Game point for Red. 10 to 8.",
                                settings=settings,
                                event_id=str(uuid.uuid4()),
                            )

        with st.expander("🤖 Local Ollama rewrite", expanded=False):
            st.session_state.commentary_ollama_rewrite_enabled = st.checkbox(
                "Use local Ollama to rewrite commentary",
                value=st.session_state.get("commentary_ollama_rewrite_enabled", False),
                key="commentary_ollama_rewrite_checkbox",
                help="Requires Ollama running locally. Disabled by default.",
            )
            if st.session_state.commentary_ollama_rewrite_enabled:
                _default_model = st.session_state.get("commentary_ollama_model", "") or "llama3:latest"
                st.session_state.commentary_ollama_model = st.text_input(
                    "Ollama model",
                    value=_default_model,
                    key="commentary_ollama_model_input",
                )
                st.session_state.commentary_ollama_timeout = st.number_input(
                    "Timeout (seconds)",
                    min_value=0.5,
                    max_value=10.0,
                    step=0.5,
                    value=float(st.session_state.get("commentary_ollama_timeout", 2.0)),
                    key="commentary_ollama_timeout_input",
                )

        # --- Audio diagnostics (collapsed by default) ---
        with st.expander("🩺 Audio diagnostics", expanded=False):
            ensure_webrtc_diag_state()
            _diag_webrtc = (
                "installed" if st.session_state.get("webrtc_diag_available") else "missing"
            )
            _diag_piper = "available" if _piper_ok else "missing"
            _diag_engine = st.session_state.get("commentary_tts_engine", "browser")
            _diag_voice_input = (
                "live microphone" if st.session_state.get("voice_scoring_enabled")
                else "push-to-talk"
            )
            _diag_browser_fallback = (
                "enabled" if _diag_engine in ("browser", "auto") or not _piper_ok
                else "disabled"
            )
            st.markdown(
                "- streamlit-webrtc: **%s**\n"
                "- Piper local: **%s**\n"
                "- selected TTS mode: **%s**\n"
                "- selected voice input mode: **%s**\n"
                "- browser speech fallback: **%s**"
                % (
                    _diag_webrtc,
                    _diag_piper,
                    _diag_engine,
                    _diag_voice_input,
                    _diag_browser_fallback,
                )
            )

        # --- Audio controls (moved from Live Scoreboard, Phase 6 / TTS Phase 4) ---
        st.divider()
        st.markdown("**Audio & spoken announcements**")

        # Sound cues toggle (writes the per-session preference).
        render_sound_toggle()

        # TTS mode selector — friendly labels, internal enum value stored.
        _tts = st.session_state.voice_tts_adapter
        _tts_mode_values, _tts_options = tts_mode_options()
        _tts_idx = _tts_mode_values.index(_tts.mode.value) if _tts.mode.value in _tts_mode_values else 0
        _new_tts_label = st.selectbox(
            "🔊 TTS mode",
            options=_tts_options,
            index=_tts_idx,
            key="tts_mode_select",
            help="Spoken score announcements (e.g. 'Tomas Z leads 5 to 3'). Choose how often the scoreboard speaks.",
        )
        _new_tts_mode = _tts_mode_values[_tts_options.index(_new_tts_label)]
        if _new_tts_mode != _tts.mode.value:
            apply_tts_selection(_tts, _new_tts_mode)
            st.rerun()

        st.divider()

        # Test sound — must NOT mutate match state or the DB.
        if st.button("🔊 Test sound", key="audio_test_sound", use_container_width=True):
            if st.session_state.get("sound_cues_enabled", False):
                play_cue("point")
            if _tts.enabled and _tts.mode not in (TTSMode.OFF, TTSMode.VISUAL_ONLY):
                _maybe_speak_tts(build_test_tts_message(st.session_state.match_manager), "increment")

        # Activation hint: browsers may block audio until first interaction.
        st.caption(
            "If nothing plays, click once or interact with the scoreboard — "
            "browsers may block audio until your first click. Ensure the tab isn't muted."
        )

        # Informative note when all audio is off.
        if not st.session_state.get("sound_cues_enabled", False) and not _tts.enabled:
            st.info("Audio is off. Scores still update as text.")


def render_pending_commentary() -> None:
    """Render the pending commentary line (speech + text preview) and clear it."""
    pending = st.session_state.get("pending_commentary")
    if not pending:
        st.session_state.pending_local_audio = None
        return

    settings = _get_commentary_settings()
    if settings.enabled and not settings.muted and pending.should_speak:
        play_commentary(
            text=pending.text,
            settings=settings,
            event_id=pending.event_id,
        )

    if pending.text:
        st.caption(f"🔊 {pending.text}")

    st.session_state.pending_commentary = None
    st.session_state.pending_local_audio = None


def render_commentary_debug() -> None:
    """Render the commentary debug panel."""
    debug = st.session_state.get("last_commentary_debug")
    if not debug:
        return
    with st.expander("🐛 Commentary debug", expanded=False):
        for k, v in debug.items():
            st.caption(f"**{k}**: `{v}`")


def render_commentary_log() -> None:
    """Show recent commentary events."""
    _match_id = st.session_state.get("voice_selected_match_id")
    try:
        from tournament_platform.services.commentary_service import get_recent_commentary_events
        events = get_recent_commentary_events(_match_id, limit=20) if _match_id else []
    except Exception:
        events = []
    if not events:
        st.caption("No commentary events yet.")
        return
    st.markdown("**Recent commentary**")
    for ev in events:
        st.caption(
            f"[{ev.created_at.strftime('%H:%M:%S') if ev.created_at else '--'}] "
            f"{ev.event_type}: {ev.final_text or ev.generated_text or ''}"
        )


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
            ctx.get("processor")
            or ctx.get("audio_processor")
            or ctx.get("voice_processor")
        )

    for attr_name in ("processor", "audio_processor", "voice_processor"):
        processor = getattr(ctx, attr_name, None)
        if processor is not None:
            return processor

    return None


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


def _render_match_diagnostics(tournament_id: int, status_filter: List[str], matches: List[Dict]) -> None:
    """Render a collapsed diagnostics expander for match-loading verification."""
    with st.expander("🔍 Match loading diagnostics", expanded=False):
        db = SessionLocal()
        try:
            tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
            t_name = tournament.name if tournament else None
            player_count = db.query(Player).count()
            generated = list(tournament.matches) if tournament else []
            generated_count = len(generated)
            repo_matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
            repo_count = len(repo_matches)
            statuses_found = sorted({_normalize_status(m.status.value) for m in repo_matches})
        except Exception as e:
            t_name = None
            player_count = 0
            generated_count = 0
            repo_count = 0
            statuses_found = [f"error: {e}"]
        finally:
            db.close()

        st.write(f"- selected tournament ID: `{tournament_id}`")
        st.write(f"- selected tournament name: `{t_name}`")
        st.write(f"- number of players: `{player_count}`")
        st.write(f"- number of generated matches (Tournament page source): `{generated_count}`")
        st.write(f"- number of DB/repository matches: `{repo_count}`")
        st.write(f"- number of pending/active matches after filter: `{len(matches)}`")
        st.write(f"- statuses found: `{statuses_found}`")
        st.write(f"- status filter applied: `{status_filter}`")


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
        # Manual player selection (rendered later on the page) is the fallback
        # path, but only when the tournament has at least 2 registered players.
        _players = get_all_players()
        if len(_players) >= 2:
            st.info(
                "No scheduled matches yet. Select two players below to start a "
                "manual match."
            )
        else:
            st.info("No active or pending matches found for this tournament.")
        _render_match_diagnostics(tournament_id, status_filter, matches)
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

    _render_match_diagnostics(tournament_id, status_filter, matches)


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

from tournament_platform.app.components.page_header import render_page_header

def _render_ui() -> None:
    render_page_header(
        title="Voice Scorekeeper",
        icon_name="voice_scorekeeper",
    )
    if get_script_run_ctx() is not None:
        render_tour("voice_scorekeeper")
        apply_global_styles()
        st.caption("Speak to update scores. The system uses local transcription - no data leaves your machine.")
    
        # Commentary Settings
        render_commentary_settings()
        with st.expander("📋 Commentary log", expanded=False):
            render_commentary_log()
        render_commentary_debug()
    
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
                prev_state = copy.deepcopy(st.session_state.match_manager.state)
                success, msg = st.session_state.match_manager._add_point("A")
                st.session_state.last_feedback = msg
                st.toast(msg, icon="✅")
                play_cue("point")
                _maybe_speak_tts(msg, "increment")
                _build_and_store_commentary("point_a", st.session_state.match_manager.state, prev_state)
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
                st.rerun()
        with _cor2:
            if st.button("↩️ Undo Game", key="undo_game_center", use_container_width=True):
                if st.session_state.match_manager.engine.round_scores:
                    success, msg = st.session_state.match_manager.undo_last_completed_game()
                    st.session_state.last_feedback = msg
                    st.toast(msg, icon="↩️")
                    play_cue("undo")
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
        # Detect transition: ON→OFF clears all pending voice state
        _curr_enabled = st.session_state.voice_scoring_enabled
        if _prev_enabled and not _curr_enabled:
            disable_voice_scoring_and_clear_pending_state("voice_toggle_off")
            st.toast("🎤 Voice scoring disabled — all pending voice commands cleared.", icon="ℹ️")
        elif not _prev_enabled and _curr_enabled:
            _increment_voice_session_epoch()
            st.toast("🎤 Voice scoring enabled — new session started.", icon="✅")
    with col_status:
        if st.session_state.voice_scoring_enabled:
            if st.session_state.voice_listening:
                st.markdown("🟢 **Listening**")
            else:
                st.markdown("🟡 **Ready**")
        else:
            st.markdown("⚪ **Disabled**")
    
        # Noise robustness & calibration (Phase 5)
        with st.expander("🎚️ Noise Robustness & Calibration", expanded=False):
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
    
    if st.session_state.voice_scoring_enabled:
        st.markdown("**Push-to-Talk** (recommended)")
        st.caption("Click the microphone, speak your command, and release to send.")
    
        # Continuous listening is optional and experimental.
        with st.expander("🔬 Experimental: Continuous Listening", expanded=False):
            st.caption(
                "Uses streamlit-webrtc for hands-free continuous voice capture. "
                "This mode is experimental and may miss commands in noisy environments. "
                "Push-to-talk remains the default reliable mode."
            )
            # Safely reflect WebRTC availability (computed once at import).
            ensure_webrtc_diag_state()
            webrtc_available = WEBRTC_AVAILABLE

            if not webrtc_available:
                # Show a friendly, once-per-session notice inside the voice
                # settings area only. Never warn globally or on every rerun.
                if not st.session_state.get("shown_webrtc_missing_warning"):
                    st.info(
                        "Live microphone mode is unavailable because "
                        "`streamlit-webrtc` is not installed. Manual scoring and "
                        "browser speech still work."
                    )
                    st.session_state.shown_webrtc_missing_warning = True
                st.caption("You can still use the push-to-talk voice input below.")
            else:
                # Start/Stop listening controls
                col_start, col_stop = st.columns(2)
                with col_start:
                    if st.button("🎙️ Start Listening", type="primary", use_container_width=True):
                        if not st.session_state.voice_listening:
                            st.session_state.voice_listening = True
                            st.session_state.voice_event_log = []
                            st.session_state.last_voice_transcript = ""
                            st.session_state.last_voice_event = None
                            st.session_state.last_voice_feedback = ""
                            st.session_state.voice_asr_status = None
                            st.rerun()
                with col_stop:
                    if st.button("⏹️ Stop Listening", use_container_width=True):
                        if st.session_state.voice_listening:
                            st.session_state.voice_listening = False
                            ctx = st.session_state.get("voice_webrtc_ctx")
                            if ctx and ctx.get("processor"):
                                ctx["processor"].stop()
                            st.rerun()
    
                if st.session_state.voice_listening:
                    st.caption("Listening for score commands... Speak clearly into your microphone.")
    
                    # Initialize ASR status on first listen
                    if st.session_state.voice_asr_status is None:
                        try:
                            st.session_state.voice_asr_status = ASRBackendFactory.backend_status()
                        except Exception as e:
                            st.session_state.voice_asr_status = {"available": False, "load_error": str(e)}
    
                    # Show ASR status
                    asr_status = _normalize_status_dict(st.session_state.voice_asr_status)
                    if not asr_status.get("available", False):
                        error_msg = asr_status.get("reason") or asr_status.get("load_error") or "Unknown error"
                        if is_running_on_streamlit_cloud():
                            logger.warning("ASR unavailable: %s", error_msg)
                            st.warning(
                                "Cloud ASR is not configured. Manual scoring is still available."
                            )
                        else:
                            st.error(f"⚠️ Local ASR not available: {error_msg}")
                            st.caption("Voice scoring requires faster-whisper. Install with: `pip install faster-whisper`")
                        st.session_state.voice_listening = False
                        st.rerun()
    
                    # WebRTC streamer
                    from streamlit_webrtc import webrtc_streamer, WebRtcMode
    
                    # Stable processor factory — defined once per session, not recreated on rerun.
                    if "voice_webrtc_processor_factory" not in st.session_state:
                        _filtering = st.session_state.get("voice_noise_filtering", False)
                        _threshold = st.session_state.get("voice_noise_threshold", 0.0)
                        _strict = st.session_state.get("voice_strict_mode", False)
                        _vad = create_vad()
                        def _make_processor():
                            return VoiceAudioProcessor(
                                noise_gate_rms=_threshold if _filtering else 0.01,
                                sample_format=SAMPLE_FORMAT_FLOAT32,
                                voice_strict_mode=_strict,
                                vad=_vad,
                            )
                        st.session_state.voice_webrtc_processor_factory = _make_processor
    
                    ctx = webrtc_streamer(
                        key="voice-scorekeeper-webrtc",
                        mode=WebRtcMode.SENDONLY,
                        audio_processor_factory=st.session_state.voice_webrtc_processor_factory,
                        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
                        media_stream_constraints={"audio": True, "video": False},
                        async_processing=True,
                    )
    
                    logger.info(
                        "WebRTC ctx: state=%s, audio_processor=%s",
                        ctx.state if ctx else "None",
                        "yes" if ctx and ctx.audio_processor else "no",
                    )
    
                    # Store processor reference in session state
                    if ctx and ctx.audio_processor:
                        if st.session_state.voice_webrtc_ctx is None:
                            st.session_state.voice_webrtc_ctx = {}
                        st.session_state.voice_webrtc_ctx["processor"] = ctx.audio_processor
                        logger.info("Stored audio processor in session state")
                    else:
                        logger.debug("No audio processor available yet (ctx=%s)", "present" if ctx else "None")
    
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
                    
                    # Voice diagnostics
                    with st.expander("🩺 Voice diagnostics", expanded=False):
                        _hf_token = get_hf_token()
                        _hf_configured = "yes" if _hf_token else "no"
                        _asr_status = _normalize_status_dict(
                            st.session_state.get("voice_asr_status"),
                            default_reason="ASR status unavailable",
                        )
                        _asr_loaded = "yes" if bool(_asr_status.get("available", False)) else "no"
                        _webrtc_ctx = st.session_state.get("voice_webrtc_ctx")
                        proc = _get_voice_webrtc_processor(_webrtc_ctx)

                        _q_size = _safe_queue_size(getattr(proc, "_chunk_queue", None)) if proc else 0
                        _dropped = int(getattr(proc, "_dropped_chunks", 0) or 0) if proc else 0
                        _evt_q = _safe_queue_size(getattr(proc, "event_queue", None)) if proc else 0
                        _last_rms = st.session_state.get("voice_last_chunk_rms", 0.0)
                        _seg_ms = getattr(proc.audio_buffer, 'get_buffer_duration_ms', lambda: 0.0)() if proc else 0.0
                        _last_transcript = st.session_state.get("last_voice_transcript", "")
                        _last_accepted = st.session_state.get("voice_last_applied_event_key")
                        _last_rejected_reason = st.session_state.get("last_voice_feedback", "")
                        st.markdown(
                            "- WebRTC installed: **%s**\n"
                            "- voice scoring enabled: **%s**\n"
                            "- HF_TOKEN configured: **%s**\n"
                            "- ASR model loaded: **%s**\n"
                            "- audio queue size: **%d**\n"
                            "- event queue size: **%d**\n"
                            "- dropped audio frames: **%d**\n"
                            "- VAD RMS latest: **%.4f**\n"
                            "- current speech segment duration: **%.1f ms**\n"
                            "- last transcript: **%s**\n"
                            "- last accepted command: **%s**\n"
                            "- last rejected command reason: **%s**"
                            % (
                                "yes" if WEBRTC_AVAILABLE else "no",
                                "yes" if st.session_state.get("voice_scoring_enabled") else "no",
                                _hf_configured,
                                _asr_loaded,
                                _q_size,
                                _evt_q,
                                _dropped,
                                _last_rms,
                                _seg_ms,
                                _last_transcript or "—",
                                _last_accepted or "—",
                                _last_rejected_reason or "—",
                            )
                        )

                    # Runtime / Ollama bridge diagnostics
                    try:
                        from tournament_platform.app.components.runtime_diagnostics import render_runtime_diagnostics

                        render_runtime_diagnostics()
                    except Exception:
                        pass

                # Confidence indicator
                if st.session_state.last_voice_event:
                    _conf = getattr(st.session_state.last_voice_event, "confidence", 0.0)
                    _conf_pct = int(_conf * 100)
                    _color = "🔴" if _conf_pct < 50 else ("🟡" if _conf_pct < 80 else "🟢")
                    st.progress(_conf, text=f"{_color} Confidence: {_conf_pct:.0f}%")
    
                # Debug expander
                with st.expander("🔍 Voice Debug", expanded=False):
                    st.markdown("**Recent Voice Events**")
                    if st.session_state.voice_event_log:
                        for entry in st.session_state.voice_event_log[-10:]:
                            st.json(entry)
                    else:
                        st.caption("No events yet.")
                    
                    st.markdown("**ASR Status**")
                    if st.session_state.voice_asr_status:
                        status_display = _normalize_status_dict(st.session_state.voice_asr_status)
                        st.json(status_display)
                    else:
                        st.caption("ASR not initialized.")
                    
                    if st.button("Clear Event Log", key="clear_voice_log"):
                        st.session_state.voice_event_log = []
                        st.rerun()
    
            # Confirmation / cancel panel (always visible when voice scoring is enabled)
            if st.session_state.voice_scoring_enabled:
                _render_confirm_panel()
    
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
                                _debug_result = _process_voice_transcript(
                                    _debug_transcript.strip(),
                                    source="debug",
                                )
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
                    "Structured audit log for voice scoring events. "
                    "Gated by VOICE_DEBUG_EVENTS; exportable per match."
                )
                event_logger = st.session_state.get("voice_event_logger")
                if event_logger is None:
                    st.caption("Event logger not initialized.")
                else:
                    recent_events = event_logger.recent(limit=50)
                    if recent_events:
                        st.markdown(f"**Recent events (showing {len(recent_events)} of {len(event_logger._events)} retained)**")
                        for i, entry in enumerate(reversed(recent_events), 1):
                            status_icon = "✅" if entry.get("accepted") else "❌"
                            note = entry.get("note", "")
                            st.markdown(
                                f"{status_icon} **{entry.get('event_type', '?')}** "
                                f"`{entry.get('previous_score', '?')}` → `{entry.get('new_score', '?')}` "
                                f"| conf: {entry.get('confidence', 0):.0%} "
                                f"| speaker: {entry.get('speaker_label', '—')} "
                                f"| {note}"
                            )
                            with st.popover("Details"):
                                st.json(entry)
                    else:
                        st.caption("No events recorded yet. Enable VOICE_DEBUG_EVENTS to start logging.")
        
                        col_export, col_clear, col_info = st.columns(3)
                        with col_export:
                            if st.button("📥 Export Audit Log (JSON)", key="export_audit_log"):
                                import json
                                from datetime import datetime
                                export_data = event_logger.export()
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
                                logger.clear()
                                st.success("Audit log cleared.")
                                st.rerun()
                        with col_info:
                            st.caption(f"Retention: {VOICE_RETENTION_DAYS} days (0 = delete immediately)")
    
    # ============================================================================
    # Process voice events BEFORE rendering scoreboard (drain queue early)
    # ============================================================================
    # Drain pending continuous voice events BEFORE rendering the live scoreboard.
    # This ensures accepted commands from background audio callbacks are applied
    # and reflected in the UI on the same render cycle.
    _process_voice_events()
    
    # ============================================================================
    # Voice Input Section
    # ============================================================================
    
    st.divider()
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
        _labels = [o["label"] for o in _options]
        _selected_label = st.selectbox("Analyze completed match", _labels, key="match_analytics_select")
        _selected_idx = _labels.index(_selected_label)
        _selected = _options[_selected_idx]

        _sel_id = _selected["id"]
        _sel_source = _selected["source"]
        _sel_p1 = _selected["player_a_name"]
        _sel_p2 = _selected["player_b_name"]

        if _sel_source == "database":
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

    # Announcements toggle
    st.divider()
    st.subheader("📢 Announcements")
    _ann_enabled = st.toggle("Enable automatic announcements", value=False, key="voice_announcements_toggle")
    if _ann_enabled:
        st.caption("Automatic match/game announcements are enabled.")
    
    _maybe_voice_rerun()
    
    # Continuous listening heartbeat: ensures accepted voice commands from background
    # audio callbacks are drained and reflected on the scoreboard without manual refresh.
    # Runs in the main Streamlit thread only; never from WebRTC/audio callbacks.
    _maybe_voice_heartbeat()
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
    - Speak clearly and at a normal pace
    - The system works best in a quiet environment
    - Use the +/− buttons for quick manual corrections
    - Duplicate voice commands within 1.2 seconds are automatically suppressed
    """)

if get_script_run_ctx() is not None:
    _render_ui()
