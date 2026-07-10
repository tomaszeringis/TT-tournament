"""
Voice Rules Assistant Handler (Phase 3)

Read-only rules/umpire assistant. Uses existing AI/Rules stack.
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


class RulesAssistantHandler:
    """Handles voice rules queries. Read-only, never mutates match state."""

    def execute(
        self,
        intent: VoiceIntent,
        slots: Dict[str, Any],
    ) -> ActionResult:
        question = slots.get("question", "")
        if not question:
            return ActionResult(
                action="error",
                payload={},
                message="No question provided.",
            )

        response = api_client.ask_rules(question)
        if response is None:
            return ActionResult(
                action="rules_answer",
                payload={"answer": "Rules assistant unavailable. Please consult the rulebook."},
                message="Rules assistant unavailable",
            )

        answer = response.get("answer", "No answer available.")
        return ActionResult(
            action="rules_answer",
            payload={"answer": answer},
            message=answer,
        )
