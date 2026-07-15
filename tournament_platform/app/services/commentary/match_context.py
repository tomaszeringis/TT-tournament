"""
Match context dataclass for the local commentary template engine.

Mirrors the fields consumed by the template bank so the engine can derive
variables without mutating the live match manager state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class MatchContext:
    score_a: int = 0
    score_b: int = 0
    games_won_a: int = 0
    games_won_b: int = 0
    current_game: int = 1
    player_a: str = "Player A"
    player_b: str = "Player B"
    player_a_id: Optional[int] = None
    player_b_id: Optional[int] = None
    serving_player: str = ""
    rally_length: Optional[int] = None
    rally_outcome: Optional[str] = None
    stroke_type: Optional[str] = None
    stroke_side: Optional[str] = None
    posture: Optional[str] = None
    tempo: Optional[str] = None
    pressure_level: Optional[str] = None
    momentum_player: Optional[str] = None
    previous_points: List[Dict[str, Any]] = field(default_factory=list)
    completed_games: List[str] = field(default_factory=list)
    commentary_log: List[str] = field(default_factory=list)
    points_to_win: int = 11
    best_of: int = 5


class MatchContextBuilder:
    @staticmethod
    def from_match_manager(match_manager: Any) -> "MatchContext":
        engine = getattr(match_manager, "engine", None)
        state = getattr(match_manager, "state", None)
        if engine is None or state is None:
            return MatchContext()

        completed_games = [f"{a}-{b}" for a, b in getattr(engine, "round_scores", [])]
        history = list(getattr(engine, "history", []))

        rally_length = None
        if len(history) >= 2:
            last = history[-1]
            if last.get("action") == "point_added":
                rally_length = last.get("rally_length")

        serving_player = getattr(engine, "serving_player", "") or getattr(state, "player_a", "")

        ctx = MatchContext(
            score_a=getattr(state, "score_a", 0),
            score_b=getattr(state, "score_b", 0),
            games_won_a=getattr(engine, "games_won_a", 0),
            games_won_b=getattr(engine, "games_won_b", 0),
            current_game=len(getattr(engine, "round_scores", [])) + 1,
            player_a=getattr(state, "player_a", "Player A"),
            player_b=getattr(state, "player_b", "Player B"),
            player_a_id=getattr(state, "player_a_id", None),
            player_b_id=getattr(state, "player_b_id", None),
            serving_player=serving_player,
            rally_length=rally_length,
            completed_games=completed_games,
            previous_points=history,
            points_to_win=getattr(engine, "points_to_win", 11),
            best_of=getattr(engine, "best_of", 5),
        )
        return ctx

    @staticmethod
    def from_spoken_score_state(state: Any) -> "MatchContext":
        history = list(getattr(state, "match_history", []))

        rally_length = None
        if len(history) >= 2:
            last = history[-1]
            if last.get("action") == "point_added":
                rally_length = last.get("rally_length")

        serving_player = getattr(state, "serving_player", "") or getattr(state, "player_a", "")

        ctx = MatchContext(
            score_a=getattr(state, "score_a", 0),
            score_b=getattr(state, "score_b", 0),
            games_won_a=getattr(state, "sets_a", 0),
            games_won_b=getattr(state, "sets_b", 0),
            current_game=getattr(state, "current_set", 1),
            player_a=getattr(state, "player_a", "Player A"),
            player_b=getattr(state, "player_b", "Player B"),
            player_a_id=getattr(state, "player_a_id", None),
            player_b_id=getattr(state, "player_b_id", None),
            serving_player=serving_player,
            rally_length=rally_length,
            previous_points=history,
            points_to_win=getattr(state, "points_to_win", 11),
            best_of=getattr(state, "best_of", 5),
        )
        return ctx

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MatchContext":
        return MatchContext(
            score_a=int(data.get("score_a", 0)),
            score_b=int(data.get("score_b", 0)),
            games_won_a=int(data.get("games_won_a", 0)),
            games_won_b=int(data.get("games_won_b", 0)),
            current_game=int(data.get("current_game", 1)),
            player_a=str(data.get("player_a", "Player A")),
            player_b=str(data.get("player_b", "Player B")),
            player_a_id=data.get("player_a_id"),
            player_b_id=data.get("player_b_id"),
            serving_player=str(data.get("serving_player", "")),
            rally_length=data.get("rally_length"),
            rally_outcome=data.get("rally_outcome"),
            stroke_type=data.get("stroke_type"),
            stroke_side=data.get("stroke_side"),
            posture=data.get("posture"),
            tempo=data.get("tempo"),
            pressure_level=data.get("pressure_level"),
            momentum_player=data.get("momentum_player"),
            previous_points=list(data.get("previous_points", [])),
            completed_games=list(data.get("completed_games", [])),
            commentary_log=list(data.get("commentary_log", [])),
            points_to_win=int(data.get("points_to_win", 11)),
            best_of=int(data.get("best_of", 5)),
        )
