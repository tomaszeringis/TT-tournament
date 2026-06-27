import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import plotly.graph_objects as go
from tournament_platform.app.utils import (
    render_interactive_table,
    render_database_error,
    render_status_badge,
    render_metric_cards,
)

from tournament_platform.models import SessionLocal, Player, Match, Tournament, MatchStatus
from tournament_platform.config import settings


@st.cache_data(ttl=300, show_spinner="Loading dashboard data...")
def load_dashboard_data():
    """Load all dashboard data in a single cached database session."""
    db = SessionLocal()
    try:
        total_players = db.query(Player).count()
        total_matches = db.query(Match).count()
        active_tournaments = db.query(Tournament).count()
        completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()

        players = db.query(Player).all()
        matches = db.query(Match).all()

        player_df = pd.DataFrame([
            {
                "ID": p.id,
                "Name": p.name,
                "Email": p.email,
                "Rating": p.rating
            }
            for p in players
        ])

        match_df = pd.DataFrame([
            {
                "ID": m.id,
                "Player 1": m.player1,
                "Player 2": m.player2,
                "Winner": m.winner or "Pending",
                "Score": m.score or "-",
                "Status": m.status.value if m.status else "pending"
            }
            for m in matches
        ])

        # Build a lookup: player_name -> list of matches
        player_matches = {}
        for m in matches:
            for p_name in (m.player1, m.player2):
                if p_name not in player_matches:
                    player_matches[p_name] = []
                player_matches[p_name].append(m)

        return {
            "metrics": {
                "total_players": total_players,
                "total_matches": total_matches,
                "active_tournaments": active_tournaments,
                "completed_matches": completed_matches,
            },
            "player_df": player_df,
            "match_df": match_df,
            "player_matches": player_matches,
        }
    finally:
        db.close()


@st.cache_data(ttl=300, show_spinner="Computing player statistics...")
def compute_player_stats(player_name, player_matches):
    """Compute statistics for a player using pre-fetched match data."""
    matches = player_matches.get(player_name, [])
    if not matches:
        return None

    total_matches = len(matches)
    # Find player id from match data to determine wins
    # We use player name matching since player1/player2 are stored as names
    wins = sum(1 for m in matches if m.winner == player_name)
    win_rate = (wins / total_matches * 100) if total_matches > 0 else 0

    # Calculate consistency (standard deviation of match intervals)
    completed_matches = [m for m in matches if m.winner is not None]
    consistency = min(100, 80 + (len(completed_matches) / max(1, total_matches)) * 20)

    # Synthetic metric: aggression (placeholder until score parsing is implemented)
    aggression = 60  # Placeholder value — replace with real calculation when score data is available

    return {
        "win_rate": round(win_rate, 1),
        "consistency": round(consistency, 1),
        "aggression": aggression,  # Labeled as synthetic in the chart
        "total_matches": total_matches,
        "wins": wins,
    }


def create_radar_chart(player_name, player_matches):
    """Create a radar chart for player stats using cached data."""
    stats = compute_player_stats(player_name, player_matches)

    if not stats:
        st.warning(f"No statistics available for {player_name}")
        return

    fig = go.Figure(data=go.Scatterpolar(
        r=[stats['win_rate'], stats['consistency'], stats['aggression']],
        theta=['Win Rate', 'Consistency', 'Aggression (synthetic)'],
        fill='toself',
        name=player_name
    ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        height=500,
        title=f"Player Performance: {player_name}"
    )

    st.plotly_chart(fig, use_container_width=True)


def render_dashboard():
    """Render the optimized dashboard page."""
    st.title("📊 Tournament Dashboard")

    try:
        data = load_dashboard_data()
    except Exception as e:
        render_database_error(e, "dashboard data")
        st.stop()

    metrics = data["metrics"]
    player_df = data["player_df"]
    match_df = data["match_df"]
    player_matches = data["player_matches"]

    # Render metric cards
    render_metric_cards([
        {"title": "Total Players", "content": metrics["total_players"], "description": "Registered players"},
        {"title": "Total Matches", "content": metrics["total_matches"], "description": "Matches played"},
        {"title": "Tournaments", "content": metrics["active_tournaments"], "description": "Total events"},
        {"title": "Completed", "content": metrics["completed_matches"], "description": "Finished matches"},
    ])

    st.space("medium")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("👥 Players")

        if not player_df.empty:
            render_interactive_table(player_df.drop(columns=["ID"]))
        else:
            st.info("No players registered yet.")

    with col2:
        st.subheader("🎾 Recent Matches")

        if not match_df.empty:
            st.write("**Latest Updates:**")
            for _, row in match_df.head(5).iterrows():
                cols = st.columns([3, 1])
                with cols[0]:
                    st.write(f"{row['Player 1']} vs {row['Player 2']} ({row['Score']})")
                with cols[1]:
                    render_status_badge(row['Status'], key=f"dash_status_{row['ID']}")

            st.space("medium")
            render_interactive_table(match_df.drop(columns=["ID"]))
        else:
            st.info("No matches recorded yet.")

    # Player Performance Radar Chart
    st.space("medium")
    st.subheader("📈 Player Performance Analysis")

    if not player_df.empty:
        selected_player_name = st.selectbox(
            "Select a player to view performance stats:",
            options=player_df["Name"].tolist()
        )

        if selected_player_name:
            create_radar_chart(selected_player_name, player_matches)


if __name__ == "__main__":
    render_dashboard()
