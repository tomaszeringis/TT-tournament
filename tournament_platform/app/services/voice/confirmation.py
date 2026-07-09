"""
Voice Confirmation Policy

Centralizes the decision of whether a parsed voice command should be
auto-applied, sent to the confirm/cancel panel, or rejected outright.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.services.settings import (
    VOICE_DEBUG_EVENTS,
    VOICE_ENABLE_CONFIRMATION,
    VOICE_STRICT_MODE,
)

logger = logging.getLogger(__name__)


class ConfirmationPolicy:
    """Decide apply/confirm/reject for a parsed voice event."""

    @staticmethod
    def decide(
        result: VoiceParseResult,
        context: Dict[str, Any],
    ) -> Literal["apply", "confirm", "reject"]:
        if result.intent == VoiceIntent.UNKNOWN:
            return "reject"

        if result.disposition and result.disposition not in (
            "",
            None,
        ):
            return "reject"

        if result.confidence < 0.5:
            return "reject"

        strict = context.get("strict_mode", False) or VOICE_STRICT_MODE
        enable_confirm = context.get("enable_confirmation", True) or VOICE_ENABLE_CONFIRMATION

        if result.intent in (
            VoiceIntent.SET_SCORE,
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

        if result.intent == VoiceIntent.SCORE_POINT:
            if strict or enable_confirm or result.confidence < 0.85:
                return "confirm"
            return "apply"

        if result.intent in (
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
