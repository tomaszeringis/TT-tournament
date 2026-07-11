"""
Getting Started Tour component for Streamlit UI.

Backward-compat shim: delegates to the new tour.py module so existing
imports and tests keep working.
"""

from tournament_platform.app.components.tour import render_tour, is_tour_completed


def render_getting_started_tour():
    """Render the home getting-started tour."""
    render_tour("home")


def is_first_visit() -> bool:
    """Return True until the user completes the home tour."""
    return not is_tour_completed("home")
