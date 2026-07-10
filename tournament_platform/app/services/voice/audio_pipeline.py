"""
Voice Audio Pipeline (Phase 2)

Unified audio processing interface for push-to-talk and WebRTC inputs.
Handles resampling to 16 kHz mono, noise gating, VAD pass-through metadata,
and chunk validation.

Design goals:
- Single source of truth for audio format conversion.
- Eliminates duplication between _audio_input_to_pcm() and AudioChunk.to_pcm_bytes().
- Provides consistent metadata (rms, duration_ms, sample_rate) for metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from tournament_platform.app.services.voice.vad import VoiceActivityDetector
from tournament_platform.services.settings import (
    VOICE_ENABLE_NOISE_FILTERING,
    VOICE_NOISE_THRESHOLD,
)

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # 16-bit


@dataclass
class PipelineResult:
    """Result of processing an audio input through the pipeline."""

    pcm_bytes: bytes
    rms: float = 0.0
    duration_ms: float = 0.0
    sample_rate: int = _SAMPLE_RATE
    channels: int = _CHANNELS
    noise_gated: bool = False
    vad_speech: bool = True
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def _compute_rms(pcm_bytes: bytes) -> float:
    """Compute RMS of 16-bit mono PCM."""
    if not pcm_bytes:
        return 0.0
    try:
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(arr ** 2)) / 32768.0)
    except Exception as exc:
        logger.debug("RMS computation failed: %s", exc)
        return 0.0


def _resample_to_16k_mono(
    audio_bytes: bytes,
    src_rate: int,
    src_format: str = "s16",
    src_channels: int = 1,
) -> bytes:
    """Resample audio to 16 kHz mono 16-bit PCM using av if available."""
    try:
        import av

        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=_SAMPLE_RATE,
        )
        container = av.open(io.BytesIO(audio_bytes))
        stream = next(s for s in container.streams if s.type == "audio")
        pcm_frames = []
        for packet in container.demux(stream):
            for frame in packet.decode():
                try:
                    resampled = resampler.resample(frame)
                except av.AudioResamplerError:
                    if frame.sample_rate != _SAMPLE_RATE or frame.channels != 1 or frame.format.name != "s16":
                        import av
                        fallback = av.AudioResampler(
                            format="s16",
                            layout="mono",
                            rate=_SAMPLE_RATE,
                        )
                        resampled = fallback.resample(frame)
                    else:
                        raise
                pcm_frames.append(resampled.to_ndarray().tobytes())
        return b"".join(pcm_frames)
    except Exception as exc:
        logger.debug("av resampling failed (%s), falling back to numpy", exc)
        return _resample_with_numpy(audio_bytes, src_rate, src_format, src_channels)


def _resample_with_numpy(
    audio_bytes: bytes,
    src_rate: int,
    src_format: str,
    src_channels: int,
) -> bytes:
    """NumPy-based resampling fallback."""
    try:
        if src_format in ("flt", "f32", "fltp", "f32p"):
            arr = np.frombuffer(audio_bytes, dtype=np.float32)
        else:
            arr = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

        if src_channels > 1:
            arr = arr.reshape(-1, src_channels).mean(axis=1)

        duration = len(arr) / src_rate
        target_len = int(duration * _SAMPLE_RATE)
        xp = np.linspace(0, len(arr) - 1, len(arr))
        fp = np.linspace(0, len(arr) - 1, target_len)
        resampled = np.interp(fp, xp, arr)
        return resampled.astype(np.int16).tobytes()
    except Exception as exc:
        logger.error("NumPy resampling failed: %s", exc)
        return audio_bytes


def _apply_noise_gate(pcm_bytes: bytes, threshold: float) -> Tuple[bytes, bool]:
    """Apply noise gate. Returns (pcm_bytes, was_gated)."""
    if threshold <= 0.0:
        return pcm_bytes, False
    rms = _compute_rms(pcm_bytes)
    if rms < threshold:
        logger.debug("Noise gate rejected chunk: RMS %.4f < threshold %.4f", rms, threshold)
        return b"", True
    return pcm_bytes, False


def validate_pcm(pcm_bytes: bytes) -> bool:
    """Basic sanity check for PCM data."""
    if not pcm_bytes:
        return False
    if len(pcm_bytes) % _SAMPLE_WIDTH != 0:
        return False
    return True


import io


class AudioPipeline:
    """
    Unified audio processing pipeline.

    Usage:
        pipeline = AudioPipeline(noise_threshold=0.01, vad=None)
        result = pipeline.process_push_to_talk(audio_file_bytes, src_rate=48000)
        # or
        chunk = pipeline.process_webrtc_frame(frame, existing_buffer)
    """

    def __init__(
        self,
        noise_threshold: float = 0.0,
        vad: Optional[VoiceActivityDetector] = None,
        enable_noise_filtering: bool = False,
    ):
        self.noise_threshold = noise_threshold if enable_noise_filtering else 0.0
        self.vad = vad
        self.enable_noise_filtering = enable_noise_filtering

    def process_push_to_talk(
        self,
        audio_file: bytes,
        src_rate: int = 48000,
        src_format: str = "flt",
        src_channels: int = 1,
    ) -> PipelineResult:
        """Process push-to-talk audio file through the pipeline."""
        start = time.time()
        pcm_bytes = _resample_to_16k_mono(audio_file, src_rate, src_format, src_channels)
        resample_ms = (time.time() - start) * 1000.0

        if not validate_pcm(pcm_bytes):
            return PipelineResult(pcm_bytes=b"", metadata={"error": "invalid_pcm"})

        pcm_bytes, gated = _apply_noise_gate(pcm_bytes, self.noise_threshold)
        rms = _compute_rms(pcm_bytes) if pcm_bytes else 0.0
        duration_ms = (len(pcm_bytes) / (_SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH)) * 1000.0

        return PipelineResult(
            pcm_bytes=pcm_bytes,
            rms=rms,
            duration_ms=duration_ms,
            sample_rate=_SAMPLE_RATE,
            channels=_CHANNELS,
            noise_gated=gated,
            metadata={
                "resample_ms": resample_ms,
                "pipeline_ms": (time.time() - start) * 1000.0,
            },
        )

    def process_webrtc_frame(self, frame, buffer) -> Optional[PipelineResult]:
        """Process a single WebRTC frame. Returns result if chunk emitted, else None."""
        # Frame-to-PCM conversion is handled by VoiceAudioBuffer;
        # this method is a placeholder for future unified chunk processing.
        return None
