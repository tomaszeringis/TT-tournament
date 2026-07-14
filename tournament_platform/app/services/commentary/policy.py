"""
Commentary policy — importance ranking, dedup, cooldown, and suppression.
"""

from typing import Set, Tuple

from tournament_platform.app.services.commentary.events import CommentaryEventType


class CommentaryPolicy:
    IMPORTANCE_MAP = {
        CommentaryEventType.POINT_WON: "normal",
        CommentaryEventType.SERVE_CHANGE: "normal",
        CommentaryEventType.UNDO: "normal",
        CommentaryEventType.RESET: "normal",
        CommentaryEventType.ADVANTAGE: "important",
        CommentaryEventType.GAME_POINT: "important",
        CommentaryEventType.MATCH_POINT: "important",
        CommentaryEventType.DEUCE: "critical",
        CommentaryEventType.GAME_WON: "critical",
        CommentaryEventType.MATCH_WON: "critical",
        CommentaryEventType.RESULT_SUBMITTED: "critical",
        CommentaryEventType.VOICE_COMMAND_REJECTED: "critical",
    }

    @staticmethod
    def rank_importance(event_type: str) -> str:
        return CommentaryPolicy.IMPORTANCE_MAP.get(event_type, "normal")

    @staticmethod
    def is_duplicate(event_id: str, seen: Set[str]) -> Tuple[bool, Set[str]]:
        if event_id in seen:
            return True, seen
        new_seen = set(seen)
        new_seen.add(event_id)
        return False, new_seen

    @staticmethod
    def cooldown_ok(event_type: str, last_time: float, cooldown: float, now: float) -> bool:
        if event_type == CommentaryEventType.POINT_WON.value:
            return (now - last_time) >= cooldown
        return True

    @staticmethod
    def should_suppress(
        mode_value: str,
        intensity_value: str,
        importance: str,
        context=None,
    ) -> bool:
        if mode_value == "off":
            return True
        if mode_value == "visual_only":
            return False
        if mode_value == "important_only":
            return importance not in ("important", "critical")
        if mode_value == "after_every_game":
            return importance != "critical"
        if mode_value == "every_point":
            return False
        if mode_value == "spoken":
            if intensity_value == "low":
                return importance != "critical"
            if intensity_value == "medium":
                return importance not in ("important", "critical")
            if intensity_value == "high":
                return False
        return True
