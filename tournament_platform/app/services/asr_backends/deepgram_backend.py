"""
Deepgram Listen v1 Streaming ASR Backend (Phase 1 Pilot)

Owns a persistent WebSocket connection to Deepgram's Nova-3 model.
A single dedicated I/O thread owns the ``DeepgramClient``, the Listen v1
``connection``, and all SDK calls.  Cross-thread audio is delivered via a
bounded ``queue.Queue`` (plan §3.3, §3.4).

Thread ownership:
  - Audio callback thread (recv_queued): calls ``enqueue_audio`` only.
  - I/O event-loop thread: owns ``_client``, ``_connection``; runs
    ``start_listening`` (blocking receive loop), ``send_media``,
    ``send_keep_alive``, ``send_finalize``, ``send_close_stream``.
  - Main Streamlit thread: calls ``get_finalized_transcripts``,
    ``get_interim_transcripts``, ``get_errors``, ``close``.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from tournament_platform.app.services.asr_backends.base import (
    StreamingASRBackend,
    DeepgramBackendMetrics,
    StreamedTranscript,
    BackendStatus,
)
from tournament_platform.app.services.asr_backends.calibration_policy import (
    ASRCapabilities,
    AudioDeliveryPolicy,
    AudioHealthStatus,
    deepgram_continuous_policy,
)
from tournament_platform.app.services.asr_backends.deepgram_adapter import (
    DeepgramAdapter,
    build_deepgram_keyterms,
)
from tournament_platform.app.services.voice_scorekeeper.events import (
    FinalizedUtterance,
)

logger = logging.getLogger(__name__)

# Audio frame queue capacity: ~200 ms of 16 kHz mono int16 PCM
_AUDIO_FRAME_QUEUE_MAXSIZE = 256
_TRANSCRIPT_QUEUE_MAXSIZE = 50
_INTERIM_QUEUE_MAXSIZE = 100
_ERROR_QUEUE_MAXSIZE = 20


class _ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    STARTING = "starting"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class _UtteranceState(StrEnum):
    IDLE = "idle"
    ACCUMULATING = "accumulating"
    SEALED = "sealed"
    FINALIZING = "finalizing"
    DONE = "done"
    DISCARDED = "discarded"


# ---------------------------------------------------------------------------
# Safe error handling
# ---------------------------------------------------------------------------

class SafeProviderError:
    """Sanitized provider error with normalized category."""

    def __init__(
        self,
        category: str,
        code: Optional[str] = None,
        message_safe: str = "",
    ) -> None:
        self.category = category
        self.code = code
        self.message_safe = message_safe or category.replace("_", " ").title()

    def __str__(self) -> str:
        return self.message_safe


def sanitize_deepgram_error(exc: BaseException, connect_timeout_seconds: float = 10.0) -> SafeProviderError:
    """Normalize an exception into a safe, categorized provider error.

    Never includes API keys, auth headers, URLs, or raw exception reprs.
    """
    msg = str(exc)

    if isinstance(exc, _AuthError) or (
        hasattr(exc, "status_code") and getattr(exc, "status_code") == 401
    ):
        return SafeProviderError(
            category="authentication_failed",
            code="401" if hasattr(exc, "status_code") else None,
            message_safe="Deepgram rejected the API credentials. Verify VOICE_DEEPGRAM_API_KEY.",
        )

    if isinstance(exc, TimeoutError) or "timed out" in msg.lower():
        return SafeProviderError(
            category="connection_timeout",
            code="CONNECT_TIMEOUT",
            message_safe=f"Connection timed out after {connect_timeout_seconds}s.",
        )

    if "connection refused" in msg.lower() or "rejected" in msg.lower():
        return SafeProviderError(
            category="connection_rejected",
            code="CONNECTION_REFUSED",
            message_safe="Connection was rejected by the server.",
        )

    if "name resolution" in msg.lower() or "dns" in msg.lower() or "getaddrinfo" in msg.lower():
        return SafeProviderError(
            category="dns_failure",
            code="DNS_ERROR",
            message_safe="DNS resolution failed for Deepgram endpoint.",
        )

    if "ssl" in msg.lower() or "tls" in msg.lower() or "certificate" in msg.lower():
        return SafeProviderError(
            category="tls_failure",
            code="TLS_ERROR",
            message_safe="TLS handshake failed with Deepgram.",
        )

    if "websocket" in msg.lower() or "ws " in msg.lower() or "close" in msg.lower():
        return SafeProviderError(
            category="websocket_closed",
            code="WS_CLOSE",
            message_safe="Deepgram connection closed unexpectedly.",
        )

    if "send" in msg.lower() or "write" in msg.lower():
        return SafeProviderError(
            category="send_failure",
            code="SEND_ERROR",
            message_safe="Failed to send audio to Deepgram.",
        )

    if "receive" in msg.lower() or "read" in msg.lower() or "recv" in msg.lower():
        return SafeProviderError(
            category="receive_failure",
            code="RECV_ERROR",
            message_safe="Failed to receive audio from Deepgram.",
        )

    if "deepgram" in msg.lower() or "sdk" in msg.lower():
        return SafeProviderError(
            category="sdk_runtime_error",
            code="SDK_ERROR",
            message_safe="Deepgram SDK encountered an error.",
        )

    safe_msg = re.sub(
        r"(?i)(authorization|api_key|apikey|token|bearer)\s*[:=]\s*\S+",
        r"\1: [REDACTED]", msg
    )
    safe_msg = re.sub(r"https?://[^\s'\"]+", "[URL REDACTED]", safe_msg)
    safe_msg = re.sub(r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "[TOKEN REDACTED]", safe_msg)
    if len(safe_msg) > 200:
        safe_msg = safe_msg[:200] + "..."

    return SafeProviderError(
        category="unknown_provider_error",
        code=None,
        message_safe=safe_msg or "Deepgram connection failed.",
    )


# ---------------------------------------------------------------------------
# Utterance accumulator
# ---------------------------------------------------------------------------

@dataclass
class _UtteranceAccumulator:
    """Accumulates final segments during a single utterance."""

    state: _UtteranceState = _UtteranceState.IDLE
    segments: list[str] = field(default_factory=list)
    raw_segments: list[str] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    speech_started: bool = False
    last_final_ts: float = 0.0
    finalize_deadline: float = 0.0
    backend: Any = None
    accumulator_final_segments: int = 0
    accumulator_seal_attempts: int = 0
    accumulator_seal_success: int = 0

    def on_message(
        self,
        *,
        text: str,
        is_final: bool,
        speech_final: bool,
        is_interim: bool,
        finalize_timeout_ms: int,
        max_utterance_ms: int,
        confidence: float = 1.0,
    ) -> Optional[tuple[str, float]]:
        now = time.monotonic()

        if is_interim:
            return None

        if not is_final:
            return None

        if state := self.state:
            if state in (_UtteranceState.DISCARDED, _UtteranceState.DONE):
                return None

            if state == _UtteranceState.IDLE:
                self.state = _UtteranceState.ACCUMULATING
                self.speech_started = True
                self.last_final_ts = now
            elif state == _UtteranceState.ACCUMULATING:
                pass

            self.segments.append(text)
            self.raw_segments.append(text)
            self.confidences.append(confidence)
            self.accumulator_final_segments += 1

            if speech_final:
                self.accumulator_seal_attempts += 1
                self.state = _UtteranceState.SEALED
                result = self._seal(now)
                if result is not None:
                    self.accumulator_seal_success += 1
                return result

            self.last_final_ts = now

            utterance_elapsed = now - (self.finalize_deadline or now)
            if utterance_elapsed > max_utterance_ms / 1000.0:
                self.finalize_deadline = now
                return None

        return None

    def on_utterance_end(self) -> Optional[tuple[str, float]]:
        if self.state in (_UtteranceState.IDLE, _UtteranceState.SEALED,
                          _UtteranceState.DISCARDED, _UtteranceState.DONE):
            return None
        self.accumulator_seal_attempts += 1
        self.state = _UtteranceState.SEALED
        result = self._seal(time.monotonic())
        if result is not None:
            self.accumulator_seal_success += 1
        return result

    def check_timeout(self, finalize_timeout_ms: int) -> Optional[tuple[str, float]]:
        if self.state != _UtteranceState.ACCUMULATING:
            return None
        now = time.monotonic()
        elapsed_ms = (now - self.last_final_ts) * 1000.0
        if elapsed_ms >= finalize_timeout_ms:
            # First threshold: set state to FINALIZING to trigger send_finalize()
            self.state = _UtteranceState.FINALIZING
            self.finalize_deadline = now
            return None

        return None

    def check_fallback_seal(self, fallback_ms: int = 1500) -> Optional[tuple[str, float]]:
        """Hard fallback seal for stuck utterances (plan §6)."""
        if self.state not in (_UtteranceState.ACCUMULATING, _UtteranceState.FINALIZING):
            return None
        
        now = time.monotonic()
        # Use last_final_ts as the anchor for segment inactivity
        elapsed_ms = (now - self.last_final_ts) * 1000.0
        
        if elapsed_ms >= fallback_ms:
            self.state = _UtteranceState.SEALED
            return self._seal(now)
            
        return None

    def needs_finalize(self) -> bool:
        return self.state == _UtteranceState.FINALIZING

    def invalidate(self) -> None:
        self.state = _UtteranceState.DISCARDED
        self.segments.clear()
        self.raw_segments.clear()

    def _seal(self, now: float) -> Optional[tuple[str, float]]:
        if not self.segments:
            self.state = _UtteranceState.IDLE
            return None
        full = " ".join(self.segments).strip()
        avg_confidence = (
            sum(self.confidences) / len(self.confidences)
            if self.confidences else 1.0
        )
        self.speech_started = False
        self.last_final_ts = now
        self.state = _UtteranceState.IDLE
        self.segments = []
        self.raw_segments = []
        self.confidences = []
        self.finalize_deadline = 0.0
        return full, avg_confidence


# ---------------------------------------------------------------------------
# Auth error helper
# ---------------------------------------------------------------------------

class _AuthError(Exception):
    """Raised on Deepgram authentication failure (401)."""
    status_code = 401


# ---------------------------------------------------------------------------
# Deepgram backend
# ---------------------------------------------------------------------------

class DeepgramASRBackend:
    """Deepgram Listen v1 streaming ASR backend.

    Implements the ``StreamingASRBackend`` protocol.

    A dedicated I/O thread owns the ``DeepgramClient``, the Listen v1
    ``connection``, and all SDK calls.  The audio callback thread only
    calls ``enqueue_audio``; the main thread only calls ``get_*``.
    """

    backend_name = "deepgram"

    @staticmethod
    def _sanitize_error_message(text: str, max_length: int = 200) -> str:
        """Sanitize an exception message for safe storage in diagnostics."""
        text = re.sub(r"(?i)(authorization|api_key|apikey|token|bearer)\s*[:=]\s*\S+", r"\1: [REDACTED]", text)
        text = re.sub(r"https?://[^\s'\"]+", "[URL REDACTED]", text)
        text = re.sub(r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "[TOKEN REDACTED]", text)
        if len(text) > max_length:
            text = text[:max_length] + "..."
        return text

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "nova-3",
        language: str = "lt",
        endpointing_ms: int = 300,
        interim_results: bool = True,
        keepalive_seconds: float = 4.0,
        sample_rate: int = 16000,
        channels: int = 1,
        max_keyterms: int = 100,
        connect_timeout_seconds: float = 10.0,
        reconnect_attempts: int = 3,
        finalize_timeout_ms: int = 1200,
        max_utterance_ms: int = 10000,
        keyterms: Optional[list[str]] = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._endpointing_ms = endpointing_ms
        self._interim_results = interim_results
        self._keepalive_seconds = keepalive_seconds
        self._sample_rate = sample_rate
        self._channels = channels
        self._max_keyterms = max_keyterms
        self._connect_timeout_seconds = connect_timeout_seconds
        self._reconnect_attempts = reconnect_attempts
        self._finalize_timeout_ms = finalize_timeout_ms
        self._max_utterance_ms = max_utterance_ms

        self._adapter = DeepgramAdapter()
        self._keyterms_raw: list[str] = list(keyterms) if keyterms else []

        self._capabilities = ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=False,
            supports_optional_audio_health_check=True,
        )
        self._delivery_policy = AudioDeliveryPolicy(
            mode="continuous",
            require_vad_calibration=False,
            allow_degraded_fallback=True,
        )

        self._audio_frame_queue: queue.Queue = queue.Queue(
            maxsize=_AUDIO_FRAME_QUEUE_MAXSIZE
        )
        self._finalized_queue: queue.Queue = queue.Queue(
            maxsize=_TRANSCRIPT_QUEUE_MAXSIZE
        )
        self._interim_queue: queue.Queue = queue.Queue(
            maxsize=_INTERIM_QUEUE_MAXSIZE
        )
        self._error_queue: queue.Queue = queue.Queue(
            maxsize=_ERROR_QUEUE_MAXSIZE
        )

        self._connection: Any = None
        self._client: Any = None
        self._connection_state: _ConnectionState = _ConnectionState.DISCONNECTED
        self._generation: int = 0
        self._session_id: str = ""
        self._utterance_accumulator = _UtteranceAccumulator()

        self._io_thread: Optional[threading.Thread] = None
        self._closed: bool = False
        self._connection_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_finalize_request: float = 0.0
        self._last_finalize_deadline: float = 0.0
        self._finalization_sequence: int = 0

        # Connection lifecycle tracking
        self._connection_attempt: int = 0
        self._connection_started_at: Optional[float] = None
        self._connection_opened_at: Optional[float] = None
        self._connection_failed_at: Optional[float] = None
        self._last_error_category: Optional[str] = None
        self._last_error_code: Optional[str] = None
        self._last_error_message_safe: Optional[str] = None
        self._last_close_code: Optional[str] = None
        self._last_close_reason_safe: Optional[str] = None
        self._reconnect_attempt: int = 0
        self._connection_open_event = threading.Event()

        # Metrics (privacy-safe: no transcripts, no API keys)
        self._metrics = DeepgramBackendMetrics()
        self._metrics_lock = threading.Lock()
        self._audio_bytes_sent = 0
        self._audio_duration_sent_ms = 0.0
        self._audio_dequeued = 0
        self._audio_send_attempts = 0
        self._audio_send_success = 0
        self._audio_send_failed = 0
        self._last_audio_send_at = 0.0
        self._keepalive_count = 0
        self._reconnect_count = 0
        self._queue_overflow_count = 0
        self._interim_count = 0
        self._final_segment_count = 0
        self._completed_utterance_count = 0
        self._empty_transcript_count = 0
        self._accumulator_final_segments = 0
        self._accumulator_seal_attempts = 0
        self._accumulator_seal_success = 0
        self._emit_finalized_calls = 0
        self._finalized_queue_put_success = 0
        self._connection_start_ts: Optional[float] = None
        self._send_loop_started = False
        self._send_loop_alive = False
        self._keepalive_loop_started = False
        self._keepalive_loop_alive = False

        # Provider event audit counters (plan §6)
        self._provider_messages_received = 0
        self._provider_open_count = 0
        self._provider_close_count = 0
        self._provider_error_count = 0
        self._provider_unerror_count = 0
        self._provider_utterance_end_count = 0
        self._provider_speech_started_count = 0
        self._provider_results_received = 0
        self._provider_results_empty = 0
        self._provider_results_with_text = 0
        self._provider_results_interim = 0
        self._provider_results_final = 0
        self._provider_results_speech_final = 0
        self._transcript_text_extracted = 0
        self._provider_metadata_count = 0
        self._provider_unknown_message_count = 0
        self._provider_message_index = 0
        self._last_provider_message_type = None
        self._last_provider_message_summary = ""
        self._last_provider_message_text = ""
        self._last_interim_text = ""
        self._last_final_text = ""
        self._last_keepalive_at = 0.0

    # ------------------------------------------------------------------
    # Public API — StreamingASRBackend protocol
    # ------------------------------------------------------------------

    def capabilities(self) -> ASRCapabilities:
        return self._capabilities

    def delivery_policy(self) -> AudioDeliveryPolicy:
        return self._delivery_policy

    def start_session(
        self,
        *,
        language: str,
        session_id: Optional[str] = None,
        generation: Optional[int] = None,
        match_id: Optional[Any] = None,
        keyterms: Optional[list[str]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        """Establish (or re-establish) the Listen v1 connection.

        Starts the I/O thread.  The WebSocket connection is opened
        asynchronously; use ``wait_until_ready`` or poll
        ``connection_state()`` to detect when it is open.
        """
        if generation is not None:
            self._generation = generation
        else:
            self._generation += 1
            
        if session_id:
            self._session_id = session_id
        else:
            self._session_id = f"dg-{uuid.uuid4().hex[:12]}"
            
        self._match_id = match_id
        self._language = language
        self._sample_rate = sample_rate
        self._channels = channels
        if keyterms is not None:
            self._keyterms_raw = list(keyterms)
        self._stop_event.clear()
        self._reset_queues()
        self._connection_open_event.clear()

        self._connection_attempt += 1
        self._connection_started_at = time.monotonic()
        self._connection_failed_at = None
        self._last_error_category = None
        self._last_error_code = None
        self._last_error_message_safe = None
        self._last_close_code = None
        self._last_close_reason_safe = None

        self._set_connection_state(_ConnectionState.STARTING)

        self._io_thread = threading.Thread(
            target=self._io_loop,
            name=f"deepgram-io-{self._generation}",
            daemon=True,
        )
        self._io_thread.start()

    def wait_until_ready(self, timeout_seconds: float = 10.0) -> bool:
        """Block until the connection is open or the timeout expires.

        Returns True if the connection opened, False on timeout or failure.
        """
        return self._connection_open_event.wait(timeout=timeout_seconds)

    def connection_state(self) -> str:
        """Return the current connection state string."""
        return self._connection_state.value

    def enqueue_audio(self, pcm_bytes: bytes) -> bool:
        """Enqueue PCM bytes for sending to Deepgram.  Non-blocking.

        Returns False if the queue is full (back-pressure) or if the
        connection is not yet open (discard-while-connecting policy).
        """
        if not pcm_bytes:
            return True
        state = self._connection_state
        if state not in (_ConnectionState.CONNECTED,):
            return False
        try:
            self._audio_frame_queue.put_nowait(pcm_bytes)
            with self._metrics_lock:
                self._metrics.audio_frames_received += 1
            return True
        except queue.Full:
            with self._metrics_lock:
                self._metrics.queue_overflow_count += 1
                self._queue_overflow_count += 1
            return False

    def send_keepalive(self) -> None:
        """Send a keep-alive frame.  Safe to call from any thread."""
        pass

    def finalize_utterance(self) -> None:
        """Request finalization of the current utterance."""
        self._last_finalize_request = time.monotonic()

    def close(self) -> None:
        """Shut down the connection and release all resources.

        Ordering:
            1. stop accepting audio (set _stop_event)
            2. close the WebSocket so start_listening unblocks
            3. join send + keepalive threads (bounded)
            4. join I/O thread (bounded)
            5. reset queues + invalidate accumulator

        Idempotent: safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True

        self._stop_event.set()
        self._set_connection_state(_ConnectionState.STOPPING)

        with self._connection_lock:
            conn = self._connection
            self._connection = None
            self._client = None

        if conn is not None:
            try:
                conn.send_close_stream()
            except Exception:
                pass

        with self._state_lock:
            if self._connection_state != _ConnectionState.FAILED:
                self._connection_state = _ConnectionState.STOPPED

        if self._io_thread is not None and self._io_thread.is_alive():
            self._io_thread.join(timeout=5.0)
            if self._io_thread.is_alive():
                logger.warning(
                    "Deepgram I/O thread did not terminate within 5s "
                    "(session=%s gen=%d)", self._session_id, self._generation
                )

        self._reset_queues()
        self._utterance_accumulator.invalidate()

    def health_status(self) -> str:
        """Return a provider-independent health status string."""
        if not self._api_key:
            return AudioHealthStatus.FAILED
        state = self._connection_state
        if state == _ConnectionState.CONNECTED:
            return "connected"
        if state == _ConnectionState.FAILED:
            return AudioHealthStatus.FAILED
        if state == _ConnectionState.STOPPED:
            return AudioHealthStatus.SKIPPED
        return "connecting"

    def get_connection_state(self) -> str:
        """Return the raw connection state string (authoritative)."""
        return self._connection_state.value

    def metrics(self) -> DeepgramBackendMetrics:
        with self._metrics_lock:
            m = self._metrics
            m.audio_bytes_sent = self._audio_bytes_sent
            m.audio_duration_sent_ms = self._audio_duration_sent_ms
            m.audio_send_attempts = self._audio_send_attempts
            m.audio_send_failed = self._audio_send_failed
            m.audio_send_success = self._audio_send_success
            m.last_audio_send_at = self._last_audio_send_at
            m.keepalive_count = self._keepalive_count
            m.reconnect_count = self._reconnect_count
            m.queue_depth = self._audio_frame_queue.qsize()
            m.connection_state = self._connection_state.value
            m.provider_messages_received = self._provider_messages_received
            m.provider_open_count = self._provider_open_count
            m.provider_close_count = self._provider_close_count
            m.provider_error_count = self._provider_error_count
            m.provider_unerror_count = self._provider_unerror_count
            m.provider_utterance_end_count = self._provider_utterance_end_count
            m.provider_speech_started_count = self._provider_speech_started_count
            m.last_provider_message_text = self._last_provider_message_text
            m.provider_results_received = self._provider_results_received
            m.provider_results_empty = self._provider_results_empty
            m.provider_results_with_text = self._provider_results_with_text
            m.provider_results_interim = self._provider_results_interim
            m.provider_results_final = self._provider_results_final
            m.provider_results_speech_final = self._provider_results_speech_final
            m.speech_final_received = getattr(m, "speech_final_received", 0)
            m.utterance_end_received = getattr(m, "utterance_end_received", 0)
            m.fallback_finalizations = getattr(m, "fallback_finalizations", 0)
            m.transcript_text_extracted = self._transcript_text_extracted
            m.provider_metadata_count = self._provider_metadata_count
            m.provider_unknown_message_count = self._provider_unknown_message_count
            m.last_provider_message_type = self._last_provider_message_type
            m.last_provider_message_summary = self._last_provider_message_summary
            m.last_interim_text = getattr(self, "_last_interim_text", "")
            m.last_final_text = getattr(self, "_last_final_text", "")
            m.send_loop_started = self._send_loop_started
            m.send_loop_alive = self._send_loop_alive
            m.keepalive_loop_started = self._keepalive_loop_started
            m.keepalive_loop_alive = self._keepalive_loop_alive
            return DeepgramBackendMetrics(**{
                f: getattr(m, f) for f in m.__dataclass_fields__
            })

    def get_connection_info(self) -> dict[str, Any]:
        """Return structured connection diagnostics (safe, no secrets)."""
        return {
            "connection_state": self._connection_state.value,
            "connection_attempt": self._connection_attempt,
            "connection_started_at": self._connection_started_at,
            "connection_opened_at": self._connection_opened_at,
            "connection_failed_at": self._connection_failed_at,
            "last_error_category": self._last_error_category,
            "last_error_code": self._last_error_code,
            "last_error_message_safe": self._last_error_message_safe,
            "last_close_code": self._last_close_code,
            "last_close_reason_safe": self._last_close_reason_safe,
            "reconnect_attempt": self._reconnect_attempt,
            "session_id": self._session_id,
            "generation": self._generation,
            "credentials_configured": bool(self._api_key),
            "provider_message_index": self._provider_message_index,
            "last_provider_message_type": self._last_provider_message_type,
            "last_provider_message_summary": self._last_provider_message_summary,
            "provider_metadata_count": self._provider_metadata_count,
            "provider_unknown_message_count": self._provider_unknown_message_count,
        }

    def clear_pending_media(self) -> None:
        """Discard all pending audio frames and reset send counters."""
        while True:
            try:
                self._audio_frame_queue.get_nowait()
            except queue.Empty:
                break
        self._audio_dequeued = 0
        self._audio_send_attempts = 0
        self._audio_send_failed = 0
        self._last_audio_send_at = 0.0
        self._finalization_sequence = 0
        self._provider_messages_received = 0
        self._provider_utterance_end_count = 0
        self._provider_speech_started_count = 0
        self._last_provider_message_text = ""
        self._provider_results_received = 0
        self._provider_results_empty = 0
        self._provider_results_with_text = 0
        self._provider_results_interim = 0
        self._provider_results_final = 0
        self._provider_results_speech_final = 0
        self._transcript_text_extracted = 0
        self._provider_metadata_count = 0
        self._provider_unknown_message_count = 0
        self._provider_message_index = 0
        self._last_provider_message_type = None
        self._last_provider_message_summary = ""

    # ------------------------------------------------------------------
    # Public API — event draining (called from main Streamlit thread)
    # ------------------------------------------------------------------

    def get_finalized_transcripts(self) -> list:
        events = []
        while True:
            try:
                event = self._finalized_queue.get_nowait()
                events.append(event)
            except queue.Empty:
                break
        return events

    def get_interim_transcripts(self) -> list:
        events = []
        while True:
            try:
                event = self._interim_queue.get_nowait()
                events.append(event)
            except queue.Empty:
                break
        return events

    def get_interim_diagnostics(self) -> dict:
        _latest_interim = ""
        _items = []
        while True:
            try:
                _items.append(self._interim_queue.get_nowait())
            except queue.Empty:
                break
        for item in _items:
            try:
                self._interim_queue.put_nowait(item)
            except queue.Full:
                break
        if _items:
            _latest_interim = str(_items[-1])

        _latest_finalized = ""
        _items = []
        while True:
            try:
                _items.append(self._finalized_queue.get_nowait())
            except queue.Empty:
                break
        for item in _items:
            try:
                self._finalized_queue.put_nowait(item)
            except queue.Full:
                break
        if _items:
            _latest_finalized = getattr(_items[-1], "transcript", str(_items[-1]))

        return {
            "last_interim_transcript": _latest_interim,
            "last_finalized_transcript": self._last_final_text or _latest_finalized,
            "backend_health": self.health_status(),
            "audio_queue_size": self._audio_frame_queue.qsize(),
            "finalized_queue_size": self._finalized_queue.qsize(),
            "interim_queue_size": self._interim_queue.qsize(),
            "finalized_utterances_emitted": self._completed_utterance_count,
        }

    def get_diagnostics(self) -> dict:
        """Return backend diagnostics without draining queues."""
        return {
            "backend_health": self.health_status(),
            "audio_queue_size": self._audio_frame_queue.qsize(),
            "finalized_queue_size": self._finalized_queue.qsize(),
            "interim_queue_size": self._interim_queue.qsize(),
            "finalized_utterances_emitted": self._completed_utterance_count,
            "empty_transcript_count": self._empty_transcript_count,
            "accumulator_final_segments": self._accumulator_final_segments,
            "accumulator_seal_attempts": self._accumulator_seal_attempts,
            "accumulator_seal_success": self._accumulator_seal_success,
            "emit_finalized_calls": self._emit_finalized_calls,
            "finalized_queue_put_success": self._finalized_queue_put_success,
        }

    def get_errors(self) -> list:
        errors = []
        while True:
            try:
                err = self._error_queue.get_nowait()
                errors.append(err)
            except queue.Empty:
                break
        return errors

    # ------------------------------------------------------------------
    # Internal — connection management (I/O thread only)
    # ------------------------------------------------------------------

    def _set_connection_state(self, state: _ConnectionState) -> None:
        with self._state_lock:
            self._connection_state = state
            if state == _ConnectionState.CONNECTED:
                self._connection_start_ts = time.monotonic()
            elif state in (
                _ConnectionState.STOPPED,
                _ConnectionState.FAILED,
                _ConnectionState.DISCONNECTED,
            ):
                self._connection_start_ts = None

    def _reset_queues(self) -> None:
        for q in (
            self._audio_frame_queue,
            self._finalized_queue,
            self._interim_queue,
            self._error_queue,
        ):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def _build_connect_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "language": self._language,
            "encoding": "linear16",
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "interim_results": self._interim_results,
            "endpointing": self._endpointing_ms,
            "smart_format": True,
            "punctuate": False,
            "numerals": True,
            "vad_events": True,
            "utterance_end_ms": 1000,
        }

        if self._keyterms_raw:
            from tournament_platform.app.services.asr_backends.deepgram_adapter import (
                build_deepgram_keyterms,
            )
            kr = build_deepgram_keyterms(
                player_names=[],
                language=self._language,
                custom_terms=self._keyterms_raw,
                max_terms=self._max_keyterms,
            )
            kwargs["keyterm"] = list(kr.terms)
            with self._metrics_lock:
                self._metrics.keyterm_count = kr.count

        return kwargs

    def _io_loop(self) -> None:
        """Main I/O loop running on the dedicated thread."""
        attempt = 0
        while not self._stop_event.is_set() and attempt <= self._reconnect_attempts:
            exc: Optional[Exception] = None
            try:
                self._connect_and_listen()
            except Exception as e:
                exc = e

            if self._stop_event.is_set():
                return

            if exc is not None:
                if isinstance(exc, _AuthError):
                    self._error_queue.put_nowait(("auth_failure", "authentication_error"))
                    self._set_connection_state(_ConnectionState.FAILED)
                    self._connection_failed_at = time.monotonic()
                    safe_err = sanitize_deepgram_error(exc, self._connect_timeout_seconds)
                    self._last_error_category = safe_err.category
                    self._last_error_code = safe_err.code
                    self._last_error_message_safe = safe_err.message_safe
                    break
                logger.warning(
                    "Deepgram I/O loop error (attempt %d): %s", attempt, exc
                )
                safe_err = sanitize_deepgram_error(exc, self._connect_timeout_seconds)
                with self._metrics_lock:
                    self._metrics.deepgram_error_category = safe_err.category
                    self._reconnect_count += 1
                    self._metrics.reconnect_count += 1
                self._last_error_category = safe_err.category
                self._last_error_code = safe_err.code
                self._last_error_message_safe = safe_err.message_safe
                self._connection_failed_at = time.monotonic()
                attempt += 1
                if not self._should_retry(attempt):
                    self._set_connection_state(_ConnectionState.FAILED)
                    self._error_queue.put_nowait(("connection_error", safe_err.message_safe))
                    break
                self._set_connection_state(_ConnectionState.RECONNECTING)
                self._reconnect_attempt = attempt
                time.sleep(min(2 ** attempt, 5.0))
            else:
                attempt += 1
                if not self._should_retry(attempt):
                    self._set_connection_state(_ConnectionState.FAILED)
                    self._error_queue.put_nowait(
                        ("connection_closed", "Deepgram connection closed")
                    )
                    self._last_close_reason_safe = "Deepgram connection closed"
                    break
                self._set_connection_state(_ConnectionState.RECONNECTING)
                self._reconnect_attempt = attempt
                time.sleep(min(2 ** attempt, 5.0))

    def _should_retry(self, attempt: int) -> bool:
        return attempt <= self._reconnect_attempts

    def _connect_and_listen(self) -> None:
        """Connect to Deepgram, start listening, and drain the audio queue."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

        api_key = self._api_key
        if not api_key:
            raise _AuthError("Deepgram API key not configured")

        try:
            from deepgram import DeepgramClient
            from deepgram.core.api_error import ApiError
        except ImportError:
            raise ImportError(
                "deepgram-sdk is not installed. Run: pip install deepgram-sdk>=7.6.0"
            )

        connect_kwargs = self._build_connect_kwargs()
        self._set_connection_state(_ConnectionState.CONNECTING)

        client = DeepgramClient(api_key=api_key)
        self._client = client

        establish_result: dict = {}

        def _establish() -> None:
            try:
                cm = client.listen.v1.connect(**connect_kwargs)
                connection = cm.__enter__()
                establish_result["connection"] = connection
                establish_result["cm"] = cm
            except ApiError as exc:
                if exc.status_code == 401:
                    establish_result["error"] = _AuthError(str(exc))
                else:
                    establish_result["error"] = exc
            except Exception as exc:
                establish_result["error"] = exc

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_establish)
        try:
            future.result(timeout=self._connect_timeout_seconds)
        except FuturesTimeoutError:
            raise TimeoutError(
                f"Deepgram connection timed out after "
                f"{self._connect_timeout_seconds}s"
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if "error" in establish_result:
            raise establish_result["error"]

        connection = establish_result["connection"]
        cm = establish_result["cm"]
        self._connection = connection
        self._on_connection_open(connection)
        self._set_connection_state(_ConnectionState.CONNECTED)
        self._connection_opened_at = time.monotonic()
        self._connection_open_event.set()

        send_thread = threading.Thread(
            target=self._send_loop, name=f"deepgram-send-{self._generation}",
            daemon=True,
        )
        keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            name=f"deepgram-keepalive-{self._generation}",
            daemon=True,
        )
        send_thread.start()
        keepalive_thread.start()

        try:
            connection.start_listening()
        finally:
            self._stop_event.set()
            send_thread.join(timeout=2.0)
            keepalive_thread.join(timeout=2.0)
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass

    def _on_connection_open(self, connection: Any) -> None:
        """Register event handlers on a newly opened connection."""
        from deepgram.core.events import EventType

        connection.on(EventType.OPEN, self._handle_open)
        connection.on(EventType.MESSAGE, self._handle_message)
        connection.on(EventType.ERROR, self._handle_error)
        connection.on(EventType.CLOSE, self._handle_close)

    def _handle_open(self, _: Any = None) -> None:
        logger.debug("Deepgram connection opened")
        with self._metrics_lock:
            self._provider_open_count += 1
        self._set_connection_state(_ConnectionState.CONNECTED)
        self._connection_opened_at = time.monotonic()
        self._connection_open_event.set()

    def _handle_message(self, message: Any) -> None:
        from deepgram.core.events import EventType

        with self._metrics_lock:
            self._provider_messages_received += 1
            self._provider_message_index = self._provider_messages_received

            if isinstance(message, dict):
                _class = "dict"
                _msg_type = message.get("type")
            else:
                _class = type(message).__name__
                _msg_type = getattr(message, "type", None)

            # Classify event type
            is_results = str(_msg_type).lower() == "results"
            is_metadata = str(_msg_type).lower() == "metadata"
            is_speech_started = str(_msg_type).lower() == "speechstarted"
            is_utterance_end = str(_msg_type).lower() == "utteranceend"

            # Results field inspection
            _channel_present = False
            _alternatives_count = 0
            _transcript_present = False
            _transcript_length = 0
            if is_results:
                if isinstance(message, dict):
                    _channel = message.get("channel")
                    _channel_present = _channel is not None
                    _alternatives = _channel.get("alternatives") if _channel else None
                    _alternatives_count = len(_alternatives) if _alternatives else 0
                    if _alternatives and len(_alternatives) > 0:
                        _text = _alternatives[0].get("transcript", "") or ""
                        _transcript_present = bool(_text)
                        _transcript_length = len(_text)
                else:
                    _channel = getattr(message, "channel", None)
                    _channel_present = _channel is not None
                    _alternatives = getattr(_channel, "alternatives", None) if _channel else None
                    _alternatives_count = len(_alternatives) if _alternatives else 0
                    if _alternatives and len(_alternatives) > 0:
                        _text = getattr(_alternatives[0], "transcript", "") or ""
                        _transcript_present = bool(_text)
                        _transcript_length = len(_text)

            self._last_provider_message_type = _msg_type
            self._last_provider_message_summary = (
                f"class={_class} type={_msg_type or 'unknown'} "
                f"results={is_results} metadata={is_metadata} "
                f"speech_started={is_speech_started} utterance_end={is_utterance_end} "
                f"transcript_present={_transcript_present} transcript_length={_transcript_length}"
            )

            # Terminal classification counters
            if is_metadata:
                self._provider_metadata_count += 1
            elif is_speech_started:
                self._provider_speech_started_count += 1
            elif is_utterance_end:
                self._provider_utterance_end_count += 1
            elif is_results:
                self._provider_results_received += 1
                text = self._adapter.extract_transcript(message)
                if text:
                    self._provider_results_with_text += 1
                    self._transcript_text_extracted += 1
                    self._last_provider_message_text = text[:200]
                    
                    # Audit/DEBUG logging for non-empty results (plan §2)
                    _is_f = self._adapter.is_final(message)
                    _is_sf = self._adapter.is_speech_final(message)
                    _conf = self._adapter.extract_confidence(message)
                    logger.debug(
                        "Deepgram Result: transcript='%s' is_final=%s speech_final=%s conf=%.3f",
                        text, _is_f, _is_sf, _conf
                    )
                else:
                    self._provider_results_empty += 1
                    self._last_provider_message_text = ""
            else:
                self._provider_unknown_message_count += 1
                logger.debug(
                    "Deepgram unknown message: class=%s type=%s",
                    _class,
                    _msg_type,
                )

        if is_results:
            self._handle_results(message)
            text = self._adapter.extract_transcript(message)
            if text:
                is_final = self._adapter.is_final(message)
                if is_final:
                    self._last_final_text = text[:200]
                else:
                    self._last_interim_text = text[:200]
        elif is_utterance_end:
            self._handle_utterance_end()

    def _handle_results(self, message: Any) -> None:
        is_final = self._adapter.is_final(message)
        speech_final = self._adapter.is_speech_final(message)
        text = self._adapter.extract_transcript(message)
        confidence = self._adapter.extract_confidence(message)

        if _is_interim_message(message):
            with self._metrics_lock:
                self._metrics.interim_transcript_count += 1
                self._interim_count += 1
                self._metrics.interim_transcript_count = self._interim_count
                self._provider_results_interim += 1
            try:
                self._interim_queue.put_nowait((text, self._session_id))
            except queue.Full:
                pass
            return

        if is_final or speech_final:
            with self._metrics_lock:
                self._metrics.final_segment_count += 1
                self._final_segment_count += 1
                if is_final:
                    self._provider_results_final += 1
                if speech_final:
                    self._provider_results_speech_final += 1

        finalized = self._utterance_accumulator.on_message(
            text=text,
            is_final=is_final,
            speech_final=speech_final,
            is_interim=False,
            finalize_timeout_ms=self._finalize_timeout_ms,
            max_utterance_ms=self._max_utterance_ms,
            confidence=confidence,
        )
        if finalized is not None:
            text, conf = finalized
            self._emit_finalized(text, "speech_final", confidence=conf)

        # Inactivity checks
        self._utterance_accumulator.check_timeout(self._finalize_timeout_ms)

        fallback = self._utterance_accumulator.check_fallback_seal(
            fallback_ms=max(self._finalize_timeout_ms + 300, 1500)
        )
        if fallback is not None:
            text, conf = fallback
            self._emit_finalized(text, "finalize_timeout", confidence=conf)

        if self._last_finalize_request > 0 and self._utterance_accumulator.needs_finalize():
            try:
                self._connection.send_finalize()
            except Exception as exc:
                logger.debug("send_finalize error: %s", exc)
            self._last_finalize_request = 0.0

    def _handle_utterance_end(self) -> None:
        sealed = self._utterance_accumulator.on_utterance_end()
        if sealed is not None:
            text, conf = sealed
            self._emit_finalized(text, "utterance_end", confidence=conf)

    def _handle_error(self, exc: Any) -> None:
        with self._metrics_lock:
            self._metrics.deepgram_error_category = "websocket_error"
            self._provider_error_count += 1
            self._provider_unerror_count = 0
        if exc is None:
            _err_desc = "websocket_error"
        else:
            _err_desc = self._sanitize_error_message(str(exc))
            if not _err_desc:
                _err_desc = type(exc).__name__
        try:
            self._error_queue.put_nowait(("websocket_error", _err_desc))
        except queue.Full:
            pass
        self._set_connection_state(_ConnectionState.FAILED)
        self._connection_failed_at = time.monotonic()
        if isinstance(exc, BaseException):
            safe_err = sanitize_deepgram_error(exc, self._connect_timeout_seconds)
            self._last_error_category = safe_err.category
            self._last_error_code = safe_err.code
            self._last_error_message_safe = safe_err.message_safe
        self._connection_open_event.clear()

    def _handle_close(self, _: Any = None) -> None:
        logger.debug("Deepgram connection closed")
        with self._metrics_lock:
            self._provider_close_count += 1
        if self._connection_state != _ConnectionState.STOPPING:
            self._set_connection_state(_ConnectionState.DISCONNECTED)
            self._last_close_reason_safe = "Deepgram connection closed by remote"
        self._connection_open_event.clear()

    def _emit_finalized(self, text: str, finalization_reason: str = "speech_final", confidence: float = 1.0) -> None:
        self._emit_finalized_calls += 1
        if not text:
            with self._metrics_lock:
                self._metrics.empty_transcript_count += 1
                self._empty_transcript_count += 1
            return

        raw_text = text
        normalized = self._adapter.process_transcript(text, is_interim=False)

        self._finalization_sequence += 1
        utterance_id = (
            f"{self._session_id}:"
            f"{self._generation}:"
            f"{self._finalization_sequence}"
        )

        utterance = FinalizedUtterance(
            voice_session_id=self._session_id,
            backend_generation=self._generation,
            match_id=None,
            language=self._language,
            utterance_id=utterance_id,
            created_at=time.time(),
            transcript=normalized,
            raw_transcript=raw_text,
            finalization_reason=finalization_reason,
            confidence=confidence,
            acoustic_confidence=confidence,  # Quick Win 8
        )

        with self._metrics_lock:
            self._metrics.completed_utterance_count += 1
            self._completed_utterance_count += 1
            self._metrics.last_finalization_reason = finalization_reason
            self._last_final_text = text[:200]
            if finalization_reason == "speech_final":
                self._metrics.speech_final_received += 1
            elif finalization_reason == "utterance_end":
                self._metrics.utterance_end_received += 1
            elif finalization_reason == "finalize_timeout":
                self._metrics.fallback_finalizations += 1

        try:
            self._finalized_queue.put_nowait(utterance)
            self._finalized_queue_put_success += 1
        except queue.Full:
            with self._metrics_lock:
                self._metrics.queue_overflow_count += 1

    def _send_loop(self) -> None:
        """Drain the audio frame queue and send PCM to Deepgram."""
        self._send_loop_started = True
        try:
            while not self._stop_event.is_set():
                self._send_loop_alive = True
                if not self._connection_open_event.is_set():
                    time.sleep(0.01)
                    continue
                try:
                    pcm = self._audio_frame_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if pcm is None:
                    break
                
                with self._metrics_lock:
                    self._audio_send_attempts += 1

                try:
                    self._connection.send_media(pcm)
                    with self._metrics_lock:
                        self._audio_bytes_sent += len(pcm)
                        self._audio_duration_sent_ms += (
                            len(pcm) / (self._sample_rate * self._channels * 2) * 1000.0
                        )
                        self._metrics.audio_bytes_sent = self._audio_bytes_sent
                        self._metrics.audio_duration_sent_ms = self._audio_duration_sent_ms
                        self._audio_send_success += 1
                        self._last_audio_send_at = time.monotonic()
                        self._audio_dequeued += 1
                except Exception as exc:
                    logger.debug("send_media error: %s", exc)
                    with self._metrics_lock:
                        self._metrics.deepgram_error_category = "send_error"
                        self._audio_send_failed += 1
        finally:
            self._send_loop_alive = False

    def _keepalive_loop(self) -> None:
        """Send keep-alive frames and perform utterance inactivity checks."""
        self._keepalive_loop_started = True
        try:
            while not self._stop_event.is_set():
                self._keepalive_loop_alive = True
                
                # Check for stuck utterances even during silence (plan §6)
                fallback = self._utterance_accumulator.check_fallback_seal(
                    fallback_ms=max(self._finalize_timeout_ms + 300, 1500)
                )
                if fallback is not None:
                    text, conf = fallback
                    self._emit_finalized(text, "finalize_timeout", confidence=conf)

                if not self._connection_open_event.is_set():
                    time.sleep(0.1)
                    continue
                
                # We use a shorter sleep here to make inactivity checks more responsive
                # while still sending keep-alives at the requested interval.
                check_interval = 0.5
                time.sleep(check_interval)
                
                if self._stop_event.is_set():
                    break
                    
                # Only send keep-alive if enough time has passed
                last_keepalive = getattr(self, "_last_keepalive_at", 0.0)
                if time.monotonic() - last_keepalive >= self._keepalive_seconds:
                    if self._connection_open_event.is_set():
                        try:
                            self._connection.send_keep_alive()
                            self._last_keepalive_at = time.monotonic()
                            with self._metrics_lock:
                                self._keepalive_count += 1
                                self._metrics.keepalive_count += 1
                        except Exception as exc:
                            logger.debug("send_keep_alive error: %s", exc)
        finally:
            self._keepalive_loop_alive = False

    # ------------------------------------------------------------------
    # BackendStatus
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if a Deepgram API key is configured."""
        return bool(self._api_key)

    def get_status(self) -> BackendStatus:
        available = self.is_available()
        status = BackendStatus(
            backend_name=self.backend_name,
            available=available,
            model_info={
                "model": self._model,
                "language": self._language,
                "sample_rate": self._sample_rate,
                "channels": self._channels,
                "endpointing_ms": self._endpointing_ms,
                "connection_state": self._connection_state.value,
            },
            load_error=None if available else "VOICE_DEEPGRAM_API_KEY not set",
            setup_instructions="" if available else (
                "Set VOICE_DEEPGRAM_ENABLED=true and VOICE_DEEPGRAM_API_KEY=<your-key>"
            ),
        )
        return status.with_capabilities(self._capabilities)


def _is_interim_message(message: Any) -> bool:
    """Check if a Deepgram message is interim (is_final is False)."""
    if isinstance(message, dict):
        return message.get("is_final") is False
    return getattr(message, "is_final", None) is False
