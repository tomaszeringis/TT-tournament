"""
Vision domain types — separated per frame vs per event vs per candidate.

BallObservation : raw single-frame detection
VisionEvent     : typed rally event derived from correlated observations
PointCandidate  : proposed point outcome with explicit lifecycle status
ArbitrationDecision : result of correlating vision, voice, and manual inputs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import List, Optional

logger = logging.getLogger(__name__)


class VisionEventType(StrEnum):
    RALLY_STARTED = "rally_started"
    BOUNCE = "bounce"
    NET_HIT = "net_hit"
    RALLY_ENDED = "rally_ended"
    CALIBRATION_LOST = "calibration_lost"


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    OVERRIDDEN = "overridden"
    REJECTED = "rejected"


class ArbitrationDecisionType(StrEnum):
    ACCEPTABLE = "acceptable"
    CONFIRM_REQUIRED = "confirm_required"
    CONFLICT = "conflict"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class BallObservation:
    """Single-frame raw ball detection."""

    monotonic_timestamp: float
    utc_timestamp: datetime
    x: float
    y: float
    confidence: float
    frame_id: Optional[str] = None


@dataclass
class VisionEvent:
    """Typed rally event derived from correlated BallObservations."""

    event_type: VisionEventType
    monotonic_timestamp: float
    utc_timestamp: datetime
    x: Optional[float] = None
    y: Optional[float] = None
    confidence: float = 0.0
    evidence_refs: List[str] = field(default_factory=list)


@dataclass
class PointCandidate:
    """Proposed point outcome with explicit lifecycle status."""

    match_id: int
    candidate_id: str
    rally_id: str
    monotonic_timestamp: float
    utc_timestamp: datetime
    suggested_winner: str  # "player_a" or "player_b"
    confidence: float
    evidence_refs: List[str]
    status: CandidateStatus = CandidateStatus.PROPOSED
    original_suggested_winner: Optional[str] = None
    original_confidence: Optional[float] = None
    reason: str = ""
    detector_backend: str = ""
    algorithm_version: str = ""

    def __post_init__(self) -> None:
        if self.original_suggested_winner is None:
            self.original_suggested_winner = self.suggested_winner
        if self.original_confidence is None:
            self.original_confidence = self.confidence

    def __post_init__(self) -> None:
        if self.original_suggested_winner is None:
            self.original_suggested_winner = self.suggested_winner
        if self.original_confidence is None:
            self.original_confidence = self.confidence

    def dismiss(self) -> None:
        self.status = CandidateStatus.DISMISSED

    def accept(self) -> None:
        self.status = CandidateStatus.ACCEPTED

    def override(self, new_winner: str) -> None:
        self.status = CandidateStatus.OVERRIDDEN
        self.suggested_winner = new_winner

    def reject(self) -> None:
        self.status = CandidateStatus.REJECTED


@dataclass
class ArbitrationDecision:
    """Result of correlating vision, voice, and manual inputs."""

    decision: ArbitrationDecisionType
    candidate: Optional[PointCandidate]
    reason: str
    confidence: float = 0.0
    conflict_source: Optional[str] = None
