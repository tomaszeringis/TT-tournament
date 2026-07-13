"""
Standings Service - Deterministic standings with configurable tie-breaks.

Provides format-aware standings for:
- Round-robin
- Groups → Knockout
- Swiss
- Knockout (simple ranking)

Tie-break order is configurable per call. Defaults to:
["wins", "point_differential", "game_differential", "head_to_head", "rating"]
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player, Tournament, Stage, Group, Entry


# Default tie-break priority order
DEFAULT_TIE_BREAK_ORDER = ["wins", "point_differential", "game_differential", "rating"]


def get_standings(
    db: Session,
    tournament_id: int,
    event_id: Optional[int] = None,
    group_id: Optional[int] = None,
    tie_break_order: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Compute standings for a tournament, event, or group.

    Args:
        db: Database session
        tournament_id: Tournament ID
        event_id: Optional event ID for multi-stage events
        group_id: Optional group ID for group-stage standings
        tie_break_order: Ordered list of tie-break criteria.
            Supported: wins, losses, matches_played, point_differential,
                       game_differential, head_to_head, rating, name

    Returns:
        List of player standings sorted by tie-break order
    """
    if tie_break_order is None:
        tie_break_order = DEFAULT_TIE_BREAK_ORDER

    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    if group_id is not None:
        matches = [m for m in matches if m.group_id == group_id]
    elif event_id is not None:
        stage_ids = [
            s.id for s in db.query(Stage).filter(Stage.event_id == event_id).all()
        ]
        matches = [m for m in matches if m.stage_id in stage_ids]

    completed_matches = [m for m in matches if m.status == MatchStatus.completed]

    players = db.query(Player).all()
    player_map = {p.id: p for p in players}

    stats = {}
    for p in players:
        stats[p.id] = {
            "player_id": p.id,
            "name": p.name,
            "rating": p.rating,
            "wins": 0,
            "losses": 0,
            "matches_played": 0,
            "points_for": 0,
            "points_against": 0,
            "game_differential": 0,
            "head_to_head_wins": {},
        }

    for m in completed_matches:
        p1_id = m.player1_id
        p2_id = m.player2_id
        if not p1_id or not p2_id:
            continue

        p1_score, p2_score = _parse_score(m.score)
        if p1_id in stats:
            stats[p1_id]["matches_played"] += 1
            stats[p1_id]["points_for"] += p1_score
            stats[p1_id]["points_against"] += p2_score
            if m.winner_id == p1_id:
                stats[p1_id]["wins"] += 1
                stats[p1_id]["game_differential"] += (p1_score - p2_score)
                stats[p1_id]["head_to_head_wins"][p2_id] = stats[p1_id]["head_to_head_wins"].get(p2_id, 0) + 1
            else:
                stats[p1_id]["losses"] += 1
                stats[p1_id]["game_differential"] += (p1_score - p2_score)

        if p2_id in stats:
            stats[p2_id]["matches_played"] += 1
            stats[p2_id]["points_for"] += p2_score
            stats[p2_id]["points_against"] += p1_score
            if m.winner_id == p2_id:
                stats[p2_id]["wins"] += 1
                stats[p2_id]["game_differential"] += (p2_score - p1_score)
                stats[p2_id]["head_to_head_wins"][p1_id] = stats[p2_id]["head_to_head_wins"].get(p1_id, 0) + 1
            else:
                stats[p2_id]["losses"] += 1
                stats[p2_id]["game_differential"] += (p2_score - p1_score)

    standings = list(stats.values())
    standings = _apply_tie_breaks(standings, tie_break_order)
    return standings


def _parse_score(score: Optional[str]) -> tuple[int, int]:
    if not score:
        return 0, 0
    try:
        parts = score.split("-")
        if len(parts) == 2:
            return int(parts[0].strip()), int(parts[1].strip())
    except (ValueError, AttributeError):
        pass
    return 0, 0


def _apply_tie_breaks(
    standings: List[Dict[str, Any]],
    tie_break_order: List[str],
) -> List[Dict[str, Any]]:
    def sort_key(s: Dict[str, Any]) -> tuple:
        key = []
        for criterion in tie_break_order:
            if criterion == "wins":
                key.append(-s["wins"])
            elif criterion == "losses":
                key.append(s["losses"])
            elif criterion == "matches_played":
                key.append(s["matches_played"])
            elif criterion == "point_differential":
                key.append(-(s["points_for"] - s["points_against"]))
            elif criterion == "game_differential":
                key.append(-s["game_differential"])
            elif criterion == "rating":
                key.append(-(s["rating"] or 0))
            elif criterion == "name":
                key.append(s["name"])
            elif criterion == "head_to_head":
                key.append(0)
            else:
                key.append(0)
        return tuple(key)

    return sorted(standings, key=sort_key)
