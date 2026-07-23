from functools import lru_cache
from typing import List, Optional, Tuple

from tournament_platform.app.services.advanced_match_analytics.schemas import WinProbabilityPoint


def game_win_probability(
    score_a: int,
    score_b: int,
    p_point_a: float = 0.5,
    target: int = 11,
    win_by: int = 2,
) -> float:
    """Return probability that A wins the game from the current state.

    Uses closed-form formulas for deuce/advantage states and memoized
    recursive DP for pre-deuce states. Hard-capped recursion depth prevents
    pathological inputs from causing infinite loops.
    """
    if p_point_a <= 0.0:
        return 0.0
    if p_point_a >= 1.0:
        return 1.0

    a, b = int(score_a), int(score_b)

    a_won = a >= target and (a - b) >= win_by
    b_won = b >= target and (b - a) >= win_by
    if a_won:
        return 1.0
    if b_won:
        return 0.0

    _validate_state(a, b, target, win_by)
    return _prob_a_wins(a, b, p_point_a, target, win_by)


def _validate_state(a: int, b: int, target: int, win_by: int) -> None:
    """Guard against pathological inputs that could blow the recursion stack."""
    cap = target + 20
    if a > cap or b > cap:
        raise ValueError(
            f"Score {a}-{b} exceeds safety cap of {cap} points for target={target}"
        )
    if win_by < 1:
        raise ValueError(f"win_by must be >= 1, got {win_by}")


@lru_cache(maxsize=None)
def _prob_a_wins(a: int, b: int, p: float, target: int, win_by: int) -> float:
    if a >= target and (a - b) >= win_by:
        return 1.0
    if b >= target and (b - a) >= win_by:
        return 0.0

    needed_offset = target - 1
    if a >= needed_offset and b >= needed_offset and abs(a - b) < win_by:
        diff = a - b
        if diff == 0:
            q = 1.0 - p
            return (p * p) / (p * p + q * q)
        if diff > 0:
            q = 1.0 - p
            deuce = (p * p) / (p * p + q * q)
            return p + q * deuce
        if diff < 0:
            q = 1.0 - p
            deuce = (p * p) / (p * p + q * q)
            return p * deuce

    return (
        p * _prob_a_wins(a + 1, b, p, target, win_by)
        + (1.0 - p) * _prob_a_wins(a, b + 1, p, target, win_by)
    )


def build_win_probability_timeline(
    point_events: list,
    p_point_a: float = 0.5,
) -> List[WinProbabilityPoint]:
    """Build a timeline of win probabilities from a list of PointEvent dicts/objects."""
    timeline: List[WinProbabilityPoint] = []

    for ev in point_events:
        if hasattr(ev, "score_a_after"):
            score_a = ev.score_a_after
            score_b = ev.score_b_after
            game_target = ev.game_target
            best_of = ev.best_of
        else:
            score_a = int(ev.get("score_a_after", 0))
            score_b = int(ev.get("score_b_after", 0))
            game_target = int(ev.get("game_target", 11))
            best_of = int(ev.get("best_of", 5))

        prob = game_win_probability(score_a, score_b, p_point_a, game_target)
        timeline.append(
            WinProbabilityPoint(
                point_index=len(timeline),
                probability_a=prob,
                probability_b=1.0 - prob,
                score_a=score_a,
                score_b=score_b,
                game_target=game_target,
                best_of=best_of,
            )
        )

    return timeline
