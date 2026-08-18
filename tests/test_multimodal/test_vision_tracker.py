"""
Tests for BallTracker and BallTrack.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_tracker import BallTracker, BallTrack
from tournament_platform.app.services.vision_events import BallObservation
from tournament_platform.app.services.vision_calibration import CalibrationState

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

def _obs(x, y, ts):
    return BallObservation(
        monotonic_timestamp=ts,
        utc_timestamp=_now(),
        x=x,
        y=y,
        confidence=0.9,
    )

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class TestBallTrack:
    def test_add_observation(self):
        track = BallTrack()
        track.add(_obs(100, 200, 1000.0))
        assert track.length == 1
        assert track.last.x == 100.0

    def test_max_history_eviction(self):
        track = BallTrack(max_history=3)
        for i in range(5):
            track.add(_obs(float(i), float(i), 1000.0 + i))
        assert track.length == 3
        assert track.observations[0].x == 2.0

    def test_impossible_jump_rejected(self):
        track = BallTrack()
        track.add(_obs(0, 0, 1000.0))
        track.add(_obs(10000, 0, 1000.1))  # 100000 px/s
        assert track.length == 1

    def test_recent_window(self):
        track = BallTrack()
        for i in range(5):
            track.add(_obs(float(i), float(i), 1000.0 + i))
        recent = track.recent(window_seconds=2.0)
        assert len(recent) <= 5

    def test_health_empty(self):
        track = BallTrack()
        h = track.health()
        assert h["status"] == "empty"

    def test_health_ok(self):
        track = BallTrack()
        track.add(_obs(100, 200, 1000.0))
        h = track.health()
        assert h["status"] == "ok"
        assert h["length"] == 1


class TestBallTracker:
    def test_update_returns_track_point(self):
        tracker = BallTracker()
        obs = _obs(100, 200, 1000.0)
        tp = tracker.update(obs)
        assert tp.x == 100.0
        assert tp.y == 200.0

    def test_smoothing(self):
        tracker = BallTracker(smoothing_window=3)
        tracker.update(_obs(100, 200, 1000.0))
        tp = tracker.update(_obs(110, 210, 1001.0))
        assert tp.x == 105.0
        assert tp.y == 205.0

    @pytest.mark.skipif(not HAS_CV2, reason="OpenCV not installed")
    def test_normalized_coordinates_with_calibration(self):
        tracker = BallTracker()
        H = np.eye(3, dtype=np.float32)
        cal = CalibrationState()
        cal.mark_valid(H, [(0, 0), (100, 0), (100, 100), (0, 100)])
        obs = _obs(50, 50, 1000.0)
        tp = tracker.update(obs, calibration=cal)
        assert tp.normalized_x is not None
        assert tp.normalized_y is not None
