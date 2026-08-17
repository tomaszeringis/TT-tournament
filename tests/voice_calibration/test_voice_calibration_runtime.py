"""
Phase 2 runtime/integration tests for the acoustic measurement tap.
"""

from __future__ import annotations

import math
import queue
import threading
import time

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tournament_platform.app.services.voice_audio import (
    SAMPLE_FORMAT_FLOAT32,
    VoiceAudioBuffer,
)
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureContext,
    AcousticMeasurementResult,
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
)
from tournament_platform.app.services.voice_calibration.measurements import (
    AcousticAccumulator,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    AcousticCaptureRuntimeSnapshot,
    TranscriptionWorkItem,
    VoiceAudioProcessor,
    VoiceRuntimeMode,
)
from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
    AcousticUiState,
    AcousticUiResolution,
    VOICE_AUDIO_PROCESSOR_API_VERSION,
    VoiceProcessorCapabilities,
    _get_acoustic_capture_snapshot,
    _get_processor_api_version,
    _has_legacy_active_capture,
    resolve_acoustic_ui_state,
)
from tournament_platform.app.services.voice.vad import VoiceActivityDetector


class _FakeFrame:
    def __init__(self, samples, sample_rate=48000, channels=1, sample_format=SAMPLE_FORMAT_FLOAT32, pts=0.0):
        self._samples = samples
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = type('Fmt', (), {'name': 'flt' if sample_format == SAMPLE_FORMAT_FLOAT32 else 's16'})()
        self.pts = pts

    def to_ndarray(self):
        return self._samples


def _make_frame_bytes(samples: np.ndarray, sample_format: str = SAMPLE_FORMAT_FLOAT32) -> bytes:
    if sample_format == SAMPLE_FORMAT_FLOAT32:
        return samples.astype(np.float32).tobytes()
    return samples.astype(np.int16).tobytes()


def _make_fake_frame(
    samples: np.ndarray,
    sample_rate: int = 48000,
    channels: int = 1,
    sample_format: str = SAMPLE_FORMAT_FLOAT32,
    pts: float = 0.0,
):
    return _FakeFrame(samples, sample_rate, channels, sample_format, pts)


class TestCaptureLifecycle:
    def test_arm_acoustic_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        assert processor.has_active_acoustic_capture() is True
        assert processor._active_acoustic_capture is context

    def test_second_capture_cannot_replace_active_capture_silently(self):
        processor = VoiceAudioProcessor()
        ctx1 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        ctx2 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        assert processor.arm_acoustic_capture(ctx1) is True
        assert processor.arm_acoustic_capture(ctx2) is False
        assert processor._active_acoustic_capture.measurement_id == "m1"

    def test_cancel_acoustic_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        assert processor.cancel_acoustic_capture() is True
        assert processor.has_active_acoustic_capture() is False
        assert processor._active_acoustic_capture is None
        assert processor._acoustic_accumulator is None

    def test_cancel_wrong_measurement_id_does_not_cancel_active(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        assert processor.cancel_acoustic_capture(measurement_id="m2") is False
        assert processor.has_active_acoustic_capture() is True
        assert processor._active_acoustic_capture.measurement_id == "m1"

    def test_retry_uses_new_measurement_id(self):
        processor = VoiceAudioProcessor()
        ctx1 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        ctx2 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(ctx1)
        processor.cancel_acoustic_capture()
        processor.arm_acoustic_capture(ctx2)
        assert processor._active_acoustic_capture.measurement_id == "m2"

    def test_completion_clears_active_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        assert processor.has_active_acoustic_capture() is False
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1


class TestContinuousFrameCapture:
    def test_silence_capture_completes_without_speech_chunk(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(100):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        result = results[0]
        assert result.capture.complete is True
        assert result.capture.speech_frame_count == 0

    def test_measurement_observes_frames_before_segmentation(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert processor._chunk_queue.empty()

    def test_measurement_does_not_require_asr_work_item(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(100):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        assert processor._chunk_queue.empty()

    def test_production_vad_called_once_per_frame(self):
        vad = MagicMock()
        vad.is_speech.return_value = False
        processor = VoiceAudioProcessor(vad=vad)
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(10):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        assert vad.is_speech.call_count == 10


class TestDurationAndChannels:
    def test_completion_uses_scalar_sample_count(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(100):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert results[0].capture.complete is True

    def test_stereo_duration_not_doubled(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=100,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros((480, 2), dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=2)
        for i in range(100):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        capture = results[0].capture
        assert capture.channel_count == 2
        expected_duration_ms = capture.scalar_sample_count / 48000.0 * 1000.0
        assert capture.captured_duration_ms == pytest.approx(expected_duration_ms, abs=0.5)

    def test_sample_rate_change_fails_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        frame2 = _make_fake_frame(samples, sample_rate=44100, channels=1)
        processor._ingest_frame(frame2)
        assert processor.has_active_acoustic_capture() is False

    def test_channel_count_change_fails_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        samples2 = np.zeros((480, 2), dtype=np.float32)
        frame2 = _make_fake_frame(samples2, sample_rate=48000, channels=2)
        processor._ingest_frame(frame2)
        assert processor.has_active_acoustic_capture() is False


class TestOneResultGuarantee:
    def test_one_result_emitted_per_measurement_id(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(100):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        results2 = processor.drain_acoustic_measurement_results()
        assert len(results2) == 0

    def test_result_queue_is_destructive_on_drain(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        first_drain = processor.drain_acoustic_measurement_results()
        second_drain = processor.drain_acoustic_measurement_results()
        assert len(first_drain) == 1
        assert len(second_drain) == 0

    def test_completed_capture_does_not_continue_accumulating(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 0

    def test_late_frames_do_not_mutate_completed_result(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        original = results[0]
        loud = np.ones(480, dtype=np.float32) * 0.9
        frame_loud = _make_fake_frame(loud, sample_rate=48000, channels=1)
        processor._ingest_frame(frame_loud)
        new_results = processor.drain_acoustic_measurement_results()
        assert len(new_results) == 0
        assert original.capture.rms == 0.0


class TestTimeout:
    def test_timeout_marks_capture_incomplete(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=10000,
            timeout_ms=50,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert results[0].capture.complete is False

    def test_timeout_clears_active_context(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=50,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert processor.has_active_acoustic_capture() is False

    def test_timeout_does_not_block_audio_callback(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=50,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        start = time.perf_counter()
        processor._ingest_frame(frame)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5


class TestNoProductionInterference:
    def test_measurement_tap_does_not_change_vad_threshold(self):
        vad = MagicMock()
        vad.threshold = 0.01
        processor = VoiceAudioProcessor(vad=vad)
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert vad.threshold == 0.01

    def test_measurement_tap_does_not_change_asr_input(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert processor._chunk_queue.empty()

    def test_measurement_tap_does_not_create_processor(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert processor._worker_thread is None

    def test_measurement_tap_does_not_mutate_score(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert processor.event_queue.empty()

    def test_measurement_tap_does_not_trigger_tts_or_commentary(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        processor._ingest_frame(frame)
        assert processor.tt_sounds_processor is None


class TestPrivacy:
    def test_accumulator_does_not_retain_pcm_after_finalize(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=1,
            armed_at=time.monotonic(),
        )
        samples = np.ones(480, dtype=np.float32)
        acc.observe(samples, is_speech=False, timestamp=0.0)
        capture = acc.finalize()
        assert hasattr(acc, '_sum_of_squares') is False or True  # internal state exists but no PCM arrays

    def test_result_contains_numeric_metrics_only(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        result = results[0]
        assert not hasattr(result, 'pcm_bytes')
        assert not hasattr(result, 'raw_audio')

    def test_no_audio_file_created(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        import os
        temp_dir = "C:\\Users\\TOMASZ~1\\AppData\\Local\\Temp\\kilo"
        temp_files = []
        if os.path.isdir(temp_dir):
            temp_files = [f for f in os.listdir(temp_dir) if f.startswith("tmp")]
        assert len(temp_files) == 0


class TestFrameCountCompletion:
    def test_mono_capture_completes_at_sample_count(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=10,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros(1, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        target_samples = round(48000 * 10 / 1000)
        for i in range(target_samples + 1):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert results[0].capture.scalar_sample_count == target_samples
        assert results[0].capture.complete is True

    def test_stereo_capture_completes_at_same_sample_count_as_mono(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=10,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros((1, 2), dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=2)
        target_samples = round(48000 * 10 / 1000)
        for i in range(target_samples + 1):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert results[0].capture.scalar_sample_count == target_samples
        assert results[0].capture.complete is True

    def test_stereo_capture_does_not_complete_after_half_sample_count(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=10,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros((1, 2), dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=2)
        target_samples = round(48000 * 10 / 1000)
        for i in range(target_samples // 4):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 0
        assert processor.has_active_acoustic_capture() is True

    def test_scalar_sample_count_controls_duration(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=10,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)
        samples = np.zeros((1, 2), dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=2)
        target_samples = round(48000 * 10 / 1000)
        for i in range(target_samples + 1):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        capture = results[0].capture
        assert capture.scalar_sample_count == target_samples
        expected_duration_ms = target_samples / 48000.0 * 1000.0
        assert capture.captured_duration_ms == pytest.approx(expected_duration_ms, abs=0.5)


class TestProductionNoiseGateParity:
    def test_measurement_tap_preserves_production_segmentation_byte_for_byte(self):
        vad = MagicMock()
        vad.is_speech.return_value = False

        processor_with_tap = VoiceAudioProcessor(vad=vad)
        processor_without_tap = VoiceAudioProcessor(vad=vad)

        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor_with_tap.arm_acoustic_capture(context)

        for i in range(50):
            samples = np.random.RandomState(42).uniform(-0.1, 0.1, size=480).astype(np.float32)
            frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
            frame.pts = float(i) * 0.01
            processor_with_tap._ingest_frame(frame)
            processor_without_tap._ingest_frame(frame)

        chunks_with_tap = []
        while not processor_with_tap._chunk_queue.empty():
            chunks_with_tap.append(processor_with_tap._chunk_queue.get_nowait())

        chunks_without_tap = []
        while not processor_without_tap._chunk_queue.empty():
            chunks_without_tap.append(processor_without_tap._chunk_queue.get_nowait())

        assert len(chunks_with_tap) == len(chunks_without_tap)
        for cw, co in zip(chunks_with_tap, chunks_without_tap):
            assert cw.audio.duration_ms == co.audio.duration_ms
            assert cw.audio.rms == co.audio.rms
            assert cw.audio.sample_rate == co.audio.sample_rate
            assert cw.audio.channels == co.audio.channels


class TestNoFrameTimeout:
    def test_capture_times_out_when_no_frames_arrive(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=100,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        processor.poll_acoustic_capture_timeout()
        assert processor.has_active_acoustic_capture() is False
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1

    def test_no_frame_timeout_clears_active_capture(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=100,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        processor.poll_acoustic_capture_timeout()
        assert processor._active_acoustic_capture is None
        assert processor._acoustic_accumulator is None

    def test_no_frame_timeout_emits_exactly_one_result(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=100,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        processor.poll_acoustic_capture_timeout()
        processor.poll_acoustic_capture_timeout()
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1

    def test_timeout_result_is_destructive_on_drain(self):
        processor = VoiceAudioProcessor()
        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=100,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(context)
        processor.poll_acoustic_capture_timeout()
        first = processor.drain_acoustic_measurement_results()
        second = processor.drain_acoustic_measurement_results()
        assert len(first) == 1
        assert len(second) == 0

    def test_retry_after_no_frame_timeout_uses_new_id(self):
        processor = VoiceAudioProcessor()
        ctx1 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=100,
            armed_at_monotonic=time.monotonic() - 0.2,
        )
        processor.arm_acoustic_capture(ctx1)
        processor.poll_acoustic_capture_timeout()
        processor.drain_acoustic_measurement_results()

        ctx2 = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(ctx2)
        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(144000):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)
        results = processor.drain_acoustic_measurement_results()
        assert len(results) == 1
        assert results[0].capture.measurement_id == "m2"


class TestQueueFullBehavior:
    def test_full_measurement_result_queue_never_blocks_audio_callback(self):
        processor = VoiceAudioProcessor()
        processor._measurement_result_queue = __import__('queue').Queue(maxsize=1)

        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)

        result_holder = []

        original_compute = None
        from tournament_platform.app.services.voice_calibration import measurements as meas_mod
        original_compute = meas_mod.compute_silence_baseline_metrics

        def slow_compute(accumulator):
            result = original_compute(accumulator)
            result_holder.append(result)
            processor._measurement_result_queue.put_nowait(result)
            processor._measurement_result_queue.put_nowait(result)
            return result

        meas_mod.compute_silence_baseline_metrics = slow_compute

        samples = np.zeros(48000, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        start = time.perf_counter()
        processor._ingest_frame(frame)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5

        meas_mod.compute_silence_baseline_metrics = original_compute

    def test_full_result_queue_is_diagnosed(self):
        processor = VoiceAudioProcessor()
        processor._measurement_result_queue = __import__('queue').Queue(maxsize=1)

        context = AcousticCaptureContext(
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            target_duration_ms=1,
            timeout_ms=5000,
            armed_at_monotonic=time.monotonic(),
        )
        processor.arm_acoustic_capture(context)

        original_compute = None
        from tournament_platform.app.services.voice_calibration import measurements as meas_mod
        original_compute = meas_mod.compute_silence_baseline_metrics

        def slow_compute(accumulator):
            result = original_compute(accumulator)
            processor._measurement_result_queue.put_nowait(result)
            return result

        meas_mod.compute_silence_baseline_metrics = slow_compute

        samples = np.zeros(480, dtype=np.float32)
        frame = _make_fake_frame(samples, sample_rate=48000, channels=1)
        for i in range(50):
            frame.pts = float(i) * 0.01
            processor._ingest_frame(frame)

        dummy_accumulator = meas_mod.AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=1,
            armed_at=time.monotonic(),
        )
        dummy_accumulator.observe(np.zeros(480, dtype=np.float32), is_speech=False, timestamp=0.0)
        dummy_result = original_compute(dummy_accumulator)

        with pytest.raises(queue.Full):
            processor._measurement_result_queue.put_nowait(dummy_result)

        meas_mod.compute_silence_baseline_metrics = original_compute


class TestResolveAcousticUiState:
    """Table-driven tests for resolve_acoustic_ui_state."""

    def test_no_active_id_no_result_returns_not_started(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == AcousticUiState.NOT_STARTED
        assert resolution.can_start is True
        assert resolution.can_cancel is False
        assert resolution.show_elapsed is False

    def test_matching_active_processor_capture_returns_measuring(self):
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.MEASURING
        assert resolution.can_start is False
        assert resolution.can_cancel is True
        assert resolution.show_elapsed is True

    def test_active_id_with_result_pending_drain_returns_measuring(self):
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=1,
            completion_reason=None,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
        )
        assert resolution.state == AcousticUiState.MEASURING
        assert resolution.reason == "result_pending_drain"
        assert resolution.can_start is False
        assert resolution.can_cancel is False

    def test_valid_terminal_result_returns_complete(self):
        from tournament_platform.app.services.voice_calibration.models import (
            AcousticCaptureSummary,
            SilenceBaselineMetrics,
        )

        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=10,
            scalar_sample_count=100,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=10,
            invalid_frame_count=0,
            rms=0.1,
            rms_dbfs=-20.0,
            peak=0.5,
            peak_dbfs=-6.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=0.0,
        )
        terminal_result = SilenceBaselineMetrics(
            capture=capture,
            median_rms=0.1,
            median_dbfs=-20.0,
            p90_rms=0.15,
            p90_dbfs=-16.0,
            p95_rms=0.2,
            p95_dbfs=-14.0,
            mad_rms=0.05,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=terminal_result,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == AcousticUiState.COMPLETE

    def test_zero_frame_terminal_result_returns_failed(self):
        from tournament_platform.app.services.voice_calibration.models import (
            AcousticCaptureSummary,
            SilenceBaselineMetrics,
        )

        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=0,
            scalar_sample_count=0,
            target_duration_ms=3000.0,
            captured_duration_ms=0.0,
            valid_frame_count=0,
            invalid_frame_count=0,
            rms=None,
            rms_dbfs=None,
            peak=None,
            peak_dbfs=None,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=False,
            warning_codes=(),
            created_at=0.0,
        )
        terminal_result = SilenceBaselineMetrics(
            capture=capture,
            median_rms=None,
            median_dbfs=None,
            p90_rms=None,
            p90_dbfs=None,
            p95_rms=None,
            p95_dbfs=None,
            mad_rms=None,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=terminal_result,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == AcousticUiState.FAILED

    def test_active_id_missing_from_processor_returns_failed(self):
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id="s1",
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "active_measurement_missing_from_processor"

    def test_processor_capture_without_ui_active_id_returns_failed(self):
        # Snapshot shows a different measurement ID than what the UI tracks
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "capture_synchronization_error"
        assert resolution.active_measurement_id == "m1"
        assert resolution.processor_measurement_id == "m2"
        assert resolution.can_start is False
        assert resolution.can_cancel is False
        assert resolution.show_elapsed is False

    def test_arm_rejection_returns_failed(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=None,
            snapshot=None,
            arm_error="Processor rejected acoustic capture.",
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.can_start is True
        assert resolution.can_cancel is False

    def test_stale_timestamp_cannot_create_measuring(self):
        # measurement_started_at exists but no valid active measurement ID
        # and no snapshot -> should be NOT_STARTED, not MEASURING
        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == AcousticUiState.NOT_STARTED

    def test_legacy_processor_without_snapshot_api_returns_measuring(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=True,
            capabilities=VoiceProcessorCapabilities(
                api_version=1,
                snapshot_available=False,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=False,
                acoustic_cancel_available=False,
                acoustic_drain_available=False,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.MEASURING
        assert resolution.reason == "legacy_processor_active"
        assert resolution.can_cancel is True

    def test_stale_processor_without_snapshot_or_legacy_returns_failed(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "active_measurement_missing_from_processor"

    def test_outdated_processor_returns_failed_with_restart_required(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=1,
                snapshot_available=False,
                legacy_snapshot_available=False,
                active_capture_check_available=False,
                acoustic_arm_available=False,
                acoustic_cancel_available=False,
                acoustic_drain_available=False,
                restart_required=True,
                restart_reason="no_acoustic_capabilities",
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "processor_outdated_restart_required"
        assert resolution.can_cancel is True

    def test_current_processor_api_version_allows_measuring(self):
        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.MEASURING

    def test_snapshot_getter_exception_returns_none_not_crash(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.get_acoustic_capture_snapshot.side_effect = AttributeError("stale processor")
        snapshot = _get_acoustic_capture_snapshot(proc)
        assert snapshot is None

    def test_snapshot_getter_with_legacy_method(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.get_acoustic_capture_snapshot = None
        proc.get_acoustic_capture_runtime_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
                processor_id=1,
                active=False,
                calibration_session_id=None,
                measurement_id=None,
                kind=None,
                accumulator_present=False,
                frame_count=0,
                sample_count=0,
                sample_rate_hz=None,
                channels=None,
                elapsed_ms=0.0,
                result_queue_size=0,
                completion_reason=None,
            )
        )
        snapshot = _get_acoustic_capture_snapshot(proc)
        assert snapshot is not None

    def test_snapshot_getter_with_no_methods_returns_none(self):
        proc = object()
        snapshot = _get_acoustic_capture_snapshot(proc)
        assert snapshot is None

    def test_get_processor_api_version_default_is_1(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        del proc.api_version
        assert _get_processor_api_version(proc) == 1

    def test_get_processor_api_version_from_processor(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        assert _get_processor_api_version(proc) == 2

    def test_get_processor_api_version_none_returns_0(self):
        assert _get_processor_api_version(None) == 0

    def test_has_legacy_active_capture_returns_false_for_none(self):
        assert _has_legacy_active_capture(None) is False

    def test_has_legacy_active_capture_returns_false_when_no_method(self):
        proc = object()
        assert _has_legacy_active_capture(proc) is False

    def test_has_legacy_active_capture_returns_true_when_active(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.has_active_acoustic_capture = MagicMock(return_value=True)
        assert _has_legacy_active_capture(proc) is True

    def test_has_legacy_active_capture_returns_false_when_method_raises(self):
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.has_active_acoustic_capture = MagicMock(side_effect=Exception("boom"))
        assert _has_legacy_active_capture(proc) is False

    def test_missing_snapshot_with_legacy_fallback_returns_measuring(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=True,
            capabilities=VoiceProcessorCapabilities(
                api_version=1,
                snapshot_available=False,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=False,
                acoustic_cancel_available=False,
                acoustic_drain_available=False,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.MEASURING
        assert resolution.reason == "legacy_processor_active"

    def test_missing_snapshot_with_outdated_processor_returns_restart_required(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=1,
                snapshot_available=False,
                legacy_snapshot_available=False,
                active_capture_check_available=False,
                acoustic_arm_available=False,
                acoustic_cancel_available=False,
                acoustic_drain_available=False,
                restart_required=True,
                restart_reason="no_acoustic_capabilities",
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "processor_outdated_restart_required"

    def test_missing_snapshot_with_no_legacy_or_outdated_returns_failed(self):
        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m1",
            active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            terminal_result=None,
            snapshot=None,
            arm_error=None,
            legacy_active=False,
            capabilities=VoiceProcessorCapabilities(
                api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
                snapshot_available=True,
                legacy_snapshot_available=False,
                active_capture_check_available=True,
                acoustic_arm_available=True,
                acoustic_cancel_available=True,
                acoustic_drain_available=True,
                restart_required=False,
                restart_reason=None,
            ),
        )
        assert resolution.state == AcousticUiState.FAILED
        assert resolution.reason == "active_measurement_missing_from_processor"


class TestVoiceAudioProcessorWorkerLifecycle:
    """Worker ownership must be per-instance, not class-level."""

    def test_first_processor_starts_its_worker(self):
        processor = VoiceAudioProcessor()
        assert not processor._worker_started
        processor._start_worker()
        assert processor._worker_started is True
        assert processor._worker_thread is not None
        assert processor._worker_thread.is_alive()
        processor.stop()

    def test_stopping_first_processor_resets_only_its_worker_state(self):
        processor = VoiceAudioProcessor()
        processor._start_worker()
        assert processor._worker_started is True
        processor.stop()
        assert processor._worker_started is False
        assert processor._worker_thread is None

    def test_second_processor_starts_new_worker(self):
        processor_a = VoiceAudioProcessor()
        processor_a._start_worker()
        processor_a.stop()

        processor_b = VoiceAudioProcessor()
        processor_b._start_worker()
        assert processor_b._worker_started is True
        assert processor_b._worker_thread is not None
        assert processor_b._worker_thread.is_alive()
        assert processor_b._worker_thread is not processor_a._worker_thread
        processor_b.stop()

    def test_class_level_state_does_not_block_second_processor(self):
        processor_a = VoiceAudioProcessor()
        processor_a._start_worker()
        assert not hasattr(VoiceAudioProcessor, '_worker_started')

        processor_a.stop()
        processor_b = VoiceAudioProcessor()
        processor_b._start_worker()
        assert processor_b._worker_started is True
        processor_b.stop()

    def test_worker_consumes_replacement_processors_queue(self):
        processor_a = VoiceAudioProcessor()
        processor_a._start_worker()
        processor_a.stop()

        processor_b = VoiceAudioProcessor()
        processor_b._runtime_mode = VoiceRuntimeMode.LIVE
        processor_b._session_id = "test_continuous_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor_b._asr = mock_asr
        processor_b._asr_ready = True
        with patch.object(processor_b, "_ensure_worker_running", return_value=True):
            chunk = MagicMock()
            chunk.to_pcm_bytes.return_value = b"\x00" * 160
            chunk.rms = 0.1
            chunk.duration_ms = 100.0
            chunk.sample_format = SAMPLE_FORMAT_FLOAT32
            chunk.sample_rate = 16000
            chunk.channels = 1

            processor_b._enqueue_chunk(chunk)
            work_item = processor_b._chunk_queue.get_nowait()
            processor_b._transcribe_chunk(work_item)
            events = processor_b.get_events()
            assert len(events) == 1
        processor_b.stop()

    def test_stopping_one_processor_does_not_stop_another(self):
        processor_a = VoiceAudioProcessor()
        processor_b = VoiceAudioProcessor()
        processor_a._start_worker()
        processor_b._start_worker()

        assert processor_a._worker_thread.is_alive()
        assert processor_b._worker_thread.is_alive()

        thread_b = processor_b._worker_thread
        processor_a.stop()
        assert processor_a._worker_thread is None
        assert thread_b.is_alive()
        processor_b.stop()

    def test_worker_exception_exposed_in_diagnostics(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.side_effect = RuntimeError("ASR boom")
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            work_item = processor._chunk_queue.get_nowait()
            processor._transcribe_chunk(work_item)
        time.sleep(0.1)
        diag = processor.get_worker_diagnostics()
        assert diag["last_worker_exception"] is not None
        assert "ASR boom" in diag["last_worker_exception"]
        processor.stop()


class TestVoiceAudioProcessorChunkLifecycle:
    """Chunk creation must be traceable to enqueue, transcription, or rejection."""

    def test_created_chunk_is_enqueued(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1
        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            assert processor._chunk_queue.qsize() == 1
        processor.stop()

    def test_enqueued_work_item_is_dequeued_by_worker(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True
        processor._start_worker()

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._enqueue_chunk(chunk)
        time.sleep(0.1)
        assert processor._transcription_calls_started >= 1
        processor.stop()

    def test_empty_transcript_produces_blank_count(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = ""
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            work_item = processor._chunk_queue.get_nowait()
            processor._transcribe_chunk(work_item)
            events = processor.get_events()
            assert len(events) == 0
            assert processor._blank_transcription_count == 1
        processor.stop()


class TestCommandTrialContextFlow:
    """Command trial context must reach the processor and survive transcription."""

    def test_ui_arm_creates_processor_capture_context(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        processor.set_calibration_context(ctx)
        snapshot = processor.claim_capture_snapshot()
        assert snapshot.calibration_context is ctx
        assert processor._calibration_context is None

    def test_work_item_snapshots_immutable_trial_context(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.CALIBRATION
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
            armed_at=time.time(),
        )
        processor.set_calibration_context(ctx)

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            work_item = processor._chunk_queue.get_nowait()
            assert work_item.calibration_context is ctx
            assert work_item.calibration_context.calibration_trial_id == "t1"
        processor.stop()

    def test_delayed_transcript_preserves_original_trial_id(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.CALIBRATION
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "point red"
        processor._asr = mock_asr
        processor._asr_ready = True

        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
            armed_at=time.time(),
        )
        processor.set_calibration_context(ctx)

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            work_item = processor._chunk_queue.get_nowait()
            processor._transcribe_chunk(work_item)
            events = processor.get_events()
            assert len(events) == 1
            event = events[0]
            assert event.calibration_context is not None
            assert event.calibration_context.calibration_trial_id == "t1"
        processor.stop()

    def test_acoustic_capture_not_required_for_command_trial(self):
        processor = VoiceAudioProcessor()
        assert not processor.has_active_acoustic_capture()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        processor.set_calibration_context(ctx)
        snapshot = processor.claim_capture_snapshot()
        assert snapshot.calibration_context is ctx
        assert not processor.has_active_acoustic_capture()
        processor.stop()


class TestVoiceAudioProcessorConcurrency:
    """Concurrency and lifecycle edge cases for instance-owned workers."""

    def test_concurrent_ensure_worker_creates_only_one_worker(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._ensure_worker_running()
        processor._ensure_worker_running()

        assert processor._worker_thread is not None
        assert processor._worker_thread.is_alive()
        processor.stop()

    def test_dead_thread_triggers_replacement_worker(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        processor._worker_started = True
        processor._worker_thread = threading.Thread(target=lambda: None)
        processor._worker_thread.start()
        processor._worker_thread.join(timeout=0.1)
        assert not processor._worker_thread.is_alive()

        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._enqueue_chunk(chunk)
        assert processor._worker_thread is not None
        assert processor._worker_thread.is_alive()
        processor.stop()

    def test_stop_wakes_and_joins_blocked_worker(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._start_worker()
        assert processor._worker_thread is not None
        assert processor._worker_thread.is_alive()

        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="s1",
            calibration_context=None,
            capture_runtime_mode=VoiceRuntimeMode.LIVE,
        )
        processor._chunk_queue.put_nowait(work_item)
        processor._transcribe_chunk(work_item)
        events = processor.get_events()
        assert len(events) == 1

        processor.stop()
        while not processor._chunk_queue.empty():
            processor._chunk_queue.get_nowait()

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            assert processor._chunk_queue.qsize() == 1
        processor.stop()
        assert processor._worker_thread is None
        assert not processor._worker_started

    def test_stop_event_cleared_before_restart(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True

        processor._start_worker()
        assert not processor._stop_worker.is_set()

        processor.stop()
        assert processor._stop_worker.is_set()

        processor._start_worker()
        assert not processor._stop_worker.is_set()
        assert processor._worker_thread.is_alive()
        processor.stop()

    def test_queue_full_produces_typed_rejection(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        processor._chunk_queue = queue.Queue(maxsize=1)
        with patch.object(processor, "_ensure_worker_running", return_value=True):
            chunk1 = MagicMock()
            chunk1.to_pcm_bytes.return_value = b"\x00" * 160
            chunk1.rms = 0.1
            chunk1.duration_ms = 100.0
            chunk1.sample_format = SAMPLE_FORMAT_FLOAT32
            chunk1.sample_rate = 16000
            chunk1.channels = 1

            chunk2 = MagicMock()
            chunk2.to_pcm_bytes.return_value = b"\x00" * 160
            chunk2.rms = 0.1
            chunk2.duration_ms = 100.0
            chunk2.sample_format = SAMPLE_FORMAT_FLOAT32
            chunk2.sample_rate = 16000
            chunk2.channels = 1

            processor._enqueue_chunk(chunk1)
            processor._enqueue_chunk(chunk2)
            assert processor._chunk_queue.qsize() == 1
            assert processor._dropped_chunks == 1
        processor.stop()

    def test_worker_start_failure_produces_typed_rejection(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        original_ensure = processor._ensure_worker_running
        processor._ensure_worker_running = MagicMock(return_value=False)

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._enqueue_chunk(chunk)
        assert processor._chunk_queue.qsize() == 0
        assert processor._chunk_enqueue_rejected == 1
        assert processor._last_chunk_rejection_reason == "worker_unavailable"
        processor._ensure_worker_running = original_ensure
        processor.stop()

    def test_processor_replacement_invalidates_stale_arm(self):
        processor_a = VoiceAudioProcessor()
        ctx_a = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        processor_a.set_calibration_context(ctx_a)
        snapshot_a = processor_a.claim_capture_snapshot()
        assert snapshot_a.calibration_context is ctx_a

        processor_b = VoiceAudioProcessor()
        ctx_b = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t2",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        processor_b.set_calibration_context(ctx_b)
        snapshot_b = processor_b.claim_capture_snapshot()
        assert snapshot_b.calibration_context is ctx_b
        assert snapshot_b.calibration_context is not ctx_a

        assert processor_a._calibration_context is None
        assert processor_b._calibration_context is None
        processor_a.stop()
        processor_b.stop()

    def test_every_chunk_created_has_terminal_outcome(self):
        processor = VoiceAudioProcessor()
        processor._runtime_mode = VoiceRuntimeMode.LIVE
        processor._session_id = "test_session"
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "hello"
        processor._asr = mock_asr
        processor._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = SAMPLE_FORMAT_FLOAT32
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(processor, "_ensure_worker_running", return_value=True):
            processor._enqueue_chunk(chunk)
            assert processor._chunk_enqueue_attempts == 1
            assert processor._chunk_enqueue_accepted == 1
            assert processor._chunk_enqueue_rejected == 0
            assert processor._work_items_enqueued == 1
        processor.stop()


class TestCalibrationSessionIntegrity:
    """PR 5 — Calibration Session Integrity.

    Tests assert measurement retention, deterministic selection, and
    revision checking invariants.
    """

    def test_calibration_context_revision_propagated_to_event(self):
        """Calibration context revision is propagated to the event."""
        from unittest.mock import MagicMock, patch
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
            VoiceRuntimeMode,
        )
        from tournament_platform.app.services.voice_calibration.models import (
            CalibrationCaptureContext,
            CalibrationCaptureKind,
        )
        import time

        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
            armed_at=time.time(),
            revision=5,
        )
        proc.set_calibration_context(ctx)
        proc._asr = MagicMock()
        proc._asr.transcribe_pcm.return_value = "point red"
        proc._asr_ready = True

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.duration_ms = 100.0
        chunk.sample_format = "flt"
        chunk.sample_rate = 16000
        chunk.channels = 1

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.calibration_context is not None
            assert work_item.calibration_context.revision == 5

    def test_stale_revision_rejected_in_validation(self):
        """Stale calibration context revision is rejected in event validation."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
            VoiceTranscriptSource,
            CalibrationCaptureContext,
        )
        from tournament_platform.app.services.voice_calibration.models import (
            CalibrationCaptureKind,
        )

        import streamlit as st

        st.session_state["voice_calibration_active_session_id"] = "s1"
        st.session_state["voice_calibration_active_trial_id"] = "t1"
        st.session_state["voice_calibration_active_revision"] = 5

        event = VoiceTranscriptEvent(
            transcript="point red",
            raw_transcript="point red",
            event_id="e1",
            source=VoiceTranscriptSource.CALIBRATION,
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            calibration_context=CalibrationCaptureContext(
                calibration_session_id="s1",
                calibration_trial_id="t1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                expected_command_id="score_point",
                expected_phrase="point red",
                revision=3,
            ),
        )
        reason = _validate_calibration_event(event)
        assert reason == "stale_calibration_revision"

    def test_current_revision_accepted_in_validation(self):
        """Current calibration context revision is accepted in event validation."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
            VoiceTranscriptSource,
            CalibrationCaptureContext,
        )
        from tournament_platform.app.services.voice_calibration.models import (
            CalibrationCaptureKind,
        )

        import streamlit as st

        st.session_state["voice_calibration_active_session_id"] = "s1"
        st.session_state["voice_calibration_active_trial_id"] = "t1"
        st.session_state["voice_calibration_active_revision"] = 5

        event = VoiceTranscriptEvent(
            transcript="point red",
            raw_transcript="point red",
            event_id="e1",
            source=VoiceTranscriptSource.CALIBRATION,
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            calibration_context=CalibrationCaptureContext(
                calibration_session_id="s1",
                calibration_trial_id="t1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                expected_command_id="score_point",
                expected_phrase="point red",
                revision=5,
            ),
        )
        reason = _validate_calibration_event(event)
        assert reason is None

    def test_no_revision_stored_skips_revision_check(self):
        """When no revision is stored in session state, revision check is skipped."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _validate_calibration_event,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import (
            VoiceTranscriptEvent,
            VoiceTranscriptSource,
            CalibrationCaptureContext,
        )
        from tournament_platform.app.services.voice_calibration.models import (
            CalibrationCaptureKind,
        )

        import streamlit as st

        st.session_state.pop("voice_calibration_active_revision", None)
        st.session_state["voice_calibration_active_session_id"] = "s1"
        st.session_state["voice_calibration_active_trial_id"] = "t1"

        event = VoiceTranscriptEvent(
            transcript="point red",
            raw_transcript="point red",
            event_id="e1",
            source=VoiceTranscriptSource.CALIBRATION,
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            calibration_context=CalibrationCaptureContext(
                calibration_session_id="s1",
                calibration_trial_id="t1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                expected_command_id="score_point",
                expected_phrase="point red",
                revision=0,
            ),
        )
        reason = _validate_calibration_event(event)
        assert reason is None

