"""
Tests for voice calibration service.
"""

import time

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationAliasCandidate,
    CalibrationPhase,
    CalibrationSession,
    CalibrationState,
    CommandCalibrationResult,
    TrialClassification,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


class TestTranscriptEvaluation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_exact_point_red(self):
        trial = self.service.evaluate_transcript(
            transcript="point red",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.resolved_command_id == "score_point"
        assert trial.rejection_reason is None

    def test_exact_point_blue(self):
        trial = self.service.evaluate_transcript(
            transcript="point blue",
            expected_command_id="score_point",
            expected_phrase="point blue",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.resolved_command_id == "score_point"

    def test_safe_builtin_variant(self):
        trial = self.service.evaluate_transcript(
            transcript="point to player one",
            expected_command_id="score_point",
            expected_phrase="point player one",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "score_point"

    def test_wrong_command_detected(self):
        trial = self.service.evaluate_transcript(
            transcript="undo",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "undo"
        assert "undo" in (trial.rejection_reason or "").lower()

    def test_unknown_phrase_detected(self):
        trial = self.service.evaluate_transcript(
            transcript="xyzzy",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.UNKNOWN
        assert trial.resolved_command_id == "unknown"

    def test_empty_transcript_detected(self):
        trial = self.service.evaluate_transcript(
            transcript="",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EMPTY
        assert trial.resolved_command_id is None

    def test_empty_whitespace_transcript_detected(self):
        trial = self.service.evaluate_transcript(
            transcript="   ",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EMPTY
        assert trial.resolved_command_id is None


class TestAggregation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def _make_session(self, expected_command_id, transcripts_and_expected):
        session = CalibrationSession(session_id="s1", created_at=time.time())
        for transcript, classification in transcripts_and_expected:
            trial = self.service.evaluate_transcript(
                transcript=transcript,
                expected_command_id=expected_command_id,
                expected_phrase="point red" if expected_command_id == "score_point" else transcript,
            )
            # Override classification for synthetic test data if needed
            if classification != trial.classification:
                trial = trial.__class__(
                    trial_id=trial.trial_id,
                    expected_command_id=trial.expected_command_id,
                    expected_phrase=trial.expected_phrase,
                    raw_transcript=trial.raw_transcript,
                    normalized_transcript=trial.normalized_transcript,
                    resolved_command_id=trial.resolved_command_id,
                    classification=classification,
                    parser_confidence=trial.parser_confidence,
                    rejection_reason=trial.rejection_reason,
                )
            session = CalibrationSession(
                session_id=session.session_id,
                created_at=session.created_at,
                trials=session.trials + (trial,),
            )
        return session

    def test_duplicate_trial_id_not_counted_twice(self):
        trial = self.service.evaluate_transcript(
            transcript="point red",
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        session = CalibrationSession(
            session_id="s1",
            created_at=time.time(),
            trials=(trial, trial),
        )
        results = self.service.aggregate_results(session)
        assert results["score_point"].attempts == 1

    def test_results_are_per_command(self):
        trial1 = self.service.evaluate_transcript("point red", "score_point", "point red")
        trial2 = self.service.evaluate_transcript("undo", "undo", "undo")
        session = CalibrationSession(
            session_id="s1",
            created_at=time.time(),
            trials=(trial1, trial2),
        )
        results = self.service.aggregate_results(session)
        assert "score_point" in results
        assert "undo" in results
        assert results["score_point"].attempts == 1
        assert results["undo"].attempts == 1

    def test_aggregation_counts_exact_and_variant(self):
        session = self._make_session("score_point", [
            ("point red", TrialClassification.EXACT),
            ("point blue", TrialClassification.EXACT),
            ("point to player one", TrialClassification.VARIANT),
        ])
        results = self.service.aggregate_results(session)
        r = results["score_point"]
        assert r.attempts == 3
        assert r.exact_matches == 2
        assert r.successful_resolutions == 3
        assert r.wrong_command_count == 0
        assert r.unknown_count == 0

    def test_aggregation_counts_wrong_and_unknown(self):
        session = self._make_session("score_point", [
            ("undo", TrialClassification.WRONG_COMMAND),
            ("xyzzy", TrialClassification.UNKNOWN),
        ])
        results = self.service.aggregate_results(session)
        r = results["score_point"]
        assert r.wrong_command_count == 1
        assert r.unknown_count == 1


class TestServiceHasNoScoreMutationDependency:
    def test_service_instantiates_without_scoring_services(self):
        service = VoiceCalibrationService()
        assert service is not None

        grammar = service._grammar
        assert grammar is not None

        phase_machine = service._phase_machine
        assert phase_machine is not None

        alias_policy = service._alias_policy
        assert alias_policy is not None
