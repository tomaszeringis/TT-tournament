"""
Tests for EventArbitrator.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_events import (
    ArbitrationDecision,
    ArbitrationDecisionType,
    CandidateStatus,
    PointCandidate,
    VisionEvent,
    VisionEventType,
)
from tournament_platform.app.services.vision_arbitrator import EventArbitrator


def _make_candidate(winner: str = "player_a", confidence: float = 0.9, status: CandidateStatus = CandidateStatus.PROPOSED) -> PointCandidate:
    return PointCandidate(
        match_id=1,
        candidate_id="cand-1",
        rally_id="rally-1",
        monotonic_timestamp=1000.0,
        utc_timestamp=_now(),
        suggested_winner=winner,
        confidence=confidence,
        evidence_refs=["ev-1"],
        status=status,
    )


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _make_event(event_type: VisionEventType = VisionEventType.BOUNCE) -> VisionEvent:
    return VisionEvent(
        event_type=event_type,
        monotonic_timestamp=1000.0,
        utc_timestamp=_now(),
    )


class TestEventArbitrator:
    def test_acceptable_when_confidence_met(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate(confidence=0.9)
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.decision == ArbitrationDecisionType.ACCEPTABLE

    def test_confirm_required_when_confidence_low(self):
        arbitrator = EventArbitrator(min_confidence=0.8)
        candidate = _make_candidate(confidence=0.6)
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.decision == ArbitrationDecisionType.CONFIRM_REQUIRED

    def test_insufficient_evidence_when_no_events(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate(confidence=0.9)
        decision = arbitrator.arbitrate(candidate, [])
        assert decision.decision == ArbitrationDecisionType.INSUFFICIENT_EVIDENCE

    def test_conflict_when_voice_disagrees(self):
        arbitrator = EventArbitrator(min_confidence=0.7, enable_voice_correlation=True)
        candidate = _make_candidate(winner="player_a", confidence=0.9)
        voice_candidate = _make_candidate(winner="player_b", confidence=0.9)
        decision = arbitrator.arbitrate(candidate, [_make_event()], voice_candidate=voice_candidate)
        assert decision.decision == ArbitrationDecisionType.CONFLICT
        assert decision.conflict_source == "voice"

    def test_conflict_when_manual_disagrees(self):
        arbitrator = EventArbitrator(min_confidence=0.7, enable_manual_correlation=True)
        candidate = _make_candidate(winner="player_a", confidence=0.9)
        decision = arbitrator.arbitrate(candidate, [_make_event()], manual_winner="player_b")
        assert decision.decision == ArbitrationDecisionType.CONFLICT
        assert decision.conflict_source == "manual"

    def test_duplicate_candidate_id(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate()
        arbitrator.arbitrate(candidate, [_make_event()])
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.decision == ArbitrationDecisionType.DUPLICATE

    def test_rejected_candidate(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate(status=CandidateStatus.REJECTED)
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.decision == ArbitrationDecisionType.REJECTED

    def test_dismissed_candidate(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate(status=CandidateStatus.DISMISSED)
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.decision == ArbitrationDecisionType.REJECTED

    def test_decision_includes_candidate_and_reason(self):
        arbitrator = EventArbitrator(min_confidence=0.7)
        candidate = _make_candidate(confidence=0.9)
        decision = arbitrator.arbitrate(candidate, [_make_event()])
        assert decision.candidate == candidate
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0
