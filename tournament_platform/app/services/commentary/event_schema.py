"""
TT-specific event schema — distinct from the legacy ``CommentaryEventType``
to avoid enum shadowing.

The 25 TT event types map cleanly to the existing category vocabulary in
``tournament_platform.services.commentary_templates``; missing slots fall
back to the canonical phrase bank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TTEventType(str, Enum):
    POINT_WON = "point_won"
    POINT_LOST = "point_lost"
    SERVE_POINT = "serve_point"
    RALLY_POINT = "rally_point"
    NET_ERROR = "net_error"
    EDGE_OR_LUCKY_POINT = "edge_or_lucky_point"
    FOREHAND_WINNER = "forehand_winner"
    BACKHAND_WINNER = "backhand_winner"
    FOREHAND_ERROR = "forehand_error"
    BACKHAND_ERROR = "backhand_error"
    LONG_RALLY = "long_rally"
    SHORT_RALLY = "short_rally"
    DEUCE = "deuce"
    ADVANTAGE = "advantage"
    GAME_POINT = "game_point"
    MATCH_POINT = "match_point"
    GAME_WON = "game_won"
    MATCH_WON = "match_won"
    COMEBACK = "comeback"
    DOMINANT_LEAD = "dominant_lead"
    MOMENTUM_SHIFT = "momentum_shift"
    TIMEOUT_OR_PAUSE = "timeout_or_pause"
    MANUAL_SCORE_CHANGE = "manual_score_change"
    VOICE_SCORE_CONFIRMED = "voice_score_confirmed"
    VOICE_SCORE_REJECTED = "voice_score_rejected"


# Mapping from TT event type to the legacy category used by the fallback bank.
_TT_TO_LEGACY_CATEGORY: Dict[TTEventType, str] = {
    TTEventType.POINT_WON: "point_won",
    TTEventType.POINT_LOST: "point_won",
    TTEventType.SERVE_POINT: "serve_change",
    TTEventType.RALLY_POINT: "point_won",
    TTEventType.NET_ERROR: "point_won",
    TTEventType.EDGE_OR_LUCKY_POINT: "point_won",
    TTEventType.FOREHAND_WINNER: "point_won",
    TTEventType.BACKHAND_WINNER: "point_won",
    TTEventType.FOREHAND_ERROR: "point_won",
    TTEventType.BACKHAND_ERROR: "point_won",
    TTEventType.LONG_RALLY: "point_won",
    TTEventType.SHORT_RALLY: "point_won",
    TTEventType.DEUCE: "deuce",
    TTEventType.ADVANTAGE: "advantage",
    TTEventType.GAME_POINT: "game_point",
    TTEventType.MATCH_POINT: "match_point",
    TTEventType.GAME_WON: "game_won",
    TTEventType.MATCH_WON: "match_won",
    TTEventType.COMEBACK: "comeback",
    TTEventType.DOMINANT_LEAD: "lead_change",
    TTEventType.MOMENTUM_SHIFT: "streak",
    TTEventType.TIMEOUT_OR_PAUSE: "timeout",
    TTEventType.MANUAL_SCORE_CHANGE: "score_update",
    TTEventType.VOICE_SCORE_CONFIRMED: "voice_command_accepted",
    TTEventType.VOICE_SCORE_REJECTED: "voice_command_rejected",
}

_LEGACY_CATEGORY_TO_TT: Dict[str, TTEventType] = {}
for _tt, _cat in _TT_TO_LEGACY_CATEGORY.items():
    if _cat not in _LEGACY_CATEGORY_TO_TT:
        _LEGACY_CATEGORY_TO_TT[_cat] = _tt


def tt_event_type_to_legacy_category(event_type: TTEventType) -> str:
    return _TT_TO_LEGACY_CATEGORY.get(event_type, "point_won")


def legacy_category_to_tt_event_type(category: str) -> TTEventType:
    return _LEGACY_CATEGORY_TO_TT.get(category, TTEventType.POINT_WON)


@dataclass
class CommentaryEventData:
    event_type: TTEventType
    player: str = ""
    opponent: str = ""
    score: str = ""
    game_score: str = ""
    match_score: str = ""
    serving_player: str = ""
    language: str = "en"
    style: str = "neutral"
    confidence: float = 1.0
    source: str = "manual"
    stroke_type: Optional[str] = None
    stroke_side: Optional[str] = None
    rally_length: Optional[int] = None
    rally_outcome: Optional[str] = None
    posture: Optional[str] = None
    tempo: Optional[str] = None
    pressure_level: Optional[str] = None
    momentum_player: Optional[str] = None
    previous_points: List[Dict[str, Any]] = field(default_factory=list)
    completed_games: List[str] = field(default_factory=list)
    commentary_log: List[str] = field(default_factory=list)

    def with_defaults(self, language: str = "en", style: str = "neutral") -> "CommentaryEventData":
        self.language = language
        self.style = style
        return self

    def is_lithuanian(self) -> bool:
        return str(self.language).lower() in {"lt", "lithuanian", "lietuvių"}

    def derived_commentary_type(self) -> str:
        tactical_events = {
            TTEventType.FOREHAND_WINNER,
            TTEventType.BACKHAND_WINNER,
            TTEventType.FOREHAND_ERROR,
            TTEventType.BACKHAND_ERROR,
            TTEventType.NET_ERROR,
            TTEventType.LONG_RALLY,
            TTEventType.SHORT_RALLY,
            TTEventType.RALLY_POINT,
            TTEventType.EDGE_OR_LUCKY_POINT,
        }
        momentum_events = {
            TTEventType.COMEBACK,
            TTEventType.DOMINANT_LEAD,
            TTEventType.MOMENTUM_SHIFT,
        }
        summary_events = {
            TTEventType.GAME_WON,
            TTEventType.MATCH_WON,
        }
        coaching_events = {TTEventType.POINT_WON, TTEventType.POINT_LOST, TTEventType.GAME_WON}

        if self.event_type in tactical_events and (self.stroke_type or self.rally_length is not None):
            return "tactical"
        if self.event_type in momentum_events:
            return "momentum"
        if self.event_type in summary_events:
            return "summary"
        if self.style == "coach" or self.event_type in coaching_events and self.style == "coach":
            return "coaching"
        return "play_by_play"

    def to_template_category(self) -> str:
        return tt_event_type_to_legacy_category(self.event_type)

    def to_template_style(self) -> str:
        style = str(self.style).lower().strip()
        aliases = {
            "short": "neutral",
        }
        return aliases.get(style, style)
