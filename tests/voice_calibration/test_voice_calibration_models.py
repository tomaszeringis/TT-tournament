"""
Tests for voice calibration models.
"""

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticMeasurementResult,
    AcousticRecommendation,
    AcousticRecommendationCode,
    AsrMetadata,
    CalibrationAliasCandidate,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    CalibrationState,
    CommandCalibrationResult,
    CommandTrial,
    Collision,
    RecommendationEvidence,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
    TrialClassification,
    ValidationResult,
)


class TestModels:
    def test_acoustic_capture_summary_creation(self):
        summary = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=1440,
            scalar_sample_count=1440,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=1440,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=1000.0,
        )
        assert summary.measurement_id == "m1"
        assert summary.kind == CalibrationMeasurementKind.SILENCE_BASELINE
        assert summary.complete is True

    def test_silence_baseline_metrics_creation(self):
        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=1440,
            scalar_sample_count=1440,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=1440,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=1000.0,
        )
        metrics = SilenceBaselineMetrics(
            capture=capture,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        assert metrics.median_rms == 0.01
        assert metrics.contaminated_by_speech is False

    def test_speech_level_metrics_creation(self):
        capture = AcousticCaptureSummary(
            measurement_id="m2",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=1440,
            scalar_sample_count=1440,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=1440,
            invalid_frame_count=0,
            rms=0.05,
            rms_dbfs=-26.0,
            peak=0.15,
            peak_dbfs=-16.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=1200,
            speech_duration_ms=2500.0,
            complete=True,
            warning_codes=(),
            created_at=1000.0,
        )
        metrics = SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=100.0,
            trailing_silence_ms=200.0,
            speech_rms=0.05,
            speech_rms_dbfs=-26.0,
            speech_to_background_difference_db=14.0,
        )
        assert metrics.speech_start_offset_ms == 100.0
        assert metrics.trailing_silence_ms == 200.0

    def test_acoustic_measurement_result_union(self):
        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=1440,
            scalar_sample_count=1440,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=1440,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=1000.0,
        )
        result: AcousticMeasurementResult = SilenceBaselineMetrics(
            capture=capture,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        assert isinstance(result, SilenceBaselineMetrics)

    def test_recommendation_evidence(self):
        evidence = RecommendationEvidence(name="rms", value=-40.0, unit="dBFS")
        assert evidence.name == "rms"
        assert evidence.value == -40.0
        assert evidence.unit == "dBFS"

    def test_acoustic_recommendation(self):
        rec = AcousticRecommendation(
            code=AcousticRecommendationCode.READY,
            severity="info",
            message="Calibration ready",
            evidence=(),
        )
        assert rec.code == AcousticRecommendationCode.READY
        assert rec.severity == "info"

    def test_asr_metadata_word_probabilities(self):
        m = AsrMetadata(
            latency_ms=120.0,
            no_speech_probability=0.0,
            average_log_probability=-0.5,
            word_probabilities=(0.9, 0.8),
        )
        assert m.word_probabilities == (0.9, 0.8)

    def test_command_trial_creation(self):
        trial = CommandTrial(
            trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            raw_transcript="point red",
            normalized_transcript="point red",
            resolved_command_id="score_point",
            classification=TrialClassification.EXACT,
            parser_confidence=0.85,
            rejection_reason=None,
        )
        assert trial.trial_id == "t1"
        assert trial.classification == TrialClassification.EXACT

    def test_calibration_state_revision_bumps(self):
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMMAND_TRIAL, revision=3)
        assert state.revision == 3

    def test_calibration_session_defaults(self):
        session = CalibrationSession(session_id="s1", created_at=0.0)
        assert session.trials == ()
        assert session.alias_candidates == ()
        assert session.measurements == ()

    def test_calibration_session_with_measurements(self):
        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=1440,
            scalar_sample_count=1440,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=1440,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=1000.0,
        )
        measurement = SilenceBaselineMetrics(
            capture=capture,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        session = CalibrationSession(
            session_id="s1",
            created_at=0.0,
            measurements=(measurement,),
        )
        assert len(session.measurements) == 1
        assert session.measurements[0].capture.measurement_id == "m1"

    def test_validation_result(self):
        ok = ValidationResult(valid=True, reason=None)
        assert ok.valid is True
        bad = ValidationResult(valid=False, reason="x")
        assert bad.reason == "x"

    def test_collision_equality(self):
        c1 = Collision(transcript="foo", conflicting_ids=("a", "b"))
        assert c1.transcript == "foo"
        assert c1.conflicting_ids == ("a", "b")

    def test_calibration_alias_candidate_defaults(self):
        c = CalibrationAliasCandidate(
            transcript="point red",
            command_id="score_point",
            classification="color",
        )
        assert c.language == "en"
        assert c.confirmed is False
