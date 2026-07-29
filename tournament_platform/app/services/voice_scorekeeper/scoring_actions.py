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


@dataclass
class ScoreActionResult:
    """Typed outcome from a score mutation."""

    success: bool
    message: str
    match_id: Optional[int] = None
    applied_event: Optional[Dict[str, Any]] = None
    diagnostics: Optional[Dict[str, Any]] = None


def apply_manual_score_action(
    action: ScoreAction,
    match_manager: Any,
    session_state: Dict[str, Any],
) -> ScoreActionResult:
    """Apply a manual score action through the shared boundary.

    Current implementation wraps the existing MatchManager methods and
    preserves all existing side-effects (toast, cue, commentary, DB
    persistence, rerun). This keeps old wrappers until parity tests pass.
    """
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

    return ScoreActionResult(
        success=success,
        message=msg,
        match_id=action.match_id,
        applied_event=None,
        diagnostics=diagnostics,
    )


def _best_of_to_games_to_win(best_of: int) -> int:
    return (best_of // 2) + 1
