"""
Tests for voice calibration alias policy.
"""

import pytest

from tournament_platform.app.services.voice_calibration.alias_policy import (
    CalibrationAliasPolicy,
)
from tournament_platform.app.services.voice_calibration.models import (
    CalibrationAliasCandidate,
    Collision,
    ValidationResult,
)


class TestAliasPolicyValidation:
    def setup_method(self):
        self.policy = CalibrationAliasPolicy()

    def test_candidate_alias_requires_explicit_confirmation(self):
        candidate = CalibrationAliasCandidate(
            transcript="point red",
            command_id="score_point",
            classification="color",
            confirmed=True,
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is False
        assert "confirmed" in result.reason.lower()

    def test_alias_collision_rejected(self):
        candidate = CalibrationAliasCandidate(
            transcript="undo",
            command_id="score_point",
            classification="builtin",
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is False
        assert "collision" in result.reason.lower() or "resolves to" in result.reason.lower()

    def test_long_alias_rejected(self):
        candidate = CalibrationAliasCandidate(
            transcript=" ".join(["word"] * 11),
            command_id="score_point",
            classification="test",
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is False
        assert "too long" in result.reason.lower()

    def test_alias_with_conflicting_action_rejected(self):
        candidate = CalibrationAliasCandidate(
            transcript="point red",
            command_id="undo",
            classification="test",
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is False
        assert "resolves to" in result.reason.lower()

    def test_empty_transcript_rejected(self):
        candidate = CalibrationAliasCandidate(
            transcript="   ",
            command_id="score_point",
            classification="test",
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is False
        assert "empty" in result.reason.lower()

    def test_valid_color_alias_accepted(self):
        candidate = CalibrationAliasCandidate(
            transcript="point red",
            command_id="score_point",
            classification="color",
        )
        result = self.policy.validate_candidate(candidate)
        assert result.valid is True
        assert result.reason is None


class TestAliasCollisionDetection:
    def setup_method(self):
        self.policy = CalibrationAliasPolicy()

    def test_same_transcript_different_commands_is_collision(self):
        candidates = [
            CalibrationAliasCandidate(transcript="point red", command_id="score_point", classification="color"),
            CalibrationAliasCandidate(transcript="point red", command_id="undo", classification="test"),
        ]
        collisions = self.policy.detect_collisions(candidates)
        assert len(collisions) == 1
        assert collisions[0].transcript == "point red"
        assert "score_point" in collisions[0].conflicting_ids
        assert "undo" in collisions[0].conflicting_ids

    def test_no_collision_for_unique_transcripts(self):
        candidates = [
            CalibrationAliasCandidate(transcript="point red", command_id="score_point", classification="color"),
            CalibrationAliasCandidate(transcript="point blue", command_id="score_point", classification="color"),
        ]
        collisions = self.policy.detect_collisions(candidates)
        assert len(collisions) == 0

    def test_alias_scoped_by_language(self):
        candidates = [
            CalibrationAliasCandidate(transcript="point red", command_id="score_point", classification="color", language="en"),
            CalibrationAliasCandidate(transcript="point red", command_id="undo", classification="test", language="lt"),
        ]
        collisions = self.policy.detect_collisions(candidates)
        assert len(collisions) == 0

    def test_same_command_same_transcript_not_collision(self):
        candidates = [
            CalibrationAliasCandidate(transcript="point red", command_id="score_point", classification="color"),
            CalibrationAliasCandidate(transcript="point red", command_id="score_point", classification="duplicate"),
        ]
        collisions = self.policy.detect_collisions(candidates)
        assert len(collisions) == 0
