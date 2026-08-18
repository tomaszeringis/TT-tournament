"""
Tests for TrajectoryAnalyzer.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_tracker import BallTracker, BallTrack
from tournament_platform.app.services.vision_trajectory import TrajectoryAnalyzer

def _obs(x, y, ts):
    from datetime import datetime, timezone
    from tournament_platform.app.services.vision_events import BallObservation
    return BallObservation(
        monotonic_timestamp=ts,
        utc_timestamp=datetime.now(timezone.utc),
        x=x,
        y=y,
        confidence=0.9,
    )


class TestTrajectoryAnalyzer:
    def test_empty_track(self):
        analyzer = TrajectoryAnalyzer()
        track = BallTrack()
        metrics = analyzer.analyze(track)
        assert metrics.point_count == 0

    def test_single_observation(self):
        analyzer = TrajectoryAnalyzer()
        track = BallTrack()
        track.add(_obs(100, 200, 1000.0))
        metrics = analyzer.analyze(track)
        assert metrics.point_count == 1

    def test_direction_reversal_detected(self):
        analyzer = TrajectoryAnalyzer()
        track = BallTrack()
        track.add(_obs(300, 100, 1000.0))
        track.add(_obs(290, 150, 1000.033))
        track.add(_obs(280, 200, 1000.066))
        track.add(_obs(270, 250, 1000.099))
        track.add(_obs(260, 300, 1000.132))
        track.add(_obs(250, 280, 1000.165))
        track.add(_obs(240, 260, 1000.198))
        metrics = analyzer.analyze(track)
        assert metrics.direction_reversal is True

    def test_track_continuity(self):
        analyzer = TrajectoryAnalyzer()
        track = BallTrack()
        for i in range(5):
            track.add(_obs(float(i), float(i), 1000.0 + i * 0.033))
        metrics = analyzer.analyze(track)
        assert metrics.track_continuity > 0.5
