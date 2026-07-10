"""
Vosk Grammar ASR Backend (Phase 2)

Provides offline, grammar-constrained speech recognition for constrained
table-tennis commands. Designed as a fallback for weak hardware where
faster-whisper is too slow.

Uses Vosk's SetGrammar to restrict decoding to a known command list,
improving accuracy in noisy halls and reducing CPU load.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from tournament_platform.app.services.asr_backends.base import ASRBackend, BackendStatus
from tournament_platform.services.settings import VOICE_ASR_VOSK_MODEL_PATH

logger = logging.getLogger(__name__)

_VOSK_GRAMMAR = [
    "point red", "point blue", "point player one", "point player two",
    "undo", "take back", "remove point",
    "score five four", "set score five four", "six all", "deuce",
    "start match", "pause", "resume", "next game", "end game",
    "timeout", "end timeout", "player one serves", "player two serves",
    "what's the score", "confirm", "cancel",
]


class VoskGrammarASR(ASRBackend):
    """Vosk-based ASR backend with grammar constraints."""

    backend_name = "vosk"

    def __init__(self, vocabulary=None):
        self._model = None
        self._model_path = VOICE_ASR_VOSK_MODEL_PATH or os.environ.get("VOSK_MODEL_PATH", "model")
        self._vocabulary = vocabulary

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from vosk import Model
            if not os.path.exists(self._model_path):
                raise FileNotFoundError(f"Vosk model not found at {self._model_path}")
            self._model = Model(self._model_path)
            return self._model
        except ImportError as exc:
            raise RuntimeError("Vosk is not installed. Install with: pip install vosk") from exc

    def transcribe_file(self, path: str) -> str:
        try:
            from vosk import KaldiRecognizer
            model = self._load_model()
            recognizer = KaldiRecognizer(model, 16000)
            recognizer.SetGrammar(_VOSK_GRAMMAR)
            with open(path, "rb") as f:
                while True:
                    data = f.read(4000)
                    if len(data) == 0:
                        break
                    recognizer.AcceptWaveform(data)
            result = json.loads(recognizer.FinalResult())
            return result.get("text", "").strip()
        except Exception as exc:
            logger.error("Vosk file transcription failed: %s", exc)
            return ""

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        try:
            from vosk import KaldiRecognizer
            model = self._load_model()
            recognizer = KaldiRecognizer(model, sample_rate)
            recognizer.SetGrammar(_VOSK_GRAMMAR)
            recognizer.AcceptWaveform(audio_bytes)
            result = json.loads(recognizer.FinalResult())
            return result.get("text", "").strip()
        except Exception as exc:
            logger.error("Vosk PCM transcription failed: %s", exc)
            return ""

    def is_available(self) -> bool:
        try:
            from vosk import Model
            return os.path.exists(self._model_path)
        except ImportError:
            return False

    def get_status(self) -> BackendStatus:
        available = self.is_available()
        return BackendStatus(
            backend_name=self.backend_name,
            available=available,
            model_info={"model_path": self._model_path, "grammar_size": len(_VOSK_GRAMMAR)},
            load_error=None if available else f"Vosk model not found at {self._model_path} or vosk not installed",
            setup_instructions="Install vosk (pip install vosk) and download a model to VOSK_MODEL_PATH.",
        )
