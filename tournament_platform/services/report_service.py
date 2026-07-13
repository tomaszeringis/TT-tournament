"""
Report Service - Structured event and match reports.

Provides printable/shareable summaries for tournaments, events, and matches.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tournament_platform.models import Tournament, Match, MatchStatus, Player


def get_event_report(
    db: Session,
    tournament_id: int,
) -> Dict[str, Any]:
    """
    Generate a structured event report for a tournament.

    Returns:
        Dict with tournament summary, match statistics, and recent results.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return {"error": "Tournament not found"}

    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    completed = [m for m in matches if m.status == MatchStatus.completed]
    active = [m for m in matches if m.status == MatchStatus.active]
    pending = [m for m in matches if m.status == MatchStatus.pending]

    total_matches = len(matches)
    completed_count = len(completed)
    active_count = len(active)
    pending_count = len(pending)

    players = set()
    for m in matches:
        if m.player1:
            players.add(m.player1)
        if m.player2:
            players.add(m.player2)

    recent_results = sorted(
        completed,
        key=lambda m: m.completed_at or m.scheduled_time or datetime.min,
        reverse=True,
    )[:10]

    return {
        "tournament": {
            "id": tournament.id,
            "name": tournament.name,
            "type": tournament.tournament_type.value if tournament.tournament_type else "knockout",
            "created_at": tournament.created_at.isoformat() if tournament.created_at else None,
        },
        "summary": {
            "total_matches": total_matches,
            "completed": completed_count,
            "active": active_count,
            "pending": pending_count,
            "player_count": len(players),
            "completion_rate": round(completed_count / total_matches * 100, 1) if total_matches else 0,
        },
        "recent_results": [
            {
                "id": m.id,
                "player1": m.player1,
                "player2": m.player2,
                "score": m.score,
                "winner": m.winner,
                "completed_at": m.completed_at.isoformat() if m.completed_at else None,
            }
            for m in recent_results
        ],
    }


def get_match_report(
    db: Session,
    match_id: int,
) -> Dict[str, Any]:
    """
    Generate a structured report for a single match.

    Returns:
        Dict with match details, participants, and result.
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"error": "Match not found"}

    player1 = db.query(Player).filter(Player.id == match.player1_id).first()
    player2 = db.query(Player).filter(Player.id == match.player2_id).first()
    winner = db.query(Player).filter(Player.id == match.winner_id).first() if match.winner_id else None

    return {
        "match": {
            "id": match.id,
            "tournament_id": match.tournament_id,
            "tournament_name": match.tournament.name if match.tournament else None,
            "status": match.status.value if match.status else "pending",
            "call_status": match.call_status or "not_called",
            "round_number": match.round_number,
            "bracket_index": match.bracket_index,
            "location": match.location,
            "scheduled_time": match.scheduled_time.isoformat() if match.scheduled_time else None,
            "started_at": match.started_at.isoformat() if match.started_at else None,
            "completed_at": match.completed_at.isoformat() if match.completed_at else None,
            "score": match.score,
            "game_scores": match.game_scores,
            "winner": match.winner,
            "winner_id": match.winner_id,
            "operator_note": match.operator_note,
        },
        "participants": {
            "player1": {
                "id": match.player1_id,
                "name": match.player1,
                "email": player1.email if player1 else None,
                "rating": player1.rating if player1 else None,
            },
            "player2": {
                "id": match.player2_id,
                "name": match.player2,
                "email": player2.email if player2 else None,
                "rating": player2.rating if player2 else None,
            },
            "winner": {
                "id": match.winner_id,
                "name": match.winner,
                "email": winner.email if winner else None,
            } if winner else None,
        },
    }
