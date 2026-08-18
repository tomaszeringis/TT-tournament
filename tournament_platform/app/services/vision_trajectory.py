"""
Trajectory Analyzer — computes velocity, direction, and continuity metrics
from a BallTrack.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from tournament_platform.app.services.vision_tracker import BallTrack

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryMetrics:
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    direction: float = 0.0
    direction_reversal: bool = False
    track_continuity: float = 1.0
    missing_duration: float = 0.0
    point_count: int = 0


class TrajectoryAnalyzer:
    """Analyze ball trajectory for bounce and rally detection."""

    def analyze(self, track: BallTrack) -> TrajectoryMetrics:
        obs = track.observations
        if len(obs) < 2:
            return TrajectoryMetrics(point_count=len(obs))

        velocities = []
        directions = []
        reversal = False
        missing_duration = 0.0

        for i in range(1, len(obs)):
            dt = obs[i].monotonic_timestamp - obs[i - 1].monotonic_timestamp
            if dt <= 0:
                continue
            vx = (obs[i].x - obs[i - 1].x) / dt
            vy = (obs[i].y - obs[i - 1].y) / dt
            velocities.append((vx, vy))
            direction = vy / (abs(vx) + 1e-6)
            directions.append(direction)

            if len(directions) >= 2:
                if directions[-1] * directions[-2] < 0 and abs(directions[-1]) > 0.5 and abs(directions[-2]) > 0.5:
                    reversal = True

            gap = dt
            expected_dt = 0.033
            if gap > expected_dt * 3:
                missing_duration += gap - expected_dt

        avg_vx = sum(v[0] for v in velocities) / len(velocities) if velocities else 0.0
        avg_vy = sum(v[1] for v in velocities) / len(velocities) if velocities else 0.0
        avg_direction = sum(directions) / len(directions) if directions else 0.0

        continuity = 1.0
        if len(obs) >= 2:
            total_duration = obs[-1].monotonic_timestamp - obs[0].monotonic_timestamp
            if total_duration > 0:
                continuity = max(0.0, 1.0 - missing_duration / total_duration)

        return TrajectoryMetrics(
            velocity_x=avg_vx,
            velocity_y=avg_vy,
            direction=avg_direction,
            direction_reversal=reversal,
            track_continuity=continuity,
            missing_duration=missing_duration,
            point_count=len(obs),
        )
