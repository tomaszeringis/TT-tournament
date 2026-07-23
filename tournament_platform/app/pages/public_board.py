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
import time
import os

from tournament_platform.models import SessionLocal, Tournament, TournamentParticipant
from tournament_platform.app.services.public_board_service import get_public_board_state, build_public_board_url, make_qr_png_bytes
from tournament_platform.app.utils import render_database_error
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_public_schedule,
)
from tournament_platform.services.standings_service import get_standings
from tournament_platform.app.services.registration_service import get_registration_link, get_registration_stats
from tournament_platform.app.components.player_path import render_player_path
from tournament_platform.app.components.pairing_explanation_component import render_pairing_expander
from tournament_platform.app.design_system import (
    COLORS,
    BRAND,
    apply_global_styles,
    render_litit_match_card,
    render_litit_coming_up_card,
    render_litit_delayed_card,
    render_litit_announcement_card,
    render_litit_result_row,
    render_qr_code_visible,
    render_status_chip,
    render_game_scores_strip,
    render_public_match_card,
    render_public_coming_up_card,
    render_public_delayed_card,
    render_public_result_row,
)
from tournament_platform.app.components.tour import render_tour
from tournament_platform.config import settings


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


def _get_app_base_url() -> str:
    """Return the best available base URL for public links."""
    base = (settings.PUBLIC_BOARD_BASE_URL or "").strip()
    if base:
        return base.rstrip("/")
    try:
        origin = st.context.headers.get("origin")
        if origin:
            return origin.rstrip("/")
    except Exception:
        pass
    env_base = os.environ.get("STREAMLIT_SERVER_BASE_URL") or os.environ.get("STREAMLIT_APP_URL")
    if env_base:
        return env_base.rstrip("/")
    return ""


@st.cache_data(ttl=30)
def load_registration_stats(tournament_id: int):
    """Load registration/check-in stats for a tournament.

    Returns a tuple of (stats, registration_open, token_present).
    """
    db = SessionLocal()
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        registration_open = bool(tournament.registration_open) if tournament else False
        token_present = bool(tournament.public_registration_token_hash) if tournament else False
        stats = get_registration_stats(db, tournament_id)
        return stats, registration_open, token_present
    finally:
        db.close()


def render_freshness_bar(kiosk: bool) -> None:
    """Render the data-freshness and auto-refresh-state chips."""
    from tournament_platform.config import settings
    from tournament_platform.app.services.public_board_service import compute_freshness
    from tournament_platform.app.design_system import render_status_chip, render_chip

    stale_seconds = settings.PUBLIC_BOARD_STALE_SECONDS
    ts = st.session_state.get("pb_data_ts")
    loaded_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    freshness = compute_freshness(loaded_at, stale_seconds)

    chip_color = "green" if freshness.state == "fresh" else "amber" if freshness.state == "stale" else "default"
    render_status_chip(freshness.message, color=chip_color)

    refresh_color = "green" if kiosk else "blue"
    refresh_label = "Auto-refresh: ON" if kiosk else "Auto-refresh: OFF"
    render_chip(refresh_label, color=refresh_color)


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
    db = SessionLocal()
    try:
        matches = get_public_schedule(db, tournament_id=tournament_id)

        from tournament_platform.app.services.public_board_service import classify_public_board_match

        lanes = {"now": [], "coming_up": [], "delayed": [], "recent": []}
        for m in matches:
            lane = classify_public_board_match(m)
            lanes[lane].append(m)

        current_matches = lanes["now"]
        called_matches = [m for m in lanes["coming_up"] if m.get("call_status") == "called"]
        next_candidates = [m for m in lanes["coming_up"] if m.get("call_status") != "called"]
        delayed_matches = lanes["delayed"]
        completed_matches = [m for m in lanes["recent"] if m.get("status") == "completed"]

        next_match = next_candidates[0] if next_candidates else None
        coming_up = next_candidates[1:4] if len(next_candidates) > 1 else []
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
    Uses the standings service for tie-break aware rankings.
    """
    db = SessionLocal()
    try:
        standings = get_standings(db, tournament_id=tournament_id)

        if not standings:
            return pd.DataFrame(columns=["Rank", "Player", "Rating", "Matches", "Wins", "Losses", "Win Rate"])

        rows = []
        for i, s in enumerate(standings, 1):
            rows.append({
                "Rank": i,
                "Player": s["name"],
                "Rating": s.get("rating") or 0,
                "Matches": s["matches_played"],
                "Wins": s["wins"],
                "Losses": s["losses"],
                "Win Rate": f"{(s['wins'] / s['matches_played'] * 100):.0f}%" if s["matches_played"] > 0 else "0%",
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

def render_match_card(match: Dict[str, Any], label: str = "Match", insight=None) -> None:
    """Render a large match card for TV/projector display."""
    render_public_match_card(match, label=label, game_scores=match.get("game_scores"), insight=insight)


def render_coming_up_card(match: Dict[str, Any]) -> None:
    """Render a smaller card for coming up matches."""
    render_public_coming_up_card(match, call_status=match.get("call_status", "not_called"))


def render_delayed_card(match: Dict[str, Any]) -> None:
    """Render a card for delayed matches."""
    render_public_delayed_card(match)


def render_public_board() -> None:
    """Render the public tournament board page."""
    kiosk = is_kiosk_mode()
    
    st.set_page_config(
        page_title=f"{BRAND['name']} Tournament Board",
        page_icon=BRAND["favicon"],
        layout="wide",
        initial_sidebar_state="collapsed" if kiosk else "expanded",
    )

    apply_global_styles()

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

    now = datetime.now(timezone.utc)
    st.markdown(
        f"<h1 style='text-align: center;'>🏆 {BRAND['name']} Tournament Board</h1>",
        unsafe_allow_html=True,
    )
    render_tour("public_board")
    # --- Tournament selector BEFORE sidebar/header to avoid selected_id crash ---
    try:
        tournaments = load_tournaments()
        st.session_state["pb_data_ts"] = time.time()
    except Exception as e:
        render_database_error(e, "tournaments")
        st.stop()

    if not tournaments:
        st.info("📭 No tournaments found. Create a tournament to get started.")
        st.stop()

    tournament_options = {t["name"]: t["id"] for t in tournaments}
    selected_name = st.selectbox(
        "Select Tournament",
        options=list(tournament_options.keys()),
        index=0,
        key="public_tournament_select",
        label_visibility="collapsed",
    )
    selected_id = tournament_options[selected_name]

    # --- Data loads ---
    try:
        match_data = load_tournament_matches(selected_id, kiosk=kiosk)
        st.session_state["pb_data_ts"] = time.time()
    except Exception as e:
        render_database_error(e, "match data")
        st.stop()

    try:
        standings_df = load_standings(selected_id)
    except Exception as e:
        render_database_error(e, "standings")
        st.stop()

    # --- Live match insights (batch-load point events) ---
    live_match_ids = [m["id"] for m in match_data.get("current", []) + match_data.get("called", []) if m.get("id")]
    insights: Dict[int, Any] = {}
    if live_match_ids:
        try:
            from tournament_platform.app.services.live_match_insights_service import batch_compute_insights
            db_insights = SessionLocal()
            try:
                insights = batch_compute_insights(live_match_ids, db_insights)
            except Exception:
                insights = {}
            finally:
                db_insights.close()
        except Exception:
            insights = {}

    # --- Freshness + Action header ---
    from tournament_platform.app.services.public_board_service import compute_freshness, BoardFreshness
    from tournament_platform.config import settings
    from tournament_platform.app.design_system import render_status_chip

    stale_seconds = settings.PUBLIC_BOARD_STALE_SECONDS
    ts = st.session_state.get("pb_data_ts")
    loaded_at_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    freshness = compute_freshness(loaded_at_dt, stale_seconds)

    col_name, col_fresh, col_refresh = st.columns([3, 2, 1])
    with col_name:
        st.caption(selected_name)
    with col_fresh:
        chip_color = "green" if freshness.state == "fresh" else "amber" if freshness.state == "stale" else "default"
        render_status_chip(freshness.message, color=chip_color)
    with col_refresh:
        auto_on = st.toggle("Auto-refresh", value=kiosk, key="auto_refresh_toggle", label_visibility="collapsed")

    # Action row: Share Live Board + Register/Check-In
    col_share, col_reg = st.columns(2)
    with col_share:
        st.markdown("**Share Live Board**")
        st.caption("Scan to follow scores on your phone")
        share_url = build_public_board_url(_get_app_base_url(), tournament_id=selected_id, kiosk=kiosk)
        st.markdown(f"`{share_url}`")
        if st.button("📋 Copy", key="copy_link_btn", use_container_width=True):
            st.session_state["copied_url"] = share_url
            st.toast("Link copied!", icon="✅")
        render_qr_code_visible(share_url, width=180)

    if settings.ENABLE_SELF_REGISTRATION:
        with col_reg:
            try:
                db_reg = SessionLocal()
                tournament = db_reg.query(Tournament).filter(Tournament.id == selected_id).first()
                registration_open = bool(tournament.registration_open) if tournament else False
                token_present = bool(tournament.public_registration_token_hash) if tournament else False
                db_reg.close()

                if registration_open:
                    reg_link = None
                    if not token_present:
                        db_reg2 = SessionLocal()
                        try:
                            from tournament_platform.app.services.registration_service import set_registration_token
                            token = set_registration_token(db_reg2, selected_id)
                            reg_link = get_registration_link(token, selected_id, base_url=_get_app_base_url())
                        except Exception:
                            reg_link = None
                        finally:
                            db_reg2.close()
                    else:
                        reg_link = build_public_board_url(_get_app_base_url(), tournament_id=selected_id, kiosk=False).replace("public=1", "public=1&register=1")

                    if reg_link:
                        reg_label = "Register to play" if registration_open else "Check In"
                        st.markdown(f"**{reg_label}**")
                        st.caption("Scan to register or check in")
                        st.markdown(f"`{reg_link}`")
                        if st.button("📋 Copy", key="copy_reg_link_btn", use_container_width=True):
                            st.session_state["copied_url"] = reg_link
                            st.toast("Registration link copied!", icon="✅")
                        render_qr_code_visible(reg_link, width=180)
                    else:
                        st.caption("Registration closed for this tournament.")
                else:
                    st.caption("Registration is closed for this tournament.")
            except Exception:
                pass

    # --- Sidebar (safe now that selected_id is defined) ---
    if not kiosk:
        with st.sidebar:
            st.markdown("---")
            if st.checkbox("📺 Kiosk Mode", value=False, key="kiosk_mode_toggle"):
                st.session_state["kiosk_mode"] = True
                st.rerun()
            st.markdown("---")

    # --- Kiosk auto-refresh ---
    if kiosk and auto_on:
        st.markdown(
            """
            <script>
            setTimeout(function() {
                window.location.reload();
            }, 5000);
            </script>
            """,
            unsafe_allow_html=True,
        )

    # --- Manual refresh ---
    if not kiosk:
        col_refresh_btn, col_spacer = st.columns([1, 5])
        with col_refresh_btn:
            if st.button("🔄 Refresh", use_container_width=True, key="public_refresh"):
                st.rerun()

    st.divider()

    current_matches = match_data.get("current", [])
    called_matches = match_data.get("called", [])
    next_match = match_data.get("next")
    coming_up = match_data.get("coming_up", [])
    delayed = match_data.get("delayed", [])
    recent = match_data.get("recent", [])

    tab_now, tab_coming, tab_delayed, tab_recent, tab_rankings = st.tabs([
        "🎾 Now Playing",
        "⏭️ Coming Up",
        "⏸️ Delayed",
        "📋 Recent Results",
        "📊 Rankings",
    ])

    with tab_now:
        if current_matches:
            for m in current_matches:
                render_match_card(m, label="LIVE", insight=insights.get(m.get("id")))
                render_pairing_expander(m)
        elif called_matches:
            for m in called_matches:
                render_match_card(m, label="CALLED", insight=insights.get(m.get("id")))
                render_pairing_expander(m)
        else:
            st.info("No active matches at the moment.")

    with tab_coming:
        if coming_up:
            active_locations = {m.get("location") for m in current_matches if m.get("location")} | {m.get("location") for m in called_matches if m.get("location")}
            for m in coming_up:
                render_coming_up_card(m)
                render_pairing_expander(m)
                if m.get("location") and m.get("location") in active_locations:
                    st.caption("⏳ Waiting for previous match on this table")
        else:
            st.info("No upcoming matches scheduled.")

    with tab_delayed:
        if delayed:
            for m in delayed:
                render_delayed_card(m)
        else:
            st.success("No delayed matches.")

    with tab_recent:
        if recent:
            for m in recent:
                p1 = m.get("player1") or "TBD"
                p2 = m.get("player2") or "TBD"
                score = m.get("score") or "vs"
                winner = m.get("winner") or "Pending"
                scheduled = m.get("scheduled_time")
                time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"
                render_public_result_row(p1, p2, score, winner, time_str, game_scores=m.get("game_scores"))
        else:
            st.info("No completed matches yet.")

    with tab_rankings:
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

    st.divider()
    st.subheader("📢 Announcements")
    try:
        announcements = load_announcements(limit=5)
    except Exception as e:
        st.error(f"Failed to load announcements: {e}")
        announcements = []

    if announcements:
        for ann in announcements:
            render_litit_announcement_card(
                ann.get('message', ''),
                ann.get('created_at', 'N/A'),
            )
    else:
        st.info("No announcements yet.")

    st.divider()
    refresh_note = "Auto-refreshes every 5s (kiosk)" if kiosk else "Use Refresh to update manually"
    st.caption(f"🕐 {refresh_note}")
    render_brand_footer()


if __name__ == "__main__":
    render_public_board()
