"""
Bounce Detector — emits bounce events from trajectory and table geometry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from tournament_platform.app.services.vision_events import VisionEvent, VisionEventType
from tournament_platform.app.services.vision_trajectory import TrajectoryAnalyzer, TrajectoryMetrics
from tournament_platform.app.services.vision_tracker import BallTrack
from tournament_platform.app.services.vision_calibration import CalibrationState

logger = logging.getLogger(__name__)


@dataclass
class BounceCandidate:
    event: VisionEvent
    confidence: float
    reason: str


class BounceDetector:
    """Detect bounces from trajectory and calibration."""

    def __init__(
        self,
        velocity_threshold: float = 1.0,
        proximity_ratio: float = 0.3,
        min_continuity: float = 0.5,
    ) -> None:
        self._velocity_threshold = velocity_threshold
        self._proximity_ratio = proximity_ratio
        self._min_continuity = min_continuity
        self._analyzer = TrajectoryAnalyzer()

    def detect(
        self,
        track: BallTrack,
        calibration: Optional[CalibrationState] = None,
    ) -> List[BounceCandidate]:
        if track.length < 3:
            return []

        metrics = self._analyzer.analyze(track)
        if not metrics.direction_reversal:
            return []

        if metrics.track_continuity < self._min_continuity:
            return []

        if abs(metrics.velocity_y) < self._velocity_threshold:
            return []

        if calibration is not None and calibration.valid and calibration.net_line_y is not None:
            last = track.last
            if last is not None:
                proximity = abs(last.y - calibration.net_line_y) / (calibration.frame_height or 480)
                if proximity > self._proximity_ratio:
                    return []

        obs = track.last
        if obs is None:
            return []

        event = VisionEvent(
            event_type=VisionEventType.BOUNCE,
            monotonic_timestamp=obs.monotonic_timestamp,
            utc_timestamp=obs.utc_timestamp,
            x=obs.x,
            y=obs.y,
            confidence=obs.confidence,
            evidence_refs=[],
        )

        return [
            BounceCandidate(
                event=event,
                confidence=obs.confidence,
                reason="trajectory_reversal",
            )
        ]
