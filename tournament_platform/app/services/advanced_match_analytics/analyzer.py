from typing import Any, Dict, List, Optional

from tournament_platform.app.services.advanced_match_analytics.schemas import (
    AdvancedMatchInsight,
    PointEvent,
)
from tournament_platform.app.services.advanced_match_analytics.score_probability import (
    build_win_probability_timeline,
)
from tournament_platform.app.services.advanced_match_analytics.momentum import (
    compute_momentum_summary,
)
from tournament_platform.app.services.advanced_match_analytics.pressure import (
    compute_pressure_summary,
    is_pressure_point,
)
from tournament_platform.app.services.advanced_match_analytics.domination import (
    compute_domination,
)
from tournament_platform.app.services.advanced_match_analytics.shot_diversity import (
    compute_shot_diversity,
)
from tournament_platform.app.services.advanced_match_analytics.formatter import (
    format_insight,
)


class AdvancedMatchAnalyticsService:
    def __init__(self, player_a_name: str = "Player A", player_b_name: str = "Player B"):
        self.player_a_name = player_a_name
        self.player_b_name = player_b_name

    def analyze(
        self,
        point_events: list,
        round_scores: Optional[List] = None,
        games_won_a: int = 0,
        games_won_b: int = 0,
        match_status: str = "in_progress",
        player_a_name: Optional[str] = None,
        player_b_name: Optional[str] = None,
        match_id: Optional[int] = None,
        game_target: int = 11,
        win_by: int = 2,
        best_of: int = 5,
    ) -> AdvancedMatchInsight:
        p1 = player_a_name or self.player_a_name
        p2 = player_b_name or self.player_b_name
        warnings: List[str] = []

        if not point_events:
            warnings.append("No point history available for advanced analytics.")

        timeline = build_win_probability_timeline(point_events)

        game_target = _effective_target(point_events, game_target)
        best_of = _effective_best_of(point_events, best_of)

        pressure_summary = compute_pressure_summary(point_events, game_target, win_by)
        warnings.extend(pressure_summary.get("warnings", []))

        momentum_summary = compute_momentum_summary(point_events)
        global_domination, domination_winner, domination_timeline = compute_domination(
            point_events,
            momentum_summary,
            pressure_summary,
            game_target,
        )

        longest_run_player = momentum_summary.get("longest_run_player", "")
        longest_run = momentum_summary.get("longest_run", 0)
        lead_changes = momentum_summary.get("lead_changes", 0)
        biggest_swing = momentum_summary.get("biggest_swing", 0.0)
        turning_points = momentum_summary.get("turning_points", [])

        shot_diversity_summary = compute_shot_diversity(point_events)
        if shot_diversity_summary.get("warning"):
            warnings.append(shot_diversity_summary["warning"])

        pressure_point_indices = _build_pressure_point_indices(point_events, game_target, win_by)

        key_turning_points = _build_key_turning_points(point_events, turning_points, p1, p2)
        narrative = _build_narrative(
            p1,
            p2,
            momentum_summary,
            pressure_summary,
            global_domination,
            longest_run_player,
            longest_run,
            lead_changes,
            biggest_swing,
            shot_diversity_summary,
            game_target,
            best_of,
        )

        return AdvancedMatchInsight(
            match_id=match_id,
            player_a_name=p1,
            player_b_name=p2,
            win_probability_timeline=timeline,
            domination_timeline=domination_timeline,
            pressure_summary=pressure_summary,
            momentum_summary=momentum_summary,
            shot_diversity_summary=shot_diversity_summary,
            global_domination=global_domination,
            domination_winner=domination_winner,
            biggest_momentum_swing=biggest_swing,
            pressure_points_won_a=pressure_summary.get("pressure_points_won_a", 0),
            total_pressure_points=pressure_summary.get("total_pressure_points", 0),
            longest_run_player=longest_run_player,
            longest_run=longest_run,
            key_turning_points=key_turning_points,
            narrative_summary=narrative,
            warnings=warnings,
            pressure_point_indices=pressure_point_indices,
        )

    def format_insight(self, insight: AdvancedMatchInsight) -> Dict[str, Any]:
        return format_insight(insight, self.player_a_name, self.player_b_name)


def _effective_target(point_events: list, default: int) -> int:
    for ev in point_events:
        if hasattr(ev, "game_target"):
            t = ev.game_target
        else:
            t = ev.get("game_target", default)
        if t and t > 0:
            return int(t)
    return default


def _effective_best_of(point_events: list, default: int) -> int:
    for ev in point_events:
        if hasattr(ev, "best_of"):
            b = ev.best_of
        else:
            b = ev.get("best_of", default)
        if b and b > 0:
            return int(b)
    return default


def _build_pressure_point_indices(point_events: list, game_target: int, win_by: int) -> List[int]:
    indices: List[int] = []
    for idx, ev in enumerate(point_events):
        try:
            if is_pressure_point(ev, game_target, win_by):
                indices.append(idx)
        except Exception:
            continue
    return indices


def _build_key_turning_points(point_events: list, turning_points: List[str], p1: str, p2: str) -> List[str]:
    tp = []
    for t in turning_points:
        tp.append(t)
    if len(point_events) > 2:
        first = point_events[0]
        last = point_events[-1]
        if hasattr(first, "score_a_after"):
            initial = f"{first.score_a_after}-{first.score_b_after}"
            final = f"{last.score_a_after}-{last.score_b_after}"
        else:
            initial = f"{first.get('score_a_after', 0)}-{first.get('score_b_after', 0)}"
            final = f"{last.get('score_a_after', 0)}-{last.get('score_b_after', 0)}"
        tp.append(f"Final score: {final}")
    return tp[:10]


def _build_narrative(
    p1: str,
    p2: str,
    momentum_summary: Dict[str, Any],
    pressure_summary: Dict[str, Any],
    global_domination: float,
    longest_run_player: str,
    longest_run: int,
    lead_changes: int,
    biggest_swing: float,
    shot_diversity_summary: Dict[str, Any],
    game_target: int,
    best_of: int,
) -> str:
    parts: List[str] = []

    if global_domination > 0.3:
        parts.append(f"{p1} dominated the match.")
    elif global_domination < -0.3:
        parts.append(f"{p2} dominated the match.")
    else:
        parts.append("The match was closely contested.")

    if longest_run >= 4:
        runner = p1 if longest_run_player == "A" else p2 if longest_run_player == "B" else longest_run_player
        parts.append(f"{runner} recorded the longest run of {longest_run} consecutive points.")

    if lead_changes > 0:
        parts.append(f"There were {lead_changes} lead change(s) during the match.")

    total_pressure = pressure_summary.get("total_pressure_points", 0)
    if total_pressure > 0:
        p_a = pressure_summary.get("pressure_points_won_a", 0)
        p_b = pressure_summary.get("pressure_points_won_b", 0)
        better = p1 if p_a > p_b else p2 if p_b > p_a else "Neither"
        parts.append(f"{total_pressure} pressure points were played; {better} performed better under pressure ({p_a}-{p_b}).")

    if not shot_diversity_summary.get("available"):
        warning = shot_diversity_summary.get("warning")
        if warning:
            parts.append(warning)

    return " ".join(parts) if parts else "Insufficient data to build a narrative."
