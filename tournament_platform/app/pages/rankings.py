import streamlit as st
import pandas as pd

from tournament_platform.services.ranking_service import RatingManager
from tournament_platform.models import SessionLocal, Player
from tournament_platform.app.utils import render_interactive_table, format_player_label

st.title("🏆 Player Rankings")
st.space("medium")

rm = RatingManager()
players = rm.get_leaderboard()

if not players:
    st.info("No rankings data available yet. Complete some matches to see the leaderboard!")
else:
    data = []
    for p in players:
        # Get trend from history
        history = sorted(p.rating_history, key=lambda x: x.timestamp)
        trend = "➖"
        if len(history) >= 2:
            last = history[-1].rating
            prev = history[-2].rating
            if last > prev:
                trend = "🔼"
            elif last < prev:
                trend = "🔽"
        
        data.append({
            "Player": p.name,
            "Rating": p.rating,
            "Trend": trend,
            "ID": p.id
        })
    
    df = pd.DataFrame(data)
    df.index = range(1, len(df) + 1)
    df.index.name = "Rank"
    
    # Display the leaderboard using itables
    render_interactive_table(df.drop(columns=["ID"]))

    st.space("medium")
    
    st.subheader("📊 Rating History Exploration")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        selected_player = st.selectbox(
            "Select a player", 
            options=players, 
            format_func=lambda x: format_player_label(x.name, x.rating)
        )
        
        view_history = st.button("👁️ View History")
    
    if view_history and selected_player:
        with col2:
            st.write(f"Showing rating progression for **{selected_player.name}**")
            history = rm.get_rating_history(selected_player.id)
            
            if history:
                h_data = [{"Timestamp": h.timestamp, "Rating": h.rating} for h in history]
                h_df = pd.DataFrame(h_data)
                h_df = h_df.sort_values("Timestamp")
                h_df.set_index("Timestamp", inplace=True)
                st.line_chart(h_df)
            else:
                st.warning("No rating history found for this player.")
