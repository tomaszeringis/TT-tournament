"""
ASR Backend Abstraction Layer

Defines the common interface that all ASR backends (faster-whisper, SpeechBrain,
future cloud/edge providers) must implement. This keeps the voice scorekeeper
decoupled from any single ASR implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any, Protocol, runtime_checkable

from tournament_platform.app.services.asr_backends.calibration_policy import (
    ASRCapabilities,
    AudioDeliveryPolicy,
)


# NOTE: FinalizedUtterance is imported lazily inside methods to avoid a
# circular import (events.py <-> runtime.py <-> asr_backends.base).


@dataclass
class BackendStatus:
    """Structured status for an ASR backend."""
    backend_name: str = ""
    available: bool = False
    model_info: dict = field(default_factory=dict)
    load_error: Optional[str] = None
    setup_instructions: str = ""

    def with_capabilities(self, capabilities: ASRCapabilities) -> "BackendStatus":
        """Attach ASR capabilities to this status for UI/policy use."""
        status = BackendStatus(
            backend_name=self.backend_name,
            available=self.available,
            model_info={**self.model_info, "capabilities": capabilities},
            load_error=self.load_error,
            setup_instructions=self.setup_instructions,
        )
        return status


@dataclass(frozen=True)
class TranscriptionResult:
    """Structured result from a calibration-only ASR experiment transcription."""
    text: str
    language: str | None = None
    latency_ms: float = 0.0
    average_log_probability: float | None = None
    no_speech_probability: float | None = None
    metadata: dict = field(default_factory=dict)


class ASRBackend(ABC):
    """
    Protocol/base class for ASR backends.

    Each backend is responsible for turning audio into text. Scoring logic,
    parsing, and match management are intentionally kept outside this layer.
    """

    backend_name: str = ""

    @abstractmethod
    def transcribe_file(self, path: str) -> str:
        """
        Transcribe an audio file and return normalized text.

        Args:
            path: Filesystem path to an audio file.

        Returns:
            Transcribed text string, or empty string on recoverable errors.
        """
        ...

    @abstractmethod
    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribe raw PCM audio bytes and return normalized text.

        Args:
            audio_bytes: Raw PCM audio bytes (typically mono, 16-bit).
            sample_rate: Sample rate of the PCM data.

        Returns:
            Transcribed text string, or empty string on recoverable errors.
        """
        ...

    @abstractmethod
    def transcribe_experiment(
        self,
        *,
        audio: bytes,
        config: Any,
    ) -> TranscriptionResult:
        """
        Transcribe audio using an explicit experiment configuration.

        This calibration-only path reuses the loaded model and passes only
        supported parameters. It never mutates production defaults or
        triggers a model reload.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the backend is ready to transcribe."""
        ...

    @abstractmethod
    def get_status(self) -> BackendStatus:
        """Return structured status information for UI/logging."""
        ...

    def get_setup_instructions(self) -> str:
        """Return human-readable setup instructions if the backend is unavailable."""
        return ""


@dataclass(frozen=True)
class StreamedTranscript:
    """A finalized or interim transcript from a streaming ASR backend."""
    text: str
    is_final: bool
    speech_final: bool
    is_interim: bool
    latency_ms: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class DeepgramBackendMetrics:
    audio_frames_received: int = 0
    audio_bytes_sent: int = 0
    audio_duration_sent_ms: float = 0.0
    audio_send_attempts: int = 0
    audio_send_success: int = 0
    audio_send_failed: int = 0
    last_audio_send_at: float = 0.0
    silence_duration_ms: float = 0.0
    keepalive_count: int = 0
    queue_depth: int = 0
    queue_overflow_count: int = 0
    interim_transcript_count: int = 0
    final_segment_count: int = 0
    completed_utterance_count: int = 0
    empty_transcript_count: int = 0
    speech_final_received: int = 0
    utterance_end_received: int = 0
    fallback_finalizations: int = 0
    last_finalization_reason: Optional[str] = None
    deepgram_error_category: Optional[str] = None
    reconnect_count: int = 0
    speech_end_to_final_latency_ms: Optional[float] = None
    connection_state: str = "disconnected"
    connection_latency_ms: Optional[float] = None
    keyterm_count: int = 0
    provider_messages_received: int = 0
    provider_open_count: int = 0
    provider_close_count: int = 0
    provider_error_count: int = 0
    provider_unerror_count: int = 0
    provider_utterance_end_count: int = 0
    provider_speech_started_count: int = 0
    last_provider_message_text: str = ""
    provider_results_received: int = 0
    provider_results_empty: int = 0
    provider_results_with_text: int = 0
    provider_results_failed_extraction: int = 0
    provider_results_interim: int = 0
    provider_results_final: int = 0
    provider_results_speech_final: int = 0
    transcript_text_extracted: int = 0
    provider_metadata_count: int = 0
    provider_unknown_message_count: int = 0
    last_provider_message_type: Optional[str] = None
    last_provider_message_summary: str = ""
    last_interim_text: str = ""
    last_final_text: str = ""
    send_loop_started: bool = False
    send_loop_alive: bool = False
    keepalive_loop_started: bool = False
    keepalive_loop_alive: bool = False


@runtime_checkable
class StreamingASRBackend(Protocol):
    """Protocol for ASR backends that maintain a persistent streaming connection.

    Streaming backends (e.g. Deepgram Listen v1) receive a continuous PCM
    byte stream and emit finalized utterances as they occur.  They do NOT
    implement the batch ``transcribe_pcm`` contract — see plan §3.4.
    """

    backend_name: str

    def start_session(
        self,
        *,
        language: str,
        session_id: str | None = None,
        generation: int | None = None,
        match_id: Any | None = None,
        keyterms: list[str] | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        """Establish (or re-establish) the streaming connection."""
        ...

    def enqueue_audio(self, pcm_bytes: bytes) -> bool:
        """Enqueue PCM bytes for sending.  Non-blocking.  Returns False if full."""
        ...

    def send_keepalive(self) -> None:
        """Send a keep-alive frame on the connection."""
        ...

    def finalize_utterance(self) -> None:
        """Signal end-of-speech and flush any pending final transcript."""
        ...

    def close(self) -> None:
        """Shut down the connection and release all resources."""
        ...

    def is_available(self) -> bool:
        """Return True if the backend is ready to process audio."""
        ...

    def health_status(self) -> str:
        """Return a provider-independent health status string."""
        ...

    def metrics(self) -> DeepgramBackendMetrics:
        """Return current streaming metrics (privacy-safe: no transcripts)."""
        ...

    def capabilities(self) -> ASRCapabilities:
        """Return the backend's capability flags."""
        ...

    def delivery_policy(self) -> AudioDeliveryPolicy:
        """Return the audio delivery policy for this backend."""
        ...

    def get_finalized_transcripts(self) -> list:
        """Drain and return finalized utterances.

        Returns a list of :class:`FinalizedUtterance` objects (not raw tuples).
        Called from the main Streamlit thread.  See plan §8B.
        """
        ...

    def get_interim_transcripts(self) -> list:
        """Drain and return interim transcript strings for diagnostics."""
        ...

    def get_errors(self) -> list:
        """Drain and return any errors that occurred on the I/O thread."""
        ...


class BatchASRBackend(Protocol):
    """Protocol for backends that transcribe discrete audio chunks (local-first).

    Existing backends (faster-whisper, vosk, speechbrain) implement this.
    """

    backend_name: str

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        ...

    def is_available(self) -> bool:
        ...

    def capabilities(self) -> ASRCapabilities:
        ...

    def delivery_policy(self) -> AudioDeliveryPolicy:
        ...
