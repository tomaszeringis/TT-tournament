"""
Match Event Service

Records and retrieves match events for AI-grounded reporting.
Distinct from VoiceEvent; tracks score changes, timeouts, and other
deterministic match milestones.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player


def record_match_event(
    db: Session,
    match_id: int,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor: str = "system",
) -> Dict[str, Any]:
    """
    Record a deterministic match event.

    Args:
        db: Database session
        match_id: The match id
        event_type: Event type (e.g., score_update, timeout, start, complete)
        payload: Optional structured payload
        actor: Who recorded the event

    Returns:
        Dict with event details
    """
    event = {
        "match_id": match_id,
        "event_type": event_type,
        "payload": payload or {},
        "actor": actor,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return event


def get_match_events(
    db: Session,
    match_id: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Retrieve recorded match events for a match.

    Note: In the current implementation, events are not persisted to a
    separate table; this returns a derived view from Match history.
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return []

    events = []
    if match.started_at:
        events.append({
            "event_type": "start",
            "created_at": match.started_at.isoformat(),
            "payload": {},
        })
    if match.completed_at:
        events.append({
            "event_type": "complete",
            "created_at": match.completed_at.isoformat(),
            "payload": {"score": match.score, "winner": match.winner},
        })
    if match.score:
        events.append({
            "event_type": "score_update",
            "created_at": (match.completed_at or match.updated_at).isoformat() if match.completed_at or match.updated_at else None,
            "payload": {"score": match.score},
        })
    return events[:limit]


def generate_match_summary(
    db: Session,
    match_id: int,
) -> Dict[str, Any]:
    """
    Generate a structured match summary grounded in match events.

    Returns:
        Dict with match summary suitable for AI report generation.
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"error": "Match not found"}

    events = get_match_events(db, match_id=match_id)
    player1 = db.query(Player).filter(Player.id == match.player1_id).first() if match.player1_id else None
    player2 = db.query(Player).filter(Player.id == match.player2_id).first() if match.player2_id else None
    winner = db.query(Player).filter(Player.id == match.winner_id).first() if match.winner_id else None

    return {
        "match_id": match.id,
        "status": match.status.value if match.status else "pending",
        "call_status": match.call_status or "not_called",
        "player1": {
            "name": match.player1,
            "rating": player1.rating if player1 else None,
        },
        "player2": {
            "name": match.player2,
            "rating": player2.rating if player2 else None,
        },
        "score": match.score,
        "winner": {
            "name": match.winner,
            "rating": winner.rating if winner else None,
        } if winner else None,
        "events": events,
        "summary": _build_summary_text(match, events),
    }


def _build_summary_text(match: Match, events: List[Dict[str, Any]]) -> str:
    """Build a human-readable summary from match data and events."""
    parts = []
    if match.status == MatchStatus.completed and match.winner:
        parts.append(f"{match.winner} won against {match.player1 if match.winner == match.player2 else match.player2}")
    if match.score:
        parts.append(f"Score: {match.score}")
    if match.location:
        parts.append(f"Table: {match.location}")
    return ". ".join(parts) if parts else "Match has not started yet."
