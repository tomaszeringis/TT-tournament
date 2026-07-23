from dataclasses import dataclass
from typing import Dict, List, Optional, Literal

from tournament_platform.services.match_point_event_repository import MatchPointEventRepository
from tournament_platform.models import MatchPointEvent


@dataclass
class MatchInsight:
    match_id: int
    last_scorer: Optional[Literal["A", "B"]]
    last_3_points: List[Literal["A", "B"]]
    current_game_score: tuple[int, int]
    current_games: tuple[int, int]
    momentum_label: str
    momentum_color: str
    is_game_point: bool
    is_match_point: bool
    point_events_available: bool


def _streak_label(points: List[str]) -> str:
    if not points:
        return ""
    last = points[-1]
    count = 0
    for p in reversed(points):
        if p == last:
            count += 1
        else:
            break
    if count >= 3:
        return f"{last}×{count}"
    return ""


def compute_match_insight(events: List[MatchPointEvent]) -> MatchInsight:
    """Derive simple momentum/insight from persisted point events."""
    if not events:
        return MatchInsight(
            match_id=0,
            last_scorer=None,
            last_3_points=[],
            current_game_score=(0, 0),
            current_games=(0, 0),
            momentum_label="No data",
            momentum_color="default",
            is_game_point=False,
            is_match_point=False,
            point_events_available=False,
        )

    last = events[-1]
    points = [ev.scorer_side for ev in events]
    last_3 = points[-3:]
    last_scorer = last.scorer_side

    streak = _streak_label(points)

    game_a = last.score_a_after
    game_b = last.score_b_after
    games_a = last.games_a_after
    games_b = last.games_b_after

    if streak:
        momentum_label = f"Hot streak: {streak}"
        momentum_color = "red" if last_scorer == "A" else "blue"
    else:
        momentum_label = "Tight game"
        momentum_color = "green"

    is_game_point = game_a >= last.game_target or game_b >= last.game_target
    target_games = (last.best_of // 2) + 1
    is_match_point = games_a >= target_games or games_b >= target_games

    return MatchInsight(
        match_id=last.match_id,
        last_scorer=last_scorer,
        last_3_points=last_3,
        current_game_score=(game_a, game_b),
        current_games=(games_a, games_b),
        momentum_label=momentum_label,
        momentum_color=momentum_color,
        is_game_point=is_game_point,
        is_match_point=is_match_point,
        point_events_available=True,
    )


def batch_compute_insights(match_ids: List[int], db_session) -> Dict[int, MatchInsight]:
    """Batch-load point events for multiple matches and compute insights in one pass."""
    if not match_ids:
        return {}

    events = (
        db_session.query(MatchPointEvent)
        .filter(MatchPointEvent.match_id.in_(match_ids))
        .order_by(MatchPointEvent.match_id, MatchPointEvent.game_index, MatchPointEvent.point_index)
        .all()
    )

    grouped: Dict[int, List[MatchPointEvent]] = {mid: [] for mid in match_ids}
    for ev in events:
        if ev.match_id in grouped:
            grouped[ev.match_id].append(ev)

    return {mid: compute_match_insight(grouped[mid]) for mid in match_ids}
