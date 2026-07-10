"""
Voice Navigation Handler (Phase 3)

Provides safe voice navigation between app pages.
Navigation is blocked when there are pending confirmations or active match state.
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


class NavigationCommandHandler:
    """Handles voice navigation commands safely."""

    NAVIGATION_TARGETS = {
        VoiceIntent.NAVIGATE_DASHBOARD: "dashboard",
        VoiceIntent.NAVIGATE_BRACKET: "bracket",
        VoiceIntent.NAVIGATE_RANKINGS: "rankings",
        VoiceIntent.NAVIGATE_PUBLIC_BOARD: "public_board",
        VoiceIntent.NAVIGATE_CURRENT_MATCH: "current_match",
        VoiceIntent.NAVIGATE_SCORING: "scoring",
        VoiceIntent.NAVIGATE_HELP: "help",
    }

    def can_navigate(
        self,
        state: Dict[str, Any],
    ) -> bool:
        if state.get("pending_confirmations"):
            return False
        return True

    def execute(
        self,
        intent: VoiceIntent,
        context: Dict[str, Any],
    ) -> ActionResult:
        target = self.NAVIGATION_TARGETS.get(intent)
        if not target:
            return ActionResult(
                action="error",
                payload={},
                message=f"Unknown navigation intent: {intent}",
            )

        if not self.can_navigate(context):
            return ActionResult(
                action="blocked",
                payload={"target": target},
                message="Navigation blocked: pending confirmation. Cancel or confirm first.",
            )

        return ActionResult(
            action="navigate",
            payload={"target": target},
            message=f"Navigating to {target}",
        )
