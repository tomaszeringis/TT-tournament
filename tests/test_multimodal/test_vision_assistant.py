"""
Tests for Vision Assistant panel and persistence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from tournament_platform.app.services.vision_events import (
    ArbitrationDecision,
    ArbitrationDecisionType,
    CandidateStatus,
    PointCandidate,
    VisionEvent,
    VisionEventType,
)
from tournament_platform.app.services.vision_repository import VisionEventRepository
from tournament_platform.app.services.voice_scorekeeper.scoring_actions import (
    ScoreAction,
    ScoreActionType,
    apply_manual_score_action,
)


def _make_candidate(winner: str = "player_a") -> PointCandidate:
    return PointCandidate(
        match_id=1,
        candidate_id="cand-1",
        rally_id="rally-1",
        monotonic_timestamp=1000.0,
        utc_timestamp=datetime.now(timezone.utc),
        suggested_winner=winner,
        confidence=0.9,
        evidence_refs=["ev-1"],
    )


class TestVisionAssistantPanelLogic:
    """Test the confirm/dismiss logic without rendering Streamlit widgets."""

    def test_confirm_point_a_creates_score_action(self):
        candidate = _make_candidate("player_a")
        match_manager = MagicMock()
        match_manager._add_point.return_value = (True, "Point for Player A")
        match_manager.state.score_a = 0
        match_manager.state.score_b = 0

        action = ScoreAction(
            action_type=ScoreActionType.ADD_POINT_A,
            match_id=1,
            source="vision",
            candidate_id=candidate.candidate_id,
            rally_id=candidate.rally_id,
            idempotency_key=candidate.candidate_id,
        )
        result = apply_manual_score_action(action, match_manager, session_state=None)
        assert result.success is True
        assert result.diagnostics["action_source"] == "vision"

    def test_confirm_point_b_creates_score_action(self):
        candidate = _make_candidate("player_b")
        match_manager = MagicMock()
        match_manager._add_point.return_value = (True, "Point for Player B")
        match_manager.state.score_a = 0
        match_manager.state.score_b = 0

        action = ScoreAction(
            action_type=ScoreActionType.ADD_POINT_B,
            match_id=1,
            source="vision",
            candidate_id=candidate.candidate_id,
            rally_id=candidate.rally_id,
            idempotency_key=candidate.candidate_id,
        )
        result = apply_manual_score_action(action, match_manager, session_state=None)
        assert result.success is True
        assert result.diagnostics["action_source"] == "vision"

    def test_dismiss_preserves_original_winner(self):
        candidate = _make_candidate("player_a")
        candidate.dismiss()
        assert candidate.status == CandidateStatus.DISMISSED
        assert candidate.suggested_winner == "player_a"
        assert candidate.original_suggested_winner == "player_a"

    def test_accept_changes_status(self):
        candidate = _make_candidate("player_a")
        candidate.accept()
        assert candidate.status == CandidateStatus.ACCEPTED


class TestVisionEventRepository:
    """Test vision event persistence."""

    def test_record_point_candidate(self):
        candidate = _make_candidate("player_a")
        repo = VisionEventRepository()
        db_event = repo.record_point_candidate(candidate, match_id=1)
        assert db_event.candidate_id == "cand-1"
        assert db_event.suggested_winner == "player_a"
        assert db_event.status == CandidateStatus.PROPOSED.value

    def test_record_vision_event(self):
        event = VisionEvent(
            event_type=VisionEventType.BOUNCE,
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            x=150.0,
            y=250.0,
            confidence=0.8,
        )
        repo = VisionEventRepository()
        db_event = repo.record_event(event, match_id=1)
        assert db_event.event_type == "bounce"
        assert db_event.ball_x == 150.0
