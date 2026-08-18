"""
Vision backends — pluggable ball detector interface and implementations.

Default backend: color-based HSV heuristic (MVP).
Optional backends: lightweight CNN/MobileNet, custom YOLO, legacy Keras model
(all gated behind optional dependencies and benchmark approval).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from tournament_platform.app.services.vision_events import BallObservation
from tournament_platform.app.services.vision_calibration import CalibrationState

logger = logging.getLogger(__name__)


class BallDetector(ABC):
    """Abstract interface for ball detection backends."""

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        calibration: Optional[CalibrationState] = None,
    ) -> Optional[BallObservation]:
        """Detect the ball in a single frame.

        Args:
            frame: BGR image as a numpy array.
            calibration: Optional calibration state for coordinate normalization.

        Returns:
            BallObservation if the ball is detected, otherwise None.
        """


class HeuristicBallDetector(BallDetector):
    """Color-based HSV heuristic ball detector (MVP default)."""

    def detect(
        self,
        frame: np.ndarray,
        calibration: Optional[CalibrationState] = None,
    ) -> Optional[BallObservation]:
        try:
            import cv2
        except ImportError:
            return None

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        lower_orange = np.array([5, 100, 100])
        upper_orange = np.array([25, 255, 255])
        lower_yellow = np.array([25, 100, 100])
        upper_yellow = np.array([40, 255, 255])

        mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
        mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
        mask = cv2.bitwise_or(mask_orange, mask_yellow)

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)

        if cv2.contourArea(largest) < 100:
            return None

        M = cv2.moments(largest)
        if M["m00"] == 0:
            return None

        x = float(M["m10"] / M["m00"])
        y = float(M["m01"] / M["m00"])
        confidence = min(cv2.contourArea(largest) / 10000.0, 1.0)

        return BallObservation(
            monotonic_timestamp=time.monotonic(),
            utc_timestamp=datetime.now(timezone.utc),
            x=x,
            y=y,
            confidence=confidence,
        )
