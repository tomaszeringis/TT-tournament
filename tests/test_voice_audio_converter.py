"""
Tests for robust audio conversion (push-to-talk / WebRTC) and the
VoiceAudioProcessor ASR-safe lifecycle.

These guard against the Streamlit Cloud runtime errors:
  - 'VoiceAudioProcessor' object has no attribute '_asr'
  - 'list' object has no attribute 'to_ndarray'
  - RuntimeWarning: invalid value encountered in divide (VAD)
"""

import numpy as np
import pytest

from tournament_platform.app.pages.voice_scorekeeper import (
    VoiceAudioProcessor,
    _audio_input_to_pcm,
    _frame_to_ndarray,
    _audio_frame_to_mono_float32,
)
from tournament_platform.app.services.voice.vad import normalize_audio


class _FakeFrame:
    """Minimal PyAV-like AudioFrame stand-in for tests."""

    def __init__(self, arr: np.ndarray):
        self._arr = np.asarray(arr)

    def to_ndarray(self) -> np.ndarray:
        return self._arr


class TestAudioConverter:
    def test_accepts_none(self):
        pcm = _audio_input_to_pcm(None)
        assert pcm == b""

    def test_accepts_numpy_int16(self):
        pcm = _audio_input_to_pcm(np.array([0, 1000, -1000], dtype=np.int16))
        assert isinstance(pcm, bytes)

    def test_accepts_numpy_float32(self):
        pcm = _audio_input_to_pcm(np.array([0.0, 0.5, -0.5], dtype=np.float32))
        assert isinstance(pcm, bytes)

    def test_accepts_single_frame(self):
        frame = _FakeFrame(np.array([0, 1000, -1000], dtype=np.int16))
        pcm = _audio_input_to_pcm(frame)
        assert isinstance(pcm, bytes)

    def test_accepts_list_of_frames(self):
        frames = [
            _FakeFrame(np.array([0, 1000, -1000], dtype=np.int16)),
            _FakeFrame(np.array([500, -500, 200], dtype=np.int16)),
        ]
        pcm = _audio_input_to_pcm(frames)
        assert isinstance(pcm, bytes)
        assert len(pcm) > 0

    def test_accepts_empty_list(self):
        assert _audio_input_to_pcm([]) == b""

    def test_skips_malformed_objects(self):
        pcm = _audio_input_to_pcm(["not", "a", "frame"])
        assert isinstance(pcm, bytes)


class TestFrameToNdarray:
    def test_none_returns_none(self):
        assert _frame_to_ndarray(None) is None

    def test_frame_returns_array(self):
        frame = _FakeFrame(np.array([1, 2, 3], dtype=np.int16))
        arr = _frame_to_ndarray(frame)
        assert arr is not None
        assert arr.shape == (3,)

    def test_ndarray_passthrough(self):
        src = np.array([1.0, 2.0], dtype=np.float32)
        arr = _frame_to_ndarray(src)
        assert arr is src

    def test_no_to_ndarray_returns_none(self):
        assert _frame_to_ndarray(object()) is None


class TestAudioFrameToMonoFloat32:
    def test_stereo_to_mono(self):
        stereo = np.array([[1.0, -1.0], [0.5, -0.5]], dtype=np.float32)
        mono = _audio_frame_to_mono_float32(stereo)
        assert mono.ndim == 1
        # Each column is meaned; float32 values stay in [-1, 1].
        assert np.allclose(mono, np.array([0.75, -0.75], dtype=np.float32))
        assert np.all(np.abs(mono) <= 1.0)

    def test_float32_range_preserved(self):
        arr = np.array([0.2, -0.3], dtype=np.float32)
        out = _audio_frame_to_mono_float32(arr)
        assert np.all(np.abs(out) <= 1.0)


class TestVadNormalizeAudio:
    def test_none_safe(self):
        assert normalize_audio(None).size == 0

    def test_empty_safe(self):
        arr = normalize_audio(np.array([], dtype=np.int16))
        assert arr.size == 0

    def test_nan_safe(self):
        arr = normalize_audio(np.array([np.nan, np.inf, -np.inf], dtype=np.float32))
        assert np.all(np.isfinite(arr))
        assert np.all(np.abs(arr) <= 1.0)

    def test_int16_divided(self):
        arr = normalize_audio(np.array([32767, -32768], dtype=np.int16))
        assert np.allclose(arr, np.array([1.0, -1.0], dtype=np.float32), atol=1e-3)

    def test_float32_not_divided(self):
        arr = normalize_audio(np.array([0.5, -0.5], dtype=np.float32))
        assert np.allclose(arr, np.array([0.5, -0.5], dtype=np.float32))

    def test_multidimensional_flattened(self):
        arr = normalize_audio(np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32))
        assert arr.ndim == 1
        assert arr.size == 4

    def test_no_nan_warning_on_silence(self):
        with np.errstate(all="raise"):
            normalize_audio(np.zeros((100,), dtype=np.float32))


class TestVoiceProcessorMissingAsr:
    def test_init_without_asr_is_safe(self):
        processor = VoiceAudioProcessor(asr=None)
        # _asr must exist after init so _get_asr() never raises AttributeError.
        assert hasattr(processor, "_asr")
        # Calling _get_asr() must never raise AttributeError; it returns the
        # lazily-loaded backend (or None when no ASR is available).
        asr = processor._get_asr()
        assert asr is None or hasattr(asr, "transcribe_pcm")
        # When no ASR backend is available, _asr must remain None-safe.
        if asr is None:
            assert processor._asr_ready is False
            assert processor._status in ("idle", "ASR unavailable")

    def test_skip_empty_chunk_does_not_crash(self):
        processor = VoiceAudioProcessor(asr=None)
        processor._transcribe_chunk(None)

    def test_stop_sets_status(self):
        processor = VoiceAudioProcessor(asr=None)
        processor.stop()
        assert processor._status == "stopped"
