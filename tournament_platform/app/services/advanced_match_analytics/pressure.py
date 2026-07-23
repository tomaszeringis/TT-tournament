from typing import Any, Dict, List, Optional

from tournament_platform.app.services.advanced_match_analytics.schemas import PointEvent


def is_pressure_point(ev: Any, game_target: int, win_by: int = 2) -> bool:
    """Determine whether a single point event qualifies as a pressure point."""
    if hasattr(ev, "score_a_before"):
        score_a = ev.score_a_before
        score_b = ev.score_b_before
        games_a = ev.games_a_before
        games_b = ev.games_b_before
        best_of = ev.best_of
    else:
        score_a = int(ev.get("score_a_before", 0) or 0)
        score_b = int(ev.get("score_b_before", 0) or 0)
        games_a = int(ev.get("games_a_before", 0) or 0)
        games_b = int(ev.get("games_b_before", 0) or 0)
        best_of = int(ev.get("best_of", 0) or 0)

    max_score = max(score_a, score_b)
    min_score = min(score_a, score_b)
    margin = abs(score_a - score_b)

    if is_deuce_state(score_a, score_b, game_target):
        return True
    if is_advantage_state(score_a, score_b, game_target):
        return True
    if is_game_point(score_a, score_b, game_target):
        return True
    if is_match_point(score_a, score_b, games_a, games_b, game_target, best_of):
        return True
    if max_score >= 8 and margin <= 2:
        return True
    if is_run_stopping_point(ev, score_a, score_b):
        return True

    return False


def is_deuce_state(score_a: int, score_b: int, target: int) -> bool:
    return score_a >= target - 1 and score_b >= target - 1 and abs(score_a - score_b) <= 1


def is_advantage_state(score_a: int, score_b: int, target: int) -> bool:
    return (
        score_a >= target
        and score_b >= target - 1
        and abs(score_a - score_b) == 1
    )


def is_game_point(score_a: int, score_b: int, target: int) -> bool:
    a_one_away = score_a >= target - 1 and (score_a - score_b) >= 1
    b_one_away = score_b >= target - 1 and (score_b - score_a) >= 1
    return a_one_away or b_one_away


def is_match_point(score_a: int, score_b: int, games_a: int, games_b: int, target: int, best_of: int) -> bool:
    if not best_of or best_of < 1:
        return False
    needed = best_of // 2 + 1
    a_one_away = games_a == needed - 1 and score_a >= target - 1 and (score_a - score_b) >= 1
    b_one_away = games_b == needed - 1 and score_b >= target - 1 and (score_b - score_a) >= 1
    return a_one_away or b_one_away


def is_run_stopping_point(ev: Any, score_a: int, score_b: int) -> bool:
    """Return True if the opponent had a run of >= 4 points and this point ends it."""
    if hasattr(ev, "scorer_side"):
        scorer = ev.scorer_side
    else:
        scorer = ev.get("scorer_side", "")
    if not scorer:
        return False

    before_score = score_a if scorer == "A" else score_b
    opponent_score = score_b if scorer == "A" else score_a
    return before_score >= 4 and opponent_score == 0


def compute_pressure_summary(point_events: list, game_target: int, win_by: int = 2) -> Dict[str, Any]:
    """Aggregate pressure statistics from a sequence of point events."""
    total_pressure = 0
    pressure_won_a = 0
    pressure_won_b = 0
    game_points_converted_a = 0
    game_points_converted_b = 0
    game_points_faced_a = 0
    game_points_faced_b = 0
    match_points_faced_a = 0
    match_points_faced_b = 0
    deuce_points_played = 0
    warnings: List[str] = []

    for ev in point_events:
        if not is_pressure_point(ev, game_target, win_by):
            continue

        total_pressure += 1

        if hasattr(ev, "scorer_side"):
            scorer = ev.scorer_side
        else:
            scorer = ev.get("scorer_side", "")

        if scorer == "A":
            pressure_won_a += 1
        else:
            pressure_won_b += 1

        score_a = ev.score_a_after if hasattr(ev, "score_a_after") else int(ev.get("score_a_after", 0))
        score_b = ev.score_b_after if hasattr(ev, "score_b_after") else int(ev.get("score_b_after", 0))

        if is_deuce_state(score_a, score_b, game_target):
            deuce_points_played += 1

        prev_score_a = ev.score_a_before if hasattr(ev, "score_a_before") else int(ev.get("score_a_before", 0) or 0)
        prev_score_b = ev.score_b_before if hasattr(ev, "score_b_before") else int(ev.get("score_b_before", 0) or 0)
        prev_games_a = ev.games_a_before if hasattr(ev, "games_a_before") else int(ev.get("games_a_before", 0) or 0)
        prev_games_b = ev.games_b_before if hasattr(ev, "games_b_before") else int(ev.get("games_b_before", 0) or 0)
        best_of = ev.best_of if hasattr(ev, "best_of") else int(ev.get("best_of", 0) or 0)

        if is_game_point(prev_score_a, prev_score_b, game_target):
            if scorer == "A":
                game_points_converted_a += 1
                game_points_faced_a += 1
            else:
                game_points_converted_b += 1
                game_points_faced_b += 1

        if is_match_point(prev_score_a, prev_score_b, prev_games_a, prev_games_b, game_target, best_of):
            if scorer == "A":
                match_points_faced_a += 1
            else:
                match_points_faced_b += 1

    if total_pressure < 3:
        warnings.append("Fewer than 3 pressure points detected; pressure index may be unreliable.")

    return {
        "total_pressure_points": total_pressure,
        "pressure_points_won_a": pressure_won_a,
        "pressure_points_won_b": pressure_won_b,
        "game_points_converted_a": game_points_converted_a,
        "game_points_converted_b": game_points_converted_b,
        "game_points_faced_a": game_points_faced_a,
        "game_points_faced_b": game_points_faced_b,
        "match_points_faced_a": match_points_faced_a,
        "match_points_faced_b": match_points_faced_b,
        "deuce_points_played": deuce_points_played,
        "warnings": warnings,
    }
