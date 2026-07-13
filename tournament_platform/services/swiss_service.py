"""
Swiss Service - Result-driven Swiss round generation.

Generates Swiss rounds on-demand based on actual match results,
replacing the current all-at-once generation with random tie-break.
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player, Tournament


def get_swiss_standings(db: Session, tournament_id: int) -> List[Dict[str, Any]]:
    """
    Calculate current Swiss standings from completed matches.

    Returns:
        List of player records sorted by: wins desc, matches_played asc, name asc
    """
    matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.status == MatchStatus.completed,
    ).all()

    players = db.query(Player).filter(
        Player.id.in_([
            m.player1_id for m in matches if m.player1_id
        ] + [
            m.player2_id for m in matches if m.player2_id
        ])
    ).all()
    player_names = {p.id: p.name for p in players}

    stats = {}
    for m in matches:
        for pid, name in [(m.player1_id, m.player1), (m.player2_id, m.player2)]:
            if not pid:
                continue
            if pid not in stats:
                stats[pid] = {
                    "player_id": pid,
                    "name": name or player_names.get(pid, f"Player {pid}"),
                    "wins": 0,
                    "losses": 0,
                    "matches_played": 0,
                }
            stats[pid]["matches_played"] += 1
            if m.winner_id == pid:
                stats[pid]["wins"] += 1
            else:
                stats[pid]["losses"] += 1

    standings = sorted(
        stats.values(),
        key=lambda s: (-s["wins"], s["matches_played"], s["name"]),
    )
    return standings


def get_next_swiss_round(
    db: Session,
    tournament_id: int,
    current_round: int,
) -> Dict[str, Any]:
    """
    Generate pairings for the next Swiss round based on current standings.

    Args:
        db: Database session
        tournament_id: Tournament ID
        current_round: The round number being generated

    Returns:
        Dict with pairings and any issues
    """
    standings = get_swiss_standings(db, tournament_id=current_round)
    if not standings:
        return {"error": "No players found"}

    # Check if previous round is complete
    prev_matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.round_number == current_round - 1,
    ).all()
    if prev_matches and any(m.status != MatchStatus.completed for m in prev_matches):
        return {"error": "Previous round is not complete"}

    active_matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.round_number == current_round,
        Match.status.in_([MatchStatus.pending, MatchStatus.active]),
    ).all()
    if active_matches:
        return {"error": f"Round {current_round} already has active/pending matches"}

    # Pair players with similar records who haven't played each other
    player_names = [s["name"] for s in standings]
    played_pairs = set()
    for m in db.query(Match).filter(Match.tournament_id == tournament_id).all():
        if m.player1 and m.player2:
            played_pairs.add(tuple(sorted([m.player1, m.player2])))

    pairings = []
    used = set()
    for i, p1 in enumerate(player_names):
        if p1 in used:
            continue
        for j in range(i + 1, len(player_names)):
            p2 = player_names[j]
            if p2 in used:
                continue
            if tuple(sorted([p1, p2])) in played_pairs:
                continue
            s1 = next(s for s in standings if s["name"] == p1)
            s2 = next(s for s in standings if s["name"] == p2)
            if abs(s1["wins"] - s2["wins"]) <= 1:
                pairings.append({"player1": p1, "player2": p2})
                used.add(p1)
                used.add(p2)
                break

    return {
        "round": current_round,
        "pairings": pairings,
        "unpaired": [n for n in player_names if n not in used],
    }
