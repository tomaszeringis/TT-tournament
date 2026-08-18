"""
Tests for vision calibration: homography, validation, and state transitions.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from tournament_platform.app.services.vision_calibration import (
    CalibrationState,
    compute_homography,
    validate_calibration,
    transform_point,
)


class TestValidateCalibration:
    def test_valid_corners_pass(self):
        corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        assert validate_calibration(corners) is None

    def test_wrong_count_fails(self):
        assert validate_calibration([(0, 0)]) is not None
        assert validate_calibration([]) is not None

    def test_degenerate_area_fails(self):
        corners = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
        assert validate_calibration(corners) is not None

    def test_collinear_fails(self):
        corners = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
        assert validate_calibration(corners) is not None


@pytest.mark.skipif(not HAS_CV2, reason="OpenCV not installed")
class TestComputeHomography:
    def test_valid_corners_produce_matrix(self):
        corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        H = compute_homography(corners)
        assert H is not None
        assert H.shape == (3, 3)

    def test_wrong_count_returns_none(self):
        assert compute_homography([(0, 0)]) is None
        assert compute_homography([]) is None


@pytest.mark.skipif(not HAS_CV2, reason="OpenCV not installed")
class TestTransformPoint:
    def test_identity_transform(self):
        corners = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        H = compute_homography(corners)
        assert H is not None
        x, y = transform_point(H, 50.0, 50.0)
        assert x is not None
        assert y is not None
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


class TestCalibrationState:
    def test_initial_state_uninitialized(self):
        state = CalibrationState()
        assert state.valid is False
        assert state.invalid is False
        assert state.stale is False

    def test_mark_valid_sets_flags(self):
        state = CalibrationState()
        H = np.eye(3, dtype=np.float32)
        state.mark_valid(H, [(0, 0), (1, 0), (1, 1), (0, 1)])
        assert state.valid is True
        assert state.invalid is False
        assert state.stale is False
        assert state.homography is not None
        assert len(state.table_corners) == 4
        assert state.last_updated_utc is not None

    def test_mark_invalid_sets_flags(self):
        state = CalibrationState()
        state.mark_invalid("bad corners")
        assert state.valid is False
        assert state.invalid is True
        assert state.error == "bad corners"

    def test_mark_stale_sets_flags(self):
        state = CalibrationState()
        state.valid = True
        state.mark_stale()
        assert state.valid is False
        assert state.stale is True
