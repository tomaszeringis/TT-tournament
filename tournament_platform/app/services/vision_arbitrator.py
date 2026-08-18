"""
Event Arbitrator — correlates vision, voice, and manual inputs.

Returns ArbitrationDecision. Never mutates or returns VisionEvent / PointCandidate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from tournament_platform.app.services.vision_events import (
    ArbitrationDecision,
    ArbitrationDecisionType,
    PointCandidate,
    VisionEvent,
)

logger = logging.getLogger(__name__)


class EventArbitrator:
    """Correlates multimodal evidence into a single ArbitrationDecision."""

    def __init__(
        self,
        min_confidence: float = 0.7,
        enable_voice_correlation: bool = False,
        enable_manual_correlation: bool = False,
    ) -> None:
        self._min_confidence = min_confidence
        self._enable_voice_correlation = enable_voice_correlation
        self._enable_manual_correlation = enable_manual_correlation
        self._last_candidate_id: Optional[str] = None

    def arbitrate(
        self,
        candidate: PointCandidate,
        vision_events: List[VisionEvent],
        voice_candidate: Optional[PointCandidate] = None,
        manual_winner: Optional[str] = None,
    ) -> ArbitrationDecision:
        """Produce an ArbitrationDecision for the given candidate.

        Args:
            candidate: The point candidate proposed by vision.
            vision_events: Supporting vision events for the current rally.
            voice_candidate: Optional candidate from the voice pipeline.
            manual_winner: Optional manual override from the operator.

        Returns:
            ArbitrationDecision with explicit state.
        """
        if candidate.status == CandidateStatus.REJECTED:
            return ArbitrationDecision(
                decision=ArbitrationDecisionType.REJECTED,
                candidate=candidate,
                reason="Candidate already rejected",
            )

        if candidate.status == CandidateStatus.DISMISSED:
            return ArbitrationDecision(
                decision=ArbitrationDecisionType.REJECTED,
                candidate=candidate,
                reason="Candidate already dismissed",
            )

        if not vision_events:
            return ArbitrationDecision(
                decision=ArbitrationDecisionType.INSUFFICIENT_EVIDENCE,
                candidate=candidate,
                reason="No supporting vision events",
            )

        if candidate.confidence < self._min_confidence:
            return ArbitrationDecision(
                decision=ArbitrationDecisionType.CONFIRM_REQUIRED,
                candidate=candidate,
                reason=f"Confidence {candidate.confidence:.2f} below threshold {self._min_confidence:.2f}",
            )

        if self._enable_voice_correlation and voice_candidate is not None:
            if voice_candidate.suggested_winner != candidate.suggested_winner:
                return ArbitrationDecision(
                    decision=ArbitrationDecisionType.CONFLICT,
                    candidate=candidate,
                    reason="Voice and vision disagree on winner",
                    conflict_source="voice",
                )

        if self._enable_manual_correlation and manual_winner is not None:
            if manual_winner != candidate.suggested_winner:
                return ArbitrationDecision(
                    decision=ArbitrationDecisionType.CONFLICT,
                    candidate=candidate,
                    reason="Manual override disagrees with vision",
                    conflict_source="manual",
                )

        if candidate.candidate_id == self._last_candidate_id:
            return ArbitrationDecision(
                decision=ArbitrationDecisionType.DUPLICATE,
                candidate=candidate,
                reason="Duplicate candidate ID",
            )

        self._last_candidate_id = candidate.candidate_id
        return ArbitrationDecision(
            decision=ArbitrationDecisionType.ACCEPTABLE,
            candidate=candidate,
            reason="Confidence threshold met; no conflicts",
            confidence=candidate.confidence,
        )


# Local import to avoid circular dependency
from tournament_platform.app.services.vision_events import CandidateStatus  # noqa: E402
