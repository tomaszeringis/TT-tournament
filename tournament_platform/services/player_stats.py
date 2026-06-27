"""Player statistics service with optimized aggregate queries."""

from sqlalchemy import func, case
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from tournament_platform.models import Player, Match


def get_player_statistics(db: Session) -> List[Dict[str, Any]]:
    """
    Get player statistics using a single aggregate query.
    
    This function computes total matches, wins, losses, and win rate for all players
    in a single database query, avoiding the N+1 query problem.
    
    Query Logic:
    - Uses LEFT JOIN to include players with zero matches
    - Uses conditional aggregation with CASE statements to count:
      - total_matches: matches where player is either player1 or player2
      - wins: matches where player is the winner
      - losses: matches where player participated but didn't win
    - Win rate is calculated as (wins / total_matches * 100)
    
    Args:
        db: SQLAlchemy database session
        
    Returns:
        List of dictionaries with player statistics:
        - ID: Player ID
        - Name: Player name
        - Email: Player email
        - Rating: Player rating
        - Matches: Total number of matches played
        - Wins: Number of matches won
        - Losses: Number of matches lost
        - Win Rate: Win rate as percentage string
    """
    # Single query to get all player statistics with aggregate counts
    # Using LEFT JOIN to include players with zero matches
    # The CASE statements count matches where the player is involved
    stats_query = db.query(
        Player.id,
        Player.name,
        Player.email,
        Player.rating,
        # Count total matches where player is either player1 or player2
        func.sum(
            case(
                (
                    (Match.player1_id == Player.id) | (Match.player2_id == Player.id),
                    1
                ),
                else_=0
            )
        ).label('total_matches'),
        # Count wins where player is the winner
        func.sum(
            case(
                (Match.winner_id == Player.id, 1),
                else_=0
            )
        ).label('wins'),
    ).outerjoin(
        Match,
        (Match.player1_id == Player.id) | (Match.player2_id == Player.id)
    ).group_by(
        Player.id, Player.name, Player.email, Player.rating
    ).order_by(
        Player.name
    )
    
    results = []
    for row in stats_query:
        total_matches = row.total_matches or 0
        wins = row.wins or 0
        losses = total_matches - wins
        
        # Calculate win rate, handling division by zero
        win_rate = f"{(wins / total_matches * 100):.1f}%" if total_matches > 0 else "0%"
        
        results.append({
            "ID": row.id,
            "Name": row.name,
            "Email": row.email,
            "Rating": row.rating,
            "Matches": total_matches,
            "Wins": wins,
            "Losses": losses,
            "Win Rate": win_rate,
        })
    
    return results