"""
Read-model helpers for public and operator screens.

Pure database helper functions - no Streamlit imports.
All functions are deterministic and read-only.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.orm import Session

from tournament_platform.models import (
    Tournament, Match, MatchStatus, Player, VenueTable
)


# ============================================================================
# 1. list_tournaments
# ============================================================================

def list_tournaments(db: Session) -> List[Dict[str, Any]]:
    """
    Return all tournaments with basic info.
    
    Returns:
        List of dicts with id, name, description, tournament_type, created_at
    """
    tournaments = db.query(Tournament).order_by(Tournament.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "tournament_type": t.tournament_type.value if t.tournament_type else "knockout",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tournaments
    ]


# ============================================================================
# 2. get_public_schedule
# ============================================================================

def get_public_schedule(
    db: Session,
    tournament_id: Optional[int] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Return upcoming, active, delayed, and recently completed matches.
    
    Each match dict includes display_label and sort_key for UI rendering.
    
    Args:
        db: Database session
        tournament_id: Optional filter for specific tournament
        limit: Maximum number of matches to return
        
    Returns:
        List of match dicts with all required fields
    """
    query = db.query(Match)
    
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)
    
    # Get matches with relevant statuses
    matches = query.order_by(Match.scheduled_time.asc()).limit(limit).all()
    
    result = []
    for m in matches:
        # Get tournament name via join
        tournament_name = None
        if m.tournament:
            tournament_name = m.tournament.name
        
        # Build display label
        label_parts = []
        if m.round_number is not None:
            label_parts.append(f"Round {m.round_number}")
        if m.location:
            label_parts.append(f"Table {m.location}")
        display_label = " · ".join(label_parts) if label_parts else "Match"
        
        # Build sort key: prioritize by status, then time, then round
        status_priority = {
            "active": 0,
            "called": 1,
            "queued": 2,
            "delayed": 3,
            "pending": 4,
            "completed": 5,
        }.get(m.call_status or "pending", 4)
        
        sort_key = (
            status_priority,
            m.scheduled_time or datetime.min,
            m.round_number or 0,
            m.bracket_index or 0,
            m.id,
        )
        
        result.append({
            "id": m.id,
            "tournament_id": m.tournament_id,
            "tournament_name": tournament_name,
            "player1": m.player1,
            "player2": m.player2,
            "winner": m.winner,
            "score": m.score,
            "status": m.status.value if m.status else "pending",
            "call_status": m.call_status or "not_called",
            "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None,
            "location": m.location,
            "round_number": m.round_number,
            "bracket_index": m.bracket_index,
            "display_label": display_label,
            "sort_key": sort_key,
        })
    
    # Sort by the computed sort_key
    result.sort(key=lambda x: x["sort_key"])
    
    # Remove sort_key from output (it's for internal use only)
    for m in result:
        del m["sort_key"]
    
    return result


# ============================================================================
# 3. get_public_rankings
# ============================================================================

def get_public_rankings(
    db: Session,
    tournament_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Return players sorted by rating descending.
    
    If tournament_id is provided, compute wins/losses from that tournament's matches.
    
    Args:
        db: Database session
        tournament_id: Optional filter for specific tournament
        
    Returns:
        List of player dicts with ranking stats
    """
    # Get all players
    players = db.query(Player).order_by(Player.rating.desc()).all()
    
    # Get match data for wins/losses
    match_query = db.query(Match)
    if tournament_id is not None:
        match_query = match_query.filter(Match.tournament_id == tournament_id)
    
    matches = match_query.filter(Match.status == MatchStatus.completed).all()
    
    # Build stats per player
    player_stats: Dict[int, Dict[str, int]] = {}
    for p in players:
        player_stats[p.id] = {"wins": 0, "losses": 0, "matches": 0}
    
    for m in matches:
        # Find player IDs for this match
        p1_id = m.player1_id
        p2_id = m.player2_id
        winner_id = m.winner_id
        
        if p1_id and p1_id in player_stats:
            player_stats[p1_id]["matches"] += 1
            if winner_id == p1_id:
                player_stats[p1_id]["wins"] += 1
            else:
                player_stats[p1_id]["losses"] += 1
        
        if p2_id and p2_id in player_stats:
            player_stats[p2_id]["matches"] += 1
            if winner_id == p2_id:
                player_stats[p2_id]["wins"] += 1
            else:
                player_stats[p2_id]["losses"] += 1
    
    # Build result
    result = []
    for p in players:
        stats = player_stats.get(p.id, {"wins": 0, "losses": 0, "matches": 0})
        win_rate = (stats["wins"] / stats["matches"] * 100) if stats["matches"] > 0 else 0.0
        
        result.append({
            "player_id": p.id,
            "name": p.name,
            "rating": p.rating,
            "matches_played": stats["matches"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(win_rate, 1),
        })
    
    return result


# ============================================================================
# 4. get_operator_queue
# ============================================================================

def get_operator_queue(
    db: Session,
    tournament_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Return pending/queued/called/active/delayed/completed matches sorted by scheduled time and round.
    
    Includes conflict flags for same table overlapping matches.
    
    Args:
        db: Database session
        tournament_id: Optional filter for specific tournament
        
    Returns:
        List of match dicts with conflict flags
    """
    # Get active/called matches first to check for conflicts
    # These are matches that are currently in progress
    active_matches = {}
    for m in db.query(Match).filter(
        Match.call_status.in_(["active", "called"])
    ).all():
        if m.location:
            active_matches[m.location] = m
    
    # Get queue matches (including completed for context)
    query = db.query(Match).filter(
        Match.call_status.in_(["not_called", "queued", "pending", "called", "active", "delayed", "completed"])
    )
    
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)
    
    matches = query.order_by(Match.scheduled_time.asc(), Match.round_number.asc()).all()
    
    result = []
    for m in matches:
        # Check for conflicts
        conflict_flags = []
        
        # Same table and overlapping active/called match (different match)
        if m.location and m.location in active_matches:
            other = active_matches[m.location]
            if other.id != m.id:
                conflict_flags.append("table_conflict")
        
        # Missing table
        if not m.location:
            conflict_flags.append("missing_table")
        
        # Missing scheduled time
        if not m.scheduled_time:
            conflict_flags.append("missing_scheduled_time")
        
        result.append({
            "id": m.id,
            "tournament_id": m.tournament_id,
            "player1": m.player1,
            "player2": m.player2,
            "status": m.status.value if m.status else "pending",
            "call_status": m.call_status or "not_called",
            "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None,
            "location": m.location,
            "round_number": m.round_number,
            "bracket_index": m.bracket_index,
            "operator_note": m.operator_note,
            "conflict_flags": conflict_flags,
        })
    
    return result


# ============================================================================
# 5. get_table_status
# ============================================================================

def get_table_status(
    db: Session,
    tournament_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Return each VenueTable and its current/next match.

    Includes is_active and a clear status string:
    - "busy" - table is active and has an active/called match
    - "available" - table is active and has no active/called match
    - "inactive" - table is not active

    Args:
        db: Database session
        tournament_id: Optional filter for specific tournament

    Returns:
        List of table status dicts
    """
    # Get ALL tables, not just active ones
    tables = db.query(VenueTable).order_by(VenueTable.name.asc()).all()

    result = []
    for table in tables:
        # Find current match (active/called) at this table
        current_match = None
        next_match = None

        query = db.query(Match).filter(Match.location == table.name)
        if tournament_id is not None:
            query = query.filter(Match.tournament_id == tournament_id)

        # Get all matches at this table
        table_matches = query.order_by(Match.scheduled_time.asc()).all()

        for m in table_matches:
            if m.call_status in ["active", "called"]:
                if current_match is None:
                    current_match = m
            elif m.call_status in ["not_called", "queued", "pending", "delayed"]:
                if next_match is None:
                    next_match = m

        # Determine status string
        is_active = bool(table.is_active)
        has_active_match = current_match is not None

        if not is_active:
            status = "inactive"
        elif has_active_match:
            status = "busy"
        else:
            status = "available"

        result.append({
            "table_id": table.id,
            "table_name": table.name,
            "is_active": is_active,
            "status": status,
            "notes": table.notes,
            "current_match": {
                "id": current_match.id,
                "player1": current_match.player1,
                "player2": current_match.player2,
                "status": current_match.status.value if current_match.status else "pending",
            } if current_match else None,
            "next_match": {
                "id": next_match.id,
                "player1": next_match.player1,
                "player2": next_match.player2,
                "scheduled_time": next_match.scheduled_time.isoformat() if next_match.scheduled_time else None,
            } if next_match else None,
        })

    return result


# ============================================================================
# 6. get_next_available_table
# ============================================================================

def get_next_available_table(
    db: Session,
    tournament_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Return the next available table.
    
    Heuristic:
    - Prefer active VenueTable with no active/called match
    - Otherwise return the table whose active/called match has the oldest scheduled_time
    
    Args:
        db: Database session
        tournament_id: Optional filter for specific tournament
        
    Returns:
        Table dict with availability info, or None
    """
    tables = db.query(VenueTable).filter(VenueTable.is_active == 1).all()
    
    if not tables:
        return None
    
    # Get active/called matches
    query = db.query(Match).filter(Match.call_status.in_(["active", "called"]))
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)
    
    active_matches = query.all()
    
    # Build table -> match mapping
    table_to_match = {}
    for m in active_matches:
        if m.location:
            table_to_match[m.location] = m
    
    # Find free tables
    free_tables = [t for t in tables if t.name not in table_to_match]
    
    if free_tables:
        # Return first free table
        table = free_tables[0]
        return {
            "table_id": table.id,
            "table_name": table.name,
            "notes": table.notes,
            "status": "free",
        }
    
    # All tables busy - find the one with oldest match
    if table_to_match:
        oldest_table_name = None
        oldest_time = None
        
        for table_name, match in table_to_match.items():
            if match.scheduled_time:
                if oldest_time is None or match.scheduled_time < oldest_time:
                    oldest_time = match.scheduled_time
                    oldest_table_name = table_name
        
        if oldest_table_name:
            table = next(t for t in tables if t.name == oldest_table_name)
            return {
                "table_id": table.id,
                "table_name": table.name,
                "notes": table.notes,
                "status": "busy",
                "oldest_match_scheduled": oldest_time.isoformat() if oldest_time else None,
            }
    
    return None


# ============================================================================
# 7. get_player_path
# ============================================================================

def get_player_path(
    db: Session,
    player_name: str,
    tournament_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get a player's path through a tournament bracket.
    
    For knockout: uses round_number, bracket_index, next_match_id
    For round-robin or incomplete data: falls back to chronological matches
    
    Args:
        db: Database session
        player_name: Name of the player
        tournament_id: Optional filter for specific tournament
        
    Returns:
        Dict with completed_matches, next_pending_match, projected_path
    """
    query = db.query(Match)
    
    if tournament_id is not None:
        query = query.filter(Match.tournament_id == tournament_id)
    
    # Get all matches involving this player
    matches = query.filter(
        (Match.player1 == player_name) | (Match.player2 == player_name)
    ).order_by(Match.scheduled_time.asc()).all()
    
    completed_matches = []
    next_pending_match = None
    projected_path = []
    
    for m in matches:
        match_info = {
            "id": m.id,
            "player1": m.player1,
            "player2": m.player2,
            "winner": m.winner,
            "score": m.score,
            "status": m.status.value if m.status else "pending",
            "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None,
            "round_number": m.round_number,
            "bracket_index": m.bracket_index,
        }
        
        if m.status == MatchStatus.completed:
            completed_matches.append(match_info)
        elif m.status == MatchStatus.pending and next_pending_match is None:
            next_pending_match = match_info
        
        # Build projected path using next_match_id
        if m.next_match_id:
            next_m = db.query(Match).filter(Match.id == m.next_match_id).first()
            if next_m:
                projected_path.append({
                    "match_id": next_m.id,
                    "round_number": next_m.round_number,
                    "player1": next_m.player1,
                    "player2": next_m.player2,
                })
    
    return {
        "player_name": player_name,
        "completed_matches": completed_matches,
        "next_pending_match": next_pending_match,
        "projected_path": projected_path,
    }