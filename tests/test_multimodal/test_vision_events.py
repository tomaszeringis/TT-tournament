"""
Tests for vision domain types: BallObservation, VisionEvent, PointCandidate, ArbitrationDecision.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tournament_platform.app.services.vision_events import (
    ArbitrationDecision,
    ArbitrationDecisionType,
    BallObservation,
    CandidateStatus,
    PointCandidate,
    VisionEvent,
    VisionEventType,
)


class TestBallObservation:
    def test_frozen_dataclass(self):
        obs = BallObservation(
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            x=100.0,
            y=200.0,
            confidence=0.9,
        )
        assert obs.x == 100.0
        assert obs.y == 200.0
        assert obs.confidence == 0.9

    def test_frame_id_optional(self):
        obs = BallObservation(
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            x=0.0,
            y=0.0,
            confidence=0.0,
        )
        assert obs.frame_id is None


class TestVisionEvent:
    def test_create_event(self):
        event = VisionEvent(
            event_type=VisionEventType.BOUNCE,
            monotonic_timestamp=1001.0,
            utc_timestamp=datetime.now(timezone.utc),
            x=150.0,
            y=250.0,
            confidence=0.8,
        )
        assert event.event_type == VisionEventType.BOUNCE
        assert event.x == 150.0

    def test_evidence_refs_default_empty(self):
        event = VisionEvent(
            event_type=VisionEventType.RALLY_STARTED,
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
        )
        assert event.evidence_refs == []


class TestPointCandidate:
    def test_initial_status_proposed(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-1",
            rally_id="rally-1",
            monotonic_timestamp=1002.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.8,
            evidence_refs=["ev-1"],
        )
        assert candidate.status == CandidateStatus.PROPOSED
        assert candidate.original_suggested_winner == "player_a"
        assert candidate.original_confidence == 0.8

    def test_dismiss_preserves_original(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-2",
            rally_id="rally-2",
            monotonic_timestamp=1003.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_b",
            confidence=0.6,
            evidence_refs=[],
        )
        candidate.dismiss()
        assert candidate.status == CandidateStatus.DISMISSED
        assert candidate.suggested_winner == "player_b"
        assert candidate.original_suggested_winner == "player_b"

    def test_accept_changes_status(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-3",
            rally_id="rally-3",
            monotonic_timestamp=1004.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.9,
            evidence_refs=[],
        )
        candidate.accept()
        assert candidate.status == CandidateStatus.ACCEPTED

    def test_override_changes_winner(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-4",
            rally_id="rally-4",
            monotonic_timestamp=1005.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.5,
            evidence_refs=[],
        )
        candidate.override("player_b")
        assert candidate.status == CandidateStatus.OVERRIDDEN
        assert candidate.suggested_winner == "player_b"
        assert candidate.original_suggested_winner == "player_a"

    def test_reject_changes_status(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-5",
            rally_id="rally-5",
            monotonic_timestamp=1006.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.1,
            evidence_refs=[],
        )
        candidate.reject()
        assert candidate.status == CandidateStatus.REJECTED


class TestArbitrationDecision:
    def test_create_decision(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-1",
            rally_id="rally-1",
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.9,
            evidence_refs=[],
        )
        decision = ArbitrationDecision(
            decision=ArbitrationDecisionType.ACCEPTABLE,
            candidate=candidate,
            reason="OK",
            confidence=0.9,
        )
        assert decision.decision == ArbitrationDecisionType.ACCEPTABLE
        assert decision.candidate == candidate
        assert decision.conflict_source is None

    def test_conflict_has_source(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-2",
            rally_id="rally-2",
            monotonic_timestamp=1001.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.8,
            evidence_refs=[],
        )
        decision = ArbitrationDecision(
            decision=ArbitrationDecisionType.CONFLICT,
            candidate=candidate,
            reason="Voice disagrees",
            conflict_source="voice",
        )
        assert decision.conflict_source == "voice"
