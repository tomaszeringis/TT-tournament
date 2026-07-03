"""
Player Registration component for Streamlit UI.

This module re-exports from participants_panel to maintain backward compatibility.
New code should import from participants_panel directly.
"""

from tournament_platform.app.components.participants_panel import (
    render_player_registration_form,
    render_player_list,
    render_player_registration_section,
    get_all_players,
    render_participants_panel,
)

__all__ = [
    "render_player_registration_form",
    "render_player_list",
    "render_player_registration_section",
    "get_all_players",
    "render_participants_panel",
]
