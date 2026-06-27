"""
Public Tournament Board

A read-only display page designed for TV or projector viewing at tournament venues.
Shows current/next matches, standings, and recent results without any admin controls.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from tournament_platform.models import SessionLocal, Tournament, Match, MatchStatus, Player
from tournament_platform.app.utils import format_match_label, format_match_score, render_database_error


# ============================================================================
# Data Loading (cached for performance)
# ============================================================================

@st.cache_data(ttl=30, show_spinner="Loading tournament data...")
def load_tournaments() -> List[Dict[str, Any]]:
    """Load all tournaments from the database."""
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).order_by(Tournament.created_at.desc()).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "type": t.tournament_type.value if t.tournament_type else "knockout",
                "created_at": t.created_at,
            }
            for t in tournaments
        ]
    finally:
        db.close()


@st.cache_data(ttl=15, show_spinner="Loading match data...")
def load_tournament_matches(tournament_id: Optional[int]) -> Dict[str, Any]:
    """
    Load matches for a specific tournament, or all matches if tournament_id is None.
    Returns dict with current, next, and recent matches.
    """
    db = SessionLocal()
    try:
        query = db.query(Match)
        if tournament_id is not None:
            query = query.filter(Match.tournament_id == tournament_id)

        matches = query.order_by(Match.scheduled_time.asc()).all()

        # Categorize matches
        current_matches = [m for m in matches if m.status == MatchStatus.active]
        pending_matches = [m for m in matches if m.status == MatchStatus.pending]
        completed_matches = [m for m in matches if m.status == MatchStatus.completed]

        # Next match = first pending match
        next_match = pending_matches[0] if pending_matches else None

        # Recent completed = last 5 completed, ordered by scheduled_time desc
        recent_completed = sorted(
            completed_matches,
            key=lambda m: m.scheduled_time or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:5]

        return {
            "current": current_matches,
            "next": next_match,
            "recent": recent_completed,
            "all": matches,
        }
    finally:
        db.close()


@st.cache_data(ttl=60, show_spinner="Loading standings...")
def load_standings(tournament_id: Optional[int]) -> pd.DataFrame:
    """
    Compute standings from completed matches.
    Uses the same logic as the dashboard for consistency.
    """
    db = SessionLocal()
    try:
        query = db.query(Match)
        if tournament_id is not None:
            query = query.filter(Match.tournament_id == tournament_id)

        matches = query.filter(Match.status == MatchStatus.completed).all()

        # Build stats: player_name -> {wins, losses, matches}
        stats: Dict[str, Dict[str, Any]] = {}
        for m in matches:
            for p_name in (m.player1, m.player2):
                if p_name not in stats:
                    stats[p_name] = {"wins": 0, "losses": 0, "matches": 0, "name": p_name}
                stats[p_name]["matches"] += 1
                if m.winner == p_name:
                    stats[p_name]["wins"] += 1
                else:
                    stats[p_name]["losses"] += 1

        if not stats:
            return pd.DataFrame(columns=["Player", "Matches", "Wins", "Losses", "Win Rate"])

        rows = []
        for name, s in stats.items():
            win_rate = (s["wins"] / s["matches"] * 100) if s["matches"] > 0 else 0.0
            rows.append({
                "Player": name,
                "Matches": s["matches"],
                "Wins": s["wins"],
                "Losses": s["losses"],
                "Win Rate": f"{win_rate:.0f}%",
            })

        df = pd.DataFrame(rows)
        df = df.sort_values(by=["Wins", "Win Rate"], ascending=[False, False]).reset_index(drop=True)
        return df
    finally:
        db.close()


# ============================================================================
# UI Rendering
# ============================================================================

def render_match_card(match: Match, label: str = "Match") -> None:
    """Render a large match card for TV/projector display."""
    p1 = match.player1 or "TBD"
    p2 = match.player2 or "TBD"
    score = match.score or "vs"
    winner = match.winner or "Pending"
    status = match.status.value if match.status else "pending"

    # Determine status color
    if status == "completed":
        status_icon = "🟢"
        border_color = "#4CAF50"
    elif status == "active":
        status_icon = "🔴"
        border_color = "#f44336"
    else:
        status_icon = "🟡"
        border_color = "#FFC107"

    st.markdown(
        f"""
        <div style="
            border: 3px solid {border_color};
            border-radius: 12px;
            padding: 20px;
            margin: 10px 0;
            background-color: #1e1e1e;
        ">
            <div style="text-align: center; font-size: 14px; color: #aaa; margin-bottom: 8px;">
                {status_icon} {label} &nbsp;|&nbsp; {status.upper()}
            </div>
            <div style="display: flex; justify-content: space-around; align-items: center;">
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 28px; font-weight: bold; color: #fff;">
                        {p1}
                    </div>
                    <div style="font-size: 48px; font-weight: bold; color: {'#4CAF50' if winner == p1 else '#fff'};">
                        {score.split('-')[0] if '-' in score else score}
                    </div>
                </div>
                <div style="font-size: 36px; color: #888; padding: 0 20px;">VS</div>
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 28px; font-weight: bold; color: #fff;">
                        {p2}
                    </div>
                    <div style="font-size: 48px; font-weight: bold; color: {'#4CAF50' if winner == p2 else '#fff'};">
                        {score.split('-')[1] if '-' in score else score}
                    </div>
                </div>
            </div>
            <div style="text-align: center; font-size: 16px; color: #aaa; margin-top: 8px;">
                Winner: {winner}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_public_board() -> None:
    """Render the public tournament board page."""
    st.set_page_config(
        page_title="Tournament Board",
        page_icon="🏆",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Hide sidebar and footer for clean TV display
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none; }
        footer { visibility: hidden; }
        header { visibility: hidden; }
        .main > div { padding-top: 1rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Title with timestamp
    now = datetime.now(timezone.utc)
    st.markdown(
        f"<h1 style='text-align: center;'>🏆 Tournament Board</h1>",
        unsafe_allow_html=True,
    )
    st.caption(f"Last updated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Manual refresh button
    col_refresh, col_spacer = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh", use_container_width=True, key="public_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.divider()

    # Load tournaments
    try:
        tournaments = load_tournaments()
    except Exception as e:
        render_database_error(e, "tournaments")
        st.stop()

    if not tournaments:
        st.info("📭 No tournaments found. Create a tournament to get started.")
        st.stop()

    # Tournament selector
    tournament_options = {t["name"]: t["id"] for t in tournaments}
    selected_name = st.selectbox(
        "Select Tournament",
        options=list(tournament_options.keys()),
        index=0,
        key="public_tournament_select",
        label_visibility="collapsed",
    )
    selected_id = tournament_options[selected_name]

    # Load match data for selected tournament
    try:
        match_data = load_tournament_matches(selected_id)
    except Exception as e:
        render_database_error(e, "match data")
        st.stop()

    # Load standings
    try:
        standings_df = load_standings(selected_id)
    except Exception as e:
        render_database_error(e, "standings")
        st.stop()

    # -------------------------------------------------------------------------
    # Current / Next Match Section
    # -------------------------------------------------------------------------
    st.subheader("🎾 Current & Next Match")

    current_matches = match_data.get("current", [])
    next_match = match_data.get("next")

    if current_matches:
        for m in current_matches:
            render_match_card(m, label="LIVE")
    elif next_match:
        render_match_card(next_match, label="UP NEXT")
    else:
        st.info("No active or upcoming matches scheduled.")

    # -------------------------------------------------------------------------
    # Standings Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("📊 Standings")

    if not standings_df.empty:
        # Format for display
        display_df = standings_df.copy()
        display_df.index = display_df.index + 1  # 1-based ranking
        display_df.index.name = "Rank"
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=False,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Player": st.column_config.TextColumn("Player", width="medium"),
                "Matches": st.column_config.NumberColumn("Matches", width="small"),
                "Wins": st.column_config.NumberColumn("Wins", width="small"),
                "Losses": st.column_config.NumberColumn("Losses", width="small"),
                "Win Rate": st.column_config.TextColumn("Win Rate", width="small"),
            },
        )
    else:
        st.info("No completed matches yet. Standings will appear after matches are played.")

    # -------------------------------------------------------------------------
    # Recent Results Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("📋 Recent Results")

    recent = match_data.get("recent", [])
    if recent:
        for m in recent:
            p1 = m.player1 or "TBD"
            p2 = m.player2 or "TBD"
            score = m.score or "vs"
            winner = m.winner or "Pending"
            scheduled = m.scheduled_time
            time_str = scheduled.strftime("%H:%M") if scheduled else "--:--"

            st.markdown(
                f"""
                <div style="
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 10px 16px;
                    border-bottom: 1px solid #333;
                ">
                    <span style="color: #aaa; font-size: 14px;">{time_str}</span>
                    <span style="flex: 1; text-align: center; font-size: 18px;">
                        <b>{p1}</b> {score} <b>{p2}</b>
                    </span>
                    <span style="color: #4CAF50; font-size: 14px;">🏆 {winner}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("No completed matches yet.")

    # -------------------------------------------------------------------------
    # Footer timestamp
    # -------------------------------------------------------------------------
    st.divider()
    st.caption(f"🕐 Auto-refreshes every 15 seconds | Last check: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")


if __name__ == "__main__":
    render_public_board()
