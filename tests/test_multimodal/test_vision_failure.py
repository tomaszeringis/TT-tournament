"""
Tests for VisionWorker failure isolation and recovery.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from tournament_platform.app.services.vision_worker import VisionWorker, VisionWorkerHealth
from tournament_platform.app.services.vision_events import CandidateStatus, PointCandidate
from tournament_platform.services.match_manager import MatchManager
from tournament_platform.app.services.voice_scorekeeper.scoring_actions import (
    ScoreAction,
    ScoreActionType,
    apply_manual_score_action,
)


class TestVisionWorkerFailureIsolation:
    def test_worker_failure_sets_error_state(self):
        def callback(frame):
            raise RuntimeError("inference boom")

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        health = worker.get_health()
        assert health.healthy is False
        assert health.error is not None
        assert "inference boom" in health.error
        worker.stop(timeout=2.0)

    def test_manual_scoring_survives_worker_failure(self):
        match_manager = MatchManager(player_a="Player A", player_b="Player B")

        action = ScoreAction(
            action_type=ScoreActionType.ADD_POINT_A,
            match_id=1,
            source="manual",
        )
        result = apply_manual_score_action(action, match_manager, session_state=None)
        assert result.success is True
        assert match_manager.state.score_a == 1

    def test_voice_scoring_survives_worker_failure(self):
        match_manager = MatchManager(player_a="Player A", player_b="Player B")

        action = ScoreAction(
            action_type=ScoreActionType.ADD_POINT_B,
            match_id=1,
            source="voice",
        )
        result = apply_manual_score_action(action, match_manager, session_state=None)
        assert result.success is True
        assert match_manager.state.score_b == 1

    def test_worker_continues_after_error(self):
        call_count = 0

        def callback(frame):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first boom")
            return None

        worker = VisionWorker(processing_callback=callback, max_queue_size=2)
        worker.start()
        worker.enqueue_frame("frame-1")
        time.sleep(0.1)
        health = worker.get_health()
        assert health.healthy is False

        worker.enqueue_frame("frame-2")
        time.sleep(0.1)
        assert call_count == 2
        worker.stop(timeout=2.0)
