"""
SpeechBrain ASR Backend

Pluggable SpeechBrain backend for the ASR abstraction layer.
Uses EncoderDecoderASR with lazy loading and graceful failure.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from typing import Optional

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.app.services.voice_vocab import VoiceVocabulary

logger = logging.getLogger(__name__)


class SpeechBrainBackend(ASRBackend):
    """
    SpeechBrain ASR backend using EncoderDecoderASR.

    The model is loaded lazily on first transcription to avoid blocking
    Streamlit import time. SpeechBrain is an optional dependency,
    so the backend reports unavailable if torch/speechbrain are missing.
    """

    backend_name = "speechbrain"

    def __init__(self, vocabulary: Optional[VoiceVocabulary] = None) -> None:
        self.vocabulary = vocabulary
        self._model = None
        self._load_attempted = False
        self._load_failed = False
        self._load_error: Optional[str] = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if self._load_attempted:
            return

        self._load_attempted = True
        try:
            from speechbrain.inference.ASR import EncoderDecoderASR  # noqa: F401

            source = os.environ.get(
                "SPEECHBRAIN_SOURCE",
                "speechbrain/asr-crdnn-rnnlm-librispeech",
            )
            device = os.environ.get("SPEECHBRAIN_DEVICE", "cpu")

            logger.info(
                "Loading SpeechBrain ASR model: source=%s, device=%s",
                source, device,
            )
            from speechbrain.inference.ASR import EncoderDecoderASR

            self._model = EncoderDecoderASR.from_hparams(source=source, device=device)
            logger.info("SpeechBrain ASR model loaded successfully")

        except ImportError as e:
            self._load_failed = True
            self._load_error = (
                "SpeechBrain is not installed. "
                "Install with: pip install speechbrain[wer,brain] torch torchaudio"
            )
            logger.error(self._load_error)
        except Exception as e:
            self._load_failed = True
            self._load_error = f"Failed to load SpeechBrain model: {e}"
            logger.error("Failed to load SpeechBrain model: %s", e)

    def _transcribe_from_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        if not audio_bytes:
            return ""

        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(fd, "wb") as f:
                with wave.open(f, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_bytes)

            text = self._model.transcribe_file(temp_path)
            return (text or "").strip()

        except Exception as e:
            logger.error("SpeechBrain transcription error: %s", e)
            return ""
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def transcribe_file(self, path: str) -> str:
        self._ensure_model()
        if self._load_failed or self._model is None:
            return ""
        try:
            text = self._model.transcribe_file(path)
            return (text or "").strip()
        except Exception as e:
            logger.error("SpeechBrainBackend file transcription error: %s", e)
            return ""

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        self._ensure_model()
        if self._load_failed or self._model is None:
            return ""
        try:
            text = self._model.transcribe_file(audio_bytes)
            return (text or "").strip()
        except Exception as e:
            logger.error("SpeechBrainBackend PCM transcription error: %s", e)
            return ""

    def is_available(self) -> bool:
        self._ensure_model()
        return not self._load_failed and self._model is not None

    def get_status(self) -> BackendStatus:
        self._ensure_model()
        info = {}
        try:
            if self._model is not None:
                info["source"] = os.environ.get(
                    "SPEECHBRAIN_SOURCE",
                    "speechbrain/asr-crdnn-rnnlm-librispeech",
                )
        except Exception:
            pass

        return BackendStatus(
            backend_name=self.backend_name,
            available=not self._load_failed and self._model is not None,
            model_info=info,
            load_error=self._load_error,
            setup_instructions=(
                "**SpeechBrain Setup**\n\n"
                "1. Install SpeechBrain: `pip install speechbrain[wer,brain]`\n"
                "2. Install PyTorch CPU-only: "
                "`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`\n"
                "3. The model will download automatically on first use.\n\n"
                "Environment variables:\n"
                "- `SPEECHBRAIN_SOURCE` (default: speechbrain/asr-crdnn-rnnlm-librispeech)\n"
                "- `SPEECHBRAIN_DEVICE` (default: cpu)"
                if self._load_failed
                else ""
            ),
        )

    def get_setup_instructions(self) -> str:
        if self._load_failed:
            return (
                "**SpeechBrain Setup**\n\n"
                "1. Install SpeechBrain: `pip install speechbrain[wer,brain]`\n"
                "2. Install PyTorch CPU-only: "
                "`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`\n"
                "3. The model will download automatically on first use.\n\n"
                "Environment variables:\n"
                "- `SPEECHBRAIN_SOURCE` (default: speechbrain/asr-crdnn-rnnlm-librispeech)\n"
                "- `SPEECHBRAIN_DEVICE` (default: cpu)"
            )
        return ""
