"""
Ball Tracker — maintains a bounded history of ball observations with
quality/health metrics and optional table-normalized coordinates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from tournament_platform.app.services.vision_events import BallObservation
from tournament_platform.app.services.vision_calibration import CalibrationState

logger = logging.getLogger(__name__)


@dataclass
class BallTrack:
    """Bounded history of BallObservations with derived metrics."""

    observations: List[BallObservation] = field(default_factory=list)
    max_history: int = 30
    _last_observation: Optional[BallObservation] = field(default=None, repr=False, compare=False)

    def add(self, observation: BallObservation) -> None:
        if self._last_observation is not None:
            dx = observation.x - self._last_observation.x
            dy = observation.y - self._last_observation.y
            dt = observation.monotonic_timestamp - self._last_observation.monotonic_timestamp
            if dt > 0:
                speed = (dx * dx + dy * dy) ** 0.5 / dt
                if speed > 2000.0:
                    logger.debug("Impossible jump rejected: %.1f px/s", speed)
                    return
        self.observations.append(observation)
        self._last_observation = observation
        if len(self.observations) > self.max_history:
            self.observations.pop(0)

    def recent(self, window_seconds: float = 2.0) -> List[BallObservation]:
        if not self.observations:
            return []
        latest = self.observations[-1].monotonic_timestamp
        return [o for o in self.observations if latest - o.monotonic_timestamp <= window_seconds]

    @property
    def last(self) -> Optional[BallObservation]:
        return self.observations[-1] if self.observations else None

    @property
    def length(self) -> int:
        return len(self.observations)

    @property
    def is_empty(self) -> bool:
        return len(self.observations) == 0

    def health(self) -> dict:
        if self.is_empty:
            return {"status": "empty", "length": 0}
        return {
            "status": "ok",
            "length": len(self.observations),
            "last_confidence": self.last.confidence,
            "duration_seconds": self.observations[-1].monotonic_timestamp - self.observations[0].monotonic_timestamp,
        }


@dataclass
class TrackPoint:
    """Smoothed track point in table-normalized or pixel coordinates."""

    x: float
    y: float
    monotonic_timestamp: float
    confidence: float
    normalized_x: Optional[float] = None
    normalized_y: Optional[float] = None


class BallTracker:
    """Maintains ball state across frames with smoothing and normalization."""

    def __init__(self, max_history: int = 30, smoothing_window: int = 3) -> None:
        self._track = BallTrack(max_history=max_history)
        self._smoothing_window = smoothing_window

    def update(self, observation: BallObservation, calibration: Optional[CalibrationState] = None) -> TrackPoint:
        self._track.add(observation)
        norm_x, norm_y = None, None
        if calibration is not None and calibration.valid and calibration.homography is not None:
            from tournament_platform.app.services.vision_calibration import transform_point
            transformed = transform_point(calibration.homography, observation.x, observation.y)
            if transformed is not None:
                norm_x, norm_y = transformed
        smoothed = self._smooth()
        return TrackPoint(
            x=smoothed[0],
            y=smoothed[1],
            monotonic_timestamp=observation.monotonic_timestamp,
            confidence=observation.confidence,
            normalized_x=norm_x,
            normalized_y=norm_y,
        )

    def _smooth(self) -> Tuple[float, float]:
        recent = self._track.observations[-self._smoothing_window:]
        if not recent:
            return 0.0, 0.0
        avg_x = sum(o.x for o in recent) / len(recent)
        avg_y = sum(o.y for o in recent) / len(recent)
        return avg_x, avg_y

    @property
    def track(self) -> BallTrack:
        return self._track
