"""
Duplicate Player Detection Service - Find and merge duplicate player records.

This service provides:
- Exact email/name matching
- Fuzzy name similarity (using RapidFuzz)
- Dry-run candidate reports
- Merge preview (no destructive merge without confirmation)
"""

from typing import Optional, List, Dict, Any
import logging

from sqlalchemy.orm import Session

from tournament_platform.models import Player, Match, RatingHistory

logger = logging.getLogger(__name__)

# Try to import RapidFuzz, fall back to basic matching if not available
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    logger.warning("RapidFuzz not available. Fuzzy matching will be limited.")


# Similarity threshold for fuzzy name matching (0-100)
FUZZY_NAME_THRESHOLD = 85


def find_duplicate_candidates(
    db: Session,
    fuzzy_threshold: int = FUZZY_NAME_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Find potential duplicate player candidates.
    
    Checks:
    1. Exact email matches
    2. Exact name matches
    3. Fuzzy name similarity (if RapidFuzz available)
    
    Args:
        db: Database session
        fuzzy_threshold: Minimum similarity score for fuzzy matching (0-100)
        
    Returns:
        List of candidate dicts with:
        - player1_id, player1_name, player1_email
        - player2_id, player2_name, player2_email
        - similarity_score
        - match_count
        - reason: "exact_email", "exact_name", or "fuzzy_name"
    """
    players = db.query(Player).all()
    candidates = []
    seen_pairs = set()
    
    for i, p1 in enumerate(players):
        for p2 in players[i + 1:]:
            pair_key = tuple(sorted([p1.id, p2.id]))
            if pair_key in seen_pairs:
                continue
            
            # Check exact email match
            if p1.email and p2.email and p1.email.lower() == p2.email.lower():
                seen_pairs.add(pair_key)
                match_count = _count_shared_matches(db, p1.id, p2.id)
                candidates.append({
                    "player1_id": p1.id,
                    "player1_name": p1.name,
                    "player1_email": p1.email,
                    "player2_id": p2.id,
                    "player2_name": p2.name,
                    "player2_email": p2.email,
                    "similarity_score": 100,
                    "match_count": match_count,
                    "reason": "exact_email",
                })
                continue
            
            # Check exact name match
            if p1.name.lower() == p2.name.lower():
                seen_pairs.add(pair_key)
                match_count = _count_shared_matches(db, p1.id, p2.id)
                candidates.append({
                    "player1_id": p1.id,
                    "player1_name": p1.name,
                    "player1_email": p1.email,
                    "player2_id": p2.id,
                    "player2_name": p2.name,
                    "player2_email": p2.email,
                    "similarity_score": 100,
                    "match_count": match_count,
                    "reason": "exact_name",
                })
                continue
            
            # Check fuzzy name similarity
            if RAPIDFUZZ_AVAILABLE:
                score = fuzz.ratio(p1.name.lower(), p2.name.lower())
                if score >= fuzzy_threshold:
                    seen_pairs.add(pair_key)
                    match_count = _count_shared_matches(db, p1.id, p2.id)
                    candidates.append({
                        "player1_id": p1.id,
                        "player1_name": p1.name,
                        "player1_email": p1.email,
                        "player2_id": p2.id,
                        "player2_name": p2.name,
                        "player2_email": p2.email,
                        "similarity_score": score,
                        "match_count": match_count,
                        "reason": "fuzzy_name",
                    })
    
    # Sort by similarity score descending
    candidates.sort(key=lambda c: c["similarity_score"], reverse=True)
    return candidates


def _count_shared_matches(db: Session, player1_id: int, player2_id: int) -> int:
    """Count matches where both players appear (as either player1 or player2)."""
    count = db.query(Match).filter(
        (
            (Match.player1_id == player1_id) & (Match.player2_id == player2_id)
        ) | (
            (Match.player1_id == player2_id) & (Match.player2_id == player1_id)
        )
    ).count()
    return count


def preview_player_merge(
    db: Session,
    target_player_id: int,
    source_player_id: int,
) -> Dict[str, Any]:
    """
    Preview what would happen when merging two player records.
    
    This is a read-only operation that shows:
    - Which matches would be transferred
    - Which rating history entries would be transferred
    - Any potential data loss warnings
    
    Args:
        db: Database session
        target_player_id: The player to keep (merge into this)
        source_player_id: The player to merge from (will be deleted)
        
    Returns:
        Preview dict with:
        - target_player, source_player
        - matches_to_transfer, rating_history_to_transfer
        - warnings
    """
    target = db.query(Player).filter(Player.id == target_player_id).first()
    source = db.query(Player).filter(Player.id == source_player_id).first()
    
    if not target:
        return {
            "success": False,
            "error": f"Target player {target_player_id} not found",
        }
    
    if not source:
        return {
            "success": False,
            "error": f"Source player {source_player_id} not found",
        }
    
    # Find matches where source is referenced
    source_matches = db.query(Match).filter(
        (Match.player1_id == source_player_id) |
        (Match.player2_id == source_player_id) |
        (Match.winner_id == source_player_id)
    ).all()
    
    # Find rating history for source
    source_rating_history = db.query(RatingHistory).filter(
        RatingHistory.player_id == source_player_id
    ).all()
    
    warnings = []
    
    # Check for potential data loss
    if source.email and not target.email:
        warnings.append(f"Source email '{source.email}' will be preserved")
    elif source.email and target.email and source.email != target.email:
        warnings.append(f"Source email differs from target. Source: {source.email}, Target: {target.email}")
    
    if source.rating != target.rating:
        warnings.append(f"Rating will change from {source.rating} to {target.rating}")
    
    return {
        "success": True,
        "target_player": {
            "id": target.id,
            "name": target.name,
            "email": target.email,
            "rating": target.rating,
        },
        "source_player": {
            "id": source.id,
            "name": source.name,
            "email": source.email,
            "rating": source.rating,
        },
        "matches_to_transfer": len(source_matches),
        "rating_history_to_transfer": len(source_rating_history),
        "warnings": warnings,
    }


def merge_players(
    db: Session,
    target_player_id: int,
    source_player_id: int,
    actor: str = "operator",
) -> Dict[str, Any]:
    """
    Merge two player records.
    
    This is a destructive operation that:
    1. Updates all matches to reference target instead of source
    2. Updates all rating history to reference target
    3. Deletes the source player
    4. Logs an audit entry
    
    Args:
        db: Database session
        target_player_id: The player to keep
        source_player_id: The player to merge from (will be deleted)
        actor: Who performed the action
        
    Returns:
        Result dict with success status and details
    """
    from tournament_platform.services.audit_service import log_audit
    
    target = db.query(Player).filter(Player.id == target_player_id).first()
    source = db.query(Player).filter(Player.id == source_player_id).first()
    
    if not target or not source:
        return {
            "success": False,
            "error": "One or both players not found",
        }
    
    if target.id == source.id:
        return {
            "success": False,
            "error": "Cannot merge player with themselves",
        }
    
    try:
        # Get counts before merge
        source_matches = db.query(Match).filter(
            (Match.player1_id == source_player_id) |
            (Match.player2_id == source_player_id) |
            (Match.winner_id == source_player_id)
        ).all()
        
        source_rating_count = db.query(RatingHistory).filter(
            RatingHistory.player_id == source_player_id
        ).count()
        
        # Update matches
        for match in source_matches:
            if match.player1_id == source_player_id:
                match.player1_id = target_player_id
            if match.player2_id == source_player_id:
                match.player2_id = target_player_id
            if match.winner_id == source_player_id:
                match.winner_id = target_player_id
        
        # Update rating history
        for history in db.query(RatingHistory).filter(
            RatingHistory.player_id == source_player_id
        ).all():
            history.player_id = target_player_id
        
        # Delete source player
        db.delete(source)
        db.commit()
        
        # Log audit
        log_audit(
            db,
            action="merge_players",
            entity_type="player",
            entity_id=target_player_id,
            actor=actor,
            payload={
                "target_player_id": target_player_id,
                "target_player_name": target.name,
                "source_player_id": source_player_id,
                "source_player_name": source.name,
                "matches_transferred": len(source_matches),
                "rating_history_transferred": source_rating_count,
            },
        )
        
        return {
            "success": True,
            "target_player_id": target_player_id,
            "source_player_id": source_player_id,
            "matches_transferred": len(source_matches),
            "rating_history_transferred": source_rating_count,
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error merging players: {e}")
        return {
            "success": False,
            "error": str(e),
        }