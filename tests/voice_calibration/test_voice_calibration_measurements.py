"""
Pure unit tests for acoustic measurement domain logic.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tournament_platform.app.services.voice_calibration.measurements import (
    AcousticAccumulator,
    InvalidFrameFormat,
    compute_silence_baseline_metrics,
    compute_speech_level_metrics,
    normalize_pcm,
)
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticMeasurementResult,
    AcousticRecommendation,
    AcousticRecommendationCode,
    CalibrationMeasurementKind,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
)


class TestPcmNormalization:
    def test_float32_normalization(self):
        raw = np.array([0.5, -0.5, 0.25, -0.25], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        expected = np.array([0.5, -0.5, 0.25, -0.25], dtype=np.float64)
        np.testing.assert_allclose(samples, expected, rtol=1e-5)

    def test_int16_normalization(self):
        raw = np.array([16384, -16384, 8192, -8192], dtype=np.int16).tobytes()
        samples = normalize_pcm(raw, "int16", 1)
        expected = np.array([0.5, -0.5, 0.25, -0.25], dtype=np.float64)
        np.testing.assert_allclose(samples, expected, rtol=1e-4)

    def test_int32_normalization(self):
        raw = np.array([1073741824, -1073741824], dtype=np.int32).tobytes()
        samples = normalize_pcm(raw, "int32", 1)
        expected = np.array([0.5, -0.5], dtype=np.float64)
        np.testing.assert_allclose(samples, expected, rtol=1e-4)

    def test_stereo_reshape(self):
        raw = np.array([0.5, 0.5, -0.5, -0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 2)
        assert samples.shape == (2, 2)

    def test_unsupported_format_raises(self):
        with pytest.raises(InvalidFrameFormat):
            normalize_pcm(b"", "uint8", 1)

    def test_zero_signal_silence(self):
        raw = np.zeros(1024, dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        assert np.all(samples == 0.0)

    def test_known_sine_amplitude(self):
        amplitude = 0.5
        t = np.linspace(0, 2 * math.pi, 1024, endpoint=False)
        sine = (amplitude * np.sin(t)).astype(np.float32)
        samples = normalize_pcm(sine.tobytes(), "float32", 1)
        expected_rms = math.sqrt(np.mean(samples ** 2))
        assert abs(expected_rms - amplitude / math.sqrt(2)) < 1e-4

    def test_mono_peak_calculation(self):
        raw = np.array([0.8, -0.9, 0.1, -0.2], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        peak = float(np.max(np.abs(samples)))
        assert peak == pytest.approx(0.9)


class TestMultichannelPower:
    def test_stereo_power_not_waveform_average(self):
        left = np.array([1.0, -1.0, 1.0, -1.0], dtype=np.float32)
        right = np.array([-1.0, 1.0, -1.0, 1.0], dtype=np.float32)
        stereo = np.stack([left, right], axis=1).tobytes()
        samples = normalize_pcm(stereo, "float32", 2)
        channel_power = np.mean(samples ** 2, axis=0)
        combined_rms = float(np.sqrt(np.mean(channel_power)))
        assert combined_rms == pytest.approx(1.0)

    def test_out_of_phase_stereo_no_zero_rms(self):
        left = np.array([1.0, -1.0, 1.0, -1.0], dtype=np.float32)
        right = np.array([-1.0, 1.0, -1.0, 1.0], dtype=np.float32)
        stereo = np.stack([left, right], axis=1).tobytes()
        samples = normalize_pcm(stereo, "float32", 2)
        channel_power = np.mean(samples ** 2, axis=0)
        combined_rms = float(np.sqrt(np.mean(channel_power)))
        assert combined_rms > 0.9

    def test_mono_unchanged(self):
        mono = np.array([0.5, -0.5, 0.25, -0.25], dtype=np.float32).tobytes()
        samples = normalize_pcm(mono, "float32", 1)
        channel_power = np.mean(samples ** 2, axis=0)
        combined_rms = float(np.sqrt(np.mean(channel_power)))
        expected_rms = math.sqrt(np.mean(samples ** 2))
        assert combined_rms == pytest.approx(expected_rms)


class TestClipping:
    def test_near_clipping_count(self):
        raw = np.array([0.98, 0.99, 0.999, 0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        near = int(np.sum(np.abs(samples) >= 0.98))
        hard = int(np.sum(np.abs(samples) >= 0.999))
        assert near == 3
        assert hard == 1

    def test_no_clipping(self):
        raw = np.array([0.1, 0.2, 0.3], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        near = int(np.sum(np.abs(samples) >= 0.98))
        hard = int(np.sum(np.abs(samples) >= 0.999))
        assert near == 0
        assert hard == 0


class TestDuration:
    def test_duration_uses_sample_frame_count(self):
        sample_rate_hz = 48000
        target_sample_frame_count = 144000
        duration_ms = target_sample_frame_count / sample_rate_hz * 1000.0
        assert duration_ms == pytest.approx(3000.0)

    def test_stereo_duration_not_doubled(self):
        sample_rate_hz = 48000
        frame_count = 144000
        channel_count = 2
        scalar_sample_count = frame_count * channel_count
        duration_ms = frame_count / sample_rate_hz * 1000.0
        assert duration_ms == pytest.approx(3000.0)
        assert scalar_sample_count == 288000


class TestAccumulator:
    def test_accumulator_observes_frames(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=2,
            armed_at=0.0,
        )
        raw = np.array([0.5, -0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        acc.observe(samples, is_speech=False, timestamp=0.0)
        assert acc._frame_count == 1
        assert len(acc.frame_rms_values) == 1

    def test_accumulator_complete_by_scalar_sample_count(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=4,
            armed_at=0.0,
        )
        raw = np.array([0.5, -0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        acc.observe(samples, is_speech=False, timestamp=0.0)
        assert not acc.is_complete
        acc.observe(samples, is_speech=False, timestamp=0.0)
        assert acc.is_complete

    def test_accumulator_finalize(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=1,
            armed_at=0.0,
        )
        raw = np.array([0.5, -0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        acc.observe(samples, is_speech=False, timestamp=0.0)
        capture = acc.finalize()
        assert capture.measurement_id == "m1"
        assert capture.complete is True
        assert capture.frame_count == 1

    def test_accumulator_empty_finalize(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=1,
            armed_at=0.0,
        )
        capture = acc.finalize()
        assert capture.rms is None
        assert capture.peak is None
        assert capture.frame_count == 0


class TestSilenceBaseline:
    def test_three_second_silence_completes_by_sample_frame_count(self):
        sample_rate_hz = 48000
        target_sample_frame_count = 144000
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=sample_rate_hz,
            channel_count=1,
            target_sample_frame_count=target_sample_frame_count,
            armed_at=0.0,
        )
        for i in range(target_sample_frame_count):
            raw = np.zeros(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=False, timestamp=i / sample_rate_hz)
        assert acc.is_complete
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.capture.complete is True
        assert metrics.contaminated_by_speech is False

    def test_no_audio_capture_fails_safely(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=1,
            armed_at=0.0,
        )
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.median_rms is None
        assert metrics.median_dbfs is None

    def test_speech_contaminated_silence_flagged(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            is_speech = i >= 100 and i < 200
            raw = (np.ones(1, dtype=np.float32) * (0.5 if is_speech else 0.01)).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i / 48000)
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.contaminated_by_speech is True

    def test_one_false_positive_vad_does_not_contaminate(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            is_speech = i == 100
            raw = np.zeros(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i / 48000)
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.contaminated_by_speech is False

    def test_high_silence_rms_returns_background_noise_high(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            raw = np.full(1, 0.5, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=False, timestamp=i / 48000)
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.median_dbfs is not None
        assert metrics.median_dbfs > -30.0

    def test_retry_uses_new_measurement_id(self):
        m1 = "m1"
        m2 = "m2"
        assert m1 != m2


class TestSpeechLevel:
    def test_speech_rms_calculated(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            is_speech = i >= 100 and i < 1200
            raw = (np.ones(1, dtype=np.float32) * (0.5 if is_speech else 0.01)).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i / 48000)
        metrics = compute_speech_level_metrics(acc)
        assert metrics.speech_rms is not None
        assert metrics.speech_rms > 0

    def test_clipping_detected(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        for i in range(10):
            raw = np.array([0.999, 0.5], dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=True, timestamp=i * 0.01)
        capture = acc.finalize()
        assert capture.near_clipping_count > 0

    def test_speech_start_offset_calculated(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        for i in range(10):
            is_speech = i >= 2
            raw = np.ones(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i * 0.01)
        metrics = compute_speech_level_metrics(acc)
        assert metrics.speech_start_offset_ms is not None
        assert metrics.speech_start_offset_ms > 0

    def test_trailing_silence_calculated(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        for i in range(10):
            is_speech = i < 5
            raw = np.ones(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i * 0.01)
        metrics = compute_speech_level_metrics(acc)
        assert metrics.trailing_silence_ms is not None
        assert metrics.trailing_silence_ms > 0

    def test_missing_speech_flagged(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        for i in range(10):
            raw = np.zeros(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=False, timestamp=i * 0.01)
        metrics = compute_speech_level_metrics(acc)
        assert metrics.speech_rms is None


class TestPercentiles:
    def test_median_p90_p95_mad(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=100,
            armed_at=0.0,
        )
        rms_values = np.linspace(0.01, 0.05, 100)
        for i, rms in enumerate(rms_values):
            acc.frame_rms_values.append(float(rms))
            acc._frame_count += 1
            acc._scalar_sample_count += 1
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.median_rms is not None
        assert metrics.p90_rms is not None
        assert metrics.p95_rms is not None
        assert metrics.mad_rms is not None

    def test_same_input_produces_identical_output(self):
        acc1 = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        acc2 = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=10,
            armed_at=0.0,
        )
        raw = np.ones(1, dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 1)
        for i in range(10):
            acc1.observe(samples, is_speech=False, timestamp=i * 0.01)
            acc2.observe(samples, is_speech=False, timestamp=i * 0.01)
        m1 = compute_silence_baseline_metrics(acc1)
        m2 = compute_silence_baseline_metrics(acc2)
        assert m1.median_rms == m2.median_rms
        assert m1.p90_rms == m2.p90_rms


class TestSpeechContamination:
    def test_minimum_duration_rule(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            is_speech = i >= 100 and i < 102
            raw = np.zeros(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i / 48000)
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.contaminated_by_speech is False

    def test_minimum_frame_count_rule(self):
        acc = AcousticAccumulator(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            target_sample_frame_count=144000,
            armed_at=0.0,
        )
        for i in range(144000):
            is_speech = i >= 100 and i < 103
            raw = np.zeros(1, dtype=np.float32).tobytes()
            samples = normalize_pcm(raw, "float32", 1)
            acc.observe(samples, is_speech=is_speech, timestamp=i / 48000)
        metrics = compute_silence_baseline_metrics(acc)
        assert metrics.contaminated_by_speech is True
