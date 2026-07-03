"""
Rankings Panel component for Streamlit UI.

Reusable rankings display that can be embedded in Dashboard or other pages.
Provides leaderboard table and rating history exploration.
"""

import streamlit as st
import pandas as pd

from tournament_platform.services.ranking_service import RatingManager
from tournament_platform.app.utils import render_interactive_table, format_player_label


@st.cache_data(ttl=60, show_spinner="Loading leaderboard...")
def get_cached_leaderboard():
    """Get cached leaderboard data."""
    rm = RatingManager()
    return rm.get_leaderboard()


@st.cache_data(ttl=60, show_spinner="Loading rating history...")
def get_cached_rating_history(player_id: int):
    """Get cached rating history for a player."""
    rm = RatingManager()
    return rm.get_rating_history(player_id)


def clear_cache_after_write():
    """Clear cached data after database writes."""
    st.cache_data.clear()


def render_leaderboard_table(players=None):
    """
    Render the leaderboard table with trend indicators.
    
    Args:
        players: Optional list of player objects. If None, loads from cache.
    """
    if players is None:
        players = get_cached_leaderboard()

    if not players:
        st.info("No rankings data available yet. Complete some matches to see the leaderboard!")
        return

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

    # Display the leaderboard
    render_interactive_table(df.drop(columns=["ID"]))


def render_rating_history_explorer(players=None):
    """
    Render the rating history exploration section.
    
    Args:
        players: Optional list of player objects. If None, loads from cache.
    """
    if players is None:
        players = get_cached_leaderboard()

    if not players:
        st.info("No players available for rating history.")
        return

    st.subheader("📊 Rating History Exploration")

    col1, col2 = st.columns([1, 2])

    with col1:
        selected_player = st.selectbox(
            "Select a player",
            options=players,
            format_func=lambda x: format_player_label(x.name, x.rating)
        )

        view_history = st.button("👁️ View History", key="view_rating_history")

    if view_history and selected_player:
        with col2:
            st.write(f"Showing rating progression for **{selected_player.name}**")
            history = get_cached_rating_history(selected_player.id)

            if history:
                h_data = [{"Timestamp": h.timestamp, "Rating": h.rating} for h in history]
                h_df = pd.DataFrame(h_data)
                h_df = h_df.sort_values("Timestamp")
                h_df.set_index("Timestamp", inplace=True)
                st.line_chart(h_df)
            else:
                st.warning("No rating history found for this player.")


def render_top3_cards(players=None):
    """
    Render top 3 player cards with medals.
    
    Args:
        players: Optional list of player objects. If None, loads from cache.
    """
    if players is None:
        players = get_cached_leaderboard()

    if not players:
        return

    st.markdown("**🏆 Top 3 Players**")
    top3 = players[:3]
    card_cols = st.columns(3)
    for idx, p in enumerate(top3):
        with card_cols[idx]:
            medal = ["🥇", "🥈", "🥉"][idx]
            # Get wins/losses from history
            history = sorted(p.rating_history, key=lambda x: x.timestamp)
            wins = sum(1 for h in history if h.rating > getattr(h, '_prev_rating', h.rating))
            losses = len(history) - wins
            st.metric(
                label=f"{medal} {p.name}",
                value=f"{p.rating} pts",
                delta=f"{wins}W - {losses}L",
            )


def render_rankings_panel(show_top3=True, show_history=True):
    """
    Render the complete rankings panel.
    
    Args:
        show_top3: Whether to show top 3 cards
        show_history: Whether to show rating history explorer
    """
    players = get_cached_leaderboard()

    if show_top3:
        render_top3_cards(players)

    st.space("small")
    st.markdown("**📋 Full Leaderboard**")
    render_leaderboard_table(players)

    if show_history:
        st.space("medium")
        render_rating_history_explorer(players)
