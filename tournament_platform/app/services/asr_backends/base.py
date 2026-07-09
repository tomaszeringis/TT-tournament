"""
ASR Backend Abstraction Layer

Defines the common interface that all ASR backends (faster-whisper, SpeechBrain,
future cloud/edge providers) must implement. This keeps the voice scorekeeper
decoupled from any single ASR implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackendStatus:
    """Structured status for an ASR backend."""
    backend_name: str = ""
    available: bool = False
    model_info: dict = field(default_factory=dict)
    load_error: Optional[str] = None
    setup_instructions: str = ""


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
