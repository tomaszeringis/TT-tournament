"""
Voice Admin Command Handler (Phase 3)

Handles voice tournament administration commands.
All commands require confirmation via VoiceConfirmationStateMachine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.api_client import api_client

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    action: str
    payload: Dict[str, Any]
    requires_confirmation: bool = False
    risk: str = "low"
    message: str = ""


DESTRUCTIVE_INTENTS = {
    VoiceIntent.ADMIN_MARK_UNAVAILABLE,
    VoiceIntent.ADMIN_PUBLISH_RESULT,
    VoiceIntent.ADMIN_MARK_NO_SHOW,
    VoiceIntent.ADMIN_DROP_PLAYER,
}


class AdminCommandHandler:
    """Handles voice admin commands with confirmation gating."""

    DESTRUCTIVE_WARNINGS = {
        VoiceIntent.ADMIN_DROP_PLAYER: "This will permanently remove the player from the tournament.",
        VoiceIntent.ADMIN_MARK_NO_SHOW: "This will mark the player as a no-show.",
        VoiceIntent.ADMIN_PUBLISH_RESULT: "This will publish the match result publicly.",
        VoiceIntent.ADMIN_MARK_UNAVAILABLE: "This will mark the player as unavailable.",
    }

    def requires_confirmation(self, intent: VoiceIntent) -> bool:
        return True

    def is_destructive(self, intent: VoiceIntent) -> bool:
        return intent in DESTRUCTIVE_INTENTS

    def get_warning(self, intent: VoiceIntent) -> str:
        return self.DESTRUCTIVE_WARNINGS.get(intent, "")

    def execute(
        self,
        intent: VoiceIntent,
        slots: Dict[str, Any],
    ) -> ActionResult:
        method = getattr(self, f"_handle_{intent.value}", None)
        if method is None:
            return ActionResult(
                action="error",
                payload={},
                message=f"Unsupported admin intent: {intent}",
            )
        return method(slots)

    def _handle_admin_call_next(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_call_next",
            payload={},
            requires_confirmation=True,
            risk="medium",
            message="Call next match",
        )

    def _handle_admin_table_ready(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_table_ready",
            payload={},
            requires_confirmation=True,
            risk="medium",
            message="Mark table as ready",
        )

    def _handle_admin_assign_table(self, slots: Dict[str, Any]) -> ActionResult:
        table = slots.get("table", "")
        return ActionResult(
            action="admin_assign_table",
            payload={"table": table},
            requires_confirmation=True,
            risk="medium",
            message=f"Assign table {table}",
        )

    def _handle_admin_mark_unavailable(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_mark_unavailable",
            payload={},
            requires_confirmation=True,
            risk="high",
            message="Mark player unavailable",
        )

    def _handle_admin_publish_result(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_publish_result",
            payload={},
            requires_confirmation=True,
            risk="high",
            message="Publish match result",
        )

    def _handle_admin_mark_no_show(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_mark_no_show",
            payload={},
            requires_confirmation=True,
            risk="high",
            message="Mark player as no-show",
        )

    def _handle_admin_drop_player(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_drop_player",
            payload={},
            requires_confirmation=True,
            risk="high",
            message="Drop player from tournament",
        )

    def _handle_admin_start_next_round(self, slots: Dict[str, Any]) -> ActionResult:
        return ActionResult(
            action="admin_start_next_round",
            payload={},
            requires_confirmation=True,
            risk="medium",
            message="Start next round",
        )
