"""
Tests for Voice Calibration normalization, semantic comparison, fallback,
and re-evaluation requirements.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    CanonicalCommandIntent,
    CommandTrial,
    TrialClassification,
    normalize_calibration_phrase,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


class TestNormalizeCalibrationPhrase:
    def test_point_red_punctuation_removed(self):
        assert normalize_calibration_phrase("Point, red.") == "point red"

    def test_point_red_exclamation_removed(self):
        assert normalize_calibration_phrase("POINT RED!") == "point red"

    def test_point_red_em_dash_replaced(self):
        assert normalize_calibration_phrase("Point—red") == "point red"

    def test_point_to_dance_preserves_to(self):
        assert normalize_calibration_phrase("Point to dance.") == "point to dance"

    def test_digit_preserved(self):
        assert normalize_calibration_phrase("point 2 red") == "point 2 red"

    def test_to_not_converted_to_2(self):
        assert "2" not in normalize_calibration_phrase("to")

    def test_unicode_preserved(self):
        assert "é" in normalize_calibration_phrase("café")


class TestSemanticComparison:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_point_red_vs_score_point_red_exact(self):
        trial = self.service.evaluate_transcript(
            transcript="point red",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.resolved_command_id == "score_point"

    def test_point_red_vs_score_point_blue_wrong_command(self):
        trial = self.service.evaluate_transcript(
            transcript="point blue",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "score_point"

    def test_point_blue_vs_score_point_blue_exact(self):
        trial = self.service.evaluate_transcript(
            transcript="point blue",
            expected_command_id="point_blue",
            expected_phrase="point blue",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.resolved_command_id == "score_point"

    def test_point_blue_vs_score_point_red_wrong_command(self):
        trial = self.service.evaluate_transcript(
            transcript="point red",
            expected_command_id="point_blue",
            expected_phrase="point blue",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "score_point"

    def test_different_actions_wrong_command(self):
        trial = self.service.evaluate_transcript(
            transcript="undo",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "undo"


class TestExactPhraseFallback:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_exact_phrase_with_parser_miss_correct(self):
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.exact_phrase_match_parser_miss is False

    def test_exact_phrase_fallback_on_parser_miss(self):
        from unittest.mock import MagicMock
        service = VoiceCalibrationService()
        service._grammar = MagicMock()
        service._grammar.parse.return_value = MagicMock(
            intent="unknown",
            normalized_text="point red",
            confidence=0.0,
        )
        trial = service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.exact_phrase_match_parser_miss is True

    def test_point_to_dance_with_parser_miss_unknown(self):
        trial = self.service.evaluate_transcript(
            transcript="Point to dance.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.UNKNOWN
        assert trial.exact_phrase_match_parser_miss is False

    def test_no_fuzzy_matching(self):
        trial = self.service.evaluate_transcript(
            transcript="point raad",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.UNKNOWN
        assert trial.exact_phrase_match_parser_miss is False


class TestReEvaluation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_stored_wrong_result_becomes_correct(self):
        session = self.service.start_session("s1")
        session = type(session)(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT

        session = self.service.consume_trials(session, (trial,))
        updated_session, counts = self.service.re_evaluate_trials(session)
        updated_trial = updated_session.trials[0]
        assert updated_trial.classification == TrialClassification.EXACT
        assert updated_trial.trial_id == trial.trial_id
        assert updated_trial.raw_transcript == "Point, red."

    def test_trial_id_and_raw_transcript_unchanged(self):
        session = self.service.start_session("s1")
        session = type(session)(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        session = self.service.consume_trials(session, (trial,))
        updated_session, _ = self.service.re_evaluate_trials(session)
        updated_trial = updated_session.trials[0]
        assert updated_trial.trial_id == trial.trial_id
        assert updated_trial.raw_transcript == trial.raw_transcript

    def test_re_evaluation_idempotent(self):
        session = self.service.start_session("s1")
        session = type(session)(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        session = self.service.consume_trials(session, (trial,))
        updated_session1, _ = self.service.re_evaluate_trials(session)
        updated_session2, _ = self.service.re_evaluate_trials(updated_session1)
        assert updated_session1.trials[0].classification == updated_session2.trials[0].classification

    def test_re_evaluation_does_not_mutate_score(self):
        session = self.service.start_session("s1")
        session = type(session)(
            session_id=session.session_id,
            created_at=session.created_at,
            commands=("point_red",),
            attempts_per_command=3,
        )
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        session = self.service.consume_trials(session, (trial,))
        updated_session, _ = self.service.re_evaluate_trials(session)
        assert not hasattr(updated_session, "score_a")
        assert not hasattr(updated_session, "score_b")


class TestIntegration:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_new_point_red_trial_correct(self):
        trial = self.service.evaluate_transcript(
            transcript="Point, red.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.EXACT
        assert trial.normalized_transcript == "point red"
        assert trial.resolved_command_id == "score_point"

    def test_new_point_blue_trial_wrong_command(self):
        trial = self.service.evaluate_transcript(
            transcript="Point blue.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.WRONG_COMMAND
        assert trial.resolved_command_id == "score_point"

    def test_new_point_to_dance_trial_unknown(self):
        trial = self.service.evaluate_transcript(
            transcript="Point to dance.",
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        assert trial.classification == TrialClassification.UNKNOWN
        assert trial.normalized_transcript == "point to dance"
        assert "2" not in trial.normalized_transcript
