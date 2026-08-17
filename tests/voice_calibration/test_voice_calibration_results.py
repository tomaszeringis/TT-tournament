"""
Phase 8 — Calibration Results and Safety Report tests.
"""

from __future__ import annotations

import time

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AcousticSummarySnapshot,
    CalibrationOverallStatus,
    CalibrationPhase,
    CalibrationResults,
    CalibrationSafetyOutcome,
    CalibrationSectionOutcome,
    CalibrationSession,
    CalibrationState,
    CommandRecognitionEntry,
    NegativeTrial,
    NegativeTrialClassification,
    TtsEchoSnapshot,
    TtsEchoTestContext,
    TtsEchoTranscript,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


class TestPhase8Results:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_compute_acoustic_summary_with_measurements(self):
        session = self.service.start_session("s1")
        silence = self.service.create_silence_measurement(session, measurement_id="m1")
        speech = self.service.create_speech_measurement(session, measurement_id="m2")
        session = self.service.consume_measurements(session, (silence, speech))
        summary = self.service.compute_acoustic_summary(session)
        assert summary.background_median_dbfs == -40.0
        assert summary.background_p95_dbfs == -37.0
        assert summary.speech_level_dbfs == -20.0
        assert summary.speech_background_difference_db == 20.0
        assert summary.clipping_detected is False
        assert summary.measurement_count == 2

    def test_compute_acoustic_summary_without_measurements(self):
        session = self.service.start_session("s1")
        summary = self.service.compute_acoustic_summary(session)
        assert summary.background_median_dbfs is None
        assert summary.speech_level_dbfs is None
        assert summary.clipping_detected is False
        assert summary.measurement_count == 0

    def test_compute_command_recognition_empty(self):
        session = self.service.start_session("s1")
        result = self.service.compute_command_recognition(session)
        assert result == ()

    def test_compute_command_recognition_with_trials(self):
        session = self.service.start_session("s1")
        session = CalibrationSession(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        trial1 = self.service.evaluate_transcript("point red", "point_red", "point red")
        trial2 = self.service.evaluate_transcript("point read", "point_red", "point red")
        trial3 = self.service.evaluate_transcript("buying trend", "point_red", "point red")
        session = self.service.consume_trials(session, (trial1, trial2, trial3))
        result = self.service.compute_command_recognition(session)
        point_red_stats = next((e for e in result if e.command_id == "point_red"), None)
        assert point_red_stats is not None
        assert point_red_stats.attempts == 3
        assert point_red_stats.exact_matches == 1
        assert point_red_stats.successful_resolutions == 2
        assert point_red_stats.wrong_command_count == 0
        assert point_red_stats.unknown_count == 1

    def test_compute_negative_speech_safety_empty(self):
        session = self.service.start_session("s1")
        result = self.service.compute_negative_speech_safety(session)
        assert result.trials == 0
        assert result.correctly_rejected == 0
        assert result.false_live_acceptable_candidates == 0

    def test_compute_negative_speech_safety_with_trials(self):
        session = self.service.start_session("s1")
        trial1 = self.service.evaluate_negative_trial("Tomas played well")
        trial2 = self.service.evaluate_negative_trial("point blue")
        trial3 = self.service.evaluate_negative_trial("undo")
        session = self.service.consume_negative_trials(session, (trial1, trial2, trial3))
        result = self.service.compute_negative_speech_safety(session)
        assert result.trials == 3
        assert result.correctly_rejected == 1
        assert result.false_point_candidates == 1
        assert result.false_undo_reset_candidates == 1
        assert result.false_live_acceptable_candidates == 2

    def test_compute_tts_echo_safety_empty(self):
        session = self.service.start_session("s1")
        result = self.service.compute_tts_echo_safety(session)
        assert result.playback_tests == 0
        assert result.transcripts_captured == 0
        assert result.live_acceptable_command_candidates == 0
        assert result.score_actions == 0

    def test_compute_tts_echo_safety_with_transcripts(self):
        session = self.service.start_session("s1")
        session, ctx = self.service.start_tts_echo_test(session, text="point red")
        transcript = self.service.create_tts_echo_transcript("point red", tts_playback_id=ctx.playback_id)
        session = self.service.consume_tts_echo_transcripts(session, (transcript,))
        result = self.service.compute_tts_echo_safety(session)
        assert result.playback_tests == 1
        assert result.transcripts_captured == 1
        assert result.live_acceptable_command_candidates == 1

    def test_compute_confusion_table_empty(self):
        session = self.service.start_session("s1")
        table = self.service.compute_confusion_table(session)
        assert table == ()

    def test_compute_confusion_table_with_data(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_transcript("point red", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        neg_trial = self.service.evaluate_negative_trial("blue is my favorite color")
        session = self.service.consume_negative_trials(session, (neg_trial,))
        session, ctx = self.service.start_tts_echo_test(session, text="point red")
        echo = self.service.create_tts_echo_transcript("point red", tts_playback_id=ctx.playback_id)
        session = self.service.consume_tts_echo_transcripts(session, (echo,))
        table = self.service.compute_confusion_table(session)
        assert len(table) == 3

    def test_compute_results_returns_calibration_results(self):
        session = self.service.start_session("s1")
        results = self.service.compute_results(session)
        assert isinstance(results, CalibrationResults)
        assert results.session_id == "s1"
        assert results.overall_pass is False

    def test_compute_results_safety_outcomes(self):
        session = self.service.start_session("s1")
        silence = self.service.create_silence_measurement(session, measurement_id="m1")
        session = self.service.consume_measurements(session, (silence,))
        trial = self.service.evaluate_transcript("point red", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        results = self.service.compute_results(session)
        categories = [o.category for o in results.safety_outcomes]
        assert "microphone_environment" in categories
        assert "command_recognition" in categories
        assert "negative_speech_safety" in categories
        assert "tts_echo_safety" in categories

    def test_compute_results_overall_pass_when_no_failures(self):
        session = self.service.start_session("s1")
        session = CalibrationSession(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        silence = self.service.create_silence_measurement(session, measurement_id="m1")
        speech = self.service.create_speech_measurement(session, measurement_id="m2")
        session = self.service.consume_measurements(session, (silence, speech))
        trial = self.service.evaluate_transcript("point red", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        neg_trial = self.service.evaluate_negative_trial("Tomas played well")
        session = self.service.consume_negative_trials(session, (neg_trial,))
        tts_session, ctx = self.service.start_tts_echo_test(session, text="the weather is nice today")
        echo = self.service.create_tts_echo_transcript("the weather is nice today", tts_playback_id=ctx.playback_id)
        tts_session = self.service.consume_tts_echo_transcripts(tts_session, (echo,))
        results = self.service.compute_results(tts_session)
        assert results.overall_pass is True
        assert results.overall_status == CalibrationOverallStatus.PASS

    def test_compute_results_overall_incomplete_when_tts_not_tested(self):
        session = self.service.start_session("s1")
        session = CalibrationSession(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        silence = self.service.create_silence_measurement(session, measurement_id="m1")
        speech = self.service.create_speech_measurement(session, measurement_id="m2")
        session = self.service.consume_measurements(session, (silence, speech))
        trial = self.service.evaluate_transcript("point red", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        neg_trial = self.service.evaluate_negative_trial("Tomas played well")
        session = self.service.consume_negative_trials(session, (neg_trial,))
        results = self.service.compute_results(session)
        assert results.overall_pass is False
        assert results.overall_status == CalibrationOverallStatus.INCOMPLETE

    def test_compute_results_overall_fails_on_false_negative_candidate(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_negative_trial("point blue")
        session = self.service.consume_negative_trials(session, (trial,))
        results = self.service.compute_results(session)
        assert results.overall_pass is False
        assert any(o.failure for o in results.safety_outcomes if o.category == "negative_speech_safety")

    def test_no_alias_candidates_created_from_negative_results(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_negative_trial("point red")
        session = self.service.consume_negative_trials(session, (trial,))
        results = self.service.compute_results(session)
        assert len(session.alias_candidates) == 0

    def test_no_alias_candidates_created_from_echo_results(self):
        session = self.service.start_session("s1")
        session, ctx = self.service.start_tts_echo_test(session, text="point red")
        transcript = self.service.create_tts_echo_transcript("point red", tts_playback_id=ctx.playback_id)
        session = self.service.consume_tts_echo_transcripts(session, (transcript,))
        results = self.service.compute_results(session)
        assert len(session.alias_candidates) == 0

    def test_results_survive_rerun(self):
        session = self.service.start_session("s1")
        silence = self.service.create_silence_measurement(session, measurement_id="m1")
        session = self.service.consume_measurements(session, (silence,))
        trial = self.service.evaluate_transcript("point red", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        results1 = self.service.compute_results(session)
        results2 = self.service.compute_results(session)
        assert results1.session_id == results2.session_id
        assert results1.overall_pass == results2.overall_pass
        assert len(results1.confusion_table) == len(results2.confusion_table)

    def test_confusion_retains_raw_and_normalized_transcripts(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_transcript("point read", "point_red", "point red")
        session = self.service.consume_trials(session, (trial,))
        table = self.service.compute_confusion_table(session)
        assert len(table) == 1
        assert table[0].transcript == "point read"
        assert table[0].normalized_transcript == "point read"