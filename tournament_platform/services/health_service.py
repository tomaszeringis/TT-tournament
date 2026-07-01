"""
Tournament Health Service - Compute tournament health metrics and detect issues.

This service provides deterministic analysis of tournament state including:
- Match counts by status
- Table utilization
- Detected issues (missing table, stale matches, etc.)
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, VenueTable, Tournament

logger = logging.getLogger(__name__)


# Default thresholds (can be overridden via settings)
DEFAULT_STALE_ACTIVE_MINUTES = 60  # Active match older than this is stale
DEFAULT_STALE_CALLED_MINUTES = 30   # Called match older than this is stale
DEFAULT_DELAYED_THRESHOLD_MINUTES = 15  # Delayed match threshold


def get_health_thresholds() -> Dict[str, int]:
    """
    Get health check thresholds from settings or defaults.
    
    Returns:
        Dict with stale_active_minutes, stale_called_minutes, delayed_threshold_minutes
    """
    # For now, use defaults. Can be extended to read from env/settings
    return {
        "stale_active_minutes": DEFAULT_STALE_ACTIVE_MINUTES,
        "stale_called_minutes": DEFAULT_STALE_CALLED_MINUTES,
        "delayed_threshold_minutes": DEFAULT_DELAYED_THRESHOLD_MINUTES,
    }


def get_tournament_health(
    db: Session,
    tournament_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compute tournament health including match counts, table utilization, and issues.
    
    Args:
        db: Database session
        tournament_id: Optional tournament filter
        
    Returns:
        Dict with:
        - tournament_id, tournament_name
        - match_counts: {active, called, delayed, completed, pending, queued, not_called}
        - table_utilization: {active_tables, total_tables, utilization_percent}
        - issues: List of detected issues
        - computed_at: ISO timestamp
    """
    thresholds = get_health_thresholds()
    now = datetime.now(timezone.utc)
    
    # Build match query
    match_query = db.query(Match)
    if tournament_id is not None:
        match_query = match_query.filter(Match.tournament_id == tournament_id)
    
    # Get all matches
    all_matches = match_query.all()
    
    # Count matches by call_status
    match_counts = {
        "active": 0,
        "called": 0,
        "delayed": 0,
        "completed": 0,
        "pending": 0,
        "queued": 0,
        "not_called": 0,
    }
    
    for m in all_matches:
        status = m.call_status or "not_called"
        if status in match_counts:
            match_counts[status] += 1
    
    # Get table utilization
    table_query = db.query(VenueTable)
    all_tables = table_query.all()
    active_tables = [t for t in all_tables if t.is_active]
    
    # Get busy tables (tables with active/called matches)
    busy_tables = set()
    for m in all_matches:
        if m.call_status in ["active", "called"] and m.location:
            busy_tables.add(m.location)
    
    table_utilization = {
        "active_tables": len(active_tables),
        "total_tables": len(all_tables),
        "busy_tables": len(busy_tables),
        "utilization_percent": round(len(busy_tables) / len(active_tables) * 100, 1) if active_tables else 0,
    }
    
    # Detect issues
    issues = []
    
    for m in all_matches:
        # Missing table
        if not m.location:
            issues.append({
                "issue_type": "missing_table",
                "match_id": m.id,
                "severity": "warning",
                "message": f"Match {m.id} ({m.player1} vs {m.player2}) has no table assigned",
                "details": {
                    "player1": m.player1,
                    "player2": m.player2,
                    "call_status": m.call_status,
                },
            })
        
        # Missing scheduled time
        if not m.scheduled_time:
            issues.append({
                "issue_type": "missing_scheduled_time",
                "match_id": m.id,
                "severity": "warning",
                "message": f"Match {m.id} has no scheduled time",
                "details": {
                    "player1": m.player1,
                    "player2": m.player2,
                },
            })
        
        # Stale active match
        if m.call_status == "active" and m.started_at:
            age_minutes = (now - m.started_at).total_seconds() / 60
            if age_minutes > thresholds["stale_active_minutes"]:
                issues.append({
                    "issue_type": "stale_active",
                    "match_id": m.id,
                    "severity": "error",
                    "message": f"Match {m.id} has been active for {int(age_minutes)} minutes",
                    "details": {
                        "age_minutes": int(age_minutes),
                        "threshold": thresholds["stale_active_minutes"],
                        "player1": m.player1,
                        "player2": m.player2,
                        "location": m.location,
                    },
                })
        
        # Stale called match
        if m.call_status == "called" and m.called_at:
            age_minutes = (now - m.called_at).total_seconds() / 60
            if age_minutes > thresholds["stale_called_minutes"]:
                issues.append({
                    "issue_type": "stale_called",
                    "match_id": m.id,
                    "severity": "warning",
                    "message": f"Match {m.id} has been called for {int(age_minutes)} minutes",
                    "details": {
                        "age_minutes": int(age_minutes),
                        "threshold": thresholds["stale_called_minutes"],
                        "player1": m.player1,
                        "player2": m.player2,
                    },
                })
        
        # Completed without score
        if m.call_status == "completed" and m.status == MatchStatus.completed:
            if not m.score:
                issues.append({
                    "issue_type": "completed_without_score",
                    "match_id": m.id,
                    "severity": "error",
                    "message": f"Match {m.id} is completed but has no score",
                    "details": {
                        "player1": m.player1,
                        "player2": m.player2,
                    },
                })
            
            # Completed without winner
            if not m.winner:
                issues.append({
                    "issue_type": "completed_without_winner",
                    "match_id": m.id,
                    "severity": "error",
                    "message": f"Match {m.id} is completed but has no winner",
                    "details": {
                        "player1": m.player1,
                        "player2": m.player2,
                        "score": m.score,
                    },
                })
        
        # Table conflicts (same table with multiple active/called matches)
        if m.location and m.call_status in ["active", "called"]:
            conflicting = [
                other for other in all_matches
                if other.location == m.location
                and other.call_status in ["active", "called"]
                and other.id != m.id
            ]
            for other in conflicting:
                issues.append({
                    "issue_type": "table_conflict",
                    "match_id": m.id,
                    "severity": "error",
                    "message": f"Table {m.location} has conflicting matches: {m.id} and {other.id}",
                    "details": {
                        "table": m.location,
                        "match1_id": m.id,
                        "match1_players": f"{m.player1} vs {m.player2}",
                        "match2_id": other.id,
                        "match2_players": f"{other.player1} vs {other.player2}",
                    },
                })
    
    # Get tournament name if filtered
    tournament_name = None
    if tournament_id is not None:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if tournament:
            tournament_name = tournament.name
    
    return {
        "tournament_id": tournament_id,
        "tournament_name": tournament_name,
        "match_counts": match_counts,
        "table_utilization": table_utilization,
        "issues": issues,
        "computed_at": now.isoformat(),
    }


def get_health_summary(db: Session, tournament_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get a simplified health summary for quick display.
    
    Returns:
        Dict with key metrics and issue counts
    """
    health = get_tournament_health(db, tournament_id=tournament_id)
    
    # Count issues by type
    issue_counts = {}
    for issue in health["issues"]:
        issue_type = issue["issue_type"]
        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
    
    return {
        "tournament_id": health["tournament_id"],
        "tournament_name": health["tournament_name"],
        "total_matches": sum(health["match_counts"].values()),
        "active_matches": health["match_counts"]["active"],
        "delayed_matches": health["match_counts"]["delayed"],
        "table_utilization": health["table_utilization"]["utilization_percent"],
        "issue_count": len(health["issues"]),
        "issue_counts": issue_counts,
        "issues": health["issues"],
    }