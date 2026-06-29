"""
Admin maintenance helpers for database overview, match management, and system health.

These functions are extracted from app/pages/admin.py to enable testing and reuse.
All functions use safe, user-friendly error messages and avoid exposing sensitive data.
"""

import importlib.metadata
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from tournament_platform.models import Player, Match, Tournament, MatchStatus, engine
from tournament_platform.config import settings
from tournament_platform.app.settings import API_BASE_URL, SHOW_DEBUG_DETAILS
from tournament_platform.app.api_client import api_client


# ---------------------------------------------------------------------------
# Database overview helpers
# ---------------------------------------------------------------------------

def get_admin_counts(db: Session) -> Dict[str, int]:
    """
    Get database summary counts for the admin panel.
    
    Returns:
        Dictionary with player_count, match_count, tournament_count, completed_matches.
    """
    return {
        "player_count": db.query(Player).count(),
        "match_count": db.query(Match).count(),
        "tournament_count": db.query(Tournament).count(),
        "completed_matches": db.query(Match).filter(Match.status == MatchStatus.completed).count(),
    }


def get_player_statistics(db: Session) -> List[Dict[str, Any]]:
    """
    Get player statistics using optimized aggregate queries.
    
    This is a wrapper around the existing player_stats service.
    """
    from tournament_platform.services.player_stats import get_player_statistics as _get_stats
    return _get_stats(db)


def get_filtered_matches(
    db: Session,
    status_filter: str = "All",
    tournament_filter: str = "All"
) -> List[Match]:
    """
    Get matches filtered by status and/or tournament.
    
    Args:
        db: Database session
        status_filter: "All", "pending", "active", or "completed"
        tournament_filter: "All" or a specific tournament name
        
    Returns:
        List of Match objects matching the filters.
    """
    query = db.query(Match)
    
    if status_filter != "All":
        try:
            query = query.filter(Match.status == MatchStatus[status_filter])
        except KeyError:
            # Invalid status filter - return empty list
            return []
    
    if tournament_filter != "All":
        tournament = db.query(Tournament).filter(Tournament.name == tournament_filter).first()
        if tournament:
            query = query.filter(Match.tournament_id == tournament.id)
    
    return query.all()


# ---------------------------------------------------------------------------
# Cache and refresh helpers
# ---------------------------------------------------------------------------

def clear_streamlit_cache() -> None:
    """
    Clear all Streamlit cached data.
    
    This is a no-op in non-Streamlit contexts.
    """
    try:
        import streamlit as st
        st.cache_data.clear()
    except Exception:
        # Not in Streamlit context or cache not available
        pass


# ---------------------------------------------------------------------------
# System health helpers
# ---------------------------------------------------------------------------

def get_runtime_versions() -> Dict[str, str]:
    """
    Get versions of key runtime packages.
    
    Returns:
        Dictionary mapping package names to their versions.
    """
    packages = ["streamlit", "fastapi", "sqlalchemy", "chromadb"]
    versions = {}
    
    for pkg in packages:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "not installed"
    
    return versions


def get_safe_database_status() -> tuple[bool, str]:
    """
    Check if database is accessible and return safe status message.
    
    Returns:
        Tuple of (is_healthy: bool, status_message: str)
        The status message is user-safe and does not expose internal details.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected"
    except Exception:
        # Return generic error message - details go to logs only
        return False, "Connection error"


def get_safe_api_status() -> tuple[bool, str]:
    """
    Check if FastAPI health endpoint is responding.

    Returns:
        Tuple of (is_healthy: bool, status_message: str)
    """
    try:
        response = api_client.health()
        if response is not None:
            status = response.get("status", "unknown")
            return True, f"Running - {status}"
        return False, "Unavailable"
    except Exception:
        return False, "Unavailable"


def get_safe_teams_status() -> tuple[bool, str]:
    """
    Check if Teams webhook is configured.
    
    Returns:
        Tuple of (is_configured: bool, status_message: str)
    """
    if settings.TEAMS_WEBHOOK_URL:
        return True, "Configured"
    return False, "Not configured"


def get_safe_azure_status() -> tuple[bool, str]:
    """
    Check if Azure integration is configured.
    
    Returns:
        Tuple of (is_configured: bool, status_message: str)
    """
    if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET:
        return True, "Configured"
    return False, "Not configured"


# ---------------------------------------------------------------------------
# User-safe error handling
# ---------------------------------------------------------------------------

def safe_error_message(error: Exception, context: str = "Operation") -> str:
    """
    Convert an exception to a user-safe error message.
    
    Args:
        error: The exception that occurred
        context: A short description of what operation failed
        
    Returns:
        A user-friendly error message that does not expose sensitive details.
    """
    # Log the full error for debugging
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"{context} failed: {error}", exc_info=True)
    
    # Return generic message to user
    return f"{context} failed. Please check logs for details."


# ---------------------------------------------------------------------------
# Environment warnings helpers
# ---------------------------------------------------------------------------

def get_environment_warnings() -> List[str]:
    """
    Get a list of environment configuration warnings.
    
    Returns:
        List of warning messages for potentially problematic configurations.
    """
    warnings = []
    
    # Check if API_BASE_URL is using default value
    if API_BASE_URL == "http://localhost:8000":
        warnings.append("API_BASE_URL is using default value (http://localhost:8000). "
                       "Set API_BASE_URL environment variable for production.")
    
    # Check if Teams webhook is configured with a placeholder
    if settings.TEAMS_WEBHOOK_URL:
        if "placeholder" in settings.TEAMS_WEBHOOK_URL.lower() or "example.com" in settings.TEAMS_WEBHOOK_URL:
            warnings.append("Teams webhook URL appears to be a placeholder. "
                           "Update TEAMS_WEBHOOK_URL with a valid webhook URL.")
    else:
        warnings.append("Teams webhook is not configured. "
                       "Set TEAMS_WEBHOOK_URL to enable notifications.")
    
    # Check if debug details are enabled in production
    if SHOW_DEBUG_DETAILS:
        warnings.append("SHOW_DEBUG_DETAILS is enabled. "
                       "This may expose sensitive information in error messages. "
                       "Set to False in production.")
    
    # Check for SQLite in multi-user scenarios
    if "sqlite" in settings.DATABASE_URL.lower():
        warnings.append("SQLite is used for the database. "
                       "This is not recommended for multi-user production environments. "
                       "Consider using PostgreSQL for production.")
    
    return warnings