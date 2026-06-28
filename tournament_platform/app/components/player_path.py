"""
Reusable player path component for public board and operator console.
"""

import streamlit as st
from difflib import get_close_matches
from typing import Optional, List, Dict, Any

from tournament_platform.models import Match, MatchStatus, Player
from tournament_platform.services.tournament_read_models import get_player_path


def render_player_path(
    db,
    player_name: str,
    tournament_id: Optional[int] = None,
    key_prefix: str = "player_path"
) -> bool:
    """
    Render a player's path through a tournament bracket.
    
    Args:
        db: Database session
        player_name: Name of the player to look up
        tournament_id: Optional tournament filter
        key_prefix: Streamlit key prefix for widget uniqueness
        
    Returns:
        True if player was found and rendered, False otherwise
    """
    # Get all player names for fuzzy matching
    all_players = db.query(Player).all()
    all_player_names = [p.name for p in all_players]
    
    # Check for exact match
    if player_name not in all_player_names:
        # Try fuzzy matching
        close_matches = get_close_matches(player_name, all_player_names, n=3, cutoff=0.6)
        if close_matches:
            st.warning(f"Player '{player_name}' not found. Did you mean: {', '.join(close_matches)}?")
        else:
            st.warning(f"Player '{player_name}' not found.")
        return False
    
    # Get player path data
    path_data = get_player_path(db, player_name, tournament_id=tournament_id)
    
    # Display player name
    st.subheader(f"Player Path: {path_data['player_name']}")
    
    # Display completed matches
    if path_data['completed_matches']:
        st.markdown("### Completed Matches")
        for match in path_data['completed_matches']:
            _render_match_row(match, key_prefix=f"{key_prefix}_completed")
    
    # Display next pending match
    if path_data['next_pending_match']:
        st.markdown("### Next Scheduled Match")
        _render_match_row(path_data['next_pending_match'], key_prefix=f"{key_prefix}_next", status="pending")
    
    # Display projected path
    if path_data['projected_path']:
        st.markdown("### Projected Path")
        for match in path_data['projected_path']:
            _render_projected_match(match, key_prefix=f"{key_prefix}_projected")
    
    return True


def _render_match_row(match: Dict[str, Any], key_prefix: str = "match", status: Optional[str] = None) -> None:
    """
    Render a single match row with result badge.
    
    Args:
        match: Match data dict
        key_prefix: Streamlit key prefix
        status: Optional override status (for next_pending_match)
    """
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
    
    # Result badge
    if status == "pending":
        badge = "⏳ Pending"
    elif match.get('winner') == match.get('player1'):
        badge = "🏆 Won" if match.get('player1') else "❓ Unknown"
    elif match.get('winner') == match.get('player2'):
        badge = "❌ Lost" if match.get('player2') else "❓ Unknown"
    else:
        badge = "❓ Unknown"
    
    with col1:
        st.write(f"**{match.get('player1', 'Unknown')}**")
    with col2:
        st.write(f"**{match.get('player2', 'Unknown')}**")
    with col3:
        st.write(badge)
    with col4:
        if match.get('score'):
            st.write(f"Score: {match['score']}")
    
    # Show round/stage and location if present
    details = []
    if match.get('round_number'):
        details.append(f"Round {match['round_number']}")
    if match.get('bracket_index') is not None:
        details.append(f"Bracket {match['bracket_index']}")
    if match.get('location'):
        details.append(f"Table {match['location']}")
    if match.get('scheduled_time'):
        details.append(f"Time: {match['scheduled_time']}")
    
    if details:
        st.caption(" · ".join(details))


def _render_projected_match(match: Dict[str, Any], key_prefix: str = "projected") -> None:
    """
    Render a projected match (next in bracket).
    
    Args:
        match: Projected match data
        key_prefix: Streamlit key prefix
    """
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        st.write(f"🎯 {match.get('player1', 'Unknown')}")
    with col2:
        st.write(f"🎯 {match.get('player2', 'Unknown')}")
    with col3:
        if match.get('round_number'):
            st.write(f"Round {match['round_number']}")
    
    st.caption(f"Match ID: {match.get('match_id', 'Unknown')}")


def render_player_path_lookup(
    db,
    tournament_id: Optional[int] = None,
    key_prefix: str = "player_lookup"
) -> None:
    """
    Render a player lookup interface with path display.
    
    Args:
        db: Database session
        tournament_id: Optional tournament filter
        key_prefix: Streamlit key prefix for widget uniqueness
    """
    # Get all player names
    all_players = db.query(Player).all()
    all_player_names = sorted([p.name for p in all_players])
    
    # Player selection
    selected_player = st.selectbox(
        "Select Player",
        options=[""] + all_player_names,
        key=f"{key_prefix}_select"
    )
    
    if selected_player:
        render_player_path(db, selected_player, tournament_id=tournament_id, key_prefix=key_prefix)