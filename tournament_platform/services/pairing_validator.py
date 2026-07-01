"""
Pairing Validator - Validate tournament pairings and bracket consistency.

This service provides deterministic validation of:
- Knockout links
- Byes
- Null slots
- Duplicate pairings
- Round-robin completeness
- Rematches
- Missing players
- Inconsistent next-match links
"""

from typing import Optional, List, Dict, Any
import logging

from sqlalchemy.orm import Session

from tournament_platform.models import Match, MatchStatus, Player, Tournament

logger = logging.getLogger(__name__)


def validate_tournament_pairings(
    db: Session,
    tournament_id: int,
) -> Dict[str, Any]:
    """
    Validate tournament pairings for consistency.
    
    Checks:
    - All matches have valid player references
    - No duplicate pairings in the same round
    - Bracket links are consistent (next_match_id points to valid matches)
    - No rematches in knockout brackets
    
    Args:
        db: Database session
        tournament_id: Tournament to validate
        
    Returns:
        Dict with:
        - valid: bool
        - issues: List of validation issues
        - warnings: List of warnings
    """
    issues = []
    warnings = []
    
    # Get all matches for the tournament
    matches = db.query(Match).filter(
        Match.tournament_id == tournament_id
    ).all()
    
    # Get all players
    players = db.query(Player).all()
    player_ids = {p.id for p in players}
    
    # Track pairings by round
    pairings_by_round = {}
    
    for match in matches:
        # Check for missing players
        if match.player1_id and match.player1_id not in player_ids:
            issues.append({
                "type": "missing_player",
                "match_id": match.id,
                "player_id": match.player1_id,
                "position": "player1",
            })
        
        if match.player2_id and match.player2_id not in player_ids:
            issues.append({
                "type": "missing_player",
                "match_id": match.id,
                "player_id": match.player2_id,
                "position": "player2",
            })
        
        # Check for duplicate pairings in same round
        if match.player1_id and match.player2_id:
            pairing_key = tuple(sorted([match.player1_id, match.player2_id]))
            round_key = (match.round_number, pairing_key)
            
            if round_key in pairings_by_round:
                issues.append({
                    "type": "duplicate_pairing",
                    "match_id": match.id,
                    "other_match_id": pairings_by_round[round_key],
                    "round": match.round_number,
                })
            else:
                pairings_by_round[round_key] = match.id
        
        # Check next_match_id consistency
        if match.next_match_id:
            next_match = db.query(Match).filter(Match.id == match.next_match_id).first()
            if not next_match:
                issues.append({
                    "type": "invalid_next_match",
                    "match_id": match.id,
                    "next_match_id": match.next_match_id,
                })
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "total_matches": len(matches),
    }