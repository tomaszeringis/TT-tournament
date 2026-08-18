"""
Shared Score-Action Boundary (Phase 3).

Introduce typed contracts so all input modes converge on one path.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ScoreActionType(Enum):
    ADD_POINT_A = "add_point_a"
    ADD_POINT_B = "add_point_b"
    UNDO_POINT = "undo_point"
    UNDO_GAME = "undo_game"
    RESET_GAME = "reset_game"
    RESET_MATCH = "reset_match"
    APPLY_FORMAT = "apply_format"


@dataclass
class ScoreAction:
    """Typed request to mutate a match score."""

    action_type: ScoreActionType
    match_id: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None
    transcript: Optional[str] = None
    tokens: Optional[List[str]] = None
    source: Optional[str] = None
    candidate_id: Optional[str] = None
    rally_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class ScoreActionResult:
    """Typed outcome from a score mutation."""

    success: bool
    message: str
    match_id: Optional[int] = None
    applied_event: Optional[Dict[str, Any]] = None
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass
class ScoreApplyResult:
    """Outcome of applying a voice score event through the canonical pipeline."""

    success: bool
    reason: str
    previous_score: str
    new_score: str
    parsed: Any
    route_result: Any
    event_key: Optional[str] = None
    event_ts: float = 0.0


def apply_manual_score_action(
    action: ScoreAction,
    match_manager: Any,
    session_state: Optional[Dict[str, Any]] = None,
) -> ScoreActionResult:
    """Apply a manual score action through the shared boundary.

    Current implementation wraps the existing MatchManager methods and
    preserves all existing side-effects (toast, cue, commentary, DB
    persistence, rerun). This keeps old wrappers until parity tests pass.
    """
    idempotency_key = action.idempotency_key or action.candidate_id
    if idempotency_key and session_state is not None:
        applied_keys: set = session_state.setdefault("_score_action_applied_keys", set())
        if idempotency_key in applied_keys:
            return ScoreActionResult(
                success=False,
                message="Duplicate score action suppressed",
                match_id=action.match_id,
                applied_event=None,
                diagnostics={"duplicate_suppressed": True, "idempotency_key": idempotency_key},
            )

    prev_state = copy.deepcopy(match_manager.state)
    success = False
    msg = ""
    diagnostics: Dict[str, Any] = {}

    if action.action_type == ScoreActionType.ADD_POINT_A:
        success, msg = match_manager._add_point("A")
    elif action.action_type == ScoreActionType.ADD_POINT_B:
        success, msg = match_manager._add_point("B")
    elif action.action_type == ScoreActionType.UNDO_POINT:
        success, msg = match_manager.undo_last_point()
    elif action.action_type == ScoreActionType.UNDO_GAME:
        if match_manager.engine.round_scores:
            success, msg = match_manager.undo_last_completed_game()
        else:
            success = False
            msg = "No completed games to undo"
    elif action.action_type == ScoreActionType.RESET_GAME:
        success, msg = match_manager.reset_current_game()
    elif action.action_type == ScoreActionType.RESET_MATCH:
        success, msg = match_manager.reset_match()
    elif action.action_type == ScoreActionType.APPLY_FORMAT:
        if action.payload:
            new_pts = action.payload.get("points_to_win", 11)
            new_bo = action.payload.get("best_of", 3)
            new_fs = action.payload.get("first_server", "A")
            match_manager.apply_format(new_pts, new_bo, new_fs)
            success = True
            msg = f"Format set: first to {new_pts}, first to {_best_of_to_games_to_win(new_bo)} games"
        else:
            success = False
            msg = "Missing format payload"
    else:
        success = False
        msg = f"Unknown action type: {action.action_type}"

    diagnostics["prev_state_hash"] = hash(str(prev_state))
    diagnostics["new_state_hash"] = hash(str(match_manager.state))
    diagnostics["action_source"] = action.source or "unknown"
    diagnostics["candidate_id"] = action.candidate_id
    diagnostics["rally_id"] = action.rally_id
    diagnostics["idempotency_key"] = action.idempotency_key
    diagnostics["action_type"] = action.action_type.value if isinstance(action.action_type, ScoreActionType) else str(action.action_type)

    if success and idempotency_key and session_state is not None:
        applied_keys.add(idempotency_key)

    return ScoreActionResult(
        success=success,
        message=msg,
        match_id=action.match_id,
        applied_event=None,
        diagnostics=diagnostics,
    )


def resolve_side_to_player(side: str, engine: Any) -> Optional[str]:
    """Resolve a display side (LEFT/RIGHT) to the current player identity (A/B).

    The live scoreboard renders player_a on the left column and player_b on
    the right column.  This helper encodes that invariant so the parser can
    produce language-neutral ``target_side`` slots while the application
    layer maps them to the correct player label.

    Args:
        side: Display side — ``"LEFT"`` or ``"RIGHT"``.
        engine: Authoritative ``MatchState`` engine (used for future display-
            order swaps; currently the scoreboard layout is hardcoded).

    Returns:
        ``"A"`` for LEFT, ``"B"`` for RIGHT, or ``None`` for unknown sides.
    """
    if side == "LEFT":
        return "A"
    if side == "RIGHT":
        return "B"
    return None


def _best_of_to_games_to_win(best_of: int) -> int:
    return (best_of // 2) + 1
