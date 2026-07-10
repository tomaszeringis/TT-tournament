"""
Voice Command Router (Phase 1)

Deterministic, ordered routing for parsed voice commands. Extracted from the
page-level decision logic so it can be tested in isolation and reused by
both push-to-talk and continuous listening paths.

Routing decisions:
- reject  → do nothing, log rejection
- confirm → enqueue for confirmation panel
- apply   → execute through MatchManager
- ignore  → duplicate or expired, log and skip
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.confirmation import policy_decision
from tournament_platform.app.services.voice.parse_result import VoiceParseResult
from tournament_platform.app.services.voice.navigation import NavigationCommandHandler, ActionResult as NavigationResult
from tournament_platform.app.services.voice.admin import AdminCommandHandler
from tournament_platform.app.services.voice.rules_assistant import RulesAssistantHandler
from tournament_platform.app.services.voice.accessibility import AccessibilityCommandHandler

logger = logging.getLogger(__name__)

_navigation_handler = NavigationCommandHandler()
_admin_handler = AdminCommandHandler()
_rules_handler = RulesAssistantHandler()
_accessibility_handler = AccessibilityCommandHandler()


class RouteDecision(str, Enum):
    REJECT = "reject"
    CONFIRM = "confirm"
    APPLY = "apply"
    IGNORE = "ignore"


@dataclass
class RouteContext:
    """Context required for routing a parsed voice command."""

    current_score_a: int = 0
    current_score_b: int = 0
    strict_mode: bool = False
    enable_confirmation: bool = True
    cooldown_ms: float = 1200.0
    last_applied_event_key: Optional[str] = None
    last_applied_event_ts: float = 0.0
    min_confidence_to_apply: float = 0.5
    min_confidence_to_confirm: float = 0.5

    def is_duplicate(self, event_key: str) -> bool:
        """True if the event is a duplicate within the cooldown window."""
        if self.last_applied_event_key != event_key:
            return False
        if self.cooldown_ms <= 0:
            return False
        elapsed_ms = (time.time() - self.last_applied_event_ts) * 1000.0
        return elapsed_ms < self.cooldown_ms


@dataclass
class RouteResult:
    """Outcome of routing a parsed voice command."""

    decision: RouteDecision
    reason: str = ""
    parse_result: Optional[VoiceParseResult] = None
    event_key: Optional[str] = None


def _make_event_key(result: VoiceParseResult) -> str:
    """Stable hash for duplicate suppression."""
    intent = result.intent.value if isinstance(result.intent, VoiceIntent) else str(result.intent)
    player = result.slots.get("player", "")
    score_a = result.slots.get("score_a", "")
    score_b = result.slots.get("score_b", "")
    raw = f"{intent}|{player}|{score_a}|{score_b}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _route_phase3_command(
    result: VoiceParseResult,
    context: RouteContext,
) -> RouteResult:
    intent = result.intent

    navigation_intents = {
        VoiceIntent.NAVIGATE_DASHBOARD,
        VoiceIntent.NAVIGATE_BRACKET,
        VoiceIntent.NAVIGATE_RANKINGS,
        VoiceIntent.NAVIGATE_PUBLIC_BOARD,
        VoiceIntent.NAVIGATE_CURRENT_MATCH,
        VoiceIntent.NAVIGATE_SCORING,
        VoiceIntent.NAVIGATE_HELP,
    }

    admin_intents = {
        VoiceIntent.ADMIN_CALL_NEXT,
        VoiceIntent.ADMIN_TABLE_READY,
        VoiceIntent.ADMIN_ASSIGN_TABLE,
        VoiceIntent.ADMIN_MARK_UNAVAILABLE,
        VoiceIntent.ADMIN_PUBLISH_RESULT,
        VoiceIntent.ADMIN_MARK_NO_SHOW,
        VoiceIntent.ADMIN_DROP_PLAYER,
        VoiceIntent.ADMIN_START_NEXT_ROUND,
    }

    rules_intents = {
        VoiceIntent.RULES_QUERY,
    }

    accessibility_intents = {
        VoiceIntent.ACCESS_REPEAT,
        VoiceIntent.ACCESS_ANNOUNCE_SCORE,
        VoiceIntent.ACCESS_LOUDER,
        VoiceIntent.ACCESS_QUIETER,
        VoiceIntent.ACCESS_MUTE,
        VoiceIntent.ACCESS_UNMUTE,
        VoiceIntent.ACCESS_SLOWER,
        VoiceIntent.ACCESS_FASTER,
        VoiceIntent.ACCESS_LARGE_TEXT,
        VoiceIntent.ACCESS_HIGH_CONTRAST,
        VoiceIntent.ACCESS_HELP,
    }

    if intent in navigation_intents:
        nav_result = _navigation_handler.execute(intent, context.__dict__)
        return RouteResult(
            decision=RouteDecision.APPLY if nav_result.action == "navigate" else RouteDecision.REJECT,
            reason=nav_result.message,
            parse_result=result,
        )

    if intent in admin_intents:
        action = _admin_handler.execute(intent, result.slots)
        decision = RouteDecision.CONFIRM if action.requires_confirmation else RouteDecision.APPLY
        return RouteResult(
            decision=decision,
            reason=action.message,
            parse_result=result,
        )

    if intent in rules_intents:
        action = _rules_handler.execute(intent, result.slots)
        return RouteResult(
            decision=RouteDecision.APPLY,
            reason=action.message,
            parse_result=result,
        )

    if intent in accessibility_intents:
        action = _accessibility_handler.execute(intent, result.slots, context.__dict__)
        return RouteResult(
            decision=RouteDecision.APPLY,
            reason=action.message,
            parse_result=result,
        )

    return RouteResult(
        decision=RouteDecision.REJECT,
        reason="unsupported_phase3_intent",
        parse_result=result,
    )


# Map legacy parser string types to canonical VoiceIntent values.
_LEGACY_INTENT_MAP = {
    "increment": VoiceIntent.SCORE_POINT,
    "unknown": VoiceIntent.UNKNOWN,
    "repeat": VoiceIntent.REPEAT_SCORE,
    "access_repeat": VoiceIntent.REPEAT_SCORE,
}


def _normalize_intent(intent: Any) -> VoiceIntent:
    """Normalize intent to a VoiceIntent enum member."""
    if isinstance(intent, VoiceIntent):
        return intent
    s = str(intent)
    mapped = _LEGACY_INTENT_MAP.get(s)
    if mapped is not None:
        return mapped
    try:
        return VoiceIntent(s)
    except ValueError:
        return VoiceIntent.UNKNOWN


def route_command(
    result: VoiceParseResult,
    context: RouteContext,
) -> RouteResult:
    """Route a parsed voice command to its next action.

    Args:
        result: Parsed voice command from VoiceCommandGrammar / VoiceParser.
        context: Current runtime context (scores, mode, cooldown, etc.).

    Returns:
        RouteResult with decision, reason, and optional event metadata.
    """
    intent = _normalize_intent(result.intent)

    # --------------------------------------------------------------- #
    # 0. Phase 3 handlers (navigation, admin, rules, accessibility)
    # --------------------------------------------------------------- #
    phase3_decision = _route_phase3_command(result, context)
    if phase3_decision.decision != RouteDecision.REJECT or phase3_decision.reason != "unsupported_phase3_intent":
        return phase3_decision

    # --------------------------------------------------------------- #
    # 1. Unknown intent → reject
    # --------------------------------------------------------------- #
    if intent == VoiceIntent.UNKNOWN:
        return RouteResult(
            decision=RouteDecision.REJECT,
            reason="unknown_intent",
            parse_result=result,
        )

    # --------------------------------------------------------------- #
    # 2. Disposition (e.g. deuce_not_allowed) → reject
    # --------------------------------------------------------------- #
    if getattr(result, "disposition", None):
        return RouteResult(
            decision=RouteDecision.REJECT,
            reason=f"disposition:{result.disposition}",
            parse_result=result,
        )

    # --------------------------------------------------------------- #
    # 3. Confidence gate
    # --------------------------------------------------------------- #
    if result.confidence < context.min_confidence_to_apply:
        return RouteResult(
            decision=RouteDecision.REJECT,
            reason=f"low_confidence:{result.confidence:.2f}",
            parse_result=result,
        )

    # --------------------------------------------------------------- #
    # 4. Duplicate suppression
    # --------------------------------------------------------------- #
    event_key = _make_event_key(result)
    if context.is_duplicate(event_key):
        return RouteResult(
            decision=RouteDecision.IGNORE,
            reason="duplicate_suppressed",
            parse_result=result,
            event_key=event_key,
        )

    # --------------------------------------------------------------- #
    # 5. Policy decision (apply | confirm | reject)
    # --------------------------------------------------------------- #
    policy_context = {
        "strict_mode": context.strict_mode,
        "enable_confirmation": context.enable_confirmation,
    }
    policy = policy_decision(result, policy_context)

    if policy == "reject":
        return RouteResult(
            decision=RouteDecision.REJECT,
            reason="policy_rejected",
            parse_result=result,
            event_key=event_key,
        )

    if policy == "confirm":
        return RouteResult(
            decision=RouteDecision.CONFIRM,
            reason="requires_confirmation",
            parse_result=result,
            event_key=event_key,
        )

    # policy == "apply"
    # Final guard: if confidence is below confirm threshold but policy said
    # apply, downgrade to confirm for safety.
    if result.confidence < context.min_confidence_to_confirm:
        return RouteResult(
            decision=RouteDecision.CONFIRM,
            reason="confidence_below_confirm_threshold",
            parse_result=result,
            event_key=event_key,
        )

    return RouteResult(
        decision=RouteDecision.APPLY,
        reason="applied",
        parse_result=result,
        event_key=event_key,
    )


def route_and_update_context(
    result: VoiceParseResult,
    context: RouteContext,
) -> RouteResult:
    """Route and update context with the latest applied-event metadata if applied.

    This is the preferred entry point for the main loop.
    """
    route_result = route_command(result, context)
    if route_result.decision == RouteDecision.APPLY and route_result.event_key:
        context.last_applied_event_key = route_result.event_key
        context.last_applied_event_ts = time.time()
    return route_result
