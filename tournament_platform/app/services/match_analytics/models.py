from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


@dataclass(frozen=True)
class MatchAnalyticsOption:
    id: str
    label: str
    player_a_name: str
    player_b_name: str
    winner_name: Optional[str] = None
    match_score: Optional[str] = None
    game_scores: Optional[List[str]] = None
    source: str = "database"


class GameLabel(str, Enum):
    TOTAL_DOMINATION = "total_domination"
    COMFORTABLE_WIN = "comfortable_win"
    CLOSE_GAME = "close_game"
    DEUCE_BATTLE = "deuce_battle"
    STRAIGHT_GAMES_WIN = "straight_games_win"
    TIGHT_MATCH = "tight_match"
    COMEBACK_MATCH = "comeback_match"
    PRESSURE_FINISH = "pressure_finish"
    ONGOING = "ongoing"


@dataclass
class GameInsight:
    game_number: int
    winner: str
    loser: str
    score: str
    margin: int
    label: GameLabel
    summary: str
    key_events: List[str] = field(default_factory=list)


@dataclass
class MomentumWindow:
    player: str
    points: int
    start_score: str
    end_score: str
    is_major: bool


@dataclass
class KeyEvent:
    event_type: str
    player: str
    score: str
    game_number: int
    text: str
    source: str


@dataclass
class MatchInsight:
    title: str
    summary: str
    confidence: str
    evidence: List[str] = field(default_factory=list)
    source: str = "deterministic"
    game_insights: List[GameInsight] = field(default_factory=list)
    momentum: List[MomentumWindow] = field(default_factory=list)
    key_events: List[KeyEvent] = field(default_factory=list)
