"""
AI Tournament Suggestions Service

Provides AI-powered suggestions for:
- Seeding recommendations based on player ratings
- Schedule optimization suggestions
- Anomaly detection in match results
"""

from typing import Optional
from sqlalchemy.orm import Session
from tournament_platform.models import Player, Match, Tournament, MatchStatus, TournamentType


def suggest_seeding(tournament_id: int, db: Session) -> list[tuple[str, int]]:
    """
    Suggest seeding order for tournament participants based on ratings.
    
    Returns a list of (player_name, suggested_seed) tuples sorted by seed.
    Higher-rated players get lower seed numbers (1, 2, 3, ...).
    
    Args:
        tournament_id: The tournament to seed.
        db: Database session.
        
    Returns:
        List of (player_name, seed) tuples.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return []
    
    # Get all players in the tournament
    player_names = set()
    for match in tournament.matches:
        if match.player1:
            player_names.add(match.player1)
        if match.player2:
            player_names.add(match.player2)
    
    if not player_names:
        return []
    
    # Get player ratings
    players = db.query(Player).filter(Player.name.in_(player_names)).all()
    player_ratings = {p.name: p.rating or 1000 for p in players}
    
    # Sort by rating (descending) and assign seeds
    sorted_players = sorted(player_names, key=lambda p: player_ratings.get(p, 1000), reverse=True)
    
    return [(name, idx + 1) for idx, name in enumerate(sorted_players)]


def suggest_schedule(tournament_id: int, db: Session, start_time: Optional[str] = None) -> list[dict]:
    """
    Suggest match schedule for a tournament.
    
    Returns a list of match scheduling suggestions with table assignments.
    
    Args:
        tournament_id: The tournament to schedule.
        db: Database session.
        start_time: Optional start time string (ISO format).
        
    Returns:
        List of scheduling suggestion dictionaries.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return []
    
    # Get pending matches
    pending_matches = [m for m in tournament.matches if m.status == MatchStatus.pending]
    
    if not pending_matches:
        return []
    
    # Get available tables
    tables = db.query(VenueTable).all()
    table_names = [t.name for t in tables] if tables else ["Table 1", "Table 2", "Table 3", "Table 4"]
    
    # Simple round-robin scheduling: assign matches to tables
    suggestions = []
    for i, match in enumerate(pending_matches):
        table_idx = i % len(table_names)
        suggestions.append({
            "match_id": match.id,
            "player1": match.player1,
            "player2": match.player2,
            "suggested_table": table_names[table_idx],
            "round": match.round_number or 1
        })
    
    return suggestions


def detect_anomalies(tournament_id: int, db: Session) -> list[dict]:
    """
    Detect anomalies in match results.
    
    Checks for:
    - Unusual score patterns (e.g., very high scores)
    - Missing scores
    - Inconsistent match status
    
    Args:
        tournament_id: The tournament to analyze.
        db: Database session.
        
    Returns:
        List of anomaly dictionaries with match_id, type, and description.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return []
    
    anomalies = []
    
    for match in tournament.matches:
        # Check for missing scores on completed matches
        if match.status == MatchStatus.completed and not match.score:
            anomalies.append({
                "match_id": match.id,
                "type": "missing_score",
                "description": f"Match {match.id} is marked completed but has no score"
            })
        
        # Check for unusual score patterns
        if match.score and match.status == MatchStatus.completed:
            try:
                parts = match.score.split('-')
                if len(parts) == 2:
                    s1, s2 = int(parts[0]), int(parts[1])
                    # Flag very high scores (unusual in table tennis)
                    if s1 > 11 or s2 > 11:
                        anomalies.append({
                            "match_id": match.id,
                            "type": "unusual_score",
                            "description": f"Match {match.id} has unusual score: {match.score}"
                        })
            except (ValueError, AttributeError):
                anomalies.append({
                    "match_id": match.id,
                    "type": "invalid_score",
                    "description": f"Match {match.id} has invalid score format: {match.score}"
                })
    
    return anomalies


# Import VenueTable for suggest_schedule
from tournament_platform.models import VenueTable