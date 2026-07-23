"""
Awards Service — Derive awards from completed match data.

All awards are computed from existing `completed_at`, `game_scores`, `score`,
`winner`, `tournament_id`, and optional `player.rating`. No new tables required.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player, Tournament


def get_awards(db: Session, tournament_id: int) -> Dict[str, Any]:
    """
    Compute tournament awards from completed matches.

    Returns:
        Dict with award categories and winners. Missing data falls back gracefully.
    """
    matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.status == MatchStatus.completed,
    ).all()

    if not matches:
        return {
            "champion": None,
            "runner_up": None,
            "closest_match": None,
            "biggest_comeback": None,
            "most_dominant_win": None,
            "longest_match": None,
            "best_decider": None,
            "fastest_win": None,
            "upset_of_the_day": None,
            "most_active_player": None,
        }

    # Enrich matches with player ratings
    players = {p.id: p for p in db.query(Player).all()}
    enriched = []
    for m in matches:
        p1_rating = players[m.player1_id].rating if m.player1_id and m.player1_id in players else None
        p2_rating = players[m.player2_id].rating if m.player2_id and m.player2_id in players else None
        enriched.append({
            "match": m,
            "p1_rating": p1_rating,
            "p2_rating": p2_rating,
            "game_scores": _parse_game_scores(m.game_scores),
            "winner": m.winner,
            "final_score": m.score,
            "completed_at": m.completed_at,
            "started_at": m.started_at,
        })

    # Champion / Runner-up (last completed match if knockout, otherwise first completed)
    # For simplicity, champion = winner of most recently completed match
    latest = max(matches, key=lambda m: m.completed_at or datetime.min)
    champion = latest.winner
    runner_up = (latest.player2 if latest.winner == latest.player1 else latest.player1)

    # Closest match (smallest point differential in final game or overall)
    closest = _find_closest_match(enriched)

    # Biggest comeback (largest deficit overcome in final game)
    biggest_comeback = _find_biggest_comeback(enriched)

    # Most dominant win (largest game margin)
    most_dominant = _find_most_dominant(enriched)

    # Longest match (from started_at to completed_at)
    longest = _find_longest_match(enriched)

    # Best decider (match went to final game with deuce)
    best_decider = _find_best_decider(enriched)

    # Fastest win (minimum duration)
    fastest = _find_fastest_win(enriched)

    # Upset of the day (winner rating > loser rating by threshold)
    upset = _find_upset(enriched)

    # Most active player (most matches completed)
    most_active = _find_most_active_player(matches)

    return {
        "champion": champion,
        "runner_up": runner_up,
        "closest_match": closest,
        "biggest_comeback": biggest_comeback,
        "most_dominant_win": most_dominant,
        "longest_match": longest,
        "best_decider": best_decider,
        "fastest_win": fastest,
        "upset_of_the_day": upset,
        "most_active_player": most_active,
    }


# ============================================================================
# Award calculators
# ============================================================================

def _parse_game_scores(game_scores: Optional[str]) -> List[tuple]:
    if not game_scores:
        return []
    results = []
    for part in game_scores.split(","):
        part = part.strip()
        try:
            p1, p2 = part.split("-")
            results.append((int(p1.strip()), int(p2.strip())))
        except (ValueError, AttributeError):
            continue
    return results


def _find_closest_match(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_margin = float("inf")
    for item in enriched:
        scores = item["game_scores"]
        if not scores:
            continue
        last_p1, last_p2 = scores[-1]
        margin = abs(last_p1 - last_p2)
        if margin < best_margin:
            best_margin = margin
            best = item
    if best:
        return {
            "player1": best["match"].player1,
            "player2": best["match"].player2,
            "winner": best["match"].winner,
            "score": best["match"].score,
            "margin": best_margin,
        }
    return None


def _find_biggest_comeback(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_deficit = 0
    for item in enriched:
        scores = item["game_scores"]
        if not scores:
            continue
        p1, p2 = scores[-1]
        winner = item["match"].winner
        p1_name = item["match"].player1
        p2_name = item["match"].player2
        if winner == p1_name:
            deficit = p2 - p1
            if deficit > best_deficit:
                best_deficit = deficit
                best = {
                    "winner": winner,
                    "loser": p2_name,
                    "score": item["match"].score,
                    "deficit": deficit,
                }
        else:
            deficit = p1 - p2
            if deficit > best_deficit:
                best_deficit = deficit
                best = {
                    "winner": winner,
                    "loser": p1_name,
                    "score": item["match"].score,
                    "deficit": deficit,
                }
    return best


def _find_most_dominant(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_margin = -1
    for item in enriched:
        scores = item["game_scores"]
        if not scores:
            continue
        max_margin = max(abs(p1 - p2) for p1, p2 in scores)
        if max_margin > best_margin:
            best_margin = max_margin
            best = {
                "winner": item["match"].winner,
                "loser": item["match"].player2 if item["match"].winner == item["match"].player1 else item["match"].player1,
                "score": item["match"].score,
                "max_margin": max_margin,
            }
    return best


def _find_longest_match(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_duration = None
    for item in enriched:
        started = item.get("started_at")
        completed = item.get("completed_at")
        if started and completed:
            duration = (completed - started).total_seconds()
            if best_duration is None or duration > best_duration:
                best_duration = duration
                best = {
                    "player1": item["match"].player1,
                    "player2": item["match"].player2,
                    "winner": item["match"].winner,
                    "score": item["match"].score,
                    "duration_seconds": int(duration),
                }
    return best


def _find_best_decider(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_deuce_count = -1
    for item in enriched:
        scores = item["game_scores"]
        if not scores:
            continue
        deuce_games = sum(1 for p1, p2 in scores if p1 >= 10 and p2 >= 10)
        if deuce_games > best_deuce_count:
            best_deuce_count = deuce_games
            best = {
                "player1": item["match"].player1,
                "player2": item["match"].player2,
                "winner": item["match"].winner,
                "score": item["match"].score,
                "deuce_games": deuce_games,
            }
    return best


def _find_fastest_win(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_duration = None
    for item in enriched:
        started = item.get("started_at")
        completed = item.get("completed_at")
        if started and completed:
            duration = (completed - started).total_seconds()
            if best_duration is None or duration < best_duration:
                best_duration = duration
                best = {
                    "winner": item["match"].winner,
                    "loser": item["match"].player2 if item["match"].winner == item["match"].player1 else item["match"].player1,
                    "score": item["match"].score,
                    "duration_seconds": int(duration),
                }
    return best


def _find_upset(enriched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best = None
    best_rating_gap = 0
    for item in enriched:
        ratings = item.get("p1_rating"), item.get("p2_rating")
        if not all(ratings):
            continue
        winner = item["match"].winner
        p1_name = item["match"].player1
        p2_name = item["match"].player2
        if winner == p1_name and ratings[0] < ratings[1]:
            gap = ratings[1] - ratings[0]
            if gap > best_rating_gap:
                best_rating_gap = gap
                best = {
                    "winner": winner,
                    "loser": p2_name,
                    "score": item["match"].score,
                    "rating_gap": gap,
                }
        elif winner == p2_name and ratings[1] < ratings[0]:
            gap = ratings[0] - ratings[1]
            if gap > best_rating_gap:
                best_rating_gap = gap
                best = {
                    "winner": winner,
                    "loser": p1_name,
                    "score": item["match"].score,
                    "rating_gap": gap,
                }
    return best


def _find_most_active_player(matches: List[Match]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for m in matches:
        counts[m.player1] = counts.get(m.player1, 0) + 1
        counts[m.player2] = counts.get(m.player2, 0) + 1
    if counts:
        return max(counts, key=counts.get)
    return None
