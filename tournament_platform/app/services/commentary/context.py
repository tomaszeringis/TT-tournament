"""
Commentary context builder — derives match context from engine state.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CommentaryContext:
    score_a: int = 0
    score_b: int = 0
    sets_a: int = 0
    sets_b: int = 0
    current_set: int = 1
    player_a: str = "Player A"
    player_b: str = "Player B"
    player_a_id: Optional[int] = None
    player_b_id: Optional[int] = None
    server: Optional[str] = None
    completed_games: List[str] = field(default_factory=list)
    streak: Optional[str] = None
    comeback: bool = False
    pressure_point: bool = False
    deciding_game: bool = False
    match_history: List[dict] = field(default_factory=list)
    points_to_win: int = 11
    best_of: int = 5


class CommentaryContextBuilder:
    @staticmethod
    def from_match_manager(match_manager) -> CommentaryContext:
        engine = match_manager.engine
        completed_games = [f"{a}-{b}" for a, b in engine.round_scores]
        total_games = engine.games_won_a + engine.games_won_b
        deciding_game = max(engine.games_won_a, engine.games_won_b) == (engine.best_of // 2 + 1) - 1

        context = CommentaryContext(
            score_a=engine.score_a,
            score_b=engine.score_b,
            sets_a=engine.games_won_a,
            sets_b=engine.games_won_b,
            current_set=len(engine.round_scores) + 1,
            player_a=engine.player_a_name,
            player_b=engine.player_b_name,
            player_a_id=engine.player_a_id,
            player_b_id=engine.player_b_id,
            server=engine.serving_player,
            completed_games=completed_games,
            deciding_game=deciding_game,
            match_history=list(engine.history),
            points_to_win=engine.points_to_win,
            best_of=engine.best_of,
        )
        context.streak = CommentaryContextBuilder._detect_streak(context)
        context.comeback = CommentaryContextBuilder._detect_comeback(context)
        context.pressure_point = CommentaryContextBuilder._detect_pressure_point(context)
        return context

    @staticmethod
    def from_spoken_score_state(state) -> CommentaryContext:
        context = CommentaryContext(
            score_a=state.score_a,
            score_b=state.score_b,
            sets_a=state.sets_a,
            sets_b=state.sets_b,
            current_set=state.current_set,
            player_a=state.player_a,
            player_b=state.player_b,
            player_a_id=state.player_a_id,
            player_b_id=state.player_b_id,
            match_history=list(state.match_history),
        )
        context.streak = CommentaryContextBuilder._detect_streak(context)
        context.comeback = CommentaryContextBuilder._detect_comeback(context)
        context.pressure_point = CommentaryContextBuilder._detect_pressure_point(context)
        return context

    @staticmethod
    def _detect_streak(context: CommentaryContext) -> Optional[str]:
        if len(context.match_history) < 3:
            return None
        recent = context.match_history[-3:]
        players = [e.get("player") for e in recent if e.get("action") == "point_added"]
        if len(players) >= 3 and len(set(players)) == 1:
            return players[0]
        return None

    @staticmethod
    def _detect_comeback(context: CommentaryContext) -> bool:
        if len(context.match_history) < 2:
            return False
        first = context.match_history[0]
        prev_diff = first.get("previous_score_a", 0) - first.get("previous_score_b", 0)
        curr_diff = context.score_a - context.score_b
        threshold = 5
        if prev_diff <= -threshold and curr_diff >= 0:
            return True
        if prev_diff >= threshold and curr_diff <= 0:
            return True
        return False

    @staticmethod
    def _detect_pressure_point(context: CommentaryContext) -> bool:
        pts = context.points_to_win
        a, b = context.score_a, context.score_b
        return (
            (a >= pts - 1 and b >= pts - 1)
            or (a >= pts - 1 and b >= pts - 2)
            or (b >= pts - 1 and a >= pts - 2)
        )
