from typing import Any, Dict, List, Optional


def compute_momentum_summary(point_events: list, window: int = 5) -> Dict[str, Any]:
    """Compute rolling momentum, longest runs, lead changes, and biggest swings."""
    if not point_events:
        return {
            "longest_run_player": "",
            "longest_run": 0,
            "max_streak_a": 0,
            "max_streak_b": 0,
            "lead_changes": 0,
            "biggest_swing": 0.0,
            "turning_points": [],
        }

    scores_a = [0]
    scores_b = [0]
    scoring_sequence: List[str] = []

    for ev in point_events:
        scorer = ev.scorer_side if hasattr(ev, "scorer_side") else ev.get("scorer_side", "")
        scoring_sequence.append(scorer)
        sa = scores_a[-1] + (1 if scorer == "A" else 0)
        sb = scores_b[-1] + (1 if scorer == "B" else 0)
        scores_a.append(sa)
        scores_b.append(sb)

    longest_run_player, longest_run = _longest_run(scoring_sequence)
    max_streak_a, max_streak_b = _max_streaks(scoring_sequence)
    lead_changes = _count_lead_changes(scores_a, scores_b)
    biggest_swing, turning_points = _biggest_swing(scores_a, scores_b, len(point_events))

    return {
        "longest_run_player": longest_run_player,
        "longest_run": longest_run,
        "max_streak_a": max_streak_a,
        "max_streak_b": max_streak_b,
        "lead_changes": lead_changes,
        "biggest_swing": biggest_swing,
        "turning_points": turning_points,
    }


def _longest_run(sequence: List[str]) -> tuple:
    if not sequence:
        return "", 0
    best_player = sequence[0]
    best_count = 1
    cur_player = sequence[0]
    cur_count = 1
    for s in sequence[1:]:
        if s == cur_player:
            cur_count += 1
        else:
            if cur_count > best_count:
                best_count = cur_count
                best_player = cur_player
            cur_player = s
            cur_count = 1
    if cur_count > best_count:
        best_count = cur_count
        best_player = cur_player
    return best_player, best_count


def _max_streaks(sequence: List[str]) -> tuple:
    max_a = 0
    max_b = 0
    cur = None
    count = 0
    for s in sequence:
        if s == cur:
            count += 1
        else:
            if cur == "A":
                max_a = max(max_a, count)
            elif cur == "B":
                max_b = max(max_b, count)
            cur = s
            count = 1
    if cur == "A":
        max_a = max(max_a, count)
    elif cur == "B":
        max_b = max(max_b, count)
    return max_a, max_b


def _count_lead_changes(scores_a: List[int], scores_b: List[int]) -> int:
    changes = 0
    prev_leader = None
    for a, b in zip(scores_a, scores_b):
        if a > b:
            leader = "A"
        elif b > a:
            leader = "B"
        else:
            leader = None
        if leader is not None and prev_leader is not None and leader != prev_leader:
            changes += 1
        if leader is not None:
            prev_leader = leader
    return changes


def _biggest_swing(scores_a: List[int], scores_b: List[int], total_points: int) -> tuple:
    biggest_swing = 0.0
    turning_points: List[str] = []
    for i in range(1, len(scores_a)):
        prev_margin = scores_a[i - 1] - scores_b[i - 1]
        new_margin = scores_a[i] - scores_b[i]
        swing = abs(new_margin - prev_margin)
        if swing > biggest_swing:
            biggest_swing = float(swing)
            turning_points = []
            turning_points.append(f"Point {i}: {scores_a[i-1]}-{scores_b[i-1]} -> {scores_a[i]}-{scores_b[i]}")
        elif swing == biggest_swing:
            turning_points.append(f"Point {i}: {scores_a[i-1]}-{scores_b[i-1]} -> {scores_a[i]}-{scores_b[i]}")
    return biggest_swing, turning_points[:5]
