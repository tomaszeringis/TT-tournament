from typing import Any, Dict, List

from tournament_platform.app.services.advanced_match_analytics.schemas import DominationPoint


_SCORE_WEIGHT = 0.50
_MOMENTUM_WEIGHT = 0.30
_PRESSURE_WEIGHT = 0.20


def compute_domination(
    point_events: list,
    momentum_summary: Dict[str, Any],
    pressure_summary: Dict[str, Any],
    game_target: int,
    window: int = 5,
) -> tuple:
    """Return (global_domination, domination_winner, domination_timeline)."""
    if not point_events:
        return 0.0, "", []

    timeline: List[DominationPoint] = []
    pressure_a = pressure_summary.get("pressure_points_won_a", 0)
    pressure_b = pressure_summary.get("pressure_points_won_b", 0)
    total_pressure = pressure_summary.get("total_pressure_points", 0)

    max_streak_a = momentum_summary.get("max_streak_a", 0)
    max_streak_b = momentum_summary.get("max_streak_b", 0)

    score_a_cum = 0
    score_b_cum = 0
    momentum_a_cum = 0
    momentum_b_cum = 0

    window_scores: List[str] = []
    for idx, ev in enumerate(point_events):
        scorer = ev.scorer_side if hasattr(ev, "scorer_side") else ev.get("scorer_side", "")
        sa = ev.score_a_after if hasattr(ev, "score_a_after") else int(ev.get("score_a_after", 0))
        sb = ev.score_b_after if hasattr(ev, "score_b_after") else int(ev.get("score_b_after", 0))

        score_a_cum = sa
        score_b_cum = sb
        window_scores.append(scorer)
        if len(window_scores) > window:
            window_scores.pop(0)

        momentum = 0.0
        if len(window_scores) >= 3:
            score_delta = score_a_cum - score_b_cum
            max_possible = max(score_a_cum, score_b_cum, 1)
            score_dom = max(-1.0, min(1.0, score_delta / max_possible))
            mom_score = sum(1 if s == "A" else -1 for s in window_scores) / len(window_scores)
            mom_dom = max(-1.0, min(1.0, mom_score))
            if total_pressure >= 3:
                p_diff = pressure_a - pressure_b
                p_dom = max(-1.0, min(1.0, p_diff / max(total_pressure, 1)))
            else:
                p_dom = 0.0
            momentum = _SCORE_WEIGHT * score_dom + _MOMENTUM_WEIGHT * mom_dom + _PRESSURE_WEIGHT * p_dom

        timeline.append(
            DominationPoint(
                point_index=idx,
                score_domination=_score_domination(sa, sb, game_target),
                momentum_domination=_window_momentum_domination(window_scores),
                pressure_domination=_pressure_domination(pressure_a, pressure_b, total_pressure),
                global_domination=momentum,
            )
        )

    if not timeline:
        return 0.0, "", []

    final = timeline[-1].global_domination
    winner = "Player A" if final > 0 else ("Player B" if final < 0 else "")
    return final, winner, timeline


def _score_domination(score_a: int, score_b: int, target: int) -> float:
    total = score_a + score_b
    if total == 0:
        return 0.0
    return (2.0 * score_a / total) - 1.0


def _window_momentum_domination(window: List[str]) -> float:
    if not window:
        return 0.0
    val = sum(1 if s == "A" else -1 for s in window) / len(window)
    return max(-1.0, min(1.0, val))


def _pressure_domination(pressure_a: int, pressure_b: int, total: int) -> float:
    if total < 3:
        return 0.0
    diff = pressure_a - pressure_b
    return max(-1.0, min(1.0, diff / total))
