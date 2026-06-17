import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from models import SessionLocal, Player, Match

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

st.title("📊 Dashboard")

db = SessionLocal()

# Fetch players
players = db.query(Player).all()
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
        # Create AG-Grid for players
        gb_players = GridOptionsBuilder.from_dataframe(player_df)
        gb_players.configure_pagination(paginationAutoPageSize=True)
        gb_players.configure_side_bar()
        gb_players.configure_selection("single", use_checkbox=False)
        gb_players.configure_columns(
            {"Name": {"width": 150}, "Email": {"width": 150}, "Rating": {"width": 100}}
        )

        grid_response_players = AgGrid(
            player_df,
            gridOptions=gb_players.build(),
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            height=400
        )

        selected_rows = grid_response_players['selected_rows']
        if selected_rows is not None and len(selected_rows) > 0:
            selected_player = selected_rows.iloc[0]
            st.info(f"Selected: {selected_player['Name']} (Rating: {selected_player['Rating']})")
    else:
        st.info("No players registered yet.")

with col2:
    st.subheader("🎾 Recent Matches")

    if not match_df.empty:
        # Create AG-Grid for matches
        gb_matches = GridOptionsBuilder.from_dataframe(match_df)
        gb_matches.configure_pagination(paginationAutoPageSize=True)
        gb_matches.configure_side_bar()
        gb_matches.configure_columns(
            {"Player 1": {"width": 120}, "Player 2": {"width": 120},
             "Winner": {"width": 100}, "Score": {"width": 80}}
        )

        AgGrid(
            match_df,
            gridOptions=gb_matches.build(),
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            height=400
        )
    else:
        st.info("No matches recorded yet.")

# Player Performance Radar Chart
st.divider()
st.subheader("📈 Player Performance Analysis")

if not player_df.empty:
    selected_player_name = st.selectbox(
        "Select a player to view performance stats:",
        options=player_df["Name"].tolist()
    )

    if selected_player_name:
        create_radar_chart(selected_player_name)


