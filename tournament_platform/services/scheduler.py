"""
Schedule Optimizer Service

Provides basic schedule generation and conflict detection for tournaments.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from tournament_platform.models import Match, VenueTable


def detect_conflicts(
    db: Session,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Tuple[Match, Match]]:
    """
    Detect overlapping matches in the schedule.
    
    Args:
        db: SQLAlchemy database session
        start_time: Optional start time filter
        end_time: Optional end time filter
        
    Returns:
        List of tuples containing conflicting match pairs
    """
    query = db.query(Match).filter(Match.status != "completed")
    
    if start_time:
        query = query.filter(Match.scheduled_time >= start_time)
    if end_time:
        query = query.filter(Match.scheduled_time <= end_time)
    
    matches = query.all()
    conflicts = []
    
    for i, m1 in enumerate(matches):
        for m2 in matches[i + 1:]:
            # Check if matches overlap in time
            if m1.scheduled_time and m2.scheduled_time:
                # Assume matches are 30 minutes by default
                m1_end = m1.scheduled_time + timedelta(minutes=30)
                m2_end = m2.scheduled_time + timedelta(minutes=30)
                
                if m1.scheduled_time < m2_end and m2.scheduled_time < m1_end:
                    # Check if they're on the same table (using location string)
                    if m1.location and m2.location and m1.location == m2.location:
                        conflicts.append((m1, m2))
    
    return conflicts


def get_next_available_table(
    db: Session,
    scheduled_time: datetime,
    duration_minutes: int = 30,
) -> Optional[VenueTable]:
    """
    Find the next available table for a given time slot.
    
    Args:
        db: SQLAlchemy database session
        scheduled_time: Desired start time
        duration_minutes: Match duration in minutes
        
    Returns:
        Available VenueTable or None if all tables are busy
    """
    tables = db.query(VenueTable).filter(VenueTable.is_active == 1).all()
    
    for table in tables:
        # Check if this table has any conflicts
        end_time = scheduled_time + timedelta(minutes=duration_minutes)
        
        conflicting = db.query(Match).filter(
            Match.location == table.name,
            Match.status != "completed",
            Match.scheduled_time < end_time,
        ).first()
        
        if not conflicting:
            return table
    
    return None


def generate_schedule(
    db: Session,
    matches: List[Match],
    start_time: datetime,
    table_names: Optional[List[str]] = None,
    match_duration: int = 30,
    break_duration: int = 10,
) -> List[Match]:
    """
    Generate a basic schedule for matches.
    
    Args:
        db: SQLAlchemy database session
        matches: List of matches to schedule
        start_time: Tournament start time
        table_names: Optional list of table names to use (all active tables if None)
        match_duration: Duration of each match in minutes
        break_duration: Break between matches in minutes
        
    Returns:
        List of matches with scheduled times
    """
    if table_names is None:
        tables = db.query(VenueTable).filter(VenueTable.is_active == 1).all()
        table_names = [t.name for t in tables]
    
    if not table_names:
        return []
    
    current_time = start_time
    table_next_available = {t: current_time for t in table_names}
    
    for match in matches:
        # Find the earliest available table
        earliest_table = min(table_names, key=lambda t: table_next_available[t])
        match.scheduled_time = table_next_available[earliest_table]
        match.location = earliest_table
        
        # Update when this table becomes available again
        table_next_available[earliest_table] = match.scheduled_time + timedelta(
            minutes=match_duration + break_duration
        )
    
    return matches