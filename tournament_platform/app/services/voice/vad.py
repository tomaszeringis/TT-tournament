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


def normalize_audio(arr: object) -> np.ndarray:
    """Normalize raw audio into float32 PCM in ``[-1, 1]``.

    Safe for empty, ``None``, NaN/inf, int16, float, and multi-dimensional
    arrays. Only integer PCM is divided by ``32768.0``; float PCM already in
    ``[-1, 1]`` is left untouched. This prevents ``RuntimeWarning: invalid
    value encountered in divide`` on silent or malformed input.

    Returns an empty float32 array when input is empty/None.
    """
    if arr is None:
        return np.empty(0, dtype=np.float32)

    arr = np.asarray(arr)

    if arr.size == 0:
        return np.empty(0, dtype=np.float32)

    if arr.ndim > 1:
        arr = arr.reshape(-1)

    if np.issubdtype(arr.dtype, np.integer):
        arr = arr.astype(np.float32) / 32768.0
    else:
        arr = arr.astype(np.float32, copy=False)

    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    # If float audio accidentally arrives in int-like scale, normalize it.
    max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
    if max_abs > 2.0:
        arr = arr / 32768.0

    return np.clip(arr, -1.0, 1.0)


def safe_rms(audio: Optional[np.ndarray]) -> float:
    """Compute RMS safely without int overflow or NaN propagation.

    Args:
        audio: Audio samples as a numpy array (any dtype), or None.

    Returns:
        Finite RMS float in [0, 1] for normalized audio, or 0.0 for empty/invalid input.
    """
    if audio is None:
        return 0.0

    arr = normalize_audio(audio)

    if arr.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(arr, dtype=np.float32), dtype=np.float32)))


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
            else:
                audio = np.frombuffer(frame_bytes, dtype=np.float32)
                if len(audio) == 0:
                    return False
            rms = safe_rms(audio)
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
            logger.warning("Silero VAD unavailable: %s; falling back to amplitude", vad._load_error)
            return AmplitudeVAD()
        return vad
    if prefer == "webrtcvad":
        vad = WebRTCVAD()
        if vad._load_error:
            logger.warning("WebRTC VAD unavailable: %s; falling back to amplitude", vad._load_error)
            return AmplitudeVAD()
        return vad
    # Default to AmplitudeVAD for reliability (especially continuous-mode
    # float32 frames), then webrtcvad, then silero.
    vad = AmplitudeVAD()
    logger.info("Using AmplitudeVAD (default)")
    return vad
