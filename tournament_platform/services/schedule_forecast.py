"""
Schedule Forecast - Deterministic simulation of match start times.

This service provides:
- Table release time forecasting
- Next-call time prediction
- Bottleneck detection
- What-if scenario support
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, VenueTable

logger = logging.getLogger(__name__)


# Default match duration in minutes
DEFAULT_MATCH_DURATION_MINUTES = 15


def forecast_match_start_times(
    db: Session,
    tournament_id: Optional[int] = None,
    match_duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES,
) -> Dict[str, Any]:
    """
    Forecast when matches will start based on current table availability.
    
    Uses deterministic simulation:
    1. Get all queued/pending matches sorted by scheduled time
    2. Get all active/called matches to determine table availability
    3. Simulate match progression to predict next available times
    
    Args:
        db: Database session
        tournament_id: Optional tournament filter
        match_duration_minutes: Assumed match duration
        
    Returns:
        Dict with:
        - forecast: List of match forecasts
        - bottlenecks: List of potential bottlenecks
        - assumptions: What assumptions were made
    """
    now = datetime.now(timezone.utc)
    
    # Get matches
    match_query = db.query(Match)
    if tournament_id is not None:
        match_query = match_query.filter(Match.tournament_id == tournament_id)
    
    all_matches = match_query.all()
    
    # Get tables
    table_query = db.query(VenueTable)
    all_tables = table_query.all()
    active_tables = [t for t in all_tables if t.is_active]
    
    # Get queued/pending matches
    queued_matches = [
        m for m in all_matches
        if m.call_status in ["queued", "pending", "not_called"]
    ]
    
    # Get active/called matches
    active_matches = [
        m for m in all_matches
        if m.call_status in ["active", "called"]
    ]
    
    # Calculate table release times
    table_release_times = {}
    for table in active_tables:
        table_matches = [m for m in active_matches if m.location == table.name]
        if table_matches:
            # Find the match that will finish last
            latest_finish = now
            for m in table_matches:
                if m.started_at:
                    finish_time = m.started_at + timedelta(minutes=match_duration_minutes)
                    if finish_time > latest_finish:
                        latest_finish = finish_time
            table_release_times[table.name] = latest_finish
        else:
            table_release_times[table.name] = now
    
    # Generate forecasts
    forecasts = []
    for match in sorted(queued_matches, key=lambda m: m.scheduled_time or now):
        # Find earliest available table
        earliest_table = None
        earliest_time = now
        
        for table_name, release_time in table_release_times.items():
            if release_time < earliest_time:
                earliest_time = release_time
                earliest_table = table_name
        
        forecasts.append({
            "match_id": match.id,
            "player1": match.player1,
            "player2": match.player2,
            "scheduled_time": match.scheduled_time.isoformat() if match.scheduled_time else None,
            "predicted_start": earliest_time.isoformat() if earliest_table else None,
            "predicted_table": earliest_table,
            "delay_minutes": max(0, (earliest_time - (match.scheduled_time or now)).total_seconds() / 60) if match.scheduled_time else 0,
        })
    
    # Identify bottlenecks
    bottlenecks = []
    if len(active_tables) < len(queued_matches):
        bottlenecks.append({
            "type": "insufficient_tables",
            "message": f"Only {len(active_tables)} active tables for {len(queued_matches)} queued matches",
        })
    
    return {
        "forecast": forecasts,
        "bottlenecks": bottlenecks,
        "assumptions": {
            "match_duration_minutes": match_duration_minutes,
            "active_tables": len(active_tables),
            "queued_matches": len(queued_matches),
        },
    }