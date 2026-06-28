"""
Announcement Service for Tournament Platform

Provides announcement creation and webhook sending for match calls and stage starts.
Vosk is optional - the app works without it and shows setup instructions.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from tournament_platform.models import SessionLocal, Announcement, Match, Tournament
from tournament_platform.services.audit_service import log_audit
from tournament_platform.config import settings

logger = logging.getLogger(__name__)

# Placeholder webhook URL that should be skipped
PLACEHOLDER_WEBHOOKS = [
    "",
    "https://example.com/webhook",
    "https://your-webhook-url-here",
    "https://teams.microsoft.com/placeholder",
]


def is_placeholder_webhook(url: str) -> bool:
    """Check if a webhook URL is a placeholder that should be skipped."""
    if not url:
        return True
    url_lower = url.lower().strip()
    for placeholder in PLACEHOLDER_WEBHOOKS:
        if placeholder and url_lower == placeholder.lower():
            return True
    return False


def create_announcement(
    db,
    message: str,
    match_id: Optional[int] = None,
    tournament_id: Optional[int] = None,
    channel: str = "local"
) -> Announcement:
    """
    Create an announcement record.
    
    Args:
        db: Database session
        message: The announcement message
        match_id: Optional match ID to associate
        tournament_id: Optional tournament ID to associate
        channel: Channel for the announcement (default: "local")
    
    Returns:
        The created Announcement object
    """
    announcement = Announcement(
        message=message,
        match_id=match_id,
        tournament_id=tournament_id,
        channel=channel,
        sent_status="pending"
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    
    # Log audit
    log_audit(
        db,
        action="create_announcement",
        entity_type="announcement",
        entity_id=announcement.id,
        payload={
            "message": message,
            "match_id": match_id,
            "tournament_id": tournament_id,
            "channel": channel
        }
    )
    
    return announcement


def send_webhook_announcement(db, announcement_id: int) -> Dict[str, Any]:
    """
    Send an announcement via webhook.
    
    Args:
        db: Database session
        announcement_id: ID of the announcement to send
    
    Returns:
        Dict with status and message
    """
    # Load the announcement
    announcement = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not announcement:
        return {"status": "error", "message": "Announcement not found"}
    
    webhook_url = settings.TEAMS_WEBHOOK_URL
    
    # Check if webhook is a placeholder
    if is_placeholder_webhook(webhook_url):
        announcement.sent_status = "skipped"
        announcement.error = "Webhook URL not configured (placeholder or empty). Set TEAMS_WEBHOOK_URL in .env to enable."
        db.commit()
        
        log_audit(
            db,
            action="send_announcement_skipped",
            entity_type="announcement",
            entity_id=announcement_id,
            payload={"reason": "placeholder_webhook"}
        )
        
        return {
            "status": "skipped",
            "message": "Webhook not configured. Announcement saved but not sent."
        }
    
    # Send the webhook
    try:
        import requests
        response = requests.post(
            webhook_url,
            json={"text": announcement.message},
            timeout=10
        )
        
        if response.status_code == 200:
            announcement.sent_status = "sent"
            announcement.error = None
            db.commit()
            
            log_audit(
                db,
                action="send_announcement_success",
                entity_type="announcement",
                entity_id=announcement_id,
                payload={"webhook_url": webhook_url[:50] + "..."}  # Truncate for privacy
            )
            
            return {"status": "success", "message": "Announcement sent successfully"}
        else:
            announcement.sent_status = "failed"
            announcement.error = f"HTTP {response.status_code}: {response.text[:200]}"
            db.commit()
            
            log_audit(
                db,
                action="send_announcement_failed",
                entity_type="announcement",
                entity_id=announcement_id,
                payload={"status_code": response.status_code, "error": announcement.error}
            )
            
            return {"status": "error", "message": f"Failed to send: HTTP {response.status_code}"}
            
    except Exception as e:
        announcement.sent_status = "failed"
        announcement.error = str(e)[:200]
        db.commit()
        
        log_audit(
            db,
            action="send_announcement_error",
            entity_type="announcement",
            entity_id=announcement_id,
            payload={"error": str(e)}
        )
        
        return {"status": "error", "message": f"Error sending announcement: {e}"}


def get_announcements(
    db,
    limit: int = 50,
    channel: Optional[str] = None,
    sent_status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get recent announcements.
    
    Args:
        db: Database session
        limit: Maximum number of announcements to return
        channel: Optional filter by channel
        sent_status: Optional filter by sent status
    
    Returns:
        List of announcement dicts
    """
    query = db.query(Announcement)
    
    if channel:
        query = query.filter(Announcement.channel == channel)
    if sent_status:
        query = query.filter(Announcement.sent_status == sent_status)
    
    announcements = query.order_by(Announcement.created_at.desc()).limit(limit).all()
    
    return [
        {
            "id": a.id,
            "message": a.message,
            "match_id": a.match_id,
            "tournament_id": a.tournament_id,
            "channel": a.channel,
            "sent_status": a.sent_status,
            "error": a.error,
            "created_at": a.created_at.isoformat() if a.created_at else None
        }
        for a in announcements
    ]


def generate_match_call_message(match: Match, table: Optional[str] = None) -> str:
    """Generate a message for a match call announcement."""
    table_str = f" to {table}" if table else ""
    return f"Match called: {match.player1} vs {match.player2}{table_str}. Please proceed to the table."


def generate_semifinal_start_message(tournament: Tournament) -> str:
    """Generate a message for semifinal start announcement."""
    return f"Semifinals starting now in {tournament.name}! Good luck to all players."


def generate_final_start_message(tournament: Tournament) -> str:
    """Generate a message for final start announcement."""
    return f"Final starting now in {tournament.name}! The championship match is about to begin."