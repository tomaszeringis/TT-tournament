"""
Table Assignment Service

Provides smart table recommendations for matches based on:
- current table load
- active/called matches
- inactive but available tables
- round-robin distribution heuristics
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from tournament_platform.models import Match, VenueTable


def recommend_table(
    db: Session,
    match_id: int,
    tournament_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Recommend a table for a match.

    Args:
        db: Database session
        match_id: The match needing a table
        tournament_id: Optional tournament filter for busy-table context

    Returns:
        Dict with:
        - recommended_table: table name or None
        - reason: why this table was recommended
        - alternatives: list of alternative table names
        - busy_tables: list of currently busy table names
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {
            "recommended_table": None,
            "reason": "Match not found",
            "alternatives": [],
            "busy_tables": [],
        }

    busy_table_names = set()
    if tournament_id is not None:
        active_matches = db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.call_status.in_(["active", "called"]),
        ).all()
        busy_table_names = {m.location for m in active_matches if m.location}

    tables = db.query(VenueTable).order_by(VenueTable.name.asc()).all()
    inactive_tables = [t for t in tables if not t.is_active]
    active_available = [t for t in tables if t.is_active and t.name not in busy_table_names]

    if inactive_tables:
        recommended = inactive_tables[0].name
        reason = "Inactive table available"
        alternatives = [t.name for t in inactive_tables[1:]] + [t.name for t in active_available]
    elif active_available:
        recommended = active_available[0].name
        reason = "Least-loaded active table"
        alternatives = [t.name for t in active_available[1:]]
    else:
        recommended = None
        reason = "No tables available"
        alternatives = []

    return {
        "recommended_table": recommended,
        "reason": reason,
        "alternatives": alternatives[:3],
        "busy_tables": sorted(busy_table_names),
    }
