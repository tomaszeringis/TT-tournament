"""
Home / Getting Started page for Tournament Platform.

This page serves as the entry point for users, showing:
- Quick actions for creating or resuming tournaments
- Setup checklist
- Recent tournaments
- Live operations summary
- Getting Started tour
"""

import streamlit as st
from datetime import datetime

from tournament_platform.models import SessionLocal, Tournament, Match, MatchStatus
from tournament_platform.app.components.page_header import render_page_header
from tournament_platform.app.components.empty_state import render_empty_state
from tournament_platform.app.components.getting_started_tour import render_getting_started_tour


@st.cache_data(ttl=30, show_spinner="Loading home data...")
def load_home_data():
    """Load data needed for the home page."""
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).all()
        matches = db.query(Match).all()

        # Get current and next matches
        current_matches = [m for m in matches if m.status == MatchStatus.active]
        next_matches = [m for m in matches if m.status == MatchStatus.pending][:3]

        return {
            "tournaments": [
                {"id": t.id, "name": t.name, "created_at": t.created_at}
                for t in tournaments
            ],
            "current_matches": [
                {"player1": m.player1, "player2": m.player2}
                for m in current_matches
            ],
            "next_matches": [
                {"player1": m.player1, "player2": m.player2, "scheduled_time": m.scheduled_time}
                for m in next_matches
            ],
        }
    finally:
        db.close()


def render_setup_checklist(tournaments: list, players_count: int):
    """Render the setup checklist showing progress toward tournament readiness."""
    st.subheader("✅ Setup Checklist")

    # Get player count
    db = SessionLocal()
    try:
        from tournament_platform.models import Player
        players_count = db.query(Player).count()
    finally:
        db.close()

    # For now, use simple checks
    has_tournaments = len(tournaments) > 0

    col1, col2, col3 = st.columns(3)

    with col1:
        if players_count >= 2:
            st.success(f"✅ Players registered ({players_count})")
        else:
            st.warning(f"⚠️ Register players ({players_count}/2 minimum)")

    with col2:
        if has_tournaments:
            st.success(f"✅ Tournament created")
        else:
            st.warning("⚠️ Create tournament")

    with col3:
        st.info("⏭️ Schedule matches")


def render_recent_tournaments(tournaments: list):
    """Render the recent tournaments section."""
    st.subheader("📋 Recent Tournaments")

    if not tournaments:
        render_empty_state(
            icon="🏆",
            title="No tournaments yet",
            description="Create your first tournament to get started",
            cta_label="Create Tournament",
            cta_key="create_tournament_home"
        )
        return

    for t in tournaments[:5]:
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{t['name']}**")
                created = t['created_at'].strftime('%Y-%m-%d') if t.get('created_at') else 'Unknown'
                st.caption(f"Created: {created}")
            with col2:
                if st.button("View", key=f"view_t_{t['id']}"):
                    st.session_state['selected_tournament_id'] = t['id']
                    st.switch_page("pages/events_draws.py")


def render_live_operations(data: dict):
    """Render the live operations summary strip."""
    st.subheader("🔴 Live Operations")

    current = data.get("current_matches", [])
    next_up = data.get("next_matches", [])

    if not current and not next_up:
        st.info("No active matches. Tournament day hasn't started yet.")
        return

    # Current matches
    if current:
        st.write("**Current Matches:**")
        for m in current:
            st.markdown(f"- {m['player1']} vs {m['player2']}")

    # Next matches
    if next_up:
        st.write("**Next Up:**")
        for m in next_up:
            time_str = m.get('scheduled_time', '').strftime('%H:%M') if m.get('scheduled_time') else 'TBD'
            st.markdown(f"- {m['player1']} vs {m['player2']} ({time_str})")


def render_home():
    """Render the main home page."""
    # Page header
    render_page_header(
        title="Tournament Platform",
        description="Manage your table tennis tournaments with ease",
        icon="🏓"
    )

    # Getting Started tour
    render_getting_started_tour()

    # Load data
    try:
        data = load_home_data()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

    tournaments = data.get("tournaments", [])

    # Quick actions
    st.subheader("🚀 Quick Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🏆 Create Tournament", use_container_width=True, type="primary"):
            st.session_state['wizard_step'] = 1
            st.switch_page("pages/events_draws.py")

    with col2:
        if tournaments and st.button("🔄 Resume Current Event", use_container_width=True):
            st.session_state['selected_tournament_id'] = tournaments[0]['id']
            st.switch_page("pages/events_draws.py")

    with col3:
        if st.button("📊 View Dashboard", use_container_width=True):
            st.switch_page("pages/dashboard.py")

    st.space("medium")

    # Setup checklist
    render_setup_checklist(tournaments, 0)

    st.space("medium")

    # Live operations
    render_live_operations(data)

    st.space("medium")

    # Recent tournaments
    render_recent_tournaments(tournaments)


# Note: This code only runs when the file is executed directly by Streamlit
if __name__ == "__main__":
    st.set_page_config(page_title="Home", page_icon="🏠", layout="wide")
    render_home()