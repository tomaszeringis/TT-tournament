"""
Voice runtime ownership module (Phase 4).

Owns the WebRTC audio processor, audio-frame conversion utilities, and the
stable / tracked processor factories. Streamlit session_state is accessed only
through explicit parameters — this module is import-safe for unit tests.

Thread-safety invariant:
    Background threads (WebRTC callbacks, Deepgram I/O, Faster Whisper worker)
    must NOT call Streamlit APIs or mutate st.session_state. They interact
    only through thread-safe containers (queue.Queue, locks, module-level
    queues). The Streamlit script thread is the sole mutator of session state,
    parser, and score engine.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from tournament_platform.app.services.voice_audio import (
    AudioChunk,
    SAMPLE_FORMAT_FLOAT32,
    SAMPLE_FORMAT_INT16,
    VoiceAudioBuffer,
)

from tournament_platform.app.services.voice_scorekeeper.events import (
    CalibrationCaptureContext,
    CaptureSnapshot,
    FinalizedUtterance,
    AudioTransportOutcome,
    InvalidVoiceTranscriptEvent,
    RuntimeTransitionAcknowledgement,
    TranscriptionWorkItem,
    VoiceRuntimeMode,
    VoiceTranscriptEvent,
    VoiceTranscriptSource,
    RuntimePermission,
    VoiceRuntimeAuditEvent,
)

# streamlit-webrtc processor base. Voice scoring degrades gracefully to
# push-to-talk if the package is unavailable, so fall back to ``object``.
try:
    from streamlit_webrtc import AudioProcessorBase
except Exception:  # pragma: no cover - optional dependency
    AudioProcessorBase = object  # type: ignore

VOICE_AUDIO_PROCESSOR_API_VERSION = 2
VOICE_RUNTIME_IMPLEMENTATION_VERSION = "command-trial-routing-v3"
VOICE_RUNTIME_SOURCE_FILE = __file__

from tournament_platform.app.services.voice.vad import VoiceActivityDetector
from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureContext,
    AcousticMeasurementResult,
    AudioFrameDecision,
    CalibrationArmAcknowledgement,
    CalibrationMeasurementKind,
    LiveVoiceRuntimeConfig,
)
from tournament_platform.app.services.voice_calibration.measurements import (
    AcousticAccumulator,
    InvalidFrameFormat,
    normalize_pcm,
)

from tournament_platform.app.services.asr_backends.base import (
    StreamingASRBackend,
    DeepgramBackendMetrics,
    TranscriptionResult,
)
from tournament_platform.app.services.asr_backends.calibration_policy import (
    CalibrationPolicy,
    ASRCapabilities,
    AudioDeliveryPolicy,
    AudioAdmissionDecision,
    AudioHealthState,
    AudioHealthStatus,
    UtteranceOutcome,
    AudioTransportOutcome as PolicyAudioTransportOutcome,
    deepgram_continuous_policy,
    local_batch_policy,
)

logger = logging.getLogger(__name__)


def _has_streamlit() -> bool:
    """Return True if Streamlit is running and session_state is available."""
    try:
        mod = __import__("streamlit")
        return bool(mod.runtime.exists()) if hasattr(mod, "runtime") else True
    except Exception:
        return False


def _get_st_session(key: str, default=None):
    """Safely read a Streamlit session_state value."""
    if not _has_streamlit():
        return default
    try:
        st_mod = __import__("streamlit")
        return st_mod.session_state.get(key, default)
    except Exception:
        return default


@dataclass(frozen=True)
class AudioIngressPacket:
    """Immutable audio frame snapshot for the non-blocking callback path."""

    packet_id: str
    processor_id: int
    processor_generation: int
    voice_session_id: str
    created_at: float
    pcm_bytes: bytes
    sample_rate: int
    channels: int
    pts: float
    format_name: str | None


@dataclass(frozen=True)
class AcousticCaptureRuntimeSnapshot:
    processor_id: int
    active: bool
    calibration_session_id: str | None
    measurement_id: str | None
    kind: CalibrationMeasurementKind | None
    accumulator_present: bool
    frame_count: int
    sample_count: int
    sample_rate_hz: int | None
    channels: int | None
    elapsed_ms: float
    result_queue_size: int
    completion_reason: str | None

# Module-level processor generation counter
_factory_diag_lock = threading.Lock()
_factory_diag: Dict[str, Any] = {
    "call_count": 0,
    "last_error": None,
    "last_processor_id": None,
    "last_processor_class": None,
    "callback_count": 0,
    "last_exception": None,
}
_processor_generation_counter = 0

# --------------------------------------------------------------------------- #
# Module-level audio frame callback diagnostics (fallback path)                 #
# --------------------------------------------------------------------------- #
_audio_callback_lock = threading.Lock()
_audio_callback_count = 0
_last_audio_frame_timestamp = 0.0
_last_audio_frame_rms = 0.0
_last_audio_frame_shape = ""
_last_audio_frame_sample_rate = 0
_last_audio_frame_method = ""
_last_main_thread_frame_audit_count = 0

# --------------------------------------------------------------------------- #
# Module-level acoustic capture audit diagnostics                               #
# --------------------------------------------------------------------------- #
_acoustic_audit_lock = threading.Lock()
_acoustic_audit_last_frame_count = 0
_acoustic_audit_last_enqueue_count = 0

# --------------------------------------------------------------------------- #
# Thread-context guard for callback threads                                    #
# --------------------------------------------------------------------------- #
_CALLBACK_THREAD_NAMES = frozenset(
    {
        "async_media_processor",
        "async_media_processor_2",
        "async_media_processor_3",
        "async_media_processor_4",
        "voice_processor",
    }
)


def _assert_not_on_audio_thread(what: str = "st.session_state") -> bool:
    """Return True if called from a forbidden thread.

    Used by tests to detect accidental Streamlit access from audio threads.
    """
    thread_name = threading.current_thread().name
    return any(cb in thread_name for cb in _CALLBACK_THREAD_NAMES)


# --------------------------------------------------------------------------- #
# Audio frame conversion helpers                                               #
# --------------------------------------------------------------------------- #
_acoustic_audit_lock = threading.Lock()
_acoustic_audit_last_frame_count = 0
_acoustic_audit_last_enqueue_count = 0


def reset_voice_runtime_state() -> None:
    global _audio_callback_count, _last_audio_frame_timestamp
    global _last_audio_frame_rms, _last_audio_frame_shape
    global _last_audio_frame_sample_rate, _last_audio_frame_method
    global _last_main_thread_frame_audit_count
    with _audio_callback_lock:
        _audio_callback_count = 0
        _last_audio_frame_timestamp = 0.0
        _last_audio_frame_rms = 0.0
        _last_audio_frame_shape = ""
        _last_audio_frame_sample_rate = 0
        _last_audio_frame_method = ""
        _last_main_thread_frame_audit_count = 0
    with _factory_diag_lock:
        _factory_diag.update(
            {
                "call_count": 0,
                "last_error": None,
                "last_processor_id": None,
                "last_processor_class": None,
                "callback_count": 0,
                "last_exception": None,
            }
        )

def _audio_frame_callback_func(frame):
    """Fallback audio_frame_callback for streamlit-webrtc.

    Receives each ``av.AudioFrame``, increments counters, updates metadata,
    and returns the frame unchanged so the stream continues.
    Does NOT access st.session_state or any UI APIs.
    """
    global _audio_callback_count, _last_audio_frame_timestamp
    global _last_audio_frame_rms, _last_audio_frame_shape
    global _last_audio_frame_sample_rate, _last_audio_frame_method

    with _audio_callback_lock:
        _audio_callback_count += 1
        _last_audio_frame_timestamp = getattr(frame, 'pts', time.time())
        _last_audio_frame_method = "audio_frame_callback"

    try:
        if hasattr(frame, 'to_ndarray'):
            arr = np.asarray(frame.to_ndarray())
            if arr.size > 0:
                _last_audio_frame_shape = f"{arr.shape}"
                if arr.dtype in (np.float32, np.float64):
                    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                else:
                    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2))) / 32768.0
                with _audio_callback_lock:
                    _last_audio_frame_rms = rms
    except Exception:
        pass

    try:
        with _audio_callback_lock:
            _last_audio_frame_sample_rate = getattr(frame, 'sample_rate', 0)
    except Exception:
        pass

    return frame


# --------------------------------------------------------------------------- #
# Audio frame conversion helpers                                               #
# --------------------------------------------------------------------------- #

def _frame_to_ndarray(frame: Any) -> Optional[np.ndarray]:
    """Extract a numpy array from a WebRTC audio frame."""
    if frame is None:
        return None
    try:
        if hasattr(frame, "to_ndarray"):
            arr = frame.to_ndarray()
        elif isinstance(frame, np.ndarray):
            arr = frame
        else:
            return None
        arr = np.asarray(arr)
        if arr.size == 0:
            return None
        return arr
    except Exception as exc:
        logger.debug("Skipping invalid audio frame: %s", exc)
        return None


def _audio_input_to_pcm(audio_file: Any) -> bytes:
    """Convert st.audio_input audio to mono PCM 16kHz int16 bytes."""
    if audio_file is None:
        logger.debug("No audio input provided")
        return b""

    if isinstance(audio_file, np.ndarray):
        return _pcm_float32_to_int16(_audio_frame_to_mono_float32(audio_file))

    if isinstance(audio_file, (list, tuple)):
        if not audio_file:
            return b""
        chunks = []
        for f in audio_file:
            arr = _frame_to_ndarray(f)
            if arr is None:
                continue
            chunks.append(_audio_frame_to_mono_float32(arr))
        if not chunks:
            logger.debug("No decodable audio frames in input list")
            return b""
        return _pcm_float32_to_int16(np.concatenate(chunks).astype(np.float32, copy=False))

    if hasattr(audio_file, "to_ndarray") and not hasattr(audio_file, "demux"):
        arr = _frame_to_ndarray(audio_file)
        if arr is None:
            return b""
        return _pcm_float32_to_int16(_audio_frame_to_mono_float32(arr))

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
        logger.debug("Failed to convert audio input to PCM: %s", exc)
        return b""


def _audio_frame_to_mono_float32(arr: np.ndarray) -> np.ndarray:
    """Convert an audio ndarray to mono float32 in ``[-1, 1]``."""
    from tournament_platform.app.services.voice.vad import normalize_audio

    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr.mean(axis=0)
    elif arr.ndim > 2:
        arr = arr.reshape(-1)
    return normalize_audio(arr)


def _pcm_float32_to_int16(arr: np.ndarray) -> bytes:
    """Convert mono float32 PCM in ``[-1, 1]`` to mono int16 16kHz bytes."""
    int16_audio = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
    return int16_audio.tobytes()


# --------------------------------------------------------------------------- #
# VoiceAudioProcessor                                                         #
# --------------------------------------------------------------------------- #

def source_from_capture_mode(
    capture_runtime_mode: VoiceRuntimeMode,
) -> VoiceTranscriptSource | None:
    match capture_runtime_mode:
        case VoiceRuntimeMode.CALIBRATION:
            return VoiceTranscriptSource.CALIBRATION
        case VoiceRuntimeMode.LIVE:
            return VoiceTranscriptSource.CONTINUOUS
        case VoiceRuntimeMode.OFF:
            return None
        case unsupported:
            raise InvalidVoiceTranscriptEvent(
                f"Unsupported capture runtime mode: {unsupported!r}"
            )


class PermissionChecker:
    """Minimal runtime permission model for voice scoring.

    Defines which runtime operations are allowed in each mode:
        OFF:    No audio processing allowed (silent)
        LIVE:   Continuous listening + scoring allowed
        CALIBRATION: Calibration capture + scoring allowed
    """

    @staticmethod
    def check(
        permission: RuntimePermission,
        runtime_mode: VoiceRuntimeMode,
        calibration_context: Optional[CalibrationCaptureContext] = None,
    ) -> tuple[bool, Optional[str]]:
        """Check if a permission is granted in the current runtime mode.

        Args:
            permission: The permission to check.
            runtime_mode: Current runtime mode.
            calibration_context: Optional calibration context.

        Returns:
            Tuple of (granted: bool, reason: Optional[str]).
        """
        if permission == RuntimePermission.OFF:
            return True, None

        if permission == RuntimePermission.LIVE:
            if runtime_mode == VoiceRuntimeMode.LIVE:
                return True, None
            if runtime_mode == VoiceRuntimeMode.OFF:
                return False, "runtime_mode_not_selected"
            if runtime_mode == VoiceRuntimeMode.CALIBRATION:
                return False, "runtime_still_calibration"
            return False, "unknown_runtime_mode"

        if permission == RuntimePermission.CALIBRATION:
            armed = calibration_context is not None and calibration_context.armed_at is not None
            if armed:
                return True, None
            if runtime_mode == VoiceRuntimeMode.CALIBRATION:
                return False, "calibration_context_not_armed"
            if runtime_mode == VoiceRuntimeMode.OFF:
                return False, "runtime_mode_not_selected"
            if runtime_mode == VoiceRuntimeMode.LIVE:
                return False, "stale_calibration_context"
            return False, "unknown_runtime_mode"

        return False, f"unknown_permission: {permission}"


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

    api_version: int = 2

    def __init__(
        self,
        noise_gate_rms: float = 0.0,
        sample_format: str = SAMPLE_FORMAT_FLOAT32,
        voice_strict_mode: bool = False,
        vad: Optional[VoiceActivityDetector] = None,
        asr: object = None,
        tt_sounds_processor: object = None,
    ):
        """Initialize the audio processor.

        Args:
            noise_gate_rms: Minimum speech-energy floor. 0.0 disables the gate.
            sample_format: Audio sample format ("float32" or "int16").
            voice_strict_mode: If True, flag score events for confirmation.
            vad: Optional VoiceActivityDetector for improved speech detection.
            asr: Optional pre-built ASR backend. When ``None`` (default), the
                backend is lazily loaded via ``_get_asr()`` and the processor
                degrades gracefully if ASR is unavailable.
            tt_sounds_processor: Optional TTRallyProcessor for impact detection.
        """
        self._sample_format = getattr(self, '_sample_format', sample_format)
        self.audio_buffer = VoiceAudioBuffer(
            noise_gate_rms=noise_gate_rms,
            sample_format=self._sample_format,
            vad=vad,
        )
        self.vocabulary = VoiceVocabulary.load()
        self.parser = VoiceParser()
        self.post_processor = TranscriptPostProcessor(self.vocabulary)
        self.event_queue: queue.Queue = queue.Queue(maxsize=50)
        self._processing = False
        self._lock = threading.Lock()
        self._voice_strict_mode = voice_strict_mode
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_started: bool = False
        self._stop_worker = threading.Event()
        self._chunk_queue: queue.Queue = queue.Queue(maxsize=20)
        self._dropped_chunks = 0
        self._audio_frames_received = 0
        self._audio_ingress_queue_full = 0  # Quick Win 11
        self._dropped_frames = 0  # Quick Win 11
        self._chunks_created = 0
        global _processor_generation_counter
        with _factory_diag_lock:
            _processor_generation_counter += 1
            self._processor_generation = _processor_generation_counter
        self._frame_classification_count = 0
        self._speech_frame_count = 0
        self._endpoint_reason: Optional[str] = None
        self._last_frame_rms = 0.0
        self._last_frame_normalized_rms = 0.0
        self._above_threshold = False
        self._vad_decision = False
        self._speech_segment_frame_count = 0
        self._asr_events_enqueued = 0
        self._last_frame_timestamp: float = 0.0

        # Point 7: Instrument processor_created
        _voice_lifecycle_events.push(
            VoiceLifecycleEvent(
                event_type="processor_created",
                processor_id=id(self),
                processor_generation=self._processor_generation,
                timestamp=time.time(),
                desired_mic_playing=None,
                last_frame_age_ms=None,
                extra={"note": "processor_init_complete"},
            )
        )
        self._last_chunk_timestamp: float = 0.0
        self._last_audio_callback_ts: float = 0.0
        self._recv_call_count: int = 0
        self._recv_queued_call_count: int = 0
        self._last_recv_timestamp: float = 0.0
        self._last_recv_queued_timestamp: float = 0.0
        self._last_ingest_timestamp: float = 0.0
        self._callback_exception_count: int = 0
        self._last_callback_exception: Optional[str] = None
        self._asr = asr
        self._asr_ready = asr is not None
        self._asr_error: Optional[str] = None
        self._status: str = "idle"
        self._last_audio_error_log_ts: float = 0.0
        self._audio_error_count: int = 0
        self._callback_count: int = 0
        self._created_at: float = time.time()
        self._implementation_version: str = VOICE_RUNTIME_IMPLEMENTATION_VERSION
        self._source_file: str = VOICE_RUNTIME_SOURCE_FILE
        self.tt_sounds_processor = tt_sounds_processor
        self._calibration_context: Optional[CalibrationCaptureContext] = None
        self._runtime_mode: VoiceRuntimeMode = VoiceRuntimeMode.OFF
        self._session_id: Optional[str] = None
        self._audio_delivery_mode: str = "batch"
        self._active_acoustic_capture: Optional[AcousticCaptureContext] = None
        self._acoustic_accumulator: Optional[AcousticAccumulator] = None
        self._measurement_result_queue: queue.Queue[AcousticMeasurementResult] = queue.Queue(maxsize=4)
        self._last_acoustic_arm_ts: float = 0.0
        self._last_armed_measurement_id: Optional[str] = None
        self._last_acoustic_clear_reason: Optional[str] = None
        self._worker_exception: Optional[Exception] = None
        self._transcription_calls_started: int = 0
        self._transcription_calls_completed: int = 0
        self._transcription_results_returned: int = 0
        self._transcript_text_extracted: int = 0
        self._events_built: int = 0
        self._events_enqueued: int = 0
        self._blank_transcription_count: int = 0
        self._last_work_item_timestamp: float = 0.0
        self._last_asr_latency_ms: float = 0.0
        self._last_asr_result_text: str = ""
        self._last_asr_result_language: str = ""
        self._last_terminal_outcome: str = "none"
        self._last_rejection_reason: str = "none"
        self._inference_lock_wait_duration_ms: float = 0.0
        self._inference_lock_owner_work_item_id: str = ""
        self._current_work_item_id: str = ""
        self._current_work_item_stage: str = "idle"
        self._queued_work_item_ids: List[str] = []
        self._chunk_enqueue_attempts: int = 0
        self._chunk_enqueue_accepted: int = 0
        self._chunk_enqueue_rejected: int = 0
        self._last_chunk_rejection_reason: Optional[str] = None
        self._work_items_enqueued: int = 0
        self._rejected_by_reason: dict[str, int] = {}
        self._last_chunk_admission_outcome: str = "none"
        self._last_chunk_runtime_mode: str = ""
        self._last_chunk_capture_source: str = ""
        self._last_chunk_continuous_session_id: Optional[str] = None
        self._config_revision: int = 0
        self._preferred_phrases: tuple[str, ...] = ()
        self._confirmed_aliases: tuple[str, ...] = ()
        self._asr_config: Any | None = None
        self._audit_queue: queue.Queue = queue.Queue(maxsize=200)
        self._audit_dropped_count: int = 0
        self._audit_event_rate_limiter: dict[str, float] = {}

        # --- Streaming backend (Deepgram Nova-3) state ---
        # Plan Â§8A: continuous audio is delivered directly to the streaming
        # backend, bypassing VoiceAudioBuffer chunking entirely.
        self._streaming_backend: Optional[StreamingASRBackend] = None
        self._calibration_policy: Optional[CalibrationPolicy] = None
        self._streaming_generation: int = 0
        self._streaming_voice_session_id: Optional[str] = None
        self._streaming_match_id: Any = None
        self._streaming_active: bool = False
        self._streaming_error: Optional[str] = None
        self._streaming_pcm_format: str = SAMPLE_FORMAT_INT16
        self._streaming_sample_rate: int = 16000
        self._streaming_channels: int = 1

        # Audio transport accounting (plan Â§8A)
        self._streaming_audio_enqueued: int = 0
        self._streaming_audio_sent: int = 0
        self._streaming_audio_queue_full: int = 0
        self._streaming_audio_stale: int = 0
        self._streaming_audio_provider_unavailable: int = 0
        self._streaming_frames_received: int = 0
        self._streaming_frames_converted: int = 0

        # Utterance accounting (plan Â§8A)
        self._streaming_finalized: int = 0
        self._streaming_duplicate: int = 0
        self._streaming_stale: int = 0
        self._streaming_match_mismatch: int = 0
        self._streaming_invalid: int = 0
        self._streaming_parser_rejected: int = 0
        self._streaming_applied: int = 0
        self._streaming_failed: int = 0
        self._streaming_drain_calls: int = 0
        self._streaming_events_drained: int = 0

        # Invalid finalized item diagnostics
        self._last_finalized_invalid_type: str = ""
        self._last_finalized_invalid_module: str = ""
        self._last_finalized_invalid_repr: str = ""
        self._last_finalized_invalid_queue_source: str = ""
        self._last_finalized_invalid_backend_object_id: int = 0
        self._last_finalized_invalid_processor_id: int = 0
        self._last_finalized_invalid_utt_is_same_class: bool = False
        self._last_finalized_invalid_utt_type_id: int = 0
        self._last_finalized_invalid_expected_type_id: int = 0

        # Event bridge (plan Â§8B)
        self._finalized_utterance_queue: queue.Queue = queue.Queue(maxsize=50)
        self._seen_utterance_ids: set[str] = set()
        self._max_seen_utterance_ids = 1000
        self._diagnostic_snapshot: Optional[dict] = None
        self._last_interim_text: str = ""
        self._last_interim_ts: float = 0.0
        self._interim_throttle_s: float = 0.5

        # --- Audio ingress worker (non-blocking callback contract) ---
        self._audio_ingress_queue: queue.Queue = queue.Queue(maxsize=64)
        self._audio_ingress_worker_thread: Optional[threading.Thread] = None
        self._audio_ingress_worker_started: bool = False
        self._stop_audio_ingress_worker_event: threading.Event = threading.Event()
        self._audio_ingress_accepted: int = 0
        self._audio_ingress_queue_full: int = 0
        self._audio_ingress_stale: int = 0
        self._audio_ingress_processed: int = 0
        self._audio_ingress_worker_failures: int = 0
        self._last_audio_ingress_error: Optional[str] = None
        self._audio_ingress_packet_id_counter: int = 0

        if tt_sounds_processor is not None:
            tt_sounds_processor.start()

    def _get_asr(self):
        """Lazy-load the ASR backend."""
        if getattr(self, "_asr", None) is not None:
            return self._asr
        try:
            backend = ASRBackendFactory.create(vocabulary=self.vocabulary)
        except Exception as exc:
            self._asr_error = str(exc)
            self._asr_ready = False
            self._set_status("ASR unavailable")
            return None
        self._asr = backend
        self._asr_ready = bool(getattr(backend, "is_available", lambda: False)())
        if not self._asr_ready:
            self._asr_error = (
                getattr(backend.get_status(), "load_error", None)
                if hasattr(backend, "get_status")
                else None
            )
            self._set_status("ASR unavailable")
        else:
            self._set_status("ASR ready")
        return self._asr

    def _set_status(self, status: str) -> None:
        """Update the processor status visible in the UI diagnostics panel."""
        self._status = status

    # ------------------------------------------------------------------ #
    # Streaming backend wiring (plan Â§8A)                                  #
    # ------------------------------------------------------------------ #

    def set_streaming_backend(
        self,
        backend: StreamingASRBackend,
        *,
        voice_session_id: str,
        match_id: Any,
        language: str,
        keyterms: Optional[list[str]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        """Attach a streaming ASR backend to this processor.

        Replaces any previously attached streaming backend.  The voice session
        ID and match ID are frozen into the processor at attach time and
        validated when finalized utterances are bridged.  The backend session
        is started immediately (plan §8A: connect on start, not on first frame).
        """
        with self._lock:
            # Close previous backend if any
            prev_backend = self._streaming_backend
            self._streaming_generation += 1
            self._streaming_voice_session_id = voice_session_id
            self._streaming_match_id = match_id
            self._streaming_backend = backend
            self._calibration_policy = CalibrationPolicy(
                capabilities=backend.capabilities(),
                delivery_policy=backend.delivery_policy(),
            )
            self._streaming_active = True
            self._streaming_sample_rate = sample_rate
            self._streaming_channels = channels
            self._audio_delivery_mode = "stream"
            self._seen_utterance_ids.clear()
            self._runtime_mode = VoiceRuntimeMode.LIVE
            while not self._finalized_utterance_queue.empty():
                try:
                    self._finalized_utterance_queue.get_nowait()
                except queue.Empty:
                    break

        if prev_backend is not None:
            try:
                prev_backend.close()
            except Exception as exc:
                logger.debug("Previous streaming backend close: %s", exc)

        # Start the backend session immediately -- do not wait for first audio frame
        try:
            backend.start_session(
                language=language,
                session_id=voice_session_id,
                generation=self._streaming_generation,
                match_id=match_id,
                keyterms=keyterms,
                sample_rate=sample_rate,
                channels=channels,
            )
        except Exception as exc:
            self._streaming_error = str(exc)
            self._set_status("streaming_connection_failed")
            logger.warning("Streaming backend start_session failed: %s", exc)
        else:
            self._set_status("streaming_connecting")

        self._emit_runtime_audit(
            "streaming_backend_attached",
            f"processor_id={id(self)} "
            f"generation={self._streaming_generation} "
            f"session={voice_session_id[:8] if voice_session_id else 'none'} "
            f"backend={backend.backend_name} "
            f"language={language}",
        )

    def clear_streaming_backend(self) -> None:
        """Detach and shut down the streaming backend (voice-off path).

        Invalidates the current generation before closing so that any
        in-flight finalized utterances are rejected by the guard check.
        Idempotent: safe to call multiple times.
        """
        with self._lock:
            backend = self._streaming_backend
            self._streaming_generation += 1
            self._streaming_active = False
            self._streaming_voice_session_id = None
            self._streaming_match_id = None
            self._streaming_backend = None
            self._audio_delivery_mode = "batch"
            self._calibration_policy = None
            self._seen_utterance_ids.clear()

        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                logger.debug("Streaming backend close error: %s", exc)

        self._emit_runtime_audit(
            "streaming_backend_detached",
            f"processor_id={id(self)} "
            f"generation={self._streaming_generation}",
        )

    def is_streaming_connected(self) -> bool:
        """Return True only when the streaming backend confirms WebSocket is open."""
        backend = self._streaming_backend
        if backend is None or not self._streaming_active:
            return False
        state = backend.health_status() if hasattr(backend, "health_status") else "unknown"
        return state == "connected"

    @property
    def effective_delivery_mode(self) -> str:
        """Return the actual delivery mode based on backend attachment."""
        if self._streaming_backend is not None and self._streaming_active:
            return "stream"
        return "batch"

    def get_streaming_diagnostics(self) -> dict:
        """Return a latest-value diagnostic snapshot for the UI.

        Interim diagnostics are droppable.  Finalized utterance IDs and
        counts are NOT droppable — they represent committed work.
        """
        backend = self._streaming_backend
        diag: dict[str, Any] = {
            "streaming_active": self._streaming_active,
            "backend_attached": backend is not None,
            "backend_generation": self._streaming_generation,
            "voice_session_id": self._streaming_voice_session_id or "none",
            "match_id": str(self._streaming_match_id) if self._streaming_match_id is not None else "none",
            "audio_enqueued": self._streaming_audio_enqueued,
            "audio_stale": self._streaming_audio_stale,
            "audio_queue_full": self._streaming_audio_queue_full,
            "streaming_finalized": self._streaming_finalized,
            "streaming_stale": self._streaming_stale,
            "streaming_duplicate": self._streaming_duplicate,
            "streaming_failed": self._streaming_failed,
            "audio_delivery_mode": self.effective_delivery_mode,
            "processor_id": id(self),
            "processor_generation": self._processor_generation,
        }
        if backend is not None and hasattr(backend, "health_status"):
            diag["backend_health"] = backend.health_status()
        if self._streaming_error:
            diag["streaming_error"] = self._streaming_error
        # Latest finalized/interim from the backend (if available)
        if backend is not None and hasattr(backend, "get_interim_diagnostics"):
            _bdiag = backend.get_interim_diagnostics()
            diag["last_finalized_transcript"] = _bdiag.get("last_finalized_transcript", "")
            diag["last_interim_transcript"] = _bdiag.get("last_interim_transcript", "")
        return diag


    def _ensure_streaming_session(
        self,
        *,
        language: str,
        keyterms: Optional[list[str]] = None,
    ) -> bool:
        """Start or restart the streaming session if needed."""
        backend = self._streaming_backend
        if backend is None:
            return False
        if getattr(backend, "_session_id", "") == "":
            backend.start_session(
                language=language,
                keyterms=keyterms,
                sample_rate=self._streaming_sample_rate,
                channels=self._streaming_channels,
            )
        return backend.is_available()

    def _route_streaming_audio(self, frame_bytes: bytes, detected_format: str | None, channels: int | None = None, sample_rate: int | None = None) -> None:
        """Convert a WebRTC frame to int16 mono PCM and enqueue for streaming.

        Normalizes the PCM to the backend's expected format (int16, 16 kHz,
        mono) and forwards it via the non-blocking ``_enqueue_streaming_audio``.
        Silence frames are passed through â Deepgram expects a continuous
        stream including silence (plan Â§8A invariant).
        """
        import numpy as np

        backend = self._streaming_backend
        if backend is None:
            return

        self._streaming_frames_received += 1

        sample_rate = sample_rate or self.audio_buffer.sample_rate
        channels = channels or self.audio_buffer.channels

        # Convert to float64 normalized array (matches normalize_pcm)
        try:
            normalized = normalize_pcm(frame_bytes, detected_format or self._sample_format, channels)
        except InvalidFrameFormat:
            normalized = None

        if normalized is None:
            # Fall back to raw decode
            if detected_format == SAMPLE_FORMAT_INT16:
                arr = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float64) / 32768.0
            else:
                try:
                    arr = np.frombuffer(frame_bytes, dtype=np.float32).astype(np.float64)
                except Exception:
                    return
            normalized = arr

        if normalized is None:
            return

        # Mix to mono
        if normalized.ndim == 2 and normalized.shape[1] > 1:
            normalized = normalized.mean(axis=1)
        elif normalized.ndim > 1:
            normalized = normalized.ravel()

        # Resample to streaming sample rate if needed
        if sample_rate != self._streaming_sample_rate:
            try:
                from scipy.signal import resample
                n_target = int(len(normalized) * self._streaming_sample_rate / sample_rate)
                normalized = resample(normalized, n_target)
            except ImportError:
                # Fallback: simple linear interpolation
                n_target = int(len(normalized) * self._streaming_sample_rate / sample_rate)
                if n_target > 0:
                    indices = np.linspace(0, len(normalized) - 1, n_target)
                    normalized = np.interp(indices, range(len(normalized)), normalized)

        # Convert to int16 PCM
        int16_arr = np.clip(normalized * 32768.0, -32768, 32767).astype(np.int16)
        pcm_int16 = int16_arr.tobytes()

        self._streaming_frames_converted += 1
        self._enqueue_streaming_audio(pcm_int16)

    def _enqueue_streaming_audio(self, pcm_int16: bytes) -> AudioTransportOutcome:
        """Forward a normalized PCM frame to the streaming backend.

        Non-blocking: the backend's internal bounded queue absorbs the bytes.
        No network calls occur here (plan Â§8A invariant).
        """
        import time as _time

        transport_outcome = AudioTransportOutcome(
            outcome="provider_unavailable",
            rejection_reason="backend_not_attached",
            timestamp=_time.time(),
        )
        with self._lock:
            if not self._streaming_active:
                self._streaming_audio_stale += 1
                return AudioTransportOutcome(
                    outcome="stale",
                    rejection_reason="backend_not_active",
                    frame_id="",
                    timestamp=_time.time(),
                )
            backend = self._streaming_backend
            generation = self._streaming_generation
            voice_session_id = self._streaming_voice_session_id

        if backend is None:
            self._streaming_audio_provider_unavailable += 1
            return AudioTransportOutcome(
                outcome="provider_unavailable",
                rejection_reason="backend_none",
                frame_id=f"gen{generation}",
                timestamp=_time.time(),
            )

        # Validate generation hasn't been invalidated (voice-off)
        if not self._streaming_active:
            self._streaming_audio_stale += 1
            return AudioTransportOutcome(
                outcome="stale",
                rejection_reason="voice_off_invalidated",
                frame_id=f"gen{generation}",
                timestamp=_time.time(),
            )

        # Audio received while backend is still connecting — discard with
        # a precise transport outcome (plan §8A: bounded behavior, no buffering)
        health = backend.health_status() if hasattr(backend, "health_status") else "unknown"
        state = backend.connection_state() if hasattr(backend, "connection_state") else health
        if state in ("connecting", "starting", "reconnecting"):
            self._streaming_audio_stale += 1
            return AudioTransportOutcome(
                outcome="stale",
                rejection_reason=f"provider_{state}",
                frame_id=f"gen{generation}",
                timestamp=_time.time(),
            )

        # Attempt non-blocking enqueue
        ok = backend.enqueue_audio(pcm_int16)
        if ok:
            self._streaming_audio_enqueued += 1
            return AudioTransportOutcome(
                outcome="enqueued",
                rejection_reason=None,
                frame_id=f"gen{generation}:{voice_session_id[:8] if voice_session_id else 'n'}",
                timestamp=_time.time(),
            )
        else:
            state = backend.connection_state() if hasattr(backend, "connection_state") else health
            if state in ("connecting", "reconnecting", "starting"):
                self._streaming_audio_provider_unavailable += 1
                return AudioTransportOutcome(
                    outcome="provider_unavailable",
                    rejection_reason=f"backend_{state}",
                    frame_id=f"gen{generation}",
                    timestamp=_time.time(),
                )
            self._streaming_audio_queue_full += 1
            return AudioTransportOutcome(
                outcome="queue_full",
                rejection_reason="audio_queue_full",
                frame_id=f"gen{generation}",
                timestamp=_time.time(),
            )

    # ------------------------------------------------------------------ #
    # Event bridge (plan Â§8B)                                            #
    # ------------------------------------------------------------------ #

    def drain_finalized_utterances(
        self,
        current_voice_session_id: Optional[str],
        current_backend_generation: int,
        current_match_id: Any,
    ) -> List[FinalizedUtterance]:
        """Drain finalized utterances from the streaming backend.

        Validates each utterance against the active voice session ID,
        backend generation, and match ID.  Stale or duplicate utterances
        are discarded (plan Â§8B double-check).

        Returns a list of validated ``FinalizedUtterance`` objects ready
        for the scoring pipeline.  Also collects interim diagnostics.
        """
        backend = self._streaming_backend
        utterances: List[FinalizedUtterance] = []

        if backend is None:
            return utterances

        # Drain finalized utterances from the backend
        try:
            finalized = backend.get_finalized_transcripts()
        except Exception as exc:
            logger.debug("get_finalized_transcripts error: %s", exc)
            self._streaming_failed += 1
            return utterances

        for utt in finalized:
            if not isinstance(utt, FinalizedUtterance):
                continue

            # --- Generation check: reject if backend was invalidated ---
            if utt.backend_generation != current_backend_generation:
                self._streaming_stale += 1
                self._emit_runtime_audit(
                    "streamed_utterance_stale",
                    f"processor_id={id(self)} "
                    f"utt_generation={utt.backend_generation} "
                    f"current_generation={current_backend_generation} "
                    f"match_id={utt.match_id}",
                )
                continue

            # --- Session check ---
            if (
                current_voice_session_id is not None
                and utt.voice_session_id != current_voice_session_id
            ):
                self._streaming_stale += 1
                continue

            # --- Match check ---
            if (
                current_match_id is not None
                and utt.match_id is not None
                and utt.match_id != current_match_id
            ):
                self._streaming_stale += 1
                continue

            # --- Annotate with current match_id ---
            # NOTE: Backend/provider dedup is handled in drain_streaming_events.
            # Application dedup is handled in _process_streaming_utterances.
            utt = dataclasses.replace(utt, match_id=current_match_id)

            utterances.append(utt)
            self._streaming_finalized += 1

        # Bound the seen IDs set
        if len(self._seen_utterance_ids) > self._max_seen_utterance_ids:
            # Keep the most recent half
            excess = len(self._seen_utterance_ids) - self._max_seen_utterance_ids // 2
            sorted_ids = sorted(self._seen_utterance_ids)
            for old_id in sorted_ids[:excess]:
                self._seen_utterance_ids.discard(old_id)

        # Update diagnostic snapshot with interim transcripts
        self._update_interim_diagnostics(backend)

        return utterances

    def _update_interim_diagnostics(self, backend: Any) -> None:
        """Drain interim transcripts and update the lightweight diagnostic snapshot.

        Does NOT trigger a full page rerun â callers read this snapshot
        on their own throttle schedule (plan Â§8B, Â§9).
        """
        now = time.monotonic()
        if now - self._last_interim_ts < self._interim_throttle_s:
            return

        # Collect interim transcripts
        try:
            interim = backend.get_interim_transcripts()
        except Exception:
            interim = []

        if interim:
            self._last_interim_text = interim[-1][0] if isinstance(interim[-1], tuple) else str(interim[-1])
            self._last_interim_ts = now

        # Collect errors
        try:
            errors = backend.get_errors()
        except Exception:
            errors = []

        # Build diagnostic snapshot (low-cardinality only)
        try:
            metrics = backend.metrics()
        except Exception:
            metrics = None

        self._diagnostic_snapshot = {
            "connection_state": getattr(metrics, "connection_state", "unknown") if metrics else "unknown",
            "queue_depth": getattr(metrics, "queue_depth", 0) if metrics else 0,
            "interim_transcript_count": getattr(metrics, "interim_transcript_count", 0) if metrics else 0,
            "completed_utterance_count": getattr(metrics, "completed_utterance_count", 0) if metrics else 0,
            "queue_overflow_count": getattr(metrics, "queue_overflow_count", 0) if metrics else 0,
            "reconnect_count": getattr(metrics, "reconnect_count", 0) if metrics else 0,
            "keepalive_count": getattr(metrics, "keepalive_count", 0) if metrics else 0,
            "keyterm_count": getattr(metrics, "keyterm_count", 0) if metrics else 0,
            "speech_end_to_final_latency_ms": getattr(metrics, "speech_end_to_final_latency_ms", None) if metrics else None,
            "last_interim_text": self._last_interim_text[:100],
            "last_final_text": "",
            "provider_messages_received": getattr(metrics, "provider_messages_received", 0) if metrics else 0,
            "interim_results_received": getattr(metrics, "interim_transcript_count", 0) if metrics else 0,
            "final_results_received": getattr(metrics, "completed_utterance_count", 0) if metrics else 0,
            "recent_errors": [str(e) for e in errors[-3:]],
            "backend_available": backend.is_available() if hasattr(backend, "is_available") else False,
        }

    def get_interim_diagnostics(self) -> Optional[dict]:
        """Return the latest diagnostic snapshot for UI display.

        Thread-safe.  Returns ``None`` if no streaming backend is attached.
        """
        return self._diagnostic_snapshot

    def has_streaming_pending_events(self) -> bool:
        """Return True if the streaming backend has finalized utterances to drain."""
        backend = self._streaming_backend
        if backend is None:
            return False
        try:
            finalized = backend.get_finalized_transcripts()
        except Exception:
            return False
        # Re-queue drained items; drain_finalized_utterances will validate them
        for utt in finalized:
            try:
                self._finalized_utterance_queue.put_nowait(utt)
            except queue.Full:
                break
        return len(finalized) > 0

    def get_streaming_transport_stats(self) -> dict:
        """Return audio transport and utterance accounting counters."""
        backend = self._streaming_backend
        audio_bytes_sent = 0
        audio_send_attempts = 0
        audio_send_success = 0
        audio_send_failed = 0
        duration_sent_ms = 0.0
        last_send_at = 0.0
        provider_messages_received = 0
        provider_open_count = 0
        provider_close_count = 0
        provider_error_count = 0
        provider_unerror_count = 0
        provider_utterance_end_count = 0
        provider_speech_started_count = 0
        last_provider_message_text = ""
        provider_results_received = 0
        provider_results_empty = 0
        provider_results_with_text = 0
        provider_results_interim = 0
        provider_results_final = 0
        provider_results_speech_final = 0
        last_interim_text = ""
        last_final_text = ""
        send_loop_started = False
        send_loop_alive = False
        keepalive_loop_started = False
        keepalive_loop_alive = False
        backend_connection_state = "none"
        provider_connected = False
        if backend is not None:
            backend_connection_state = backend.get_connection_state() if hasattr(backend, "get_connection_state") else "unknown"
            provider_connected = backend_connection_state == "connected"
            if hasattr(backend, "metrics"):
                try:
                    m = backend.metrics()
                    audio_bytes_sent = getattr(m, "audio_bytes_sent", 0) or 0
                    audio_send_attempts = getattr(m, "audio_send_attempts", 0) or 0
                    audio_send_success = getattr(m, "audio_send_success", 0) or 0
                    audio_send_failed = getattr(m, "audio_send_failed", 0) or 0
                    duration_sent_ms = getattr(m, "audio_duration_sent_ms", 0.0) or 0.0
                    last_send_at = getattr(m, "last_audio_send_at", 0.0) or 0.0
                    provider_messages_received = getattr(m, "provider_messages_received", 0) or 0
                    provider_open_count = getattr(m, "provider_open_count", 0) or 0
                    provider_close_count = getattr(m, "provider_close_count", 0) or 0
                    provider_error_count = getattr(m, "provider_error_count", 0) or 0
                    provider_unerror_count = getattr(m, "provider_unerror_count", 0) or 0
                    provider_utterance_end_count = getattr(m, "provider_utterance_end_count", 0) or 0
                    provider_speech_started_count = getattr(m, "provider_speech_started_count", 0) or 0
                    last_provider_message_text = getattr(m, "last_provider_message_text", "") or ""
                    provider_results_received = getattr(m, "provider_results_received", 0) or 0
                    provider_results_empty = getattr(m, "provider_results_empty", 0) or 0
                    provider_results_with_text = getattr(m, "provider_results_with_text", 0) or 0
                    provider_results_interim = getattr(m, "provider_results_interim", 0) or 0
                    provider_results_final = getattr(m, "provider_results_final", 0) or 0
                    provider_results_speech_final = getattr(m, "provider_results_speech_final", 0) or 0
                    last_interim_text = getattr(m, "last_interim_text", "") or ""
                    last_final_text = getattr(m, "last_final_text", "") or ""
                    send_loop_started = getattr(m, "send_loop_started", False)
                    send_loop_alive = getattr(m, "send_loop_alive", False)
                    keepalive_loop_started = getattr(m, "keepalive_loop_started", False)
                    keepalive_loop_alive = getattr(m, "keepalive_loop_alive", False)
                except Exception:
                    pass
        self._streaming_audio_sent = audio_bytes_sent
        return {
            "audio_enqueued": self._streaming_audio_enqueued,
            "audio_sent": self._streaming_audio_sent,
            "audio_send_attempts": audio_send_attempts,
            "audio_send_success": audio_send_success,
            "audio_send_failed": audio_send_failed,
            "audio_bytes_sent": audio_bytes_sent,
            "audio_duration_sent_ms": duration_sent_ms,
            "last_streaming_audio_send_at": last_send_at,
            "streaming_frames_received": self._streaming_frames_received,
            "streaming_frames_converted": self._streaming_frames_converted,
            "streaming_audio_enqueue_attempts": self._streaming_audio_enqueued,
            "audio_queue_full": self._streaming_audio_queue_full,
            "audio_stale": self._streaming_audio_stale,
            "audio_provider_unavailable": self._streaming_audio_provider_unavailable,
            "utterances_finalized": self._streaming_finalized,
            "utterances_duplicate": self._streaming_duplicate,
            "utterances_stale": self._streaming_stale,
            "utterances_parser_rejected": self._streaming_parser_rejected,
            "utterances_applied": self._streaming_applied,
            "utterances_failed": self._streaming_failed,
            "streaming_generation": self._streaming_generation,
            "streaming_voice_session_id": self._streaming_voice_session_id,
            "streaming_match_id": self._streaming_match_id,
            "input_sample_rate": self.audio_buffer.sample_rate,
            "input_channels": self.audio_buffer.channels,
            "input_format": self._sample_format,
            "output_sample_rate": self._streaming_sample_rate,
            "output_channels": self._streaming_channels,
            "output_encoding": "linear16",
            "output_frame_bytes": self._streaming_sample_rate * self._streaming_channels * 2 // 50,
            "output_frame_duration_ms": 20,
            "provider_messages_received": provider_messages_received,
            "provider_open_count": provider_open_count,
            "provider_close_count": provider_close_count,
            "provider_error_count": provider_error_count,
            "provider_unerror_count": provider_unerror_count,
            "provider_utterance_end_count": provider_utterance_end_count,
            "provider_speech_started_count": provider_speech_started_count,
            "provider_results_received": provider_results_received,
            "provider_results_empty": provider_results_empty,
            "provider_results_with_text": provider_results_with_text,
            "provider_results_interim": provider_results_interim,
            "provider_results_final": provider_results_final,
            "provider_results_speech_final": provider_results_speech_final,
            "last_provider_message_text": last_provider_message_text,
            "last_interim_text": last_interim_text,
            "last_final_text": last_final_text,
            "send_loop_started": send_loop_started,
            "send_loop_alive": send_loop_alive,
            "keepalive_loop_started": keepalive_loop_started,
            "keepalive_loop_alive": keepalive_loop_alive,
            "backend_connection_state": backend_connection_state,
            "provider_connected": provider_connected,
            "voice_scoring_ready": provider_connected and self._streaming_active,
            "deepgram_connected_no_audio_sent": (
                backend is not None
                and backend.connection_state() == "connected"
                and audio_bytes_sent == 0
            ),
        }

    def on_ended(self) -> None:
        """Called by streamlit-webrtc when the audio track ends.

        Must NOT call Streamlit APIs. Pushes a thread-safe lifecycle event
        into the module-level VoiceLifecycleEventQueue instead.
        """
        _last_frame_age_ms = None
        if self._last_audio_callback_ts:
            _last_frame_age_ms = (time.time() - self._last_audio_callback_ts) * 1000
        try:
            _voice_lifecycle_events.push(
                VoiceLifecycleEvent(
                    event_type="audio_processor_on_ended",
                    processor_id=id(self),
                    processor_generation=self._processor_generation,
                    timestamp=time.time(),
                    desired_mic_playing=None,  # read from session_state by caller
                    last_frame_age_ms=_last_frame_age_ms,
                    extra={
                        "audio_frames_received": self._audio_frames_received,
                        "runtime_mode": str(self._runtime_mode),
                    },
                )
            )
        except Exception:
            pass

    def get_lifecycle_events(self) -> List[VoiceLifecycleEvent]:
        """Drain lifecycle events for this processor (main thread)."""
        return _voice_lifecycle_events.drain()

    def get_calibration_trial_snapshot(self) -> Optional[dict]:
        """Return a thread-safe snapshot of the current calibration trial state."""
        with self._lock:
            ctx = self._calibration_context
            if ctx is None:
                return None
            return {
                "processor_id": id(self),
                "calibration_session_id": ctx.calibration_session_id,
                "trial_id": ctx.calibration_trial_id,
                "capture_kind": ctx.capture_kind,
                "expected_command_id": ctx.expected_command_id,
                "expected_phrase": ctx.expected_phrase,
                "armed_at": ctx.armed_at,
                "claimed": False,
            }

    def set_calibration_context(self, context: Optional[CalibrationCaptureContext]) -> None:
        """Atomically set calibration capture context under the processor lock."""
        with self._lock:
            self._calibration_context = context

    def arm_calibration_trial(
        self,
        context: CalibrationCaptureContext,
    ) -> CalibrationArmAcknowledgement:
        """Arm a calibration trial with typed acknowledgement.

        Returns CalibrationArmAcknowledgement with accepted=True when the
        processor successfully stores the context. Otherwise returns
        accepted=False with a rejection reason.
        """
        
        self._emit_runtime_audit(
            "calibration_command_trial_arm_requested",
            f"processor_id={id(self)} "
            f"session={context.calibration_session_id[:8]} "
            f"trial={context.calibration_trial_id[:8]} "
            f"kind={context.capture_kind.value} "
            f"command={context.expected_command_id} "
            f"phrase={context.expected_phrase}",
        )
        with self._lock:
            if self._calibration_context is not None:
                reason = "active_capture_already_set"
                self._emit_runtime_audit(
                    "calibration_command_trial_arm_rejected",
                    f"processor_id={id(self)} "
                    f"session={context.calibration_session_id[:8]} "
                    f"trial={context.calibration_trial_id[:8]} "
                    f"reason={reason}",
                )
                return CalibrationArmAcknowledgement(
                    accepted=False,
                    processor_id=id(self),
                    calibration_session_id=context.calibration_session_id,
                    trial_id=context.calibration_trial_id,
                    capture_kind=context.capture_kind,
                    armed_at=None,
                    rejection_reason=reason,
                )
            armed_at = time.time()
            self._calibration_context = dataclasses.replace(
                context, armed_at=armed_at
            )
            self._emit_runtime_audit(
                "calibration_command_trial_armed",
                f"processor_id={id(self)} "
                f"session={context.calibration_session_id[:8]} "
                f"trial={context.calibration_trial_id[:8]} "
                f"kind={context.capture_kind.value} "
                f"command={context.expected_command_id} "
                f"phrase={context.expected_phrase} "
                f"armed_at={armed_at:.3f}",
            )
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(self),
                calibration_session_id=context.calibration_session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=context.capture_kind,
                armed_at=armed_at,
                rejection_reason=None,
            )

    def set_runtime_mode(self, mode: VoiceRuntimeMode) -> None:
        """Set the runtime mode atomically under the processor lock."""
        with self._lock:
            self._runtime_mode = mode

    def _emit_runtime_audit(self, stage: str, note: str = "", **metadata) -> None:
        """Emit an immutable audit event to the bounded queue.

        Safe from any thread. Never touches Streamlit.
        """
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceRuntimeAuditEvent,
        )

        event = VoiceRuntimeAuditEvent(
            timestamp=time.time(),
            processor_id=id(self),
            processor_generation=self._processor_generation,
            thread_name=threading.current_thread().name,
            stage=stage,
            note=note,
            metadata=tuple(sorted(metadata.items())),
        )
        try:
            self._audit_queue.put_nowait(event)
        except queue.Full:
            self._audit_dropped_count += 1
            logger.debug("Audit queue full; dropped event stage=%s", stage)

    def drain_runtime_audit_events(self) -> tuple[VoiceRuntimeAuditEvent, ...]:
        """Drain all pending audit events from the thread-safe queue.

        Returns a tuple of events. The queue is emptied so the same events
        are not returned on subsequent calls. Safe to call from the main
        Streamlit thread only.
        """
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceRuntimeAuditEvent,
        )

        events: list[VoiceRuntimeAuditEvent] = []
        while True:
            try:
                events.append(self._audit_queue.get_nowait())
            except queue.Empty:
                break
        return tuple(events)

    def _clear_acoustic_capture_locked(
        self,
        *,
        reason: str,
        expected_measurement_id: str | None = None,
    ) -> bool:
        if self._active_acoustic_capture is None:
            return False
        if expected_measurement_id is not None:
            if self._active_acoustic_capture.measurement_id != expected_measurement_id:
                
                self._emit_runtime_audit(
                    "calibration_acoustic_cancel_mismatch",
                    f"requested={expected_measurement_id[:8] if expected_measurement_id else 'none'} active={self._active_acoustic_capture.measurement_id[:8]}",
                )
                return False
        active_measurement_id = getattr(self._active_acoustic_capture, "measurement_id", None)
        self._active_acoustic_capture = None
        self._acoustic_accumulator = None
        self._last_acoustic_clear_reason = reason
        
        mid_str = active_measurement_id[:8] if active_measurement_id else "none"
        self._emit_runtime_audit(
            "calibration_acoustic_capture_cleared",
            f"measurement={mid_str} reason={reason}",
        )
        return True

    def claim_capture_snapshot(self) -> CaptureSnapshot:
        """Atomically read and clear calibration context, capturing runtime mode and session ID."""
        with self._lock:
            snapshot = CaptureSnapshot(
                runtime_mode=self._runtime_mode,
                calibration_context=self._calibration_context,
                runtime_session_id=self._session_id,
            )
            self._calibration_context = None
            return snapshot

    def clear_calibration_context(self) -> None:
        """Clear calibration capture context."""
        with self._lock:
            self._calibration_context = None

    def transition_runtime(
        self,
        target_mode: VoiceRuntimeMode,
        continuous_session_id: Optional[str] = None,
        clear_calibration_state: bool = False,
    ) -> RuntimeTransitionAcknowledgement:
        """Atomically transition the processor to a new runtime mode.

        When ``clear_calibration_state`` is True, clears calibration context,
        active acoustic capture, and pending calibration work items from the
        chunk queue before applying the new mode.

        Returns a ``RuntimeTransitionAcknowledgement`` reflecting the actual
        post-transition processor state. The caller must verify ``accepted``
        before treating the transition as successful.
        """
        

        with self._lock:
            previous_mode = self._runtime_mode
            previous_session_id = self._session_id
            calibration_cleared = False
            acoustic_cleared = False
            work_cleared = False

            if clear_calibration_state:
                calibration_cleared = self._calibration_context is not None
                self._calibration_context = None

                if self._active_acoustic_capture is not None:
                    self._clear_acoustic_capture_locked(
                        reason="transition_runtime_clear"
                    )
                    acoustic_cleared = True
                else:
                    acoustic_cleared = True

                work_cleared = self._drain_pending_calibration_work_locked()

            if target_mode == VoiceRuntimeMode.LIVE:
                if continuous_session_id is not None:
                    self._session_id = continuous_session_id
            elif target_mode == VoiceRuntimeMode.OFF:
                # Invalidate streaming generation BEFORE any backend shutdown
                # so in-flight finalized utterances are rejected (plan Â§8A).
                self._streaming_generation += 1
                self._streaming_active = False
                self._seen_utterance_ids.clear()
                if self._streaming_backend is not None:
                    self._streaming_backend.finalize_utterance()
                self._session_id = None
            elif target_mode == VoiceRuntimeMode.CALIBRATION:
                pass

            self._runtime_mode = target_mode

            ack = RuntimeTransitionAcknowledgement(
                accepted=True,
                processor_id=id(self),
                previous_mode=previous_mode,
                new_mode=self._runtime_mode,
                previous_continuous_session_id=previous_session_id,
                new_continuous_session_id=self._session_id,
                calibration_context_cleared=calibration_cleared,
                acoustic_capture_cleared=acoustic_cleared,
                pending_calibration_work_cleared=work_cleared,
                config_revision=self._config_revision,
                rejection_reason=None,
                transitioned_at=time.time(),
            )

        self._emit_runtime_audit(
            "runtime_transition",
            f"processor_id={id(self)} "
            f"previous_mode={previous_mode.value} "
            f"new_mode={target_mode.value} "
            f"previous_session={previous_session_id[:8] if previous_session_id else 'none'} "
            f"new_session={self._session_id[:8] if self._session_id else 'none'} "
            f"clear_calibration={clear_calibration_state} "
            f"calibration_cleared={ack.calibration_context_cleared} "
            f"acoustic_cleared={ack.acoustic_capture_cleared}",
        )
        return ack

    def _drain_pending_calibration_work_locked(self) -> bool:
        """Drain calibration-related items from the chunk queue while holding ``self._lock``.

        Returns True if any work items were drained.
        """
        drained_any = False
        while True:
            try:
                item = self._chunk_queue.get_nowait()
            except queue.Empty:
                break
            if getattr(item, 'calibration_context', None) is not None:
                drained_any = True
            else:
                try:
                    self._chunk_queue.put_nowait(item)
                except queue.Full:
                    pass
        return drained_any

    def arm_acoustic_capture(self, context: AcousticCaptureContext) -> bool:
        """Arm an acoustic measurement capture.

        Returns True when the capture was armed. Returns False when a capture
        is already active and the new request is rejected.
        """
        
        self._emit_runtime_audit(
            "calibration_acoustic_arm_requested",
            f"session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value}",
        )
        with self._lock:
            if self._active_acoustic_capture is not None:
                self._emit_runtime_audit(
                    "calibration_acoustic_arm_rejected",
                    "active_capture_already_set",
                )
                return False
            self._active_acoustic_capture = context
            self._acoustic_accumulator = AcousticAccumulator(
                measurement_id=context.measurement_id,
                calibration_session_id=context.calibration_session_id,
                kind=context.kind,
                sample_rate_hz=self.audio_buffer.sample_rate,
                channel_count=self.audio_buffer.channels,
                target_sample_frame_count=round(
                    self.audio_buffer.sample_rate * context.target_duration_ms / 1000
                ),
                armed_at=context.armed_at_monotonic,
                timeout_ms=context.timeout_ms,
            )
            self._last_acoustic_arm_ts = context.armed_at_monotonic
            self._last_armed_measurement_id = context.measurement_id
            self._emit_runtime_audit(
                "calibration_acoustic_arm_accepted",
                f"session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value}",
            )
            if self._active_acoustic_capture is None or self._acoustic_accumulator is None:
                self._clear_acoustic_capture_locked(reason="arm_state_verification_failed")
                self._emit_runtime_audit(
                    "arm_state_verification_failed",
                    f"processor_id={id(self)} session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value} accumulator_present=False snapshot_active=False",
                )
                return False
            if self._active_acoustic_capture.measurement_id != context.measurement_id:
                self._clear_acoustic_capture_locked(reason="arm_state_verification_failed")
                self._emit_runtime_audit(
                    "arm_state_verification_failed",
                    f"processor_id={id(self)} session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value} accumulator_present=True snapshot_active=False",
                )
                return False
            if self._active_acoustic_capture.kind != context.kind:
                self._clear_acoustic_capture_locked(reason="arm_state_verification_failed")
                self._emit_runtime_audit(
                    "arm_state_verification_failed",
                    f"processor_id={id(self)} session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value} accumulator_present=True snapshot_active=False",
                )
                return False
            self._emit_runtime_audit(
                "calibration_acoustic_arm_state_verified",
                f"processor_id={id(self)} session={context.calibration_session_id[:8]} measurement={context.measurement_id[:8]} kind={context.kind.value} accumulator_present=True snapshot_active=True",
            )
            return True

    def cancel_acoustic_capture(
        self,
        *,
        measurement_id: str | None = None,
    ) -> bool:
        """Cancel the active acoustic capture.

        If measurement_id is provided, only cancels when it matches the
        active capture. Returns True if a capture was cleared.
        """
        with self._lock:
            return self._clear_acoustic_capture_locked(
                reason="operator_cancelled",
                expected_measurement_id=measurement_id,
            )

    def has_active_acoustic_capture(self) -> bool:
        """Return True when an acoustic capture is armed."""
        with self._lock:
            return self._active_acoustic_capture is not None

    def get_acoustic_capture_snapshot(self) -> AcousticCaptureRuntimeSnapshot:
        """Return a thread-safe snapshot of the current acoustic capture state."""
        with self._lock:
            context = self._active_acoustic_capture
            accumulator = self._acoustic_accumulator
            now = time.monotonic()
            elapsed_ms = (
                (now - accumulator.armed_at) * 1000.0
                if accumulator is not None
                else 0.0
            )
            completion_reason = None
            if accumulator is not None:
                if accumulator.is_complete:
                    completion_reason = "complete"
                elif accumulator.is_expired:
                    completion_reason = "expired"
            return AcousticCaptureRuntimeSnapshot(
                processor_id=id(self),
                active=context is not None,
                calibration_session_id=context.calibration_session_id if context else None,
                measurement_id=context.measurement_id if context else None,
                kind=context.kind if context else None,
                accumulator_present=accumulator is not None,
                frame_count=accumulator._frame_count if accumulator else 0,
                sample_count=accumulator._scalar_sample_count if accumulator else 0,
                sample_rate_hz=accumulator.sample_rate_hz if accumulator else None,
                channels=accumulator.channel_count if accumulator else None,
                elapsed_ms=elapsed_ms,
                result_queue_size=self._measurement_result_queue.qsize(),
                completion_reason=completion_reason,
            )

    def _classify_frame_once(
        self,
        *,
        frame_bytes: bytes,
        sample_rate_hz: int,
    ) -> AudioFrameDecision:
        """Compute the production frame decision once: noise gate + VAD.

        This preserves the exact original production logic from
        VoiceAudioBuffer.push_frame() so the measurement tap never bypasses
        the noise gate.
        """
        rms = self.audio_buffer._compute_rms(frame_bytes)
        passes_noise_gate = (
            self.audio_buffer.noise_gate_rms <= 0.0
            or rms >= self.audio_buffer.noise_gate_rms
        )
        vad_speech = False
        if passes_noise_gate and self.audio_buffer.vad is not None:
            vad_speech = self.audio_buffer.vad.is_speech(frame_bytes, sample_rate_hz)
        is_speech = vad_speech or (passes_noise_gate and rms > self.audio_buffer.silence_threshold)
        return AudioFrameDecision(passes_noise_gate=passes_noise_gate, is_speech=is_speech)

    def poll_acoustic_capture_timeout(
        self,
        *,
        now_monotonic: float | None = None,
    ) -> tuple[AcousticMeasurementResult, ...]:
        """Poll for acoustic capture timeout and emit incomplete results.

        Safe to call from any thread. Returns any newly emitted results.
        """
        if now_monotonic is None:
            now_monotonic = time.monotonic()

        results: list[AcousticMeasurementResult] = []
        with self._lock:
            accumulator = self._acoustic_accumulator
            context = self._active_acoustic_capture
            if accumulator is None or context is None:
                return tuple(results)

            if not accumulator.is_expired:
                return tuple(results)

            completed = accumulator
            self._clear_acoustic_capture_locked(reason="timeout_expired")

        if completed is not None:
            
            self._emit_runtime_audit(
                "calibration_acoustic_capture_cleared",
                f"measurement={completed.measurement_id[:8]} reason=timeout_expired",
            )
            from tournament_platform.app.services.voice_calibration.measurements import (
                compute_silence_baseline_metrics,
                compute_speech_level_metrics,
            )

            if completed.kind == CalibrationMeasurementKind.SILENCE_BASELINE:
                result: AcousticMeasurementResult = compute_silence_baseline_metrics(completed)
            else:
                result = compute_speech_level_metrics(completed)

            try:
                self._measurement_result_queue.put_nowait(result)
                results.append(result)
            except queue.Full:
                logger.warning(
                    "Acoustic measurement result queue full on timeout; dropping result measurement_id=%s",
                    completed.measurement_id,
                )

        return tuple(results)

    def drain_acoustic_measurement_results(
        self,
    ) -> tuple[AcousticMeasurementResult, ...]:
        """Drain all pending measurement results from the queue.

        Returns a tuple of results. The queue is emptied so the same result
        is not returned on subsequent calls.
        """
        
        self.poll_acoustic_capture_timeout()
        results: list[AcousticMeasurementResult] = []
        while True:
            try:
                results.append(self._measurement_result_queue.get_nowait())
            except queue.Empty:
                break
        if results:
            self._emit_runtime_audit(
                "calibration_acoustic_result_drained",
                f"count={len(results)} queue_size={self._measurement_result_queue.qsize()}",
            )
        return tuple(results)

    def apply_runtime_config(self, config: LiveVoiceRuntimeConfig) -> None:
        """Apply a validated runtime configuration atomically.

        Updates noise gate, strict mode, preferred phrases, confirmed aliases,
        and ASR configuration under the processor lock. Does NOT write to
        ``st.session_state`` from the audio thread.

        Args:
            config: The validated runtime configuration to apply.
        """
        with self._lock:
            self._config_revision = config.revision
            self.audio_buffer.noise_gate_rms = (
                config.noise_threshold_rms if config.noise_gate_enabled else 0.0
            )
            self._voice_strict_mode = config.strict_mode_enabled
            self._preferred_phrases = config.preferred_phrases
            self._confirmed_aliases = config.confirmed_aliases
            self._asr_config = config.asr_config

    def get_current_runtime_config(self) -> LiveVoiceRuntimeConfig:
        """Return a thread-safe snapshot of the current runtime configuration."""
        with self._lock:
            return LiveVoiceRuntimeConfig(
                revision=self._config_revision,
                noise_gate_enabled=self.audio_buffer.noise_gate_rms > 0.0,
                noise_threshold_rms=self.audio_buffer.noise_gate_rms,
                strict_mode_enabled=self._voice_strict_mode,
                preferred_phrases=self._preferred_phrases,
                confirmed_aliases=self._confirmed_aliases,
                asr_config=self._asr_config,
            )

    def _observe_acoustic_frame(
        self,
        *,
        normalized_samples: np.ndarray,
        sample_rate_hz: int,
        channel_count: int,
        is_speech: bool,
        timestamp: float,
    ) -> None:
        """Observe a single normalized audio frame for acoustic measurement.

        Returns immediately when no capture is armed. Validates sample rate
        and channel count against the first frame, updates the accumulator,
        and finalizes when the target scalar sample count is reached.
        """
        
        with self._lock:
            context = self._active_acoustic_capture
            accumulator = self._acoustic_accumulator
            if context is None or accumulator is None:
                now = time.monotonic()
                if now - self._last_acoustic_arm_ts < 5.0:
                    self._emit_runtime_audit(
                        "calibration_acoustic_frame_without_active_capture",
                        f"processor_id={id(self)} last_armed_measurement_id={self._last_armed_measurement_id} last_arm_ts={self._last_acoustic_arm_ts:.3f} last_clear_reason={self._last_acoustic_clear_reason} time_since_arm={(now - self._last_acoustic_arm_ts) * 1000.0:.1f}ms",
                    )
                return

            if accumulator._first_sample_rate is None:
                accumulator._first_sample_rate = sample_rate_hz
                accumulator.channel_count = channel_count
            else:
                if sample_rate_hz != accumulator._first_sample_rate:
                    self._clear_acoustic_capture_locked(reason="sample_rate_changed")
                    return
                if channel_count != accumulator.channel_count:
                    self._clear_acoustic_capture_locked(reason="channel_count_changed")
                    return

            accumulator.observe(normalized_samples, is_speech, timestamp)

            global _acoustic_audit_last_frame_count
            frame_delta = accumulator._frame_count - _acoustic_audit_last_frame_count
            if frame_delta >= 50 or _acoustic_audit_last_frame_count == 0:
                _acoustic_audit_last_frame_count = accumulator._frame_count
                self._emit_runtime_audit(
                    "calibration_acoustic_frame_observed",
                    f"measurement={context.measurement_id[:8]} "
                    f"frames={accumulator._frame_count} "
                    f"samples={accumulator._scalar_sample_count} "
                    f"rate={sample_rate_hz}Hz "
                    f"channels={channel_count}",
                )

            if accumulator.is_complete or accumulator.is_expired:
                completed = self._acoustic_accumulator
                self._clear_acoustic_capture_locked(
                    reason="complete" if accumulator.is_complete else "expired"
                )
            else:
                completed = None

        if completed is not None:
            try:
                from tournament_platform.app.services.voice_calibration.measurements import (
                    compute_silence_baseline_metrics,
                    compute_speech_level_metrics,
                )

                if completed.kind == CalibrationMeasurementKind.SILENCE_BASELINE:
                    result: AcousticMeasurementResult = compute_silence_baseline_metrics(completed)
                else:
                    result = compute_speech_level_metrics(completed)

                completion_reason = "complete" if completed.is_complete else "expired"
                self._emit_runtime_audit(
                    "calibration_acoustic_target_reached",
                    f"measurement={completed.measurement_id[:8]} "
                    f"kind={completed.kind.value} "
                    f"frames={completed._frame_count} "
                    f"samples={completed._scalar_sample_count} "
                    f"reason={completion_reason}",
                )

                try:
                    self._measurement_result_queue.put_nowait(result)
                    self._emit_runtime_audit(
                        "calibration_acoustic_result_enqueued",
                        f"measurement={completed.measurement_id[:8]} "
                        f"queue_size={self._measurement_result_queue.qsize()}",
                    )
                except queue.Full:
                    logger.warning(
                        "Acoustic measurement result queue full; dropping result measurement_id=%s",
                        completed.measurement_id,
                    )
            except Exception as exc:
                logger.debug("Acoustic measurement result computation failed: %s", exc)

    def _log_rate_limited(self, message: str, exc: Optional[Exception] = None) -> None:
        """Log repeated audio/transcription errors at most once per 30 seconds."""
        now = time.time()
        self._audio_error_count += 1
        if now - self._last_audio_error_log_ts >= 30.0:
            last_err = str(exc) if exc else ""
            logger.warning(
                "%s: %d failures in last 30s. Last error: %s",
                message,
                self._audio_error_count,
                last_err,
            )
            self._last_audio_error_log_ts = now
            self._audio_error_count = 0

    def _ensure_worker_running(self) -> bool:
        """Instance-owned, locked, idempotent worker startup."""
        try:
            with self._lock:
                if self._worker_thread is not None and self._worker_thread.is_alive():
                    return True
                self._stop_worker.clear()
                self._worker_started = True

                def _worker_loop() -> None:
                    """Consume work items from _chunk_queue and transcribe them safely."""
                    try:
                        while not self._stop_worker.is_set():
                            asr = self._get_asr()
                            if asr is None:
                                self._set_status("ASR unavailable")
                                break

                            try:
                                work_item = self._chunk_queue.get(timeout=0.25)
                            except queue.Empty:
                                continue

                            if work_item is None:
                                continue

                            self._last_work_item_timestamp = time.time()
                            self._transcription_calls_started += 1
                            
                            _cal_ctx = work_item.calibration_context
                            self._emit_runtime_audit(
                                "voice_asr_work_item_dequeued",
                                f"processor_id={id(self)} "
                                f"work_item_id={id(work_item)} "
                                f"runtime_mode={work_item.capture_runtime_mode} "
                                f"calibration_session_id={getattr(_cal_ctx, 'calibration_session_id', None) or 'none'} "
                                f"calibration_trial_id={getattr(_cal_ctx, 'calibration_trial_id', None) or 'none'} "
                                f"capture_kind={getattr(_cal_ctx, 'capture_kind', None) or 'none'} "
                                f"queue_size={self._chunk_queue.qsize()}",
                            )
                            self._transcribe_chunk(work_item)
                            self._transcription_calls_completed += 1
                    except Exception as exc:
                        self._worker_exception = exc
                        logger.exception("Worker loop exception: %s", exc)
                    finally:
                        self._worker_started = False

                self._worker_thread = threading.Thread(target=_worker_loop, daemon=True)
                self._worker_thread.start()
                return True
        except Exception as exc:
            self._worker_exception = exc
            logger.exception("Failed to start worker: %s", exc)
            return False

    def _start_worker(self) -> None:
        """Start the single background transcription worker for this instance if not already running."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._stop_worker.clear()
        self._worker_started = True

        def _worker_loop() -> None:
            """Consume work items from _chunk_queue and transcribe them safely."""
            try:
                while not self._stop_worker.is_set():
                    asr = self._get_asr()
                    if asr is None:
                        self._set_status("ASR unavailable")
                        break

                    try:
                        work_item = self._chunk_queue.get(timeout=0.25)
                    except queue.Empty:
                        continue

                    if work_item is None:
                        continue

                    self._last_work_item_timestamp = time.time()
                    self._transcription_calls_started += 1
                    
                    _cal_ctx = work_item.calibration_context
                    self._emit_runtime_audit(
                        "voice_asr_work_item_dequeued",
                        f"processor_id={id(self)} "
                        f"work_item_id={id(work_item)} "
                        f"runtime_mode={work_item.capture_runtime_mode} "
                        f"calibration_session_id={getattr(_cal_ctx, 'calibration_session_id', None) or 'none'} "
                        f"calibration_trial_id={getattr(_cal_ctx, 'calibration_trial_id', None) or 'none'} "
                        f"capture_kind={getattr(_cal_ctx, 'capture_kind', None) or 'none'} "
                        f"queue_size={self._chunk_queue.qsize()}",
                    )
                    self._transcribe_chunk(work_item)
                    self._transcription_calls_completed += 1
            except Exception as exc:
                self._worker_exception = exc
                logger.exception("Worker loop exception: %s", exc)
            finally:
                self._worker_started = False

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        self._worker_thread.start()

    def _ingest_frame(self, frame) -> None:
        """Legacy wrapper: copy frame into a packet and ingest it in the worker.

        Kept for backward compatibility. New code paths should enqueue
        ``AudioIngressPacket`` directly and let the worker call
        ``_ingest_packet``.
        """
        packet = self._copy_audio_packet(frame)
        self._ingest_packet(packet)

    def _reject_chunk(
        self,
        *,
        reason: str,
        capture_runtime_mode: Optional[VoiceRuntimeMode] = None,
        continuous_session_id: Optional[str] = None,
    ) -> None:
        """Record a chunk rejection with typed reason and diagnostics."""
        self._chunk_enqueue_rejected += 1
        self._last_chunk_rejection_reason = reason
        self._rejected_by_reason[reason] = self._rejected_by_reason.get(reason, 0) + 1
        self._last_chunk_admission_outcome = "REJECTED"
        if capture_runtime_mode is not None:
            self._last_chunk_runtime_mode = capture_runtime_mode.value
        if continuous_session_id is not None:
            self._last_chunk_continuous_session_id = continuous_session_id
        
        self._emit_runtime_audit(
            "voice_asr_chunk_rejected",
            f"processor_id={id(self)} "
            f"chunk_id={self._chunks_created} "
            f"reason={reason} "
            f"runtime_mode={capture_runtime_mode.value if capture_runtime_mode else 'unknown'} "
            f"session={continuous_session_id[:8] if continuous_session_id else 'none'}",
        )

    def _evaluate_disabled_mode(self) -> AudioAdmissionDecision:
        """Use ``CalibrationPolicy`` to decide the OFF-mode rejection reason.

        For streaming backends (Deepgram) the reason is ``runtime_voice_disabled``;
        for legacy local batch providers it remains ``runtime_off_no_calibration_context``
        so existing regression tests stay green (plan Â§3.8).
        """
        if self._calibration_policy is not None:
            return self._calibration_policy.evaluate_disabled_mode()
        # No policy attached â use local_batch_policy to preserve the
        # original behavior for existing batch providers.
        return local_batch_policy().evaluate_disabled_mode()

    def _enqueue_chunk(self, chunk: AudioChunk) -> None:
        """Enqueue a chunk with explicit admission rules and full observability.

        Admission rules:
            Calibration work:
                valid CalibrationCaptureContext exists
                AND the context is armed (armed_at is not None)
                â source=calibration, enqueue calibration work item

            Live continuous work:
                runtime_mode == LIVE
                AND continuous session ID exists
                AND no calibration context is attached
                â source=continuous, enqueue live work item

            All other cases are rejected with a typed reason.
        """
        

        self._chunk_enqueue_attempts += 1
        self._last_chunk_timestamp = time.time()

        worker_ok = self._ensure_worker_running()
        if not worker_ok:
            self._reject_chunk(reason="worker_unavailable")
            return

        snapshot = self.claim_capture_snapshot()
        runtime_mode = snapshot.runtime_mode
        calibration_context = snapshot.calibration_context
        session_id = snapshot.runtime_session_id

        capture_source: Optional[VoiceTranscriptSource] = None
        effective_mode: VoiceRuntimeMode = runtime_mode
        armed = calibration_context is not None and calibration_context.armed_at is not None

        if calibration_context is not None:
            if armed:
                effective_mode = VoiceRuntimeMode.CALIBRATION
                capture_source = VoiceTranscriptSource.CALIBRATION
            else:
                self._reject_chunk(
                    reason="stale_calibration_context",
                    capture_runtime_mode=runtime_mode,
                    continuous_session_id=session_id,
                )
                return
        else:
            if runtime_mode == VoiceRuntimeMode.LIVE:
                if session_id is None:
                    self._reject_chunk(
                        reason="missing_continuous_session",
                        capture_runtime_mode=runtime_mode,
                        continuous_session_id=session_id,
                    )
                    return
                effective_mode = VoiceRuntimeMode.LIVE
                capture_source = VoiceTranscriptSource.CONTINUOUS
            elif runtime_mode == VoiceRuntimeMode.CALIBRATION:
                self._reject_chunk(
                    reason="runtime_still_calibration",
                    capture_runtime_mode=runtime_mode,
                    continuous_session_id=session_id,
                )
                return
            elif runtime_mode == VoiceRuntimeMode.OFF:
                decision = self._evaluate_disabled_mode()
                self._reject_chunk(
                    reason=decision.rejection_reason,
                    capture_runtime_mode=runtime_mode,
                    continuous_session_id=session_id,
                )
                return

        if capture_source is None:
            self._reject_chunk(
                reason="unknown_rejection",
                capture_runtime_mode=runtime_mode,
                continuous_session_id=session_id,
            )
            return

        work_item_id = f"wi_{id(chunk)}_{time.time()}"
        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id=session_id,
            calibration_context=calibration_context,
            capture_runtime_mode=effective_mode,
        )

        self._current_work_item_id = work_item_id
        self._current_work_item_stage = "enqueued"
        self._queued_work_item_ids.append(work_item_id)

        try:
            self._chunk_queue.put_nowait(work_item)
        except queue.Full:
            try:
                self._chunk_queue.get_nowait()
                self._dropped_chunks += 1
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait(work_item)
            except queue.Full:
                self._reject_chunk(
                    reason="queue_full",
                    capture_runtime_mode=effective_mode,
                    continuous_session_id=session_id,
                )
                return

        self._chunk_enqueue_accepted += 1
        self._work_items_enqueued += 1
        self._last_chunk_admission_outcome = "ENQUEUED"
        self._last_chunk_runtime_mode = effective_mode.value
        self._last_chunk_capture_source = capture_source.value
        self._last_chunk_continuous_session_id = session_id

        _cal_ctx = work_item.calibration_context
        self._emit_runtime_audit(
            "voice_asr_work_item_enqueued",
            f"processor_id={id(self)} "
            f"chunk_id={self._chunks_created} "
            f"work_item_id={work_item_id} "
            f"runtime_mode={work_item.capture_runtime_mode} "
            f"calibration_session_id={getattr(_cal_ctx, 'calibration_session_id', None) or 'none'} "
            f"calibration_trial_id={getattr(_cal_ctx, 'calibration_trial_id', None) or 'none'} "
            f"capture_kind={getattr(_cal_ctx, 'capture_kind', None) or 'none'} "
            f"queue_size={self._chunk_queue.qsize()}",
        )

    def _copy_audio_packet(self, frame) -> AudioIngressPacket:
        """Extract a minimal immutable audio packet from a WebRTC frame.

        This is the only place where the callback touches frame data.
        It must be fast and never block.
        """
        import uuid as _uuid

        array = _frame_to_ndarray(frame)
        if array is None:
            # Return an empty packet; the worker will drop it.
            pcm_bytes = b""
        else:
            pcm_bytes = array.tobytes()

        return AudioIngressPacket(
            packet_id=_uuid.uuid4().hex,
            processor_id=id(self),
            processor_generation=self._processor_generation,
            voice_session_id=self._session_id or "",
            created_at=time.monotonic(),
            pcm_bytes=pcm_bytes,
            sample_rate=getattr(frame, "sample_rate", self.audio_buffer.sample_rate),
            channels=getattr(frame, "channels", self.audio_buffer.channels),
            pts=float(getattr(frame, "pts", time.time())),
            format_name=getattr(getattr(frame, "format", None), "name", None),
        )

    def _ingest_packet(self, packet: AudioIngressPacket) -> None:
        """Process one audio ingress packet in the background worker.

        Contains the full production logic previously in ``_ingest_frame``.
        """
        if not packet.pcm_bytes:
            return

        self._audio_frames_received += 1
        _frame_idx = self._audio_frames_received
        if _frame_idx % 50 == 0 or _frame_idx == 1:
            self._emit_runtime_audit(
                "voice_frame_received",
                f"processor_id={id(self)} "
                f"generation={self._processor_generation} "
                f"frame={_frame_idx} "
                f"pts={packet.pts:.3f}",
            )

        fmt_name = packet.format_name
        sample_rate = packet.sample_rate
        channels = packet.channels
        frame_bytes = packet.pcm_bytes

        detected_format = None
        if fmt_name in ("s16", "s16p"):
            detected_format = SAMPLE_FORMAT_INT16
        elif fmt_name in ("flt", "fltp", "f32", "f32p"):
            detected_format = SAMPLE_FORMAT_FLOAT32

        if detected_format is None:
            detected_format = self._sample_format

        needs_flush = False
        if detected_format != self._sample_format:
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
                    self._enqueue_chunk(flushed)

        if detected_format != self._sample_format:
            self._sample_format = detected_format
            if self.audio_buffer.sample_format != self._sample_format:
                self.audio_buffer.update_format(sample_format=self._sample_format)

        if sample_rate is not None and sample_rate != self.audio_buffer.sample_rate:
            self.audio_buffer.update_format(sample_rate=sample_rate)

        if channels is not None and channels != self.audio_buffer.channels:
            self.audio_buffer.update_format(channels=channels)

        try:
            normalized = normalize_pcm(frame_bytes, self._sample_format, self.audio_buffer.channels)
        except InvalidFrameFormat:
            normalized = None

        decision = None
        if normalized is not None and normalized.size > 0:
            decision = self._classify_frame_once(
                frame_bytes=frame_bytes,
                sample_rate_hz=self.audio_buffer.sample_rate,
            )

            self._last_frame_rms = self.audio_buffer._compute_rms(frame_bytes)
            self._last_frame_normalized_rms = (
                float(np.sqrt(np.mean(normalized.astype(np.float64) ** 2))) if normalized.size > 0 else 0.0
            )
            self._above_threshold = decision.passes_noise_gate
            self._vad_decision = decision.is_speech
            self._frame_classification_count += 1
            _frame_idx = self._frame_classification_count

            if _frame_idx % 50 == 0 or _frame_idx == 1:
                self._emit_runtime_audit(
                    "voice_frame_classified",
                    f"processor_id={id(self)} "
                    f"generation={self._processor_generation} "
                    f"frame={_frame_idx} "
                    f"rms={self._last_frame_rms:.6f} "
                    f"normalized_rms={self._last_frame_normalized_rms:.6f} "
                    f"passes_gate={decision.passes_noise_gate} "
                    f"vad={self._vad_decision} "
                    f"is_speech={decision.is_speech}",
                )

            if decision.is_speech:
                self._speech_frame_count += 1
                if self._speech_frame_count % 20 == 0:
                    self._emit_runtime_audit(
                        "voice_speech_segment_extended",
                        f"processor_id={id(self)} "
                        f"generation={self._processor_generation} "
                        f"speech_frames={self._speech_frame_count}",
                    )

            self._observe_acoustic_frame(
                normalized_samples=normalized,
                sample_rate_hz=self.audio_buffer.sample_rate,
                channel_count=self.audio_buffer.channels,
                is_speech=decision.is_speech,
                timestamp=packet.pts,
            )

        if self._streaming_backend is not None and self._streaming_active:
            self._route_streaming_audio(frame_bytes, detected_format, channels=channels, sample_rate=sample_rate)
            if self.tt_sounds_processor is not None:
                try:
                    self.tt_sounds_processor.ingest_frame(frame_bytes)
                except Exception:
                    pass
            return

        if self.effective_delivery_mode == "stream":
            self._streaming_audio_provider_unavailable += 1
            self._emit_runtime_audit(
                "streaming_audio_provider_unavailable",
                f"processor_id={id(self)} "
                f"delivery_mode=stream "
                f"backend_attached={self._streaming_backend is not None} "
                f"streaming_active={self._streaming_active} "
                f"reason=streaming_backend_not_attached",
            )
            return

        chunk = self.audio_buffer.push_frame(frame_bytes, decision=decision)

        if chunk is not None:
            self._chunks_created += 1
            self._enqueue_chunk(chunk)

    def _start_audio_ingress_worker(self) -> None:
        """Start the single audio-ingress worker thread if not already running."""
        if self._audio_ingress_worker_thread is not None and self._audio_ingress_worker_thread.is_alive():
            return

        self._stop_audio_ingress_worker_event.clear()
        self._audio_ingress_worker_started = True

        def _worker_loop() -> None:
            try:
                while not self._stop_audio_ingress_worker_event.is_set():
                    try:
                        packet = self._audio_ingress_queue.get(timeout=0.25)
                    except queue.Empty:
                        continue

                    if packet is None:
                        continue

                    try:
                        self._ingest_packet(packet)
                        self._audio_ingress_processed += 1
                    except Exception as exc:
                        self._audio_ingress_worker_failures += 1
                        self._last_audio_ingress_error = str(exc)
                        logger.debug("Audio ingress worker packet error: %s", exc)
            finally:
                self._audio_ingress_worker_started = False

        self._audio_ingress_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        self._audio_ingress_worker_thread.start()

    def _stop_audio_ingress_worker(self) -> None:
        """Stop the audio-ingress worker and drain the queue."""
        self._stop_audio_ingress_worker_event.set()
        if self._audio_ingress_worker_thread is not None and self._audio_ingress_worker_thread.is_alive():
            self._audio_ingress_worker_thread.join(timeout=1.0)
        self._audio_ingress_worker_thread = None
        self._audio_ingress_worker_started = False
        while not self._audio_ingress_queue.empty():
            try:
                self._audio_ingress_queue.get_nowait()
            except queue.Empty:
                break

    def recv(self, frame):
        """streamlit-webrtc callback (sync / non-async mode).

        Non-blocking producer: copies frame data into an immutable packet
        and enqueues it for the background audio-ingress worker.
        """
        self._recv_call_count += 1
        self._last_recv_timestamp = time.monotonic()
        now = time.time()
        _last_age = (now - self._last_audio_callback_ts) * 1000 if self._last_audio_callback_ts > 0 else None
        self._last_audio_callback_ts = now

        try:
            packet = self._copy_audio_packet(frame)
            self._audio_frames_received += 1
            self._last_frame_timestamp = packet.created_at

            # Point 7: Throttled heartbeat every 100 frames
            if self._audio_frames_received % 100 == 0 or self._audio_frames_received == 1:
                _voice_lifecycle_events.push(
                    VoiceLifecycleEvent(
                        event_type="last_audio_callback",
                        processor_id=id(self),
                        processor_generation=self._processor_generation,
                        timestamp=now,
                        desired_mic_playing=None,
                        last_frame_age_ms=_last_age,
                        extra={"frame_count": self._audio_frames_received},
                    )
                )

            try:
                self._audio_ingress_queue.put_nowait(packet)
                self._audio_ingress_accepted += 1
            except queue.Full:
                self._audio_ingress_queue_full += 1
            self._start_audio_ingress_worker()
            self._callback_count += 1
            with _factory_diag_lock:
                _factory_diag["callback_count"] = self._callback_count
            return frame
        except Exception as exc:
            self._callback_exception_count += 1
            self._last_callback_exception = str(exc)
            raise

    async def recv_queued(self, frames):
        """streamlit-webrtc callback (async mode — the default).

        Non-blocking producer: copies each frame into an immutable packet
        and enqueues it for the background audio-ingress worker.
        """
        self._recv_queued_call_count += 1
        self._last_recv_queued_timestamp = time.monotonic()
        now = time.time()
        _last_age = (now - self._last_audio_callback_ts) * 1000 if self._last_audio_callback_ts > 0 else None
        self._last_audio_callback_ts = now

        try:
            for frame in frames:
                packet = self._copy_audio_packet(frame)
                self._audio_frames_received += 1
                self._last_frame_timestamp = packet.created_at
                
                # Point 7: Throttled heartbeat every 100 frames
                if self._audio_frames_received % 100 == 0 or self._audio_frames_received == 1:
                    _voice_lifecycle_events.push(
                        VoiceLifecycleEvent(
                            event_type="last_audio_frame",
                            processor_id=id(self),
                            processor_generation=self._processor_generation,
                            timestamp=now,
                            desired_mic_playing=None,
                            last_frame_age_ms=_last_age,
                            extra={"frame_count": self._audio_frames_received},
                        )
                    )

                try:
                    self._audio_ingress_queue.put_nowait(packet)
                    self._audio_ingress_accepted += 1
                except queue.Full:
                    self._audio_ingress_queue_full += 1
            self._start_audio_ingress_worker()
            self._callback_count += 1
            with _factory_diag_lock:
                _factory_diag["callback_count"] = self._callback_count
            return frames
        except Exception as exc:
            self._callback_exception_count += 1
            self._last_callback_exception = str(exc)
            raise

    def _maybe_log_first_frame(self) -> None:
        """No-op in callback threads."""
        return

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return processor diagnostics for the UI panel."""
        return {
            "audio_frames_received": self._audio_frames_received,
            "audio_ingress_queue_full": self._audio_ingress_queue_full,  # Quick Win 11
            "dropped_frames": self._dropped_frames,  # Quick Win 11
            "chunks_created": self._chunks_created,
            "asr_events_enqueued": self._asr_events_enqueued,
            "dropped_chunks": self._dropped_chunks,
            "last_frame_timestamp": self._last_frame_timestamp,
            "last_chunk_timestamp": self._last_chunk_timestamp,
            "asr_ready": self._asr_ready,
            "asr_error": self._asr_error,
            "status": self._status,
            "processor_class": type(self).__name__,
            "processor_id": id(self),
            "processor_generation": self._processor_generation,
            "callback_count": self._callback_count,
            "worker_started": self._worker_started,
            "worker_thread_alive": self._worker_thread.is_alive() if self._worker_thread else False,
            "worker_exception": str(self._worker_exception) if self._worker_exception else None,
            "transcription_calls_started": self._transcription_calls_started,
            "transcription_calls_completed": self._transcription_calls_completed,
            "transcription_results_returned": self._transcription_results_returned,
            "worker_counter_invariant_valid": (
                self._transcription_calls_started
                >= self._transcription_calls_completed
                + self._blank_transcription_count
            ),
            "transcript_text_extracted": self._transcript_text_extracted,
            "events_built": self._events_built,
            "events_enqueued": self._events_enqueued,
            "blank_transcription_count": self._blank_transcription_count,
            "last_asr_latency_ms": self._last_asr_latency_ms,
            "last_asr_result_text": self._last_asr_result_text[:80] if self._last_asr_result_text else "",
            "last_terminal_outcome": self._last_terminal_outcome,
            "last_rejection_reason": self._last_rejection_reason,
            "current_work_item_id": self._current_work_item_id,
            "current_work_item_stage": self._current_work_item_stage,
            "queued_work_item_ids": self._queued_work_item_ids[-5:],
            "chunk_admission_attempts": self._chunk_enqueue_attempts,
            "chunks_enqueued": self._chunk_enqueue_accepted,
            "chunks_rejected": self._chunk_enqueue_rejected,
            "rejected_by_reason": dict(self._rejected_by_reason),
            "last_chunk_admission_outcome": self._last_chunk_admission_outcome,
            "last_chunk_rejection_reason": self._last_chunk_rejection_reason,
            "last_chunk_runtime_mode": self._last_chunk_runtime_mode,
            "last_chunk_capture_source": self._last_chunk_capture_source,
            "last_chunk_continuous_session_id": self._last_chunk_continuous_session_id,
            "work_items_enqueued": self._work_items_enqueued,
            "runtime_mode": self._runtime_mode.value if self._runtime_mode else None,
            "session_id": self._session_id,
            "last_frame_rms": self._last_frame_rms,
            "last_frame_normalized_rms": self._last_frame_normalized_rms,
            "noise_threshold_rms": self.audio_buffer.noise_gate_rms,
            "noise_threshold_dbfs": 20.0 * np.log10(max(self.audio_buffer.noise_gate_rms, 1e-10)) if self.audio_buffer.noise_gate_rms > 0 else None,
            "above_threshold": self._above_threshold,
            "vad_decision": self._vad_decision,
            "speech_frame_count": self._speech_frame_count,
            "frame_classification_count": self._frame_classification_count,
            "endpoint_reason": self._endpoint_reason,
            "recv_call_count": self._recv_call_count,
            "recv_queued_call_count": self._recv_queued_call_count,
            "last_recv_timestamp": self._last_recv_timestamp,
            "last_recv_queued_timestamp": self._last_recv_queued_timestamp,
            "last_ingest_timestamp": self._last_ingest_timestamp,
            "callback_exception_count": self._callback_exception_count,
            "last_callback_exception": self._last_callback_exception,
            "audit_dropped_count": self._audit_dropped_count,
            "audit_queue_size": self._audit_queue.qsize(),
        }

    def get_streaming_diagnostics(self) -> Dict[str, Any]:
        """Return merged streaming + batch diagnostics for the UI panel."""
        diags = self.get_diagnostics()
        diags.update(self.get_streaming_transport_stats())
        diags["interim_diagnostics_snapshot"] = self._diagnostic_snapshot
        diags["audio_delivery_mode"] = self.effective_delivery_mode
        diags["processor_id"] = id(self)
        diags["processor_generation"] = self._processor_generation
        diags["streaming_voice_session_id"] = self._streaming_voice_session_id
        diags["streaming_generation"] = self._streaming_generation
        diags["streaming_match_id"] = self._streaming_match_id
        diags["streaming_finalized_count"] = self._streaming_finalized
        diags["streaming_stale_count"] = self._streaming_stale
        diags["streaming_duplicate_count"] = self._streaming_duplicate
        diags["streaming_match_mismatch_count"] = self._streaming_match_mismatch
        diags["streaming_invalid_count"] = self._streaming_invalid
        diags["streaming_failed_count"] = self._streaming_failed
        diags["streaming_drain_calls"] = self._streaming_drain_calls
        diags["processor_finalized_queue_depth"] = self._finalized_utterance_queue.qsize()
        if self._streaming_backend is not None:
            diags["backend_object_id"] = id(self._streaming_backend)
            if hasattr(self._streaming_backend, "get_diagnostics"):
                try:
                    _backend_diag = self._streaming_backend.get_diagnostics()
                    diags["backend_finalized_emitted"] = _backend_diag.get(
                        "finalized_utterances_emitted", 0
                    )
                    diags["backend_finalized_queue_depth"] = _backend_diag.get(
                        "finalized_queue_size", 0
                    )
                    diags["expected_finalized_utterance_module"] = (
                        FinalizedUtterance.__module__
                    )
                except Exception:
                    pass
        diags["processor_streaming_events_drained"] = self._streaming_events_drained
        diags["last_finalized_invalid_type"] = self._last_finalized_invalid_type
        diags["last_finalized_invalid_module"] = self._last_finalized_invalid_module
        diags["last_finalized_invalid_repr"] = self._last_finalized_invalid_repr
        diags["last_finalized_invalid_queue_source"] = self._last_finalized_invalid_queue_source
        diags["last_finalized_invalid_backend_object_id"] = self._last_finalized_invalid_backend_object_id
        diags["last_finalized_invalid_processor_id"] = self._last_finalized_invalid_processor_id
        diags["last_finalized_invalid_utt_is_same_class"] = self._last_finalized_invalid_utt_is_same_class
        diags["last_finalized_invalid_utt_type_id"] = self._last_finalized_invalid_utt_type_id
        diags["last_finalized_invalid_expected_type_id"] = self._last_finalized_invalid_expected_type_id
        return diags

    def drain_streaming_events(self) -> List[FinalizedUtterance]:
        """Drain validated finalized utterances from the streaming backend.

        Reads the current voice session ID and backend generation from
        the processor's own tracking state and from Streamlit session_state
        for match ID.  Returns only utterances that pass generation +
        session + match validation (plan Â§8B double-check).
        """
        self._streaming_drain_calls += 1
        current_session = self._streaming_voice_session_id
        current_gen = self._streaming_generation
        current_match = self._streaming_match_id
        
        with self._lock:
            current_calibration = self._calibration_context

        # Collect ALL pending utterances â both from the internal queue
        # (re-queued by has_pending_events) and directly from the backend.
        all_utterances: List[FinalizedUtterance] = []
        queue_sources: List[str] = []

        while not self._finalized_utterance_queue.empty():
            try:
                all_utterances.append(self._finalized_utterance_queue.get_nowait())
                queue_sources.append("processor_internal_queue")
            except queue.Empty:
                break

        if self._streaming_backend is not None:
            try:
                backend_finalized = self._streaming_backend.get_finalized_transcripts()
                all_utterances.extend(backend_finalized)
                queue_sources.extend(["backend_finalized_queue"] * len(backend_finalized))
            except Exception as exc:
                logger.debug("drain_streaming_events: backend drain error: %s", exc)
                self._streaming_failed += 1

        # Validate EVERY utterance — generation, session, match, dedup
        validated: List[FinalizedUtterance] = []
        for idx, utt in enumerate(all_utterances):
            if not isinstance(utt, FinalizedUtterance):
                self._streaming_invalid += 1
                _invalid_type = type(utt)
                _queue_source = queue_sources[idx] if idx < len(queue_sources) else "unknown"
                self._last_finalized_invalid_type = _invalid_type.__name__
                self._last_finalized_invalid_module = getattr(
                    _invalid_type, "__module__", ""
                )
                self._last_finalized_invalid_repr = repr(utt)[:300]
                self._last_finalized_invalid_queue_source = _queue_source
                self._last_finalized_invalid_backend_object_id = (
                    id(self._streaming_backend) if self._streaming_backend else 0
                )
                self._last_finalized_invalid_processor_id = id(self)
                self._last_finalized_invalid_utt_is_same_class = (
                    _invalid_type is FinalizedUtterance
                )
                self._last_finalized_invalid_utt_type_id = id(_invalid_type)
                self._last_finalized_invalid_expected_type_id = id(FinalizedUtterance)
                logger.debug(
                    "drain_streaming_events: invalid finalized item type=%s module=%s "
                    "repr=%s queue_source=%s backend_id=%s processor_id=%s "
                    "is_same_class=%s type_id=%s expected_id=%s",
                    _invalid_type.__name__,
                    getattr(_invalid_type, "__module__", ""),
                    repr(utt)[:300],
                    _queue_source,
                    id(self._streaming_backend) if self._streaming_backend else 0,
                    id(self),
                    _invalid_type is FinalizedUtterance,
                    id(_invalid_type),
                    id(FinalizedUtterance),
                )
                continue

            # Generation check
            if utt.backend_generation != current_gen:
                self._streaming_stale += 1
                logger.debug("drain_streaming_events: stale generation: %s != %s",
                             utt.backend_generation, current_gen)
                continue

            # Session check
            if (
                current_session is not None
                and utt.voice_session_id != current_session
            ):
                self._streaming_stale += 1
                logger.debug("drain_streaming_events: stale session: %s != %s", 
                             utt.voice_session_id, current_session)
                continue

            # Match check
            if (
                current_match is not None
                and utt.match_id is not None
                and str(utt.match_id) != str(current_match)
            ):
                self._streaming_match_mismatch += 1
                logger.debug("drain_streaming_events: match mismatch: %s != %s",
                             utt.match_id, current_match)
                continue

            # Annotate with current match_id and calibration_context
            utt = dataclasses.replace(
                utt, 
                match_id=current_match,
                calibration_context=current_calibration
            )

            # Duplicate check
            if utt.utterance_id in self._seen_utterance_ids:
                self._streaming_duplicate += 1
                continue

            self._seen_utterance_ids.add(utt.utterance_id)
            validated.append(utt)
            self._streaming_finalized += 1

        self._streaming_events_drained = len(validated)

        # Bound the seen IDs set
        if len(self._seen_utterance_ids) > self._max_seen_utterance_ids:
            excess = len(self._seen_utterance_ids) - self._max_seen_utterance_ids // 2
            sorted_ids = sorted(self._seen_utterance_ids)
            for old_id in sorted_ids[:excess]:
                self._seen_utterance_ids.discard(old_id)

        # Update diagnostics
        if self._streaming_backend is not None:
            self._update_interim_diagnostics(self._streaming_backend)

        return validated

    def _transcribe_chunk(self, work_item: TranscriptionWorkItem | None) -> None:
        """Transcribe an audio chunk in the background worker thread."""
        if work_item is None or getattr(work_item, "audio", None) is None:
            logger.debug("Skipping transcription: work_item or audio is None")
            self._last_terminal_outcome = "empty_work_item"
            return
        chunk = work_item.audio
        calibration_context = work_item.calibration_context
        work_item_id = getattr(work_item, '_work_item_id', str(id(work_item)))
        
        
        self._current_work_item_id = work_item_id
        self._current_work_item_stage = "transcribing"
        self._emit_runtime_audit(
            "voice_asr_transcription_started",
            f"processor_id={id(self)} "
            f"work_item_id={work_item_id} "
            f"runtime_mode={work_item.capture_runtime_mode} "
            f"calibration_session_id={getattr(work_item.calibration_context, 'calibration_session_id', None) or 'none'} "
            f"calibration_trial_id={getattr(work_item.calibration_context, 'calibration_trial_id', None) or 'none'} "
            f"capture_kind={getattr(work_item.calibration_context, 'capture_kind', None) or 'none'} "
            f"duration_ms={getattr(chunk, 'duration_ms', 0.0)} "
            f"rms={getattr(chunk, 'rms', 0.0)}",
        )
        try:
            asr = self._get_asr()
            if asr is None:
                self._set_status("ASR unavailable")
                logger.debug("Skipping transcription: ASR unavailable")
                self._last_terminal_outcome = "asr_unavailable"
                return

            pcm_bytes = chunk.to_pcm_bytes()
            if not pcm_bytes:
                logger.debug("Empty PCM bytes, skipping transcription")
                self._last_terminal_outcome = "empty_pcm"
                return

            if chunk.rms < 0.01:
                logger.debug(
                    "Chunk RMS %.4f below floor, skipping transcription",
                    chunk.rms,
                )
                self._last_terminal_outcome = "rms_below_floor"
                return

            logger.debug(
                "Transcribing chunk: pcm_len=%d, chunk_format=%s, chunk_rate=%d, "
                "chunk_channels=%d, chunk_rms=%.4f",
                len(pcm_bytes), chunk.sample_format, chunk.sample_rate,
                chunk.channels, chunk.rms,
            )

            inference_lock_wait_start = time.time()
            asr = self._get_asr()
            if asr is None:
                self._set_status("ASR unavailable")
                logger.debug("Skipping transcription: ASR unavailable")
                self._last_terminal_outcome = "asr_unavailable"
                return

            inference_lock_acquired = time.time()
            self._inference_lock_wait_duration_ms = (inference_lock_acquired - inference_lock_wait_start) * 1000.0

            start = time.time()
            raw_text = asr.transcribe_pcm(pcm_bytes)
            latency_ms = (time.time() - start) * 1000.0
            inference_lock_released = time.time()

            self._transcription_results_returned += 1
            self._last_asr_latency_ms = latency_ms
            self._last_work_item_timestamp = time.time()
            logger.debug("ASR raw result: '%s' (latency: %.1f ms)", raw_text, latency_ms)
            
            if not raw_text:
                self._blank_transcription_count += 1
                self._last_terminal_outcome = "blank_transcript"
                self._current_work_item_stage = "blank"
                
                self._emit_runtime_audit(
                    "voice_asr_blank_transcript",
                    f"processor_id={id(self)} "
                    f"work_item_id={work_item_id} "
                    f"duration_ms={chunk.duration_ms:.1f} "
                    f"latency_ms={latency_ms:.1f} "
                    f"rms={chunk.rms:.4f}",
                )
                return

            text = self.post_processor.process(raw_text)
            self._transcript_text_extracted += 1
            self._last_asr_result_text = text
            logger.debug("Post-processed text: '%s'", text)
            self._emit_runtime_audit(
                "voice_asr_text_extracted",
                f"processor_id={id(self)} "
                f"work_item_id={work_item_id} "
                f"text_length={len(text)} "
                f"language=en "
                f"capture_kind={getattr(calibration_context, 'capture_kind', None) or 'none'} "
                f"calibration_trial_id={getattr(calibration_context, 'calibration_trial_id', None) or 'none'}",
            )

            self._emit_runtime_audit(
                "voice_asr_event_build_started",
                f"processor_id={id(self)} "
                f"work_item_id={work_item_id} "
                f"text='{text[:40]}'",
            )

            source = source_from_capture_mode(work_item.capture_runtime_mode)
            if source is None:
                self._last_terminal_outcome = "source_validation_failed"
                self._current_work_item_stage = "failed"
                self._emit_runtime_audit(
                    "voice_asr_event_rejected",
                    f"processor_id={id(self)} "
                    f"work_item_id={work_item_id} "
                    f"reason=source_validation_failed "
                    f"runtime_mode={work_item.capture_runtime_mode}",
                )
                return

            # Use occurrence-based ID for dedup (Quick Win 10)
            event_id = f"batch:{self._session_id}:{self._processor_generation}:{self._chunks_created}"
            
            event = VoiceTranscriptEvent(
                transcript=text,
                raw_transcript=raw_text,
                event_id=event_id,
                source=source,
                runtime_session_id=work_item.runtime_session_id,
                match_id=self._streaming_match_id,
                calibration_context=calibration_context,
                created_at=time.time(),
            )

            self._events_built += 1
            self._emit_runtime_audit(
                "voice_asr_event_built",
                f"processor_id={id(self)} "
                f"work_item_id={work_item_id} "
                f"text='{text[:40]}'",
            )

            try:
                self.event_queue.put_nowait(event)
                self._asr_events_enqueued += 1
                self._events_enqueued += 1
                self._last_terminal_outcome = "event_enqueued"
                self._current_work_item_stage = "enqueued"
                
                self._emit_runtime_audit(
                    "voice_asr_transcript_event_enqueued",
                    f"processor_id={id(self)} "
                    f"work_item_id={work_item_id} "
                    f"text={text[:40]} "
                    f"latency_ms={latency_ms:.1f} "
                    f"calibration_session_id={getattr(work_item.calibration_context, 'calibration_session_id', None) or 'none'} "
                    f"calibration_trial_id={getattr(work_item.calibration_context, 'calibration_trial_id', None) or 'none'}",
                )
            except queue.Full:
                self._last_terminal_outcome = "event_queue_full"
                self._current_work_item_stage = "failed"
                self._emit_runtime_audit(
                    "voice_asr_event_rejected",
                    f"processor_id={id(self)} "
                    f"work_item_id={work_item_id} "
                    f"reason=event_queue_full",
                )
            logger.debug("Voice event queued: text='%s'", text)

        except Exception as e:
            self._worker_exception = e
            self._log_rate_limited("Error in voice transcription thread", e)
            self._last_terminal_outcome = f"transcription_exception:{type(e).__name__}"
            self._current_work_item_stage = "failed"
            
            self._emit_runtime_audit(
                "voice_asr_transcription_exception",
                f"processor_id={id(self)} "
                f"work_item_id={work_item_id} "
                f"error={type(e).__name__}: {e}",
            )
        finally:
            self._current_work_item_stage = "completed"

    def get_events(self) -> List[VoiceTranscriptEvent]:
        """Drain all pending events from the queue."""
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def has_pending_events(self) -> bool:
        """Return True if the event queue or streaming backend has pending events."""
        with self._lock:
            if not self.event_queue.empty():
                return True
            if not self._finalized_utterance_queue.empty():
                return True
        # Check streaming backend (non-blocking)
        if self._streaming_backend is not None and self._streaming_active:
            try:
                finalized = self._streaming_backend.get_finalized_transcripts()
                if finalized:
                    # Re-queue drained items
                    for utt in finalized:
                        try:
                            self._finalized_utterance_queue.put_nowait(utt)
                        except queue.Full:
                            break
                    return True
            except Exception:
                pass
        return False

    def peek_events(self, max_items: int = 5) -> List[Dict[str, Any]]:
        """Return a snapshot of pending events without draining."""
        items = []
        with self._lock:
            q = list(self.event_queue.queue)[:max_items]
            for event in q:
                items.append({
                    "raw_transcript": getattr(event, 'raw_transcript', '')[:80],
                    "transcript": getattr(event, 'transcript', '')[:80],
                    "event_id": getattr(event, 'event_id', '')[:16],
                })
        return items

    def peek_chunks(self, max_items: int = 5) -> List[Dict[str, Any]]:
        """Return a snapshot of queued chunks without draining."""
        items = []
        with self._lock:
            q = list(self._chunk_queue.queue)[:max_items]
            for chunk in q:
                items.append({
                    "duration_ms": getattr(chunk, 'duration_ms', 0.0),
                    "frames": len(getattr(chunk, 'frames', [])),
                    "rms": getattr(chunk, 'rms', 0.0),
                    "timestamp": getattr(chunk, 'timestamp', 0.0),
                })
        return items

    def stop(self) -> None:
        """Stop processing and flush remaining audio."""
        # Invalidate streaming generation first (plan Â§8A invariant:
        # voice-off invalidates generation before backend shutdown).
        with self._lock:
            self._streaming_generation += 1
            self._streaming_active = False
            self._seen_utterance_ids.clear()

        self._stop_worker.set()
        self._stop_audio_ingress_worker_event.set()
        self._set_status("stopped")
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self._worker_thread = None
        self._worker_started = False
        if self._audio_ingress_worker_thread is not None and self._audio_ingress_worker_thread.is_alive():
            self._audio_ingress_worker_thread.join(timeout=1.0)
        self._audio_ingress_worker_thread = None
        self._audio_ingress_worker_started = False
        self.audio_buffer.reset()
        with self._lock:
            self._clear_acoustic_capture_locked(reason="processor_stopped")
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
            while not self._measurement_result_queue.empty():
                try:
                    self._measurement_result_queue.get_nowait()
                except queue.Empty:
                    break
            while not self._finalized_utterance_queue.empty():
                try:
                    self._finalized_utterance_queue.get_nowait()
                except queue.Empty:
                    break

        # Close streaming backend AFTER generation invalidation
        if self._streaming_backend is not None:
            try:
                self._streaming_backend.close()
            except Exception as exc:
                logger.debug("Streaming backend close during stop: %s", exc)

    def get_worker_diagnostics(self) -> Dict[str, Any]:
        """Return truthful worker status for diagnostics."""
        thread = self._worker_thread
        return {
            "processor_id": id(self),
            "worker_started": self._worker_started,
            "worker_thread_exists": thread is not None,
            "worker_thread_alive": thread is not None and thread.is_alive(),
            "worker_thread_name": thread.name if thread is not None else None,
            "worker_stop_event_set": self._stop_worker.is_set(),
            "audio_queue_size": self._chunk_queue.qsize(),
            "event_queue_size": self.event_queue.qsize(),
            "measurement_result_queue_size": self._measurement_result_queue.qsize(),
            "chunk_enqueue_attempts": self._chunk_enqueue_attempts,
            "chunk_enqueue_accepted": self._chunk_enqueue_accepted,
            "chunk_enqueue_rejected": self._chunk_enqueue_rejected,
            "last_chunk_rejection_reason": self._last_chunk_rejection_reason,
            "total_work_items_enqueued": self._work_items_enqueued,
            "total_work_items_dequeued": self._transcription_calls_started,
            "transcription_calls_started": self._transcription_calls_started,
            "transcription_calls_completed": self._transcription_calls_completed,
            "transcription_results_returned": self._transcription_results_returned,
            "worker_counter_invariant_valid": (
                self._transcription_calls_started
                >= self._transcription_calls_completed
                + self._blank_transcription_count
            ),
            "transcript_text_extracted": self._transcript_text_extracted,
            "events_built": self._events_built,
            "events_enqueued": self._events_enqueued,
            "blank_transcription_count": self._blank_transcription_count,
            "last_asr_latency_ms": self._last_asr_latency_ms,
            "last_asr_result_text": self._last_asr_result_text[:80] if self._last_asr_result_text else "",
            "last_terminal_outcome": self._last_terminal_outcome,
            "last_rejection_reason": self._last_rejection_reason,
            "current_work_item_id": self._current_work_item_id,
            "current_work_item_stage": self._current_work_item_stage,
            "queued_work_item_ids": self._queued_work_item_ids[-5:],
            "last_worker_exception": str(self._worker_exception) if self._worker_exception else None,
            "last_work_item_timestamp": self._last_work_item_timestamp,
            "asr_ready": self._asr_ready,
            "asr_error": self._asr_error,
            "status": self._status,
            "audit_dropped_count": self._audit_dropped_count,
            "audit_queue_size": self._audit_queue.qsize(),
        }

    def get_processor_diagnostics(self) -> Dict[str, Any]:
        """Return full processor diagnostics for the UI panel."""
        worker_diag = self.get_worker_diagnostics()
        acoustic_snapshot = self.get_acoustic_capture_snapshot()
        _diag = {
            "processor_id": id(self),
            "processor_generation": self._processor_generation,
            "api_version": self.api_version,
            "implementation_version": self._implementation_version,
            "source_file": self._source_file,
            "created_at": self._created_at,
            "status": self._status,
            "asr_ready": self._asr_ready,
            "asr_error": self._asr_error,
            "audio_frames_received": self._audio_frames_received,
            "chunks_created": self._chunks_created,
            "chunk_enqueue_attempts": self._chunk_enqueue_attempts,
            "chunks_enqueued": self._chunk_enqueue_accepted,
            "chunks_rejected": self._chunk_enqueue_rejected,
            "rejected_by_reason": dict(self._rejected_by_reason),
            "last_chunk_admission_outcome": self._last_chunk_admission_outcome,
            "last_chunk_rejection_reason": self._last_chunk_rejection_reason,
            "last_chunk_runtime_mode": self._last_chunk_runtime_mode,
            "last_chunk_capture_source": self._last_chunk_capture_source,
            "last_chunk_continuous_session_id": self._last_chunk_continuous_session_id,
            "work_items_enqueued": self._work_items_enqueued,
            "dropped_chunks": self._dropped_chunks,
            "asr_events_enqueued": self._asr_events_enqueued,
            "event_queue_size": self.event_queue.qsize(),
            "chunk_queue_size": self._chunk_queue.qsize(),
            "measurement_result_queue_size": self._measurement_result_queue.qsize(),
            "runtime_mode": self._runtime_mode.value if self._runtime_mode else None,
            "session_id": self._session_id,
            "calibration_session_id": getattr(self._calibration_context, 'calibration_session_id', None) if self._calibration_context else None,
            "calibration_trial_id": getattr(self._calibration_context, 'calibration_trial_id', None) if self._calibration_context else None,
            "capture_kind": getattr(self._calibration_context, 'capture_kind', None).value if self._calibration_context else None,
            "worker_diagnostics": worker_diag,
            "acoustic_snapshot": {
                "active": acoustic_snapshot.active,
                "measurement_id": acoustic_snapshot.measurement_id,
                "kind": acoustic_snapshot.kind.value if acoustic_snapshot.kind else None,
                "frame_count": acoustic_snapshot.frame_count,
                "sample_count": acoustic_snapshot.sample_count,
                "sample_rate_hz": acoustic_snapshot.sample_rate_hz,
                "channels": acoustic_snapshot.channels,
                "elapsed_ms": acoustic_snapshot.elapsed_ms,
                "result_queue_size": acoustic_snapshot.result_queue_size,
                "completion_reason": acoustic_snapshot.completion_reason,
            },
            "noise_gate_rms": getattr(self.audio_buffer, "noise_gate_rms", 0.0) if self.audio_buffer else 0.0,
            "config_revision": self._config_revision,
            "last_frame_rms": self._last_frame_rms,
            "last_frame_normalized_rms": self._last_frame_normalized_rms,
            "noise_threshold_rms": self.audio_buffer.noise_gate_rms if self.audio_buffer else 0.0,
            "noise_threshold_dbfs": 20.0 * np.log10(max(self.audio_buffer.noise_gate_rms, 1e-10)) if self.audio_buffer and self.audio_buffer.noise_gate_rms > 0 else None,
            "above_threshold": self._above_threshold,
            "vad_decision": self._vad_decision,
            "speech_frame_count": self._speech_frame_count,
            "frame_classification_count": self._frame_classification_count,
            "endpoint_reason": self._endpoint_reason,
            "recv_call_count": self._recv_call_count,
            "recv_queued_call_count": self._recv_queued_call_count,
            "last_recv_timestamp": self._last_recv_timestamp,
            "last_recv_queued_timestamp": self._last_recv_queued_timestamp,
            "last_ingest_timestamp": self._last_ingest_timestamp,
            "callback_exception_count": self._callback_exception_count,
            "last_callback_exception": self._last_callback_exception,
            "audit_dropped_count": self._audit_dropped_count,
            "audit_queue_size": self._audit_queue.qsize(),
            "audio_ingress_queue_size": self._audio_ingress_queue.qsize(),
            "audio_ingress_accepted": self._audio_ingress_accepted,
            "audio_ingress_queue_full": self._audio_ingress_queue_full,
            "audio_ingress_stale": self._audio_ingress_stale,
            "audio_ingress_processed": self._audio_ingress_processed,
            "audio_ingress_worker_alive": (
                self._audio_ingress_worker_thread is not None
                and self._audio_ingress_worker_thread.is_alive()
            ),
            "audio_ingress_worker_failures": self._audio_ingress_worker_failures,
            "last_audio_ingress_error": self._last_audio_ingress_error,
        }
        return _diag


# --------------------------------------------------------------------------- #
# Factory helpers                                                              #
# --------------------------------------------------------------------------- #
# Factory helpers                                                              #
# --------------------------------------------------------------------------- #

def build_audio_processor_factory(
    filtering: bool,
    threshold: float,
    strict: bool,
    vad: Optional[VoiceActivityDetector],
    tt_sounds_enabled: bool = False,
) -> Any:
    """Build a factory that creates a configured VoiceAudioProcessor.

    The returned factory is a zero-argument callable compatible with
    ``webrtc_streamer(audio_processor_factory=...)``.
    """
    def factory():
        _tt_proc = None
        if tt_sounds_enabled:
            try:
                from tournament_platform.app.services.tt_sounds import (
                    ImpactDetector,
                    TTRallyProcessor,
                    TT_SOUNDS_ABS_MIN_ENERGY,
                    TT_SOUNDS_THRESHOLD_MULTIPLIER,
                    TT_SOUNDS_NOISE_FLOOR_DECAY,
                    TT_SOUNDS_COOLDOWN_MS,
                    TT_SOUNDS_WINDOW_MS,
                )
                _detector = ImpactDetector(
                    abs_min_energy=TT_SOUNDS_ABS_MIN_ENERGY,
                    threshold_multiplier=TT_SOUNDS_THRESHOLD_MULTIPLIER,
                    noise_floor_decay=TT_SOUNDS_NOISE_FLOOR_DECAY,
                    cooldown_ms=TT_SOUNDS_COOLDOWN_MS,
                    window_ms=TT_SOUNDS_WINDOW_MS,
                    sample_rate=48000,
                )
                _tt_proc = TTRallyProcessor(detector=_detector, sample_rate=48000)
            except Exception:
                _tt_proc = None
        try:
            return VoiceAudioProcessor(
                noise_gate_rms=threshold if filtering else 0.01,
                sample_format=SAMPLE_FORMAT_FLOAT32,
                voice_strict_mode=strict,
                vad=vad,
                tt_sounds_processor=_tt_proc,
            )
        except Exception:
            raise

    return factory


def tracked_audio_processor_factory(
    raw_factory: Any,
    diag_lock: threading.Lock,
    diag: Dict[str, Any],
    session_state: Any,
    post_init_callback: Any = None,
) -> Any:
    """Wrap ``raw_factory`` with call-count and error tracking.

    Writes metrics into ``session_state`` so they survive Streamlit reruns.
    """
    def factory():
        with diag_lock:
            diag["call_count"] += 1
            session_state._voice_factory_call_count = diag["call_count"]
        try:
            processor = raw_factory()
            with diag_lock:
                diag["last_error"] = None
                diag["last_processor_id"] = id(processor)
                diag["last_processor_class"] = type(processor).__name__
                session_state._voice_last_processor_id = diag["last_processor_id"]
                session_state._voice_last_processor_class = diag["last_processor_class"]
            if callable(post_init_callback):
                try:
                    post_init_callback(processor)
                except Exception:
                    pass
            return processor
        except Exception as exc:
            with diag_lock:
                diag["last_error"] = f"{type(exc).__name__}: {exc}"
                diag["last_exception"] = exc
                session_state._voice_factory_last_error = diag["last_error"]
                session_state._voice_last_processor_exception = diag["last_exception"]
            raise

    return factory


class VoiceProcessorFactory:
    """Stable callable factory for VoiceAudioProcessor with mutable config.

    Unlike the closure-based ``tracked_audio_processor_factory``, this class
    instance is created once and stored in ``st.session_state``. Its ``__call__``
    reads config from a thread-safe holder, so the *same callable object* is
    passed to ``webrtc_streamer()`` on every Streamlit rerun. This prevents
    unnecessary processor replacement when configuration toggles (e.g.
    TT-sounds, noise filtering) change during an active session.

    The factory is *not* recreated on config change — config is read from the
    holder at call time. The processor is only created when the WebRTC worker
    requests it (initial mount or after a transport reset).

    Diagnostics are managed internally — the factory owns its lock and
    diagnostics dict. Callers (including Streamlit render code) must use
    ``get_diagnostics()`` to read them, never accessing the lock directly.
    """

    __slots__ = (
        "_config",
        "_diag_lock",
        "_diag",
        "_session_state",
        "_post_init_callback",
        "_creation_count",
        "_last_processor_id",
        "_config_version",
    )

    def __init__(
        self,
        config_holder: "VoiceProcessorConfigHolder",
        session_state: Any = None,
        post_init_callback: Any = None,
    ) -> None:
        self._config = config_holder
        self._diag_lock = threading.Lock()
        self._diag: Dict[str, Any] = {
            "call_count": 0,
            "callback_count": 0,
            "last_error": None,
            "last_exception": None,
            "last_processor_id": None,
            "last_processor_class": None,
            "created_at": time.time(),
        }
        self._session_state = session_state
        self._post_init_callback = post_init_callback
        self._creation_count = 0
        self._last_processor_id = None
        self._config_version = config_holder.version_string()

    @property
    def config(self) -> "VoiceProcessorConfigHolder":
        return self._config

    @property
    def config_version(self) -> str:
        return self._config_version

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return a thread-safe snapshot of factory diagnostics.

        This is the ONLY way for external code (including Streamlit render
        code) to read factory diagnostics. The lock is owned by the factory
        and never exposed.
        """
        with self._diag_lock:
            return dict(self._diag)

    def update_config_version(self) -> None:
        """Update the cached config version string after a config update."""
        with self._diag_lock:
            self._config_version = self._config.version_string()

    def __call__(self) -> VoiceAudioProcessor:
        cfg = self._config.snapshot
        with self._diag_lock:
            self._diag["call_count"] += 1
            self._creation_count += 1
            if self._session_state is not None:
                self._session_state._voice_factory_call_count = self._diag["call_count"]
        try:
            processor = VoiceAudioProcessor(
                noise_gate_rms=cfg.threshold if cfg.filtering else 0.01,
                sample_format=SAMPLE_FORMAT_FLOAT32,
                voice_strict_mode=cfg.strict,
                vad=cfg.vad,
                tt_sounds_processor=cfg.tt_proc,
            )
            with self._diag_lock:
                self._diag["last_error"] = None
                self._diag["last_processor_id"] = id(processor)
                self._diag["last_processor_class"] = type(processor).__name__
                self._last_processor_id = id(processor)
                if self._session_state is not None:
                    self._session_state._voice_last_processor_id = id(processor)
                    self._session_state._voice_last_processor_class = type(processor).__name__
            if callable(self._post_init_callback):
                try:
                    self._post_init_callback(processor)
                except Exception:
                    pass
            return processor
        except Exception as exc:
            with self._diag_lock:
                self._diag["last_error"] = f"{type(exc).__name__}: {exc}"
                self._diag["last_exception"] = exc
                if self._session_state is not None:
                    self._session_state._voice_factory_last_error = self._diag["last_error"]
                    self._session_state._voice_last_processor_exception = self._diag["last_exception"]
            raise


class VoiceProcessorConfigHolder:
    """Thread-safe mutable configuration holder for VoiceProcessorFactory.

    The factory reads from this holder at call time, so the factory callable
    identity remains stable across Streamlit reruns even when config toggles
    change. This is the key to preventing processor replacement churn.
    """

    __slots__ = ("_lock", "_filtering", "_threshold", "_strict", "_vad", "_tt_sounds_enabled", "_tt_proc")

    def __init__(
        self,
        filtering: bool = False,
        threshold: float = 0.0,
        strict: bool = False,
        vad: Optional[VoiceActivityDetector] = None,
        tt_sounds_enabled: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._filtering = filtering
        self._threshold = threshold
        self._strict = strict
        self._vad = vad
        self._tt_sounds_enabled = tt_sounds_enabled

    @property
    def snapshot(self) -> "VoiceProcessorConfigSnapshot":
        with self._lock:
            return VoiceProcessorConfigSnapshot(
                filtering=self._filtering,
                threshold=self._threshold,
                strict=self._strict,
                vad=self._vad,
                tt_sounds_enabled=self._tt_sounds_enabled,
            )

    def update(
        self,
        *,
        filtering: Optional[bool] = None,
        threshold: Optional[float] = None,
        strict: Optional[bool] = None,
        vad: Optional[VoiceActivityDetector] = None,
        tt_sounds_enabled: Optional[bool] = None,
    ) -> None:
        from tournament_platform.app.services.tt_sounds import (
            ImpactDetector,
            TTRallyProcessor,
            TT_SOUNDS_ABS_MIN_ENERGY,
            TT_SOUNDS_THRESHOLD_MULTIPLIER,
            TT_SOUNDS_NOISE_FLOOR_DECAY,
            TT_SOUNDS_COOLDOWN_MS,
            TT_SOUNDS_WINDOW_MS,
        )
        with self._lock:
            if filtering is not None:
                self._filtering = filtering
            if threshold is not None:
                self._threshold = threshold
            if strict is not None:
                self._strict = strict
            if vad is not None:
                self._vad = vad
            if tt_sounds_enabled is not None:
                self._tt_sounds_enabled = tt_sounds_enabled
            if tt_sounds_enabled:
                try:
                    _detector = ImpactDetector(
                        abs_min_energy=TT_SOUNDS_ABS_MIN_ENERGY,
                        threshold_multiplier=TT_SOUNDS_THRESHOLD_MULTIPLIER,
                        noise_floor_decay=TT_SOUNDS_NOISE_FLOOR_DECAY,
                        cooldown_ms=TT_SOUNDS_COOLDOWN_MS,
                        window_ms=TT_SOUNDS_WINDOW_MS,
                        sample_rate=48000,
                    )
                    self._tt_proc = TTRallyProcessor(detector=_detector, sample_rate=48000)
                except Exception:
                    self._tt_proc = None
            else:
                self._tt_proc = None

    def version_string(self) -> str:
        """Return a version string for diagnostics/cache invalidation."""
        snap = self.snapshot
        return (
            f"{VOICE_AUDIO_PROCESSOR_API_VERSION}:{VOICE_RUNTIME_IMPLEMENTATION_VERSION}:"
            f"{snap.filtering}:{snap.threshold}:{snap.strict}:{snap.tt_sounds_enabled}"
        )


@dataclass(frozen=True)
class VoiceProcessorConfigSnapshot:
    """Immutable snapshot of processor config."""
    filtering: bool
    threshold: float
    strict: bool
    vad: Optional[VoiceActivityDetector]
    tt_sounds_enabled: bool
    tt_proc: Optional[Any] = None


@dataclass(frozen=True)
class StreamingSessionIdentity:
    """Provider-neutral identity for a streaming session.

    Captures the canonical tuple of identities that must remain stable
    during one active voice session:

        WebRTC component → VoiceAudioProcessor → Deepgram backend

    Every operation (audio routing, backend diagnostics, finalized utterance
    drain, event drain, shutdown, unexpected stop handling) must validate
    against this identity to prevent stale processor/backend mismatches.
    """

    voice_session_id: str
    processor_id: int
    processor_generation: int
    backend_generation: int
    match_id: str
    language: str


@dataclass(frozen=True)
class WebRtcRenderSnapshot:
    """Immutable per-render snapshot of the WebRTC streamer context.

    This is the sole authority for the current WebRTC state during a Streamlit
    render. It is captured immediately after ``webrtc_streamer()`` returns and
    passed to all downstream functions, eliminating the split-brain problem
    where _refresh_streaming_diagnostics(), _get_current_webrtc_processor(),
    and the rendering section each read from different sources.

    ``processor`` may be None during transient worker/context transitions even
    when playing=True. Callers must treat this as "unknown/transitional", not
    as a processor replacement or backend ownership failure.
    """

    context: Any | None
    playing: bool
    signalling: bool
    processor: Any | None
    processor_id: int | None
    processor_generation: int | None
    audio_frames_received: int
    audio_ingress_queue_full: int = 0  # Quick Win 11
    dropped_frames: int = 0  # Quick Win 11
    requested_constraints: Optional[dict] = None  # Quick Win 12
    # Point 5: Detailed connection states
    connection_state: str | None = None
    ice_connection_state: str | None = None
    ice_gathering_state: str | None = None
    signaling_state: str | None = None
    component_rendered: bool = False
    mount_error: str | None = None

    @property
    def has_processor(self) -> bool:
        return self.processor is not None

    @classmethod
    def unavailable(cls) -> WebRtcRenderSnapshot:
        """Create a safe snapshot when the WebRTC component has not been rendered."""
        return cls(
            context=None,
            playing=False,
            signalling=False,
            processor=None,
            processor_id=None,
            processor_generation=None,
            audio_frames_received=0,
            component_rendered=False,
            mount_error=None,
        )


@dataclass
class VoiceLifecycleEvent:
    """Thread-safe lifecycle event pushed from audio callbacks/worker threads."""

    event_type: str
    processor_id: int | None
    processor_generation: int | None
    timestamp: float
    desired_mic_playing: bool | None
    last_frame_age_ms: float | None
    extra: dict = field(default_factory=dict)


class VoiceLifecycleEventQueue:
    """Thread-safe queue for lifecycle events from audio callbacks.

    Processor lifecycle hooks (on_ended, etc.) may fire from streamlit-webrtc's
    worker thread. They must NOT call Streamlit APIs directly. Instead, they
    push events here, and the main Streamlit thread drains them in
    _reconcile_streaming_lifecycle().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: List[VoiceLifecycleEvent] = []

    def push(self, event: VoiceLifecycleEvent) -> None:
        with self._lock:
            self._queue.append(event)

    def drain(self) -> List[VoiceLifecycleEvent]:
        with self._lock:
            events = self._queue
            self._queue = []
            return events

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)


# Module-level lifecycle event queue (thread-safe)
_voice_lifecycle_events = VoiceLifecycleEventQueue()
