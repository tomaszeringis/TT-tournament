"""
Voice Confirmation Policy

Centralizes the decision of whether a parsed voice command should be
auto-applied, sent to the confirm/cancel panel, or rejected outright.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, Literal, Optional

# Auto-confirm threshold: when parser confidence >= this value, scoring commands
# (SCORE_POINT, SET_SCORE) are accepted without manual confirmation.
# Set to 1.0 to disable auto-confirm entirely (require manual for everything).
AUTO_CONFIRM_CONFIDENCE_THRESHOLD = 0.70

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.services.settings import (
    VOICE_DEBUG_EVENTS,
    VOICE_ENABLE_CONFIRMATION,
    VOICE_STRICT_MODE,
)

logger = logging.getLogger(__name__)


class ConfirmationState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class VoiceConfirmationStateMachine:
    """Deterministic state machine for voice command confirmations.

    Guarantees that:
    - Only one confirmation can be pending at a time.
    - Pending confirmations expire after a TTL.
    - Confirm/cancel/expire are explicit transitions.
    - No destructive command can execute without a visual confirmation card.
    """

    def __init__(self, ttl_seconds: float = 8.0) -> None:
        self.state: ConfirmationState = ConfirmationState.IDLE
        self.pending: Optional[VoiceParseResult] = None
        self.expires_at: float = 0.0
        self.ttl_seconds: float = ttl_seconds

    def submit(self, result: VoiceParseResult) -> Literal["pending", "reject"]:
        """Try to enter PENDING state with the given result.

        Returns:
            "pending" if accepted, "reject" if already pending.
        """
        if self.state != ConfirmationState.IDLE:
            logger.debug(
                "Confirmation rejected: state=%s, intent=%s",
                self.state.value,
                result.intent.value if isinstance(result.intent, VoiceIntent) else result.intent,
            )
            return "reject"

        self.pending = result
        self.expires_at = time.time() + self.ttl_seconds
        self.state = ConfirmationState.PENDING
        logger.info(
            "Confirmation pending: intent=%s, expires_in=%.1fs",
            result.intent.value if isinstance(result.intent, VoiceIntent) else result.intent,
            self.ttl_seconds,
        )
        return "pending"

    def confirm(self) -> Optional[VoiceParseResult]:
        """Confirm the pending command and return it, or None if not pending."""
        if self.state != ConfirmationState.PENDING:
            return None

        result = self.pending
        self.pending = None
        self.state = ConfirmationState.CONFIRMED
        logger.info("Confirmation accepted: intent=%s", result.intent.value if isinstance(result.intent, VoiceIntent) else result.intent)
        return result

    def cancel(self) -> None:
        """Cancel the pending command."""
        self.pending = None
        self.state = ConfirmationState.CANCELLED
        logger.info("Confirmation cancelled")

    def expire(self) -> None:
        """Expire the pending command."""
        self.pending = None
        self.state = ConfirmationState.EXPIRED
        logger.info("Confirmation expired")

    def tick(self) -> str:
        """Check expiration. Returns current effective state.

        If pending and expired, transitions to EXPIRED.
        """
        if self.state == ConfirmationState.PENDING and time.time() > self.expires_at:
            self.expire()
            return ConfirmationState.EXPIRED.value
        return self.state.value

    def pending_result(self) -> Optional[VoiceParseResult]:
        """Return the pending result, or None."""
        return self.pending

    def is_idle(self) -> bool:
        return self.state == ConfirmationState.IDLE

    def reset(self) -> None:
        """Force reset to idle."""
        self.pending = None
        self.state = ConfirmationState.IDLE


class ConfirmationPolicy:
    """Decide apply/confirm/reject for a parsed voice event."""

    @staticmethod
    def decide(
        result: VoiceParseResult,
        context: Dict[str, Any],
    ) -> Literal["apply", "confirm", "reject"]:
        raw_intent = result.intent
        if hasattr(raw_intent, "value"):
            intent = raw_intent
        else:
            intent_map = {
                "increment": VoiceIntent.SCORE_POINT,
                "unknown": VoiceIntent.UNKNOWN,
                "repeat": VoiceIntent.REPEAT_SCORE,
                "access_repeat": VoiceIntent.REPEAT_SCORE,
            }
            intent = intent_map.get(str(raw_intent))
            if intent is None:
                try:
                    intent = VoiceIntent(str(raw_intent))
                except ValueError:
                    intent = VoiceIntent.UNKNOWN

        if intent == VoiceIntent.UNKNOWN:
            return "reject"

        if result.disposition and result.disposition not in (
            "",
            None,
        ):
            return "reject"

        if result.confidence < 0.5:
            return "reject"

        strict = context.get("strict_mode", False) or VOICE_STRICT_MODE
        enable_confirm = bool(context.get("enable_confirmation", True))

        if intent in (
            VoiceIntent.START_MATCH,
            VoiceIntent.PAUSE_MATCH,
            VoiceIntent.RESUME_MATCH,
            VoiceIntent.START_NEXT_GAME,
            VoiceIntent.END_GAME,
            VoiceIntent.TIMEOUT_START,
            VoiceIntent.TIMEOUT_END,
            VoiceIntent.SET_SERVER,
        ):
            return "confirm"

        # Auto-confirm scoring commands when confidence >= threshold.
        # This lets high-confidence voice commands update the scoreboard
        # immediately without manual confirmation.
        if intent == VoiceIntent.SET_SCORE:
            if result.confidence >= AUTO_CONFIRM_CONFIDENCE_THRESHOLD:
                return "apply"
            return "confirm"

        if intent == VoiceIntent.SCORE_POINT:
            if result.confidence >= AUTO_CONFIRM_CONFIDENCE_THRESHOLD:
                return "apply"
            if strict or enable_confirm or result.confidence < 0.85:
                return "confirm"
            return "apply"

        if intent in (
            VoiceIntent.UNDO,
            VoiceIntent.REPEAT_SCORE,
            VoiceIntent.SERVER_CHECK,
            VoiceIntent.CONFIRM,
            VoiceIntent.CANCEL,
        ):
            return "apply"

        return "confirm"


def policy_decision(
    result: VoiceParseResult,
    context: Dict[str, Any],
) -> Literal["apply", "confirm", "reject"]:
    return ConfirmationPolicy.decide(result, context)
