"""
Faster-Whisper Backend

Wraps the existing LocalASR implementation so it can be used interchangeably
with other ASR backends through the ASRBackend protocol.
"""

from __future__ import annotations

import logging
from typing import Optional

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.voice_asr import LocalASR
from tournament_platform.app.services.voice_vocab import VoiceVocabulary

logger = logging.getLogger(__name__)


class FasterWhisperBackend(ASRBackend):
    """
    Faster-whisper ASR backend.

    Delegates to the existing LocalASR wrapper to preserve the current
    environment variable overrides, lazy loading behavior, and model cache.
    """

    backend_name = "faster_whisper"

    def __init__(self, vocabulary: Optional[VoiceVocabulary] = None) -> None:
        self.vocabulary = vocabulary
        self._asr: Optional[LocalASR] = None

    def _get_asr(self) -> LocalASR:
        if self._asr is None:
            self._asr = LocalASR(vocabulary=self.vocabulary)
        return self._asr

    def transcribe_file(self, path: str) -> str:
        asr = self._get_asr()
        try:
            import wave
            with wave.open(path, "rb") as wf:
                frames = wf.readframes(wf.getnframes())
            sample_rate = wf.getframerate()
            return self.transcribe_pcm(frames, sample_rate=sample_rate)
        except Exception as e:
            logger.error("FasterWhisperBackend file transcription error: %s", e)
            return ""

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        asr = self._get_asr()
        try:
            return asr.transcribe_chunk(audio_bytes)
        except Exception as e:
            logger.error("FasterWhisperBackend PCM transcription error: %s", e)
            return ""

    def is_available(self) -> bool:
        try:
            return self._get_asr().is_available()
        except Exception:
            return False

    def get_status(self) -> BackendStatus:
        asr = self._get_asr()
        status = asr.get_status()
        available = bool(status.get("available", False))
        return BackendStatus(
            backend_name=self.backend_name,
            available=available,
            model_info={
                "model_size": status.get("model_size"),
                "device": status.get("device"),
                "compute_type": status.get("compute_type"),
                "state": status.get("state"),
                "reason": status.get("reason"),
            },
            load_error=status.get("load_error") if not available else None,
            setup_instructions=asr.get_setup_instructions() if not available else "",
        )

    def get_setup_instructions(self) -> str:
        try:
            return self._get_asr().get_setup_instructions()
        except Exception:
            return "Install faster-whisper: pip install faster-whisper"
