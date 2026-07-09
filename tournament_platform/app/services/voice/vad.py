"""
Voice Activity Detection (Phase 3)

Provides a VAD interface with multiple backends:
- webrtcvad (primary, lightweight, no model download)
- Silero VAD (optional, ONNX, more accurate in noise)
- Amplitude/RMS fallback (always available)
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32, SAMPLE_FORMAT_INT16

logger = logging.getLogger(__name__)


class VoiceActivityDetector(ABC):
    """Abstract base class for voice activity detectors."""

    @abstractmethod
    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        """Return True if the frame contains speech."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError


class AmplitudeVAD(VoiceActivityDetector):
    """RMS-amplitude based VAD (always available fallback)."""

    def __init__(self, threshold: float = 0.01, sample_format: str = SAMPLE_FORMAT_FLOAT32):
        self.threshold = threshold
        self.sample_format = sample_format

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        if not frame_bytes:
            return False
        try:
            if self.sample_format == SAMPLE_FORMAT_INT16:
                audio = np.frombuffer(frame_bytes, dtype=np.int16)
                if len(audio) == 0:
                    return False
                float_audio = audio.astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(float_audio ** 2)))
            else:
                audio = np.frombuffer(frame_bytes, dtype=np.float32)
                if len(audio) == 0:
                    return False
                rms = float(np.sqrt(np.mean(audio ** 2)))
            return rms > self.threshold
        except Exception:
            return False

    @property
    def name(self) -> str:
        return "amplitude"


class WebRTCVAD(VoiceActivityDetector):
    """webrtcvad-based VAD (primary, lightweight)."""

    def __init__(self, aggressiveness: int = 2):
        self._vad = None
        self._aggressiveness = aggressiveness
        self._load_error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self._aggressiveness)
        except ImportError:
            self._load_error = "webrtcvad not installed"
        except Exception as exc:
            self._load_error = str(exc)

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        if self._vad is None:
            return False
        try:
            if sample_rate not in (8000, 16000, 32000, 48000):
                return False
            frame_duration_ms = self._infer_frame_duration_ms(frame_bytes, sample_rate)
            if frame_duration_ms not in (10, 20, 30):
                return False
            return self._vad.is_speech(frame_bytes, sample_rate)
        except Exception:
            return False

    @staticmethod
    def _infer_frame_duration_ms(frame_bytes: bytes, sample_rate: int) -> int:
        num_samples = len(frame_bytes) / 2  # int16
        duration_ms = (num_samples / sample_rate) * 1000.0
        candidates = (10, 20, 30)
        return min(candidates, key=lambda ms: abs(ms - duration_ms))

    @property
    def name(self) -> str:
        return "webrtcvad"


class SileroVAD(VoiceActivityDetector):
    """Silero VAD (optional, ONNX, accurate in noisy venues)."""

    def __init__(self):
        self._model = None
        self._load_error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            from silero_vad import load_silero_vad, get_speech_timestamps
            self._model = load_silero_vad()
            self._get_speech_timestamps = get_speech_timestamps
        except ImportError:
            self._load_error = "silero-vad not installed"
        except Exception as exc:
            self._load_error = str(exc)

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        if self._model is None:
            return False
        try:
            import torch
            audio = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            tensor = torch.from_numpy(audio)
            timestamps = self._get_speech_timestamps(tensor, self._model, sampling_rate=sample_rate)
            return len(timestamps) > 0
        except Exception:
            return False

    @property
    def name(self) -> str:
        return "silero"


def create_vad(prefer: Optional[str] = None) -> VoiceActivityDetector:
    """Create the best available VAD.

    Args:
        prefer: Optional backend name ("webrtcvad", "silero", "amplitude").

    Returns:
        VoiceActivityDetector instance.
    """
    if prefer == "amplitude":
        return AmplitudeVAD()
    if prefer == "silero":
        vad = SileroVAD()
        if vad._load_error:
            logger.warning("Silero VAD unavailable: %s; falling back to webrtcvad", vad._load_error)
            return create_vad(prefer="webrtcvad")
        return vad
    if prefer == "webrtcvad":
        vad = WebRTCVAD()
        if vad._load_error:
            logger.warning("WebRTC VAD unavailable: %s; falling back to amplitude", vad._load_error)
            return AmplitudeVAD()
        return vad
    # Auto-select: webrtcvad > silero > amplitude
    vad = WebRTCVAD()
    if vad._load_error:
        vad = SileroVAD()
        if vad._load_error:
            return AmplitudeVAD()
    return vad
