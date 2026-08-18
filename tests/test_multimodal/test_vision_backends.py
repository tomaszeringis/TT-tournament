"""
Tests for vision backends: BallDetector interface and HeuristicBallDetector.
"""

from __future__ import annotations

import numpy as np
import pytest

from tournament_platform.app.services.vision_backends import BallDetector, HeuristicBallDetector
from tournament_platform.app.services.vision_calibration import CalibrationState


class TestHeuristicBallDetector:
    def test_interface_contract(self):
        detector = HeuristicBallDetector()
        assert isinstance(detector, BallDetector)

    def test_detect_no_cv2_returns_none(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "cv2", None)
        detector = HeuristicBallDetector()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert result is None

    def test_detect_empty_frame_returns_none(self):
        detector = HeuristicBallDetector()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert result is None

    def test_detect_returns_ball_observation(self):
        try:
            import cv2
        except ImportError:
            pytest.skip("OpenCV not installed")

        detector = HeuristicBallDetector()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[40:60, 40:60] = (0, 200, 200)  # orange-ish patch
        result = detector.detect(frame)
        assert result is not None
        assert result.confidence >= 0.0
        assert result.x >= 0.0
        assert result.y >= 0.0
