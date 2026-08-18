"""
Point Candidate Generator — produces PointCandidates from rally evidence.

Combines:
- BallTracker
- BounceDetector
- RallyStateMachine
- EventArbitrator

Produces at most one unresolved PointCandidate per rally.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from tournament_platform.app.services.vision_events import (
    CandidateStatus,
    PointCandidate,
    VisionEvent,
    VisionEventType,
)
from tournament_platform.app.services.vision_tracker import BallTracker, BallTrack
from tournament_platform.app.services.vision_bounce import BounceDetector, BounceCandidate
from tournament_platform.app.services.vision_rally import RallyStateMachine, RallyState
from tournament_platform.app.services.vision_arbitrator import EventArbitrator, ArbitrationDecision
from tournament_platform.app.services.vision_calibration import CalibrationState

logger = logging.getLogger(__name__)


@dataclass
class CandidateGenerationResult:
    candidate: Optional[PointCandidate]
    decision: Optional[ArbitrationDecision]
    rally_id: str
    generated: bool


class PointCandidateGenerator:
    """Generate at most one unresolved PointCandidate per rally."""

    def __init__(
        self,
        match_id: int,
        detector_backend: str = "heuristic",
        algorithm_version: str = "mvp",
        arbitrator: Optional[EventArbitrator] = None,
    ) -> None:
        self._match_id = match_id
        self._detector_backend = detector_backend
        self._algorithm_version = algorithm_version
        self._arbitrator = arbitrator or EventArbitrator()
        self._tracker = BallTracker()
        self._bounce_detector = BounceDetector()
        self._active_rally: Optional[RallyStateMachine] = None
        self._last_candidate_id: Optional[str] = None

    def process_observation(
        self,
        observation,
        calibration: Optional[CalibrationState] = None,
    ) -> CandidateGenerationResult:
        if self._active_rally is None or self._active_rally.context.state == RallyState.ENDED:
            rally_id = str(uuid.uuid4())
            self._active_rally = RallyStateMachine(rally_id=rally_id)
            self._last_candidate_id = None

        rally = self._active_rally
        track_point = self._tracker.update(observation, calibration=calibration)

        vision_events: List[VisionEvent] = []
        bounces = self._bounce_detector.detect(self._tracker.track, calibration=calibration)
        for bounce in bounces:
            rally.feed(bounce.event)
            vision_events.append(bounce.event)

        if not vision_events:
            return CandidateGenerationResult(
                candidate=None,
                decision=None,
                rally_id=rally.context.rally_id,
                generated=False,
            )

        if self._last_candidate_id is not None:
            return CandidateGenerationResult(
                candidate=None,
                decision=None,
                rally_id=rally.context.rally_id,
                generated=False,
            )

        last_bounce = vision_events[-1]
        frame_width = (calibration.frame_width if calibration is not None else 640) or 640
        side = "player_a" if last_bounce.x < frame_width / 2 else "player_b"
        confidence = sum(e.confidence for e in vision_events) / len(vision_events)

        candidate_id = str(uuid.uuid4())
        candidate = PointCandidate(
            match_id=self._match_id,
            candidate_id=candidate_id,
            rally_id=rally.context.rally_id,
            monotonic_timestamp=last_bounce.monotonic_timestamp,
            utc_timestamp=last_bounce.utc_timestamp,
            suggested_winner=side,
            confidence=confidence,
            evidence_refs=[],
            status=CandidateStatus.PROPOSED,
            reason="bounce_detected",
            detector_backend=self._detector_backend,
            algorithm_version=self._algorithm_version,
        )

        decision = self._arbitrator.arbitrate(candidate, vision_events)
        if decision.decision.value == "acceptable":
            self._last_candidate_id = candidate_id
            return CandidateGenerationResult(
                candidate=candidate,
                decision=decision,
                rally_id=rally.context.rally_id,
                generated=True,
            )

        return CandidateGenerationResult(
            candidate=None,
            decision=decision,
            rally_id=rally.context.rally_id,
            generated=False,
        )

    def reset(self) -> None:
        self._active_rally = None
        self._last_candidate_id = None
        self._tracker = BallTracker()
