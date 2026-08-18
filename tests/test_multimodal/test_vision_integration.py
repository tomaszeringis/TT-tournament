"""
End-to-end integration test for the vision-assisted scoring pipeline.

Exercises:
prerecorded/synthetic ball observations
→ tracker
→ bounce/rally detection
→ PointCandidate
→ worker output/event drain
→ Streamlit-side candidate handling abstraction
→ operator confirmation
→ ScoreAction
→ MatchManager
→ score_engine
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from tournament_platform.app.services.vision_events import CandidateStatus, PointCandidate, VisionEvent, VisionEventType
from tournament_platform.app.services.vision_tracker import BallTracker, BallTrack
from tournament_platform.app.services.vision_bounce import BounceDetector
from tournament_platform.app.services.vision_rally import RallyStateMachine
from tournament_platform.app.services.vision_candidate import PointCandidateGenerator
from tournament_platform.app.services.vision_worker import VisionWorker
from tournament_platform.app.services.voice_scorekeeper.scoring_actions import (
    ScoreAction,
    ScoreActionType,
    apply_manual_score_action,
)
from tournament_platform.services.match_manager import MatchManager


def _make_observation(x: float, y: float, ts: float) -> PointCandidate:
    from tournament_platform.app.services.vision_events import BallObservation
    return BallObservation(
        monotonic_timestamp=ts,
        utc_timestamp=datetime.now(timezone.utc),
        x=x,
        y=y,
        confidence=0.9,
    )


class TestEndToEndVisionPipeline:
    def test_full_pipeline_scores_exactly_once(self):
        match_manager = MatchManager(player_a="Player A", player_b="Player B")
        match_id = 1
        generator = PointCandidateGenerator(match_id=match_id, algorithm_version="mvp")

        observations = [
            _make_observation(300, 100, 1000.0),
            _make_observation(290, 150, 1000.033),
            _make_observation(280, 200, 1000.066),
            _make_observation(270, 250, 1000.099),
            _make_observation(260, 300, 1000.132),
            _make_observation(250, 280, 1000.165),
            _make_observation(240, 260, 1000.198),
            _make_observation(230, 240, 1000.231),
            _make_observation(220, 220, 1000.264),
            _make_observation(210, 200, 1000.297),
            _make_observation(200, 180, 1000.33),
        ]

        candidate = None
        for obs in observations:
            result = generator.process_observation(obs)
            if result.generated and result.candidate is not None:
                candidate = result.candidate
                break

        assert candidate is not None
        assert candidate.match_id == match_id
        assert candidate.status == CandidateStatus.PROPOSED

        action = ScoreAction(
            action_type=ScoreActionType.ADD_POINT_A,
            match_id=match_id,
            source="vision",
            candidate_id=candidate.candidate_id,
            rally_id=candidate.rally_id,
            idempotency_key=candidate.candidate_id,
        )
        session_state = {"_score_action_applied_keys": set()}
        result1 = apply_manual_score_action(action, match_manager, session_state)
        assert result1.success is True
        assert match_manager.state.score_a == 1

        result2 = apply_manual_score_action(action, match_manager, session_state)
        assert result2.success is False
        assert result2.diagnostics.get("duplicate_suppressed") is True
        assert match_manager.state.score_a == 1

    def test_worker_emits_candidate_to_main_thread(self):
        candidate = PointCandidate(
            match_id=1,
            candidate_id="cand-e2e-1",
            rally_id="rally-e2e-1",
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_a",
            confidence=0.9,
            evidence_refs=[],
            status=CandidateStatus.PROPOSED,
            reason="test",
            detector_backend="heuristic",
            algorithm_version="mvp",
        )

        worker = VisionWorker(processing_callback=lambda frame: [candidate], max_queue_size=2)
        worker.start()
        worker.enqueue_frame(MagicMock())
        time.sleep(0.1)
        events = worker.drain_events()
        assert candidate in events
        worker.stop(timeout=2.0)

    def test_vision_event_persisted_with_correct_match_id(self):
        from tournament_platform.app.services.vision_repository import VisionEventRepository
        candidate = PointCandidate(
            match_id=42,
            candidate_id="cand-persist-1",
            rally_id="rally-persist-1",
            monotonic_timestamp=1000.0,
            utc_timestamp=datetime.now(timezone.utc),
            suggested_winner="player_b",
            confidence=0.8,
            evidence_refs=[],
            status=CandidateStatus.PROPOSED,
        )
        repo = VisionEventRepository()
        db_event = repo.record_point_candidate(candidate)
        assert db_event.match_id == 42
        assert db_event.candidate_id == "cand-persist-1"
        assert db_event.rally_id == "rally-persist-1"
        assert db_event.suggested_winner == "player_b"
