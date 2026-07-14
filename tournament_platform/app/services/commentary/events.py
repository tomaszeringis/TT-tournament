"""
Commentary events — normalized, stable identifiers for dedup and cache keys.
"""

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CommentaryEventType(str, Enum):
    POINT_WON = "point_won"
    SERVE_CHANGE = "serve_change"
    DEUCE = "deuce"
    ADVANTAGE = "advantage"
    GAME_POINT = "game_point"
    MATCH_POINT = "match_point"
    GAME_WON = "game_won"
    MATCH_WON = "match_won"
    UNDO = "undo"
    RESET = "reset"
    RESULT_SUBMITTED = "result_submitted"
    VOICE_COMMAND_REJECTED = "voice_command_rejected"


@dataclass
class CommentaryEvent:
    event_type: CommentaryEventType
    event_id: str
    priority: int = 2
    importance: str = "normal"
    source: str = "unknown"
    match_id: Optional[int] = None
    game_number: int = 1
    score_before: Optional[str] = None
    score_after: Optional[str] = None
    server: Optional[str] = None
    player: Optional[str] = None

    @staticmethod
    def compute_event_id(
        event_type: str,
        match_id: Optional[int] = None,
        score_before: Optional[str] = None,
        score_after: Optional[str] = None,
        game_number: int = 1,
        server: Optional[str] = None,
    ) -> str:
        payload = json.dumps({
            "event_type": event_type,
            "match_id": match_id,
            "score_before": score_before or "",
            "score_after": score_after or "",
            "game_number": game_number,
            "server": server or "",
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
