"""
Voice-Activated Tournament Scorekeeper

A privacy-focused scorekeeping system using:
- streamlit-webrtc for continuous microphone capture
- faster-whisper for local transcription
- VoiceParser for structured intent parsing
- Manual scoring always available
"""

import streamlit as st

import asyncio
import os
import copy
import uuid
import threading
import queue
import logging
import time
from typing import Any, Optional, Tuple, Dict, List
from dataclasses import is_dataclass, asdict

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
# Import game-by-game scoring utilities
from tournament_platform.app.services.match_score import (
    parse_game_score,
    validate_game_score,
    summarize_match,
)
from tournament_platform.app.services.score_engine import is_deuce, get_serving_player
from tournament_platform.app.services.ui_feedback import play_cue, render_sound_toggle
from tournament_platform.app.services.voice_speaker import SpeakerTagger, DEFAULT_SPEAKERS
from tournament_platform.app.services.voice_tts import TTSConfirmationAdapter, TTSMode
# Import voice scoring modules
from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.app.services.voice.commands import VoiceIntent, parse as parse_command, cheat_sheet as command_cheat_sheet
from tournament_platform.app.services.voice.confirmation import policy_decision
from tournament_platform.app.services.voice.vad import VoiceActivityDetector, create_vad
from tournament_platform.app.services.voice.dataset_recorder import VoiceDatasetRecorder, VoiceDatasetSample
from tournament_platform.app.services.voice_audio import VoiceAudioBuffer, AudioChunk
from tournament_platform.app.services.voice_asr import LocalASR, LocalASRError
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice_audit import EventLogger
from tournament_platform.app.services.voice_noise import NoiseFilter, NoiseProfiler
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

# Duplicate-command cooldown (Phase 4 / PingScore port).
# Ignore identical (type, player, score_a, score_b) events within COOLDOWN_MS.
if 'voice_last_applied_event_key' not in st.session_state:
    st.session_state.voice_last_applied_event_key = None
if 'voice_last_applied_event_ts' not in st.session_state:
    st.session_state.voice_last_applied_event_ts = 0.0

# Confirmation panel state (Phase 1)
if 'pending_confirmations' not in st.session_state:
    st.session_state.pending_confirmations = []

# Dataset recorder state (Phase 4)
if 'voice_dataset_recorder' not in st.session_state:
    st.session_state.voice_dataset_recorder = VoiceDatasetRecorder(enabled=VOICE_DATASET_OPT_IN)
if 'voice_dataset_samples' not in st.session_state:
    st.session_state.voice_dataset_samples = []

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
        self.asr = ASRBackendFactory.create(vocabulary=self.vocabulary)
        self.parser = VoiceParser()
        self.post_processor = TranscriptPostProcessor(self.vocabulary)
        self.event_queue: queue.Queue = queue.Queue()
        self._processing = False
        self._lock = threading.Lock()
        # Configuration passed from main thread (not read from session state
        # here to keep __init__ safe for any calling thread).
        self._voice_strict_mode = voice_strict_mode
        # Single worker thread for all chunks (avoids thread explosion)
        self._worker_thread: Optional[threading.Thread] = None
        self._chunk_queue: queue.Queue = queue.Queue()
        self._stop_worker = threading.Event()

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
        
        # Detect format from frame and update buffer accordingly
        fmt_name = getattr(getattr(frame, 'format', None), 'name', None)
        sample_rate = getattr(frame, 'sample_rate', None)
        channels = getattr(frame, 'channels', None)
        
        detected_format = None
        if fmt_name in ('s16', 's16p'):
            detected_format = SAMPLE_FORMAT_INT16
        elif fmt_name in ('flt', 'fltp', 'f32', 'f32p'):
            detected_format = SAMPLE_FORMAT_FLOAT32
        
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
                    self._sample_format = fallback_format
                    if self.audio_buffer.sample_format != self._sample_format:
                        self.audio_buffer.update_format(sample_format=self._sample_format)
            except Exception:
                pass

        frame_bytes = frame.to_ndarray().tobytes()
        chunk = self.audio_buffer.push_frame(frame_bytes)

        if chunk is not None:
            logger.info(
                "VoiceAudioProcessor: emitted chunk %.1f ms, RMS=%.4f, frames=%d",
                chunk.duration_ms, chunk.rms, len(chunk.frames),
            )
            # Ensure worker is running and queue the chunk
            self._start_worker()
            self._chunk_queue.put(chunk)

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

            # Measure ASR latency for observability (Phase 1/5).
            start = time.time()
            raw_text = self.asr.transcribe_pcm(pcm_bytes)
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
            self.event_queue.put((raw_text, text, event))
            logger.info("Voice event queued: type=%s, text='%s'", event.type, text)

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

    processed = TranscriptPostProcessor(VoiceVocabulary.load()).process(raw_text)
    score_a = st.session_state.match_manager.state.score_a
    score_b = st.session_state.match_manager.state.score_b
    event = VoiceParser().parse(processed, current_score_a=score_a, current_score_b=score_b)
    event.source = "asr_push_to_talk"

    if VOICE_DATASET_OPT_IN:
        try:
            recorder = st.session_state.get("voice_dataset_recorder")
            if recorder is not None:
                recorder.record(
                    transcript=processed,
                    parsed_intent=event.type,
                    expected_intent=event.type if event.type != "unknown" else None,
                    match_id=st.session_state.get("voice_selected_match_id"),
                    match_context={
                        "score_before": f"{score_a}-{score_b}",
                        "score_after": _predict_score_after(
                            VoiceParseResult(
                                intent=parse_command(processed, score_a, score_b).intent,
                                slots=parse_command(processed, score_a, score_b).slots,
                            )
                        ) if event.type != "unknown" else f"{score_a}-{score_b}",
                        "confidence": event.confidence,
                    },
                    mic_type="push_to_talk",
                    noise_condition="unknown",
                )
        except Exception as exc:
            logger.debug("Push-to-talk dataset record skipped: %s", exc)

    return event


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


def _render_confirm_panel() -> None:
    pending = st.session_state.get("pending_confirmations", [])
    if not pending:
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
                    st.session_state.pending_confirmations.pop(idx)
                    st.session_state.last_voice_feedback = "Cancelled"
                    st.rerun()


def _apply_pending(idx: int) -> None:
    item = st.session_state.pending_confirmations.pop(idx)
    intent_str = item.get("intent", "unknown")
    slots = item.get("slots", {})
    raw = item.get("raw_transcript", "")
    source = item.get("source", "asr")
    confidence = item.get("confidence", 0.0)
    event_id = item.get("event_id", str(uuid.uuid4()))

    if intent_str == VoiceIntent.SCORE_POINT.value:
        event_type = "increment"
        player = slots.get("player")
    elif intent_str == VoiceIntent.SET_SCORE.value:
        event_type = "set_score"
        player = None
    elif intent_str == VoiceIntent.UNDO.value:
        event_type = "undo"
        player = None
    elif intent_str == VoiceIntent.START_MATCH.value:
        event_type = "start_match"
        player = None
    elif intent_str == VoiceIntent.PAUSE_MATCH.value:
        event_type = "pause_match"
        player = None
    elif intent_str == VoiceIntent.RESUME_MATCH.value:
        event_type = "resume_match"
        player = None
    elif intent_str == VoiceIntent.START_NEXT_GAME.value:
        event_type = "start_next_game"
        player = None
    elif intent_str == VoiceIntent.END_GAME.value:
        event_type = "end_game"
        player = None
    elif intent_str == VoiceIntent.TIMEOUT_START.value:
        event_type = "timeout_start"
        player = None
    elif intent_str == VoiceIntent.TIMEOUT_END.value:
        event_type = "timeout_end"
        player = None
    elif intent_str == VoiceIntent.SET_SERVER.value:
        event_type = "set_server"
        player = slots.get("player")
    elif intent_str == VoiceIntent.REPEAT_SCORE.value:
        event_type = "repeat"
        player = None
    else:
        event_type = "unknown"
        player = None

    score_a = slots.get("score_a")
    score_b = slots.get("score_b")
    if event_type == "set_score" and score_a is None and score_b is None and raw:
        _mm = st.session_state.match_manager
        _reparsed = VoiceParser().parse(raw, _mm.state.score_a, _mm.state.score_b)
        score_a = _reparsed.score_a
        score_b = _reparsed.score_b
        event_type = _reparsed.type if _reparsed.type != "unknown" else event_type

    event = VoiceScoreEvent(
        type=event_type,
        score_a=score_a,
        score_b=score_b,
        player=player,
        raw_text=raw,
        confidence=confidence,
        event_id=event_id,
        source=source,
        requires_confirmation=True,
    )
    success, msg = st.session_state.match_manager.apply_voice_event(event)
    st.session_state.last_voice_event = event
    st.session_state.last_voice_feedback = msg
    new_score = st.session_state.match_manager.state.get_score_string()
    prev_score = item.get("predicted_score_before", new_score)

    if success:
        st.toast(f"🎤 {msg}", icon="✅")
        if event.type == "increment":
            play_cue("point")
        elif event.type == "undo":
            play_cue("undo")
        elif event.type == "set_score":
            _e2 = st.session_state.match_manager.engine
            if _e2.match_status == "game_won":
                play_cue("game")
            elif _e2.match_status == "match_won":
                play_cue("match")
        _tts_adapter = st.session_state.get("voice_tts_adapter")
        if _tts_adapter and _tts_adapter.enabled:
            _tts_adapter.speak(msg)
        _voice_match_id = st.session_state.get("voice_selected_match_id")
        if _voice_match_id:
            try:
                persist_voice_match_to_db(_voice_match_id, st.session_state.match_manager.engine)
            except Exception as exc:
                logger.warning("Failed to persist voice match %s: %s", _voice_match_id, exc)
    else:
        st.warning(f"🎤 Voice: {msg}")
        play_cue("reject")

    if VOICE_DEBUG_EVENTS:
        st.session_state.voice_event_logger.record(
            event,
            accepted=success,
            previous_score=prev_score,
            new_score=new_score,
            note="confirmed",
        )


def _process_voice_events() -> None:
    """Process pending voice events from the WebRTC audio processor.

    Runs in the main Streamlit thread. Reads events from the processor's
    queue, validates them, applies them to the MatchManager, and updates
    session state for UI display.
    """
    if not st.session_state.voice_listening:
        return

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
    _context = {
        "strict_mode": st.session_state.get("voice_strict_mode", False),
        "enable_confirmation": VOICE_ENABLE_CONFIRMATION,
    }

    # Expire stale pending confirmations (> 8 s old).
    _now = time.time()
    _stale_idx = []
    for _idx, _pending in enumerate(st.session_state.pending_confirmations):
        if _now - _pending.get("received_at", _now) > 8.0:
            _stale_idx.append(_idx)
    for _idx in reversed(_stale_idx):
        st.session_state.pending_confirmations.pop(_idx)

    logger.info("_process_voice_events: processing %d events", len(events))
    _any_success = False
    for raw_text, text, event in events:
        # Parse with new grammar to get VoiceParseResult
        parsed = parse_command(
            text,
            current_score_a=_current_score_a,
            current_score_b=_current_score_b,
        )
        # Preserve metadata from the background-thread parse
        parsed.asr_latency_ms = event.asr_latency_ms
        parsed.noise_rms = event.noise_rms
        parsed.speaker_label = getattr(event, "speaker_label", None)

        decision = policy_decision(parsed, _context)

        if decision == "reject":
            prev_score = st.session_state.match_manager.state.get_score_string()
            if VOICE_DEBUG_EVENTS:
                st.session_state.voice_event_logger.record(
                    event,
                    accepted=False,
                    previous_score=prev_score,
                    new_score=prev_score,
                    note="policy_rejected",
                )
            st.session_state.last_voice_feedback = "Voice command rejected"
            st.warning("🎤 Voice: command rejected")
            continue

        if decision == "confirm":
            _pending = {
                "event_id": parsed.event_id,
                "intent": parsed.intent,
                "slots": parsed.slots,
                "confidence": parsed.confidence,
                "raw_transcript": parsed.raw_transcript,
                "predicted_score_before": st.session_state.match_manager.state.get_score_string(),
                "predicted_score_after": _predict_score_after(parsed),
                "received_at": _now,
                "source": parsed.source,
            }
            st.session_state.pending_confirmations.append(_pending)
            st.session_state.last_voice_transcript = parsed.raw_transcript
            st.session_state.last_voice_event = parsed.to_score_event()
            st.session_state.last_voice_feedback = "Awaiting confirmation"
            st.toast("🎤 Command pending confirmation", icon="⏳")
            continue

        # decision == "apply"
        _score_event = parsed.to_score_event()
        if _score_event.type == "set_score" and _score_event.raw_text:
            _reparsed = processor.parser.parse(
                _score_event.raw_text,
                current_score_a=_current_score_a,
                current_score_b=_current_score_b,
            )
            _reparsed.noise_rms = _score_event.noise_rms
            _reparsed.asr_latency_ms = _score_event.asr_latency_ms
            _reparsed.requires_confirmation = _score_event.requires_confirmation
            _score_event = _reparsed

        st.session_state.last_voice_transcript = parsed.raw_transcript
        st.session_state.last_voice_event = _score_event

        prev_score = st.session_state.match_manager.state.get_score_string()

        # Noise robustness (Phase 5): reject chunks below the configured gate.
        if (st.session_state.voice_noise_filtering and parsed.noise_rms is not None
                and parsed.noise_rms < st.session_state.voice_noise_threshold):
            if VOICE_DEBUG_EVENTS:
                st.session_state.voice_event_logger.record(
                    _score_event, accepted=False, previous_score=prev_score,
                    new_score=prev_score, note="noise_rejected",
                )
            st.session_state.last_voice_feedback = (
                f"Rejected: noise below threshold {st.session_state.voice_noise_threshold}"
            )
            st.warning("🎤 Voice: noise below threshold, ignored")
            continue

        # Duplicate-command cooldown (Phase 4 / PingScore port): ignore identical
        # (type, player, score_a, score_b) events within COOLDOWN_MS.
        _COOLDOWN_MS = 1200.0
        _event_key = (_score_event.type, _score_event.player, _score_event.score_a, _score_event.score_b)
        _last_key = st.session_state.voice_last_applied_event_key
        _last_ts = st.session_state.voice_last_applied_event_ts
        if _event_key == _last_key and (time.time() - _last_ts) * 1000.0 < _COOLDOWN_MS:
            if VOICE_DEBUG_EVENTS:
                st.session_state.voice_event_logger.record(
                    _score_event, accepted=False, previous_score=prev_score,
                    new_score=prev_score, note="duplicate_suppressed",
                )
            st.session_state.last_voice_feedback = "Duplicate command suppressed"
            st.toast("🎤 Duplicate command suppressed", icon="⚠️")
            continue

        # Apply the event to the match manager
        if _score_event.type != "unknown":
            success, msg = st.session_state.match_manager.apply_voice_event(_score_event)
            st.session_state.last_voice_feedback = msg
            new_score = st.session_state.match_manager.state.get_score_string()
            note = "" if success else msg
            if success:
                st.toast(f"🎤 {msg}", icon="✅")
                # Sound cue for accepted voice event
                if _score_event.type == "increment":
                    play_cue("point")
                elif _score_event.type == "undo":
                    play_cue("undo")
                elif _score_event.type == "set_score":
                    # Check if this set_score completed a game or match
                    _e2 = st.session_state.match_manager.engine
                    if _e2.match_status == "game_won":
                        play_cue("game")
                    elif _e2.match_status == "match_won":
                        play_cue("match")
                # TTS confirmation (Phase 4)
                _tts_adapter = st.session_state.get("voice_tts_adapter")
                if _tts_adapter and _tts_adapter.enabled:
                    _tts_adapter.speak(msg)
                _any_success = True
                # Update cooldown tracking on successful apply
                st.session_state.voice_last_applied_event_key = _event_key
                st.session_state.voice_last_applied_event_ts = time.time()
                # Persist match state to DB when a tournament match is selected
                _voice_match_id = st.session_state.get("voice_selected_match_id")
                if _voice_match_id:
                    try:
                        persist_voice_match_to_db(_voice_match_id, st.session_state.match_manager.engine)
                    except Exception as exc:
                        logger.warning("Failed to persist voice match %s: %s", _voice_match_id, exc)
            else:
                st.warning(f"🎤 Voice: {msg}")
                play_cue("reject")
        else:
            success = False
            msg = "Unknown command"
            st.session_state.last_voice_feedback = msg
            new_score = prev_score
            note = "unrecognized transcript"

        # Structured, hardened event logging (Phase 1 / observability).
        # Gated by VOICE_DEBUG_EVENTS; bounded in-memory ring buffer.
        if VOICE_DEBUG_EVENTS:
            st.session_state.voice_event_logger.record(
                _score_event,
                accepted=success,
                previous_score=prev_score,
                new_score=new_score,
                note=note,
            )

        # Backward-compatible UI log entry, now enriched with hardened metadata.
        log_entry = {
            "timestamp": _score_event.timestamp,
            "event_id": _score_event.event_id,
            "transcript": text,
            "event_type": _score_event.type,
            "score_a": _score_event.score_a,
            "score_b": _score_event.score_b,
            "player": _score_event.player,
            "confidence": _score_event.confidence,
            "source": _score_event.source,
            "speaker_label": _score_event.speaker_label,
            "language": _score_event.language,
            "asr_latency_ms": _score_event.asr_latency_ms,
            "noise_rms": _score_event.noise_rms,
            "accepted": success,
            "previous_score": prev_score,
            "new_score": new_score,
        }
        st.session_state.voice_event_log.append(log_entry)

        # Keep only last 50 events
        if len(st.session_state.voice_event_log) > 50:
            st.session_state.voice_event_log = st.session_state.voice_event_log[-50:]

        # Dataset recorder (Phase 4): opt-in capture of transcripts and labels.
        if VOICE_DATASET_OPT_IN:
            try:
                recorder = st.session_state.get("voice_dataset_recorder")
                if recorder is not None:
                    recorder.record(
                        transcript=text,
                        parsed_intent=_score_event.type,
                        expected_intent=_score_event.type if success else None,
                        match_id=st.session_state.get("voice_selected_match_id"),
                        match_context={
                            "score_before": prev_score,
                            "score_after": new_score,
                            "confidence": _score_event.confidence,
                        },
                        mic_type="webrtc",
                        noise_condition="low" if (_score_event.noise_rms or 0.0) > 0.01 else "high",
                    )
            except Exception as exc:
                logger.debug("Dataset record skipped: %s", exc)

    # Keep the event loop alive while listening so queued events are drained
    # promptly. streamlit-webrtc only reruns the script on SDP/state lifecycle
    # changes, not during continuous playback, so without this the background
    # worker's events would sit in the queue until the next user interaction.
    # A short sleep throttles the rerun to avoid a tight busy-loop. The WebRTC
    # streamer uses a stable key ("voice_score_webrtc") and the processor
    # factory is stored in session state, so rerunning does not disrupt
    # continuous listening.
    if st.session_state.get("voice_listening"):
        time.sleep(0.1)
        st.rerun()


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
        new_bo = st.selectbox("Best of", [1, 3, 5], index=[1, 3, 5].index(_bo), key="setup_bestof")
    with _sc3:
        new_fs = st.selectbox("First server", ["A", "B"], index=["A", "B"].index(_fs), key="setup_firstserver")
    if st.button("Apply format (resets match)", key="apply_format", use_container_width=True):
        st.session_state.match_manager.apply_format(new_pts, new_bo, new_fs)
        st.toast(f"Format set: first to {new_pts}, best of {new_bo}", icon="⚙️")
        st.rerun()

# Three-column scoreboard: Player A | Center | Player B
score_col1, score_colc, score_col2 = st.columns([1, 1, 1])

with score_col1:
    st.markdown(f"<div style='text-align:center;'><h3>{st.session_state.match_manager.state.player_a}</h3></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center; font-size:72px; font-weight:bold; color:#1f77b4;'>{st.session_state.match_manager.state.score_a}</div>", unsafe_allow_html=True)
    _b1, _b2 = st.columns(2)
    with _b1:
        if st.button("➕ A", key="add_point_a", use_container_width=True):
            prev_state = copy.deepcopy(st.session_state.match_manager.state)
            success, msg = st.session_state.match_manager._add_point("A")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            play_cue("point")
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
                    _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
            st.rerun()

with score_colc:
    st.markdown("<div style='text-align:center;'><h4>VS</h4></div>", unsafe_allow_html=True)
    # Serve indicator
    _server = get_serving_player(st.session_state.match_manager.engine)
    _server_name = st.session_state.match_manager.state.player_a if _server == "A" else st.session_state.match_manager.state.player_b
    st.markdown(f"<div style='text-align:center;'>🏓 <b>Serve:</b> {_server_name}</div>", unsafe_allow_html=True)
    # Deuce badge
    if is_deuce(st.session_state.match_manager.engine):
        st.markdown("<div style='text-align:center; color:red;'><b>⚡ DEUCE</b></div>", unsafe_allow_html=True)
    # Format + games won
    _e = st.session_state.match_manager.engine
    st.markdown(f"<div style='text-align:center; font-size:13px;'>First to {_e.points_to_win} · Best of {_e.best_of}</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center; font-size:13px;'>Games: {_e.games_won_a} – {_e.games_won_b}</div>", unsafe_allow_html=True)
    # Undo + Reset
    if st.button("↩️ Undo", key="undo", use_container_width=True):
        prev_state = copy.deepcopy(st.session_state.match_manager.state)
        success, msg = st.session_state.match_manager.undo_last_point()
        st.session_state.last_feedback = msg
        st.toast(msg, icon="↩️")
        play_cue("undo")
        _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
        st.rerun()
    if st.button("🔄 Reset", key="reset", use_container_width=True):
        prev_state = copy.deepcopy(st.session_state.match_manager.state)
        success, msg = st.session_state.match_manager.reset_match()
        st.session_state.last_feedback = msg
        st.toast(msg, icon="🔄")
        play_cue("undo")
        _build_and_store_commentary("reset", st.session_state.match_manager.state, prev_state)
        st.rerun()
    # Voice status
    if st.session_state.get("last_voice_feedback"):
        st.caption(f"🎙️ {st.session_state.last_voice_feedback}")
    # Sound toggle (Phase 6)
    render_sound_toggle()
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
    # TTS mode selector (Phase 4)
    _tts = st.session_state.voice_tts_adapter
    _tts_mode_options = [m.value for m in TTSMode]
    _tts_idx = _tts_mode_options.index(_tts.mode.value) if _tts.mode.value in _tts_mode_options else 0
    _new_tts_mode = st.selectbox(
        "🔊 TTS mode",
        options=_tts_mode_options,
        index=_tts_idx,
        key="tts_mode_select",
        help="Spoken confirmation mode (offline-first, never blocks scoring).",
    )
    if _new_tts_mode != _tts.mode.value:
        _tts.mode = TTSMode(_new_tts_mode)
        st.rerun()

with score_col2:
    st.markdown(f"<div style='text-align:center;'><h3>{st.session_state.match_manager.state.player_b}</h3></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center; font-size:72px; font-weight:bold; color:#ff7f0e;'>{st.session_state.match_manager.state.score_b}</div>", unsafe_allow_html=True)
    _b1, _b2 = st.columns(2)
    with _b1:
        if st.button("➕ B", key="add_point_b", use_container_width=True):
            prev_state = copy.deepcopy(st.session_state.match_manager.state)
            success, msg = st.session_state.match_manager._add_point("B")
            st.session_state.last_feedback = msg
            st.toast(msg, icon="✅")
            play_cue("point")
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
                    _build_and_store_commentary("undo", st.session_state.match_manager.state, prev_state)
            st.rerun()

# ============================================================================
# Round / Match Winner Screens (Phase 5 / PingScore port)
# ============================================================================

_e = st.session_state.match_manager.engine
_mm = st.session_state.match_manager

if _e.match_status == "game_won":
    # Determine who won the just-completed game
    last_game = _e.round_scores[-1] if _e.round_scores else (0, 0)
    game_winner_name = _mm.state.player_a if last_game[0] > last_game[1] else _mm.state.player_b
    st.divider()
    st.success(f"🏆 **Game {len(_e.round_scores)}** — {game_winner_name} wins {last_game[0]}-{last_game[1]}!")
    st.caption(f"Games: {_e.games_won_a} – {_e.games_won_b}  |  Next game starting…")
    play_cue("game")
    if st.button("▶️ Next Game", key="next_game_btn", use_container_width=True, type="primary"):
        # The engine is already reset for the next game; just clear the game_won status
        # and rerun to show the live scoreboard again.
        _e.match_status = "in_progress"
        st.rerun()

if _e.match_status == "match_won":
    match_winner_name = _mm.state.player_a if _e.games_won_a > _e.games_won_b else _mm.state.player_b
    st.divider()
    st.balloons()
    st.success(f"🏅 **Match Complete!** {match_winner_name} wins {_e.games_won_a}-{_e.games_won_b}!")
    st.caption(f"Format: first to {_e.points_to_win}, best of {_e.best_of}")
    play_cue("match")

_rem1, _rem2, _rem3 = st.columns(3)
with _rem1:
    if st.button("🔄 Rematch", key="rematch_btn", use_container_width=True, type="primary"):
        _mm.rematch()
        st.toast("Rematch! First server swapped.", icon="🔄")
        st.rerun()
with _rem2:
    if st.button("🆕 New Match", key="new_match_btn", use_container_width=True):
        _mm.reset_match()
        st.toast("New match ready.", icon="🆕")
        st.rerun()
with _rem3:
    if st.button("📤 Submit Result", key="submit_from_scoreboard_btn", use_container_width=True):
        # Reuse the existing game-by-game submission flow by pre-filling
        # the in-progress games from the engine's round_scores.
        match_id = st.session_state.get("voice_selected_match_id")
        if match_id:
            if "in_progress_game_scores" not in st.session_state:
                st.session_state.in_progress_game_scores = {}
            st.session_state.in_progress_game_scores[match_id] = list(_e.round_scores)
            st.toast("Scores loaded into submission form — scroll down to submit.", icon="📤")
            st.rerun()
        else:
            st.warning("Select a tournament match first to enable submission.")

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
# Voice Scoring Section (WebRTC + Local ASR)
# ============================================================================

st.divider()
st.subheader("🎤 Voice Scoring (Continuous Listening)")

# Voice scoring toggle
col_enable, col_status = st.columns([2, 1])
with col_enable:
    st.session_state.voice_scoring_enabled = st.toggle(
        "Enable Voice Scoring",
        value=st.session_state.voice_scoring_enabled,
        help="Turn on continuous voice listening for score commands. Uses local faster-whisper ASR.",
    )
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
    # Check if streamlit-webrtc is available
    try:
        from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase  # noqa: F401
        webrtc_available = True
    except ImportError:
        webrtc_available = False
    
    if not webrtc_available:
        st.warning(
            "⚠️ streamlit-webrtc is not installed. "
            "Install it with: `pip install streamlit-webrtc` "
            "or enable the `[live]` extras in pyproject.toml."
        )
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
            asr_status = st.session_state.voice_asr_status
            if is_dataclass(asr_status):
                asr_status = asdict(asr_status)
            if asr_status and not asr_status.get("available", False):
                error_msg = asr_status.get("load_error", "Unknown error")
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
                        noise_gate_rms=_threshold if _filtering else 0.0,
                        sample_format=SAMPLE_FORMAT_FLOAT32,
                        voice_strict_mode=_strict,
                        vad=_vad,
                    )
                st.session_state.voice_webrtc_processor_factory = _make_processor
            
            ctx = webrtc_streamer(
                key="voice_score_webrtc",
                mode=WebRtcMode.SENDONLY,
                audio_processor_factory=st.session_state.voice_webrtc_processor_factory,
                rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
                media_stream_constraints={"audio": True, "video": False},
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

            # Confidence indicator
            if st.session_state.last_voice_event:
                _conf = getattr(st.session_state.last_voice_event, "confidence", 0.0)
                _conf_pct = int(_conf * 100)
                _color = "🔴" if _conf_pct < 50 else ("🟡" if _conf_pct < 80 else "🟢")
                st.progress(_conf, text=f"{_color} Confidence: {_conf_pct:.0f}%")

            # Confirmation / cancel panel
            _render_confirm_panel()

            # Command cheat sheet
            with st.expander("📋 Voice Command Cheat Sheet", expanded=False):
                _cheat = command_cheat_sheet()
                for row in _cheat:
                    st.markdown(f"- **{row['example']}** — {row['description']}")
            
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
                    status_display = asdict(st.session_state.voice_asr_status) if is_dataclass(st.session_state.voice_asr_status) else st.session_state.voice_asr_status
                    st.json(status_display)
                else:
                    st.caption("ASR not initialized.")
                
                if st.button("Clear Event Log", key="clear_voice_log"):
                    st.session_state.voice_event_log = []
                    st.rerun()

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
        else:
            # Not listening - show stopped state
            if st.session_state.voice_webrtc_ctx and st.session_state.voice_webrtc_ctx.get("processor"):
                st.session_state.voice_webrtc_ctx["processor"].stop()
            st.caption("Click 'Start Listening' to begin voice scoring.")

# ============================================================================
# Process voice events AFTER WebRTC streamer is set up
# ============================================================================
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
        event = _process_push_to_talk_audio(audio_file)
        if event is not None:
            st.session_state.last_voice_transcript = event.raw_text
            st.session_state.last_voice_event = event
            st.session_state.last_voice_raw_transcript = event.raw_text
            if event.type == "unknown":
                st.warning(f"🎤 Voice: Unknown command (transcript: {event.raw_text})")
            else:
                st.success(f"🎤 Parsed: {event.type} (confidence: {event.confidence:.0%})")

# Real-time mode controls
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

**PingScore-style color aliases (Phase 4):**
- "Blue" / "Teal" / "Green" — point to Player A
- "Red" / "Orange" / "Read" — point to Player B

**Tips:**
- Speak clearly and at a normal pace
- The system works best in a quiet environment
- Use the +/− buttons for quick manual corrections
- Duplicate voice commands within 1.2 seconds are automatically suppressed
""")
