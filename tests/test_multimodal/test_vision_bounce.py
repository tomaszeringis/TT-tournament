"""
Tests for BounceDetector.
"""

from __future__ import annotations

import pytest

from tournament_platform.app.services.vision_tracker import BallTracker, BallTrack
from tournament_platform.app.services.vision_bounce import BounceDetector
from tournament_platform.app.services.vision_calibration import CalibrationState

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


class TestBounceDetector:
    def test_no_bounce_on_short_track(self):
        detector = BounceDetector()
        track = BallTrack()
        track.add(_obs(100, 200, 1000.0))
        track.add(_obs(110, 210, 1000.033))
        bounces = detector.detect(track)
        assert len(bounces) == 0

    def test_bounce_detected_with_reversal(self):
        detector = BounceDetector()
        track = BallTrack()
        for i, (x, y) in enumerate([
            (300, 100), (290, 150), (280, 200), (270, 250), (260, 300),
            (250, 280), (240, 260), (230, 240),
        ]):
            track.add(_obs(x, y, 1000.0 + i * 0.033))
        bounces = detector.detect(track)
        assert len(bounces) == 1
        assert bounces[0].event.event_type.value == "bounce"

    def test_calibration_proximity_check(self):
        detector = BounceDetector(proximity_ratio=0.1)
        H = __import__("numpy").eye(3, dtype=__import__("numpy").float32)
        cal = CalibrationState()
        cal.mark_valid(H, [(0, 0), (100, 0), (100, 100), (0, 100)])
        cal.frame_height = 100
        cal.net_line_y = 50.0
        track = BallTrack()
        for i, (x, y) in enumerate([
            (300, 100), (290, 150), (280, 200), (270, 250), (260, 300),
            (250, 280), (240, 260), (230, 240),
        ]):
            track.add(_obs(x, y, 1000.0 + i * 0.033))
        bounces = detector.detect(track, calibration=cal)
        assert len(bounces) == 0
