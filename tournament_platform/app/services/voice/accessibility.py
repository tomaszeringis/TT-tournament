"""
Voice Accessibility Handler (Phase 3)

Handles voice accessibility commands. UI-state only, never mutates match score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tournament_platform.app.services.voice.commands import VoiceIntent

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    action: str
    payload: Dict[str, Any]
    requires_confirmation: bool = False
    risk: str = "low"
    message: str = ""


class AccessibilityCommandHandler:
    """Handles voice accessibility commands."""

    def execute(
        self,
        intent: VoiceIntent,
        slots: Dict[str, Any],
        state: Dict[str, Any],
    ) -> ActionResult:
        if intent == VoiceIntent.ACCESS_REPEAT:
            return ActionResult(
                action="access_repeat",
                payload={},
                message="Repeating last score",
            )
        if intent == VoiceIntent.ACCESS_ANNOUNCE_SCORE:
            return ActionResult(
                action="access_announce_score",
                payload={},
                message="Announcing score",
            )
        if intent == VoiceIntent.ACCESS_LOUDER:
            return ActionResult(
                action="access_volume_adjust",
                payload={"direction": "up"},
                message="Volume increased",
            )
        if intent == VoiceIntent.ACCESS_QUIETER:
            return ActionResult(
                action="access_volume_adjust",
                payload={"direction": "down"},
                message="Volume decreased",
            )
        if intent == VoiceIntent.ACCESS_MUTE:
            return ActionResult(
                action="access_mute",
                payload={"muted": True},
                message="Audio muted",
            )
        if intent == VoiceIntent.ACCESS_UNMUTE:
            return ActionResult(
                action="access_mute",
                payload={"muted": False},
                message="Audio unmuted",
            )
        if intent == VoiceIntent.ACCESS_SLOWER:
            return ActionResult(
                action="access_rate_adjust",
                payload={"direction": "down"},
                message="Speech rate slowed",
            )
        if intent == VoiceIntent.ACCESS_FASTER:
            return ActionResult(
                action="access_rate_adjust",
                payload={"direction": "up"},
                message="Speech rate increased",
            )
        if intent == VoiceIntent.ACCESS_LARGE_TEXT:
            return ActionResult(
                action="access_large_text",
                payload={"enabled": True},
                message="Large text enabled",
            )
        if intent == VoiceIntent.ACCESS_HIGH_CONTRAST:
            return ActionResult(
                action="access_high_contrast",
                payload={"enabled": True},
                message="High contrast enabled",
            )
        if intent == VoiceIntent.ACCESS_HELP:
            return ActionResult(
                action="access_help",
                payload={},
                message="Accessibility help: say louder, quieter, mute, unmute, slower, faster, large text, high contrast, repeat, announce score",
            )
        return ActionResult(
            action="error",
            payload={},
            message=f"Unknown accessibility intent: {intent}",
        )
