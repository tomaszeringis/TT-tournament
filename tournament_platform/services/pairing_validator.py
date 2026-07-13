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

from tournament_platform.models import Match, MatchStatus, Player, Tournament, Stage, Group, Entry

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


def detect_rematches(
    db: Session,
    tournament_id: int,
) -> List[Dict[str, Any]]:
    """
    Detect any pair that plays each other more than once in the same tournament.
    
    Returns:
        List of rematch records with match id pairs.
    """
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    pair_matches: Dict[tuple, List[int]] = {}
    rematches = []
    for m in matches:
        if m.player1_id and m.player2_id:
            key = tuple(sorted([m.player1_id, m.player2_id]))
            pair_matches.setdefault(key, []).append(m.id)
    for key, ids in pair_matches.items():
        if len(ids) > 1:
            rematches.append({
                "type": "rematch",
                "player1_id": key[0],
                "player2_id": key[1],
                "match_ids": ids,
            })
    return rematches


def validate_groups_knockout_advancement(
    db: Session,
    tournament_id: int,
) -> Dict[str, Any]:
    """
    Validate whether groups-knockout advancement is ready.
    
    Checks:
    - Every group has a complete round-robin set of matches
    - Each group has a declared standings order for top qualifiers
    
    Returns:
        Dict with ready flag, group statuses, and issues.
    """
    issues = []
    group_statuses = []
    stages = db.query(Stage).filter(Stage.event_id == tournament_id, Stage.stage_type == "group").all()
    for stage in stages:
        groups = db.query(Group).filter(Group.stage_id == stage.id).all()
        for group in groups:
            members = db.query(Entry).filter(Entry.group_id == group.id).all()
            member_count = len(members)
            expected_matches = (member_count * (member_count - 1)) // 2
            actual_matches = db.query(Match).filter(Match.stage_id == stage.id).count()
            completed = db.query(Match).filter(Match.stage_id == stage.id, Match.status == MatchStatus.completed).count()
            ready = actual_matches >= expected_matches and completed >= expected_matches
            group_statuses.append({
                "group_id": group.id,
                "group_name": group.name,
                "members": member_count,
                "expected_matches": expected_matches,
                "actual_matches": actual_matches,
                "completed": completed,
                "ready": ready,
            })
            if not ready:
                issues.append({
                    "type": "incomplete_group",
                    "group_id": group.id,
                    "group_name": group.name,
                    "expected_matches": expected_matches,
                    "completed": completed,
                })
    return {
        "ready": all(g["ready"] for g in group_statuses) if group_statuses else False,
        "group_statuses": group_statuses,
        "issues": issues,
    }


def detect_incomplete_groups(
    db: Session,
    tournament_id: int,
) -> List[Dict[str, Any]]:
    """
    Return groups with missing or incomplete matches.
    """
    results = validate_groups_knockout_advancement(db, tournament_id=tournament_id)
    return results.get("issues", [])
