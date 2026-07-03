"""
Public Tournament Board

A read-only display page designed for TV or projector viewing at tournament venues.
Shows current/next matches, standings, and recent results without any admin controls.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import urllib.parse

from tournament_platform.models import SessionLocal
from tournament_platform.app.utils import render_database_error
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_public_schedule,
    get_public_rankings,
)
from tournament_platform.app.components.player_path import render_player_path


def is_kiosk_mode() -> bool:
    """Check if kiosk mode is enabled via query parameter or session state."""
    # Check query parameter
    query_params = st.query_params
    if query_params.get("kiosk") == "1":
        return True
    # Check session state (for sidebar toggle)
    return st.session_state.get("kiosk_mode", False)


def is_public_read_mode() -> bool:
    """Check if public read-only mode is enabled via query parameter."""
    query_params = st.query_params
    return query_params.get("public_read") == "1"


def get_public_url(tournament_id: Optional[int] = None) -> str:
    """Generate the public URL for the current page, optionally with tournament context."""
    # Streamlit doesn't have a get_url() method, use a placeholder that can be overridden
    # In production, this should be set via environment variable or config
    base_url = "http://localhost:8501/public_board"
    if tournament_id:
        return f"{base_url}?tournament={tournament_id}"
    return base_url


# ============================================================================
# Data Loading (cached for performance)
# ============================================================================

@st.cache_data(ttl=30, show_spinner="Loading tournament data...")
def load_tournaments() -> List[Dict[str, Any]]:
    """Load all tournaments from the database."""
    db = SessionLocal()
    try:
        return list_tournaments(db)
    finally:
        db.close()


@st.cache_data(ttl=15, show_spinner="Loading match data...")
def load_tournament_matches(tournament_id: Optional[int], kiosk: bool = False) -> Dict[str, Any]:
    """
    Load matches for a specific tournament, or all matches if tournament_id is None.
    Returns dict with current, next, coming_up, delayed, and recent matches.
    
    In kiosk mode, uses shorter TTL for more responsive updates.
    """
    # In kiosk mode, we want faster updates - use 5 second TTL
    if kiosk:
        # Clear cache and reload for fresh data
        st.cache_data.clear()
    
    db = SessionLocal()
    try:
        matches = get_public_schedule(db, tournament_id=tournament_id)

        # Categorize matches by call_status
        current_matches = [m for m in matches if m.get("call_status") == "active"]
        called_matches = [m for m in matches if m.get("call_status") == "called"]
        next_matches = [m for m in matches if m.get("call_status") in ("queued", "pending", "not_called")]
        delayed_matches = [m for m in matches if m.get("call_status") == "delayed"]
        completed_matches = [m for m in matches if m.get("status") == "completed"]

        # Next match = first queued/called/pending match
        next_match = next_matches[0] if next_matches else None

        # Coming Up = next 3 pending matches
        coming_up = next_matches[:3] if len(next_matches) > 1 else []

        # Recent completed = last 5 completed, ordered by scheduled_time desc
        recent_completed = sorted(
            completed_matches,
            key=lambda m: m.get("scheduled_time") or "",
            reverse=True,
        )[:5]

        return {
            "current": current_matches,
            "called": called_matches,
            "next": next_match,
            "coming_up": coming_up,
            "delayed": delayed_matches,
            "recent": recent_completed,
            "all": matches,
        }
    finally:
        db.close()


@st.cache_data(ttl=60, show_spinner="Loading standings...")
def load_standings(tournament_id: Optional[int]) -> pd.DataFrame:
    """
    Compute standings from completed matches.
    Uses the read model for consistency.
    """
    db = SessionLocal()
    try:
        rankings = get_public_rankings(db, tournament_id=tournament_id)

        if not rankings:
            return pd.DataFrame(columns=["Rank", "Player", "Rating", "Matches", "Wins", "Losses", "Win Rate"])

        rows = []
        for i, r in enumerate(rankings, 1):
            rows.append({
                "Rank": i,
                "Player": r["name"],
                "Rating": r["rating"],
                "Matches": r["matches_played"],
                "Wins": r["wins"],
                "Losses": r["losses"],
                "Win Rate": f"{r['win_rate']:.0f}%",
            })

        df = pd.DataFrame(rows)
        return df
    finally:
        db.close()


@st.cache_data(ttl=30, show_spinner="Loading announcements...")
def load_announcements(limit: int = 10) -> List[Dict[str, Any]]:
    """Load recent announcements from the database."""
    db = SessionLocal()
    try:
        from tournament_platform.services.announcement_service import get_announcements
        return get_announcements(db, limit=limit)
    finally:
        db.close()


# ============================================================================
# UI Rendering
# ============================================================================

def render_match_card(match: Dict[str, Any], label: str = "Match") -> None:
    """Render a large match card for TV/projector display."""
    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    score = match.get("score") or "vs"
    winner = match.get("winner") or "Pending"
    status = match.get("status") or "pending"
    call_status = match.get("call_status") or "not_called"
    location = match.get("location") or "No table"
    round_num = match.get("round_number")

    # Determine status color
    if status == "completed":
        status_icon = "🟢"
        border_color = "#4CAF50"
    elif call_status == "active":
        status_icon = "🔴"
        border_color = "#f44336"
    elif call_status == "called":
        status_icon = "🟡"
        border_color = "#FFC107"
    else:
        status_icon = "🔵"
        border_color = "#2196F3"

    # Build round label
    round_str = f"Round {round_num}" if round_num else ""
    table_str = f"Table {location}" if location and location != "No table" else "No table"
    label_str = " · ".join([x for x in [round_str, table_str] if x])

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
                {status_icon} {label} &nbsp;|&nbsp; {label_str}
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


def render_coming_up_card(match: Dict[str, Any]) -> None:
    """Render a smaller card for coming up matches."""
    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    location = match.get("location") or "No table"
    round_num = match.get("round_number")
    scheduled = match.get("scheduled_time")
    time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"

    st.markdown(
        f"""
        <div style="
            border: 2px solid #2196F3;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background-color: #1e1e1e;
        ">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #aaa; font-size: 12px;">{time_str} · Table {location}</span>
                <span style="font-size: 14px;"><b>{p1}</b> vs <b>{p2}</b></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_delayed_card(match: Dict[str, Any]) -> None:
    """Render a card for delayed matches."""
    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    location = match.get("location") or "No table"
    operator_note = match.get("operator_note") or ""
    scheduled = match.get("scheduled_time")
    time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"

    st.markdown(
        f"""
        <div style="
            border: 2px solid #FF9800;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background-color: #1e1e1e;
        ">
            <div style="font-size: 14px; color: #FF9800; margin-bottom: 4px;">
                ⏸️ DELAYED
            </div>
            <div style="font-size: 16px;"><b>{p1}</b> vs <b>{p2}</b></div>
            <div style="color: #aaa; font-size: 12px;">Table: {location} | Scheduled: {time_str}</div>
            {f'<div style="color: #888; font-size: 12px; margin-top: 4px;">Note: {operator_note}</div>' if operator_note else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_public_board() -> None:
    """Render the public tournament board page."""
    # Check for kiosk mode
    kiosk = is_kiosk_mode()
    
    st.set_page_config(
        page_title="Tournament Board",
        page_icon="🏆",
        layout="wide",
        initial_sidebar_state="collapsed" if kiosk else "expanded",
    )

    # Kiosk mode styling - hide sidebar and footer for clean TV display
    if kiosk:
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
        f"<h1 style='text-align: center;'>🏆 Public Tournament Board</h1>",
        unsafe_allow_html=True,
    )
    st.caption(f"Last updated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Kiosk mode toggle in sidebar (only when not in kiosk mode)
    if not kiosk:
        with st.sidebar:
            st.markdown("---")
            if st.checkbox("📺 Kiosk Mode", value=False, key="kiosk_mode_toggle"):
                st.session_state["kiosk_mode"] = True
                st.rerun()
            st.markdown("---")
            
            # Copy public link button
            public_url = get_public_url()
            st.markdown("**Share this board:**")
            if st.button("📋 Copy Public Link", key="copy_link_btn"):
                st.session_state["copied_url"] = public_url
                st.toast("Link copied to clipboard!", icon="✅")
    
    # Auto-refresh in kiosk mode (every 10 seconds)
    if kiosk:
        st.markdown(
            """
            <script>
            setTimeout(function() {
                window.location.reload();
            }, 10000);
            </script>
            """,
            unsafe_allow_html=True,
        )
    
    # Manual refresh button (only in non-kiosk mode)
    if not kiosk:
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
        match_data = load_tournament_matches(selected_id, kiosk=kiosk)
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
    # Now Playing Section
    # -------------------------------------------------------------------------
    st.subheader("🎾 Now Playing")

    current_matches = match_data.get("current", [])
    called_matches = match_data.get("called", [])

    if current_matches:
        for m in current_matches:
            render_match_card(m, label="LIVE")
    elif called_matches:
        for m in called_matches:
            render_match_card(m, label="CALLED")
    else:
        st.info("No active matches at the moment.")

    # -------------------------------------------------------------------------
    # Next Match Countdown
    # -------------------------------------------------------------------------
    next_match = match_data.get("next")
    if next_match:
        scheduled = next_match.get("scheduled_time")
        if scheduled:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                diff = scheduled_dt - now
                if diff.total_seconds() > 0:
                    mins = int(diff.total_seconds() // 60)
                    secs = int(diff.total_seconds() % 60)
                    st.markdown(
                        f"<div style='text-align: center; font-size: 24px; color: #4CAF50; margin: 10px 0;'>"
                        f"⏰ Next match in: {mins}m {secs}s"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Coming Up Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("⏭️ Coming Up")

    coming_up = match_data.get("coming_up", [])
    if coming_up:
        for m in coming_up:
            render_coming_up_card(m)
    else:
        st.info("No upcoming matches scheduled.")

    # -------------------------------------------------------------------------
    # Delayed Section
    # -------------------------------------------------------------------------
    delayed = match_data.get("delayed", [])
    if delayed:
        st.divider()
        st.subheader("⏸️ Delayed")
        for m in delayed:
            render_delayed_card(m)

    # -------------------------------------------------------------------------
    # Standings Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("📊 Rankings")

    if not standings_df.empty:
        st.dataframe(
            standings_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Player": st.column_config.TextColumn("Player", width="medium"),
                "Rating": st.column_config.NumberColumn("Rating", width="small"),
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
            p1 = m.get("player1") or "TBD"
            p2 = m.get("player2") or "TBD"
            score = m.get("score") or "vs"
            winner = m.get("winner") or "Pending"
            scheduled = m.get("scheduled_time")
            time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"

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
    # Player Lookup Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("🔍 Player Lookup")

    player_name = st.text_input(
        "Enter player name to see their path",
        key="player_lookup_input",
        label_visibility="collapsed",
        placeholder="Type player name...",
    )

    if player_name:
        db = SessionLocal()
        try:
            found = render_player_path(db, player_name, tournament_id=selected_id, key_prefix="public_lookup")
            if not found:
                st.info(f"No matches found for player '{player_name}'")
        except Exception as e:
            st.error(f"Failed to get player path: {e}")
        finally:
            db.close()

    # -------------------------------------------------------------------------
    # Announcements Section
    # -------------------------------------------------------------------------
    st.divider()
    st.subheader("📢 Announcements")

    try:
        announcements = load_announcements(limit=5)
    except Exception as e:
        st.error(f"Failed to load announcements: {e}")
        announcements = []

    if announcements:
        for ann in announcements:
            st.markdown(
                f"""
                <div style="
                    border: 2px solid #4CAF50;
                    border-radius: 8px;
                    padding: 12px;
                    margin: 8px 0;
                    background-color: #1e1e1e;
                ">
                    <div style="font-size: 18px; font-weight: bold; color: #4CAF50;">
                        📣 {ann.get('message', '')}
                    </div>
                    <div style="color: #aaa; font-size: 12px; margin-top: 4px;">
                        {ann.get('created_at', 'N/A')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("No announcements yet.")

    # -------------------------------------------------------------------------
    # Footer timestamp
    # -------------------------------------------------------------------------
    st.divider()
    st.caption(f"🕐 Auto-refreshes every 15 seconds | Last check: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")


if __name__ == "__main__":
    render_public_board()
