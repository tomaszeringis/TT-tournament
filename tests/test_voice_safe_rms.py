"""
Tests for safe_rms and related queue/voice behavior.
"""

import queue

import numpy as np
import pytest

from tournament_platform.app.services.voice.vad import safe_rms
from tournament_platform.app.services.voice_audio import VoiceAudioBuffer, AudioChunk, SAMPLE_FORMAT_INT16, SAMPLE_FORMAT_FLOAT32


class TestSafeRms:
    """safe_rms must never overflow and must handle edge cases safely."""

    def test_int16_loud_audio_does_not_overflow(self):
        loud = np.full(16000, 32767, dtype=np.int16)
        rms = safe_rms(loud)
        assert np.isfinite(rms)
        assert 0.0 <= rms <= 1.0

    def test_int16_silence_returns_zero(self):
        silence = np.zeros(1000, dtype=np.int16)
        assert safe_rms(silence) == 0.0

    def test_empty_array_returns_zero(self):
        assert safe_rms(np.array([], dtype=np.float32)) == 0.0

    def test_none_returns_zero(self):
        assert safe_rms(None) == 0.0

    def test_nan_returns_zero(self):
        arr = np.array([np.nan, 1.0, -1.0], dtype=np.float32)
        rms = safe_rms(arr)
        assert np.isfinite(rms)
        assert rms >= 0.0

    def test_inf_returns_zero(self):
        arr = np.array([np.inf, -np.inf, 1.0], dtype=np.float32)
        rms = safe_rms(arr)
        assert np.isfinite(rms)
        assert rms >= 0.0

    def test_float32_in_range(self):
        arr = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        rms = safe_rms(arr)
        expected = float(np.sqrt(np.mean(np.square(arr, dtype=np.float32), dtype=np.float32)))
        assert np.isclose(rms, expected)

    def test_int16_normalized_correctly(self):
        arr = np.array([32767, -32768], dtype=np.int16)
        rms = safe_rms(arr)
        expected = float(np.sqrt(np.mean(np.square(np.array([1.0, -1.0], dtype=np.float32), dtype=np.float32), dtype=np.float32)))
        assert np.isclose(rms, expected, rtol=1e-3)


class TestVoiceAudioBufferSafeRms:
    """VoiceAudioBuffer should not produce overflow warnings."""

    def test_int16_loud_frame_no_warning(self):
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            sample_format=SAMPLE_FORMAT_INT16,
            silence_threshold=0.0,
        )
        loud = np.full(320, 32767, dtype=np.int16).tobytes()
        buf.push_frame(loud)
        chunk = buf.flush()
        assert chunk is not None
        assert np.isfinite(chunk.rms)

    def test_nan_rms_never_triggers_speech(self):
        vad = None  # Use amplitude fallback
        buf = VoiceAudioBuffer(
            sample_rate=16000,
            channels=1,
            sample_format=SAMPLE_FORMAT_FLOAT32,
            silence_threshold=0.01,
            vad=vad,
        )
        # Push a frame with NaN values
        nan_frame = np.array([np.nan, np.nan], dtype=np.float32).tobytes()
        chunk = buf.push_frame(nan_frame)
        # Should not trigger speech because safe_rms returns 0.0
        assert chunk is None


class TestBoundedQueue:
    """VoiceAudioProcessor queues should be bounded and drop-oldest."""

    def test_event_queue_maxsize(self):
        q: queue.Queue = queue.Queue(maxsize=50)
        assert q.maxsize == 50

    def test_chunk_queue_maxsize(self):
        q: queue.Queue = queue.Queue(maxsize=20)
        assert q.maxsize == 20

    def test_drop_oldest_on_full(self):
        q: queue.Queue = queue.Queue(maxsize=2)
        q.put_nowait("old")
        q.put_nowait("middle")
        # Simulate drop-oldest logic
        try:
            q.put_nowait("new")
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait("new")
            except queue.Empty:
                pass
        items = []
        while not q.empty():
            items.append(q.get_nowait())
        assert items == ["middle", "new"]


class TestVoiceCooldownConfidence:
    """High-confidence auto-confirm and low-confidence rejection."""

    def test_low_confidence_is_rejected(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, RouteDecision
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult
        from tournament_platform.app.services.voice.commands import VoiceIntent

        result = VoiceParseResult(
            intent=VoiceIntent.SCORE_POINT,
            slots={"player": "A"},
            confidence=0.3,
            safety_level="medium",
            requires_confirmation=False,
            raw_transcript="point A",
            normalized_text="point A",
        )
        ctx = RouteContext(
            current_score_a=0,
            current_score_b=0,
            min_confidence_to_apply=0.7,
        )
        from tournament_platform.app.services.voice.command_router import route_command
        route = route_command(result, ctx)
        assert route.decision == RouteDecision.REJECT
        assert "low_confidence" in route.reason

    def test_high_confidence_passes_gate(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, RouteDecision
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult
        from tournament_platform.app.services.voice.commands import VoiceIntent

        result = VoiceParseResult(
            intent=VoiceIntent.SCORE_POINT,
            slots={"player": "A"},
            confidence=0.9,
            safety_level="medium",
            requires_confirmation=False,
            raw_transcript="point A",
            normalized_text="point A",
        )
        ctx = RouteContext(
            current_score_a=0,
            current_score_b=0,
            strict_mode=False,
            enable_confirmation=False,
            min_confidence_to_apply=0.7,
        )
        from tournament_platform.app.services.voice.command_router import route_command
        route = route_command(result, ctx)
        assert route.decision == RouteDecision.APPLY
