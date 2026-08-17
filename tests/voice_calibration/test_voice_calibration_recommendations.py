"""
Pure unit tests for acoustic recommendation rules.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticRecommendation,
    AcousticRecommendationCode,
    CalibrationMeasurementKind,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
)
from tournament_platform.app.services.voice_calibration.recommendations import (
    generate_silence_recommendations,
    generate_speech_recommendations,
)


def _make_capture(
    measurement_id: str = "m1",
    frame_count: int = 144000,
    complete: bool = True,
    median_dbfs: float | None = -40.0,
    near_clipping_count: int = 0,
    speech_frame_count: int = 0,
    speech_duration_ms: float = 0.0,
    contaminated_by_speech: bool = False,
    sample_rate_changed: bool = False,
    kind: CalibrationMeasurementKind = CalibrationMeasurementKind.SILENCE_BASELINE,
) -> AcousticCaptureSummary:
    return AcousticCaptureSummary(
        measurement_id=measurement_id,
        calibration_session_id="s1",
        kind=kind,
        sample_rate_hz=48000,
        channel_count=1,
        frame_count=frame_count,
        scalar_sample_count=frame_count,
        target_duration_ms=3000.0,
        captured_duration_ms=frame_count / 48000 * 1000.0,
        valid_frame_count=frame_count,
        invalid_frame_count=0,
        rms=10 ** (median_dbfs / 20) if median_dbfs is not None else None,
        rms_dbfs=median_dbfs,
        peak=0.05,
        peak_dbfs=-26.0,
        near_clipping_count=near_clipping_count,
        hard_clipping_count=0,
        speech_frame_count=speech_frame_count,
        speech_duration_ms=speech_duration_ms,
        complete=complete,
        warning_codes=("sample_rate_changed",) if sample_rate_changed else (),
        created_at=1000.0,
    )


def _make_silence_metrics(
    capture: AcousticCaptureSummary,
    median_rms: float | None = 0.01,
    median_dbfs: float | None = -40.0,
    contaminated_by_speech: bool = False,
    speech_frame_count: int = 0,
    speech_duration_ms: float = 0.0,
) -> SilenceBaselineMetrics:
    return SilenceBaselineMetrics(
        capture=capture,
        median_rms=median_rms,
        median_dbfs=median_dbfs,
        p90_rms=0.012,
        p90_dbfs=-38.0,
        p95_rms=0.013,
        p95_dbfs=-37.0,
        mad_rms=0.001,
        transient_count=0,
        contaminated_by_speech=contaminated_by_speech,
        speech_frame_count=speech_frame_count,
        speech_duration_ms=speech_duration_ms,
    )


def _make_speech_metrics(
    capture: AcousticCaptureSummary,
    speech_start_offset_ms: float | None = 100.0,
    trailing_silence_ms: float | None = 200.0,
    speech_rms: float | None = 0.05,
    speech_rms_dbfs: float | None = -26.0,
    speech_to_background_difference_db: float | None = 14.0,
) -> SpeechLevelMetrics:
    return SpeechLevelMetrics(
        capture=capture,
        speech_start_offset_ms=speech_start_offset_ms,
        trailing_silence_ms=trailing_silence_ms,
        speech_rms=speech_rms,
        speech_rms_dbfs=speech_rms_dbfs,
        speech_to_background_difference_db=speech_to_background_difference_db,
    )


class TestSilenceRecommendations:
    def test_no_audio_returns_error(self):
        capture = _make_capture(frame_count=0, complete=False)
        metrics = _make_silence_metrics(capture)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.NO_AUDIO.value in codes

    def test_incomplete_capture_returns_warning(self):
        capture = _make_capture(frame_count=100, complete=False)
        metrics = _make_silence_metrics(capture)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.INCOMPLETE_CAPTURE.value in codes

    def test_high_noise_floor_returns_warning(self):
        capture = _make_capture(median_dbfs=-25.0)
        metrics = _make_silence_metrics(capture, median_dbfs=-25.0)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.BACKGROUND_NOISE_HIGH.value in codes

    def test_very_quiet_returns_info(self):
        capture = _make_capture(median_dbfs=-65.0)
        metrics = _make_silence_metrics(capture, median_dbfs=-65.0)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.TOO_QUIET.value in codes

    def test_speech_contamination_returns_error(self):
        capture = _make_capture(speech_frame_count=100, speech_duration_ms=200.0)
        metrics = _make_silence_metrics(
            capture,
            contaminated_by_speech=True,
            speech_frame_count=100,
            speech_duration_ms=200.0,
        )
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.SPEECH_STARTED_TOO_EARLY.value in codes

    def test_clipping_returns_warning(self):
        capture = _make_capture(near_clipping_count=5)
        metrics = _make_silence_metrics(capture)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.CLIPPING.value in codes

    def test_perfect_silence_returns_ready(self):
        capture = _make_capture()
        metrics = _make_silence_metrics(capture)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.READY.value in codes

    def test_silence_recommendations_never_return_speech_too_quiet(self):
        capture = _make_capture(median_dbfs=-65.0)
        metrics = _make_silence_metrics(capture, median_dbfs=-65.0)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.SPEECH_TOO_QUIET.value not in codes

    def test_multiple_recommendations_can_coexist(self):
        capture = _make_capture(
            median_dbfs=-25.0,
            complete=False,
            near_clipping_count=5,
        )
        metrics = _make_silence_metrics(capture, median_dbfs=-25.0)
        recs = generate_silence_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.BACKGROUND_NOISE_HIGH.value in codes
        assert AcousticRecommendationCode.INCOMPLETE_CAPTURE.value in codes
        assert AcousticRecommendationCode.CLIPPING.value in codes


class TestSpeechRecommendations:
    def test_no_speech_detected_returns_error(self):
        capture = _make_capture(
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            speech_frame_count=0,
        )
        metrics = _make_speech_metrics(capture, speech_rms=None, speech_rms_dbfs=None)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.NO_SPEECH_DETECTED.value in codes

    def test_speech_too_quiet_returns_warning(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_rms_dbfs=-50.0)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.SPEECH_TOO_QUIET.value in codes

    def test_speech_too_loud_returns_warning(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_rms_dbfs=-2.0)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.SPEECH_TOO_LOUD.value in codes

    def test_clipping_returns_warning(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, near_clipping_count=3, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.CLIPPING.value in codes

    def test_speech_started_too_early_returns_info(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_start_offset_ms=10.0)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.SPEECH_STARTED_TOO_EARLY.value in codes

    def test_trailing_silence_high_returns_info(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, trailing_silence_ms=2500.0)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.TRAILING_SILENCE_HIGH.value in codes

    def test_low_speech_to_background_returns_warning(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_to_background_difference_db=3.0)
        silence = _make_silence_metrics(capture, median_dbfs=-40.0)
        recs = generate_speech_recommendations(metrics, silence_baseline=silence)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.LOW_SPEECH_TO_BACKGROUND_DIFFERENCE.value in codes

    def test_perfect_speech_returns_ready(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_rms_dbfs=-20.0)
        recs = generate_speech_recommendations(metrics)
        codes = [r.code for r in recs]
        assert AcousticRecommendationCode.READY.value in codes

    def test_evidence_included_in_recommendation(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_rms_dbfs=-50.0)
        recs = generate_speech_recommendations(metrics)
        speech_too_quiet = next(r for r in recs if r.code == AcousticRecommendationCode.SPEECH_TOO_QUIET.value)
        assert len(speech_too_quiet.evidence) > 0
        assert speech_too_quiet.evidence[0].name == "speech_rms_dbfs"

    def test_silence_and_speech_use_different_rules(self):
        capture = _make_capture(median_dbfs=-65.0)
        silence_metrics = _make_silence_metrics(capture, median_dbfs=-65.0)
        silence_recs = generate_silence_recommendations(silence_metrics)
        silence_codes = {r.code for r in silence_recs}
        assert AcousticRecommendationCode.TOO_QUIET.value in silence_codes
        assert AcousticRecommendationCode.SPEECH_TOO_QUIET.value not in silence_codes

        speech_capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        speech_metrics = _make_speech_metrics(speech_capture, speech_rms_dbfs=-50.0)
        speech_recs = generate_speech_recommendations(speech_metrics)
        speech_codes = {r.code for r in speech_recs}
        assert AcousticRecommendationCode.SPEECH_TOO_QUIET.value in speech_codes
        assert AcousticRecommendationCode.TOO_QUIET.value not in speech_codes

    def test_no_recommendation_mutates_state(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture)
        recs = generate_speech_recommendations(metrics)
        for rec in recs:
            assert rec.code in {
                AcousticRecommendationCode.READY.value,
                AcousticRecommendationCode.SPEECH_TOO_QUIET.value,
                AcousticRecommendationCode.SPEECH_TOO_LOUD.value,
                AcousticRecommendationCode.CLIPPING.value,
                AcousticRecommendationCode.SPEECH_STARTED_TOO_EARLY.value,
                AcousticRecommendationCode.TRAILING_SILENCE_HIGH.value,
                AcousticRecommendationCode.NO_SPEECH_DETECTED.value,
                AcousticRecommendationCode.LOW_SPEECH_TO_BACKGROUND_DIFFERENCE.value,
            }


class TestDeterminism:
    def test_quiet_speech_is_deterministic(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_rms_dbfs=-50.0)
        recs1 = generate_speech_recommendations(metrics)
        recs2 = generate_speech_recommendations(metrics)
        assert [r.code for r in recs1] == [r.code for r in recs2]

    def test_clipping_is_deterministic(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, near_clipping_count=5, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture)
        recs1 = generate_speech_recommendations(metrics)
        recs2 = generate_speech_recommendations(metrics)
        assert [r.code for r in recs1] == [r.code for r in recs2]

    def test_high_noise_is_deterministic(self):
        capture = _make_capture(median_dbfs=-25.0)
        metrics = _make_silence_metrics(capture, median_dbfs=-25.0)
        recs1 = generate_silence_recommendations(metrics)
        recs2 = generate_silence_recommendations(metrics)
        assert [r.code for r in recs1] == [r.code for r in recs2]

    def test_speech_start_warning_is_deterministic(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, speech_start_offset_ms=10.0)
        recs1 = generate_speech_recommendations(metrics)
        recs2 = generate_speech_recommendations(metrics)
        assert [r.code for r in recs1] == [r.code for r in recs2]

    def test_trailing_silence_warning_is_deterministic(self):
        capture = _make_capture(kind=CalibrationMeasurementKind.NORMAL_SPEECH, speech_frame_count=1000)
        metrics = _make_speech_metrics(capture, trailing_silence_ms=2500.0)
        recs1 = generate_speech_recommendations(metrics)
        recs2 = generate_speech_recommendations(metrics)
        assert [r.code for r in recs1] == [r.code for r in recs2]
