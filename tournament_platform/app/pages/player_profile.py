"""
Player Profile page for Tournament Platform.

This page shows individual player information including:
- Rating/ranking trend
- Match history
- Current event path
- Upcoming matches
- Organizer notes
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import Optional

from tournament_platform.app.design_system import apply_global_styles
from tournament_platform.models import SessionLocal, Player, Match, MatchStatus, RatingHistory
from tournament_platform.app.components.page_header import render_page_header


@st.cache_data(ttl=60, show_spinner="Loading player data...")
def load_player_data(player_id: int):
    """Load all data for a specific player."""
    db = SessionLocal()
    try:
        player = db.query(Player).filter(Player.id == player_id).first()
        if not player:
            return None

        # Get rating history
        rating_history = db.query(RatingHistory).filter(
            RatingHistory.player_id == player_id
        ).order_by(RatingHistory.timestamp).all()

        # Get match history
        matches_as_p1 = db.query(Match).filter(Match.player1 == player.name).all()
        matches_as_p2 = db.query(Match).filter(Match.player2 == player.name).all()
        all_matches = list(set(matches_as_p1 + matches_as_p2))

        # Get upcoming matches
        upcoming_matches = [m for m in all_matches if m.status in (MatchStatus.pending, MatchStatus.active)]

        return {
            "player": {
                "id": player.id,
                "name": player.name,
                "email": player.email,
                "rating": player.rating,
            },
            "rating_history": [
                {"timestamp": rh.timestamp, "rating": rh.rating}
                for rh in rating_history
            ],
            "match_history": [
                {
                    "id": m.id,
                    "player1": m.player1,
                    "player2": m.player2,
                    "winner": m.winner,
                    "score": m.score,
                    "status": m.status.value if m.status else "pending",
                    "scheduled_time": m.scheduled_time,
                }
                for m in sorted(all_matches, key=lambda x: x.scheduled_time or datetime.min, reverse=True)
            ],
            "upcoming_matches": [
                {
                    "id": m.id,
                    "player1": m.player1,
                    "player2": m.player2,
                    "scheduled_time": m.scheduled_time,
                }
                for m in sorted(upcoming_matches, key=lambda x: x.scheduled_time or datetime.min)
            ],
        }
    finally:
        db.close()


def render_rating_trend(rating_history: list):
    """Render the rating trend chart."""
    st.subheader("📈 Rating Trend")

    if not rating_history:
        st.info("No rating history yet. Rating will update after matches.")
        return

    df = pd.DataFrame(rating_history)
    if df.empty:
        st.info("No rating history yet.")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=df['rating'],
        mode='lines+markers',
        name='Rating',
        line=dict(color='#00C853', width=2),
    ))

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Rating",
        height=300,
        margin=dict(l=0, r=0, t=0, b=0),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_match_history(match_history: list):
    """Render the match history table."""
    st.subheader("📋 Match History")

    if not match_history:
        st.info("No matches played yet.")
        return

    df = pd.DataFrame(match_history)
    df = df[["id", "player1", "player2", "winner", "score", "status", "scheduled_time"]]
    df = df.rename(columns={
        "id": "Match #",
        "player1": "Player 1",
        "player2": "Player 2",
        "winner": "Winner",
        "score": "Score",
        "status": "Status",
        "scheduled_time": "Date",
    })

    st.dataframe(df, use_container_width=True, hide_index=True)


def render_upcoming_matches(upcoming_matches: list):
    """Render the upcoming matches section."""
    st.subheader("⏭️ Upcoming Matches")

    if not upcoming_matches:
        st.info("No upcoming matches scheduled.")
        return

    for m in upcoming_matches:
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{m['player1']} vs {m['player2']}**")
            with col2:
                if m.get('scheduled_time'):
                    st.caption(m['scheduled_time'].strftime('%Y-%m-%d %H:%M'))


def render_player_profile():
    """Render the player profile page."""
    # Get player_id from query params or session state
    query_params = st.query_params
    player_id = query_params.get("player_id")

    if not player_id:
        st.warning("No player selected. Please select a player from the Rankings or Events & Draws page.")
        st.stop()

    try:
        player_id = int(player_id)
    except (ValueError, TypeError):
        st.error("Invalid player ID.")
        st.stop()

    # Load player data
    data = load_player_data(player_id)
    if not data:
        st.error("Player not found.")
        st.stop()

    player = data["player"]

    # Page header
    render_page_header(
        title=player["name"],
        description=f"Rating: {player['rating']} | Email: {player['email']}",
        icon="👤"
    )

    # Rating trend
    render_rating_trend(data["rating_history"])

    st.space("medium")

    # Upcoming matches
    render_upcoming_matches(data["upcoming_matches"])

    st.space("medium")

    # Match history
    render_match_history(data["match_history"])


# Note: This code only runs when the file is executed directly by Streamlit
if __name__ == "__main__":
    st.set_page_config(page_title="LIT_IT Player Profile", page_icon="👤", layout="wide")
    apply_global_styles()
    render_player_profile()