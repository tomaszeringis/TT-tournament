"""
Announcement Templates - Deterministic template rendering for announcements.

This module provides:
- Template definitions for different announcement types
- Deterministic rendering (AI may rewrite, but template is source of truth)
- Preview functionality before sending
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone

from tournament_platform.models import Match, Tournament


# ============================================================================
# Template Definitions
# ============================================================================

TEMPLATES = {
    "match_call": {
        "title": "Match Call",
        "description": "Call players to a table",
        "template": "Match called: {player1} vs {player2}{table_str}. Please proceed to the table.",
    },
    "semifinal_start": {
        "title": "Semifinal Start",
        "description": "Announce semifinals beginning",
        "template": "Semifinals starting now in {tournament_name}! Good luck to all players.",
    },
    "final_start": {
        "title": "Final Start",
        "description": "Announce final beginning",
        "template": "Final starting now in {tournament_name}! The championship match is about to begin.",
    },
    "delay": {
        "title": "Match Delay",
        "description": "Announce match delay",
        "template": "Match {player1} vs {player2} is delayed. New start time: {new_time}.",
    },
    "table_change": {
        "title": "Table Change",
        "description": "Announce table change",
        "template": "Match {player1} vs {player2} has been moved to {new_table}.",
    },
    "event_close": {
        "title": "Event Close",
        "description": "Announce event completion",
        "template": "Tournament {tournament_name} has concluded. Thank you to all players and officials!",
    },
}


# ============================================================================
# Template Rendering
# ============================================================================

def get_template_types() -> list:
    """Get list of available template types."""
    return list(TEMPLATES.keys())


def render_announcement_template(
    template_type: str,
    match: Optional[Match] = None,
    tournament: Optional[Tournament] = None,
    **kwargs
) -> str:
    """
    Render an announcement template.
    
    Args:
        template_type: Type of template (match_call, semifinal_start, etc.)
        match: Optional match for context
        tournament: Optional tournament for context
        **kwargs: Additional template variables
        
    Returns:
        Rendered message string
    """
    if template_type not in TEMPLATES:
        raise ValueError(f"Unknown template type: {template_type}")
    
    template = TEMPLATES[template_type]["template"]
    
    # Build context
    context = {}
    
    if match:
        context["player1"] = match.player1
        context["player2"] = match.player2
        context["table_str"] = f" to {match.location}" if match.location else ""
    
    if tournament:
        context["tournament_name"] = tournament.name
    
    # Add any additional kwargs
    context.update(kwargs)
    
    # Render template
    try:
        return template.format(**context)
    except KeyError as e:
        raise ValueError(f"Missing template variable: {e}")


def preview_announcement(
    template_type: str,
    match_id: Optional[int] = None,
    tournament_id: Optional[int] = None,
    db = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Preview an announcement without saving.
    
    Args:
        template_type: Type of template
        match_id: Optional match ID
        tournament_id: Optional tournament ID
        db: Database session (optional, for fetching match/tournament)
        **kwargs: Additional template variables
        
    Returns:
        Dict with preview data
    """
    match = None
    tournament = None
    
    if db:
        if match_id:
            match = db.query(Match).filter(Match.id == match_id).first()
        if tournament_id:
            tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    
    if not match and not tournament:
        return {
            "success": False,
            "error": "Either match_id or tournament_id required",
        }
    
    try:
        message = render_announcement_template(
            template_type,
            match=match,
            tournament=tournament,
            **kwargs
        )
        
        return {
            "success": True,
            "message": message,
            "template_type": template_type,
            "match_id": match_id,
            "tournament_id": tournament_id,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }