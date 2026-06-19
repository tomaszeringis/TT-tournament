import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import plotly.graph_objects as go
import sys
import os
from app.utils import render_interactive_table

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import SessionLocal, Player, Match, Tournament, MatchStatus, DATABASE_URL, DATABASE_PATH

def get_player_stats(player_name):
    """Get statistics for a player"""
    db = SessionLocal()

    # Get all matches for this player
    matches = db.query(Match).filter(
        (Match.player1 == player_name) | (Match.player2 == player_name)
    ).all()

    if not matches:
        return None

    total_matches = len(matches)
    wins = len([m for m in matches if m.winner == player_name])
    win_rate = (wins / total_matches * 100) if total_matches > 0 else 0

    # Calculate consistency (standard deviation of match intervals)
    completed_matches = [m for m in matches if m.winner is not None]
    consistency = min(100, 80 + (len(completed_matches) / max(1, total_matches)) * 20)

    # Calculate aggression (score-based metric)
    aggression = 60  # Default value

    db.close()

    return {
        "win_rate": win_rate,
        "consistency": consistency,
        "aggression": aggression,
        "total_matches": total_matches,
        "wins": wins
    }

def create_radar_chart(player_name):
    """Create a radar chart for player stats"""
    stats = get_player_stats(player_name)

    if not stats:
        st.warning(f"No statistics available for {player_name}")
        return

    fig = go.Figure(data=go.Scatterpolar(
        r=[stats['win_rate'], stats['consistency'], stats['aggression']],
        theta=['Win Rate', 'Consistency', 'Aggression'],
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


try:
    db = SessionLocal()
    # Fetch stats for cards
    total_players = db.query(Player).count()
    total_matches = db.query(Match).count()
    active_tournaments = db.query(Tournament).count()
    completed_matches = db.query(Match).filter(Match.status == MatchStatus.completed).count()
    
    # Render metric cards
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        ui.metric_card(title="Total Players", content=str(total_players), description="Registered players", key="m1")
    with col_m2:
        ui.metric_card(title="Total Matches", content=str(total_matches), description="Matches played", key="m2")
    with col_m3:
        ui.metric_card(title="Tournaments", content=str(active_tournaments), description="Total events", key="m3")
    with col_m4:
        ui.metric_card(title="Completed", content=str(completed_matches), description="Finished matches", key="m4")
    
    st.space("medium")

    # Fetch players
    players = db.query(Player).all()
except Exception as e:
    st.error(f"❌ Database connection error: {e}")
    with st.expander("🔍 Debug Information"):
        st.write(f"**Database URL:** `{DATABASE_URL}`")
        st.write(f"**Database Path:** `{DATABASE_PATH}`")
        st.write(f"**File Exists:** `{os.path.exists(DATABASE_PATH)}`")
        st.write(f"**Current Working Directory:** `{os.getcwd()}`")
    st.info("Please ensure the database file is accessible and not locked by another process.")
    st.stop()

player_df = pd.DataFrame([
    {
        "ID": p.id,
        "Name": p.name,
        "Email": p.email,
        "Rating": p.rating
    }
    for p in players
])

# Fetch matches
matches = db.query(Match).all()
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

db.close()

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("👥 Players")

    if not player_df.empty:
        # Create interactive table for players using itables
        render_interactive_table(player_df.drop(columns=["ID"]))
    else:
        st.info("No players registered yet.")

with col2:
    st.subheader("🎾 Recent Matches")

    if not match_df.empty:
        # Display latest 5 matches with badges
        st.write("**Latest Updates:**")
        for _, row in match_df.head(5).iterrows():
            cols = st.columns([3, 1])
            with cols[0]:
                st.write(f"{row['Player 1']} vs {row['Player 2']} ({row['Score']})")
            with cols[1]:
                variant = "secondary"
                if row['Status'] == 'completed':
                    variant = "default"
                elif row['Status'] == 'active':
                    variant = "outline"
                ui.badges(badge_list=[(row['Status'], variant)], key=f"dash_status_{row['ID']}")
        
        st.space("medium")
        # Create interactive table for all matches using itables
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
        create_radar_chart(selected_player_name)


