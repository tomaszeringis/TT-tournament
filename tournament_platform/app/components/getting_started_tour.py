"""
Getting Started Tour component for Streamlit UI.

Interactive tour for first-time users to understand the platform.
"""

import streamlit as st


def render_getting_started_tour():
    """
    Render an interactive getting started tour for first-time users.
    Shows a modal dialog with step-by-step guidance.
    """
    # Check if user has seen the tour
    if "tour_completed" not in st.session_state:
        st.session_state.tour_completed = False

    # Show tour button in sidebar
    with st.sidebar:
        st.divider()
        if st.button("❓ Getting Started Tour", use_container_width=True):
            st.session_state.show_tour = True
            st.session_state.tour_step = 1

    # Tour modal
    if st.session_state.get("show_tour", False):
        _render_tour_modal()


def _render_tour_modal():
    """Render the tour modal dialog."""
    tour_steps = [
        {
            "title": "Welcome to Tournament Platform!",
            "content": "This app helps you manage table tennis tournaments from setup to match day.",
            "icon": "🏓"
        },
        {
            "title": "Setup Your Tournament",
            "content": "Go to Events & Draws to create a tournament, register players, and generate brackets.",
            "icon": "🏆"
        },
        {
            "title": "Manage Matches",
            "content": "Use Match Center to call matches, assign tables, and record results during tournament day.",
            "icon": "🎛️"
        },
        {
            "title": "View Public Board",
            "content": "The Public Board shows live match status for spectators and players.",
            "icon": "📺"
        },
        {
            "title": "Track Progress",
            "content": "Check the Dashboard for analytics, rankings, and match insights.",
            "icon": "📊"
        }
    ]

    step = st.session_state.get("tour_step", 1)
    total_steps = len(tour_steps)

    if step > total_steps:
        # Tour completed
        st.session_state.show_tour = False
        st.session_state.tour_completed = True
        st.rerun()
        return

    current = tour_steps[step - 1]

    # Use st.dialog for the tour (Streamlit 1.35+)
    @st.dialog(f"Getting Started - Step {step} of {total_steps}", width="large")
    def tour_dialog():
        st.markdown(f"### {current['icon']} {current['title']}")
        st.write(current['content'])

        # Progress indicator
        progress = step / total_steps
        st.progress(progress)

        col1, col2 = st.columns([1, 1])
        with col1:
            if step > 1:
                if st.button("← Previous", use_container_width=True):
                    st.session_state.tour_step = step - 1
                    st.rerun()
        with col2:
            if step < total_steps:
                if st.button("Next →", use_container_width=True, type="primary"):
                    st.session_state.tour_step = step + 1
                    st.rerun()
            else:
                if st.button("Finish", use_container_width=True, type="primary"):
                    st.session_state.show_tour = False
                    st.session_state.tour_completed = True
                    st.rerun()

    tour_dialog()


def is_first_visit() -> bool:
    """
    Check if this is the user's first visit.
    Shows tour automatically on first visit.
    """
    if "tour_shown" not in st.session_state:
        st.session_state.tour_shown = True
        return True
    return False