"""
Public Tournament Board — Read-only renderer for embedded/public display.

This module is designed to be imported and called from ``main.py`` when
``?public=1`` is detected in the query parameters. No auth or navigation is
rendered here.

IMPORTANT: This module does NOT call ``st.set_page_config``. ``main.py`` must
call it before importing/running this module.
"""

import streamlit as st
import urllib.parse
import time
import os
from datetime import datetime, timezone

from tournament_platform.models import SessionLocal, Tournament, TournamentParticipant
from tournament_platform.app.utils import render_database_error
from tournament_platform.app.services.public_board_service import get_public_board_state, build_public_board_url, make_qr_png_bytes, BoardFreshness, compute_freshness
from tournament_platform.app.services.live_match_insights_service import batch_compute_insights
from tournament_platform.app.services.registration_service import get_registration_link
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
    render_public_match_card,
    render_public_coming_up_card,
    render_public_delayed_card,
    render_public_result_row,
)
from tournament_platform.app.components.tour import render_tour
from tournament_platform.config import settings


# ============================================================================
# Query-param helpers
# ============================================================================

def is_kiosk_mode() -> bool:
    query_params = st.query_params
    if query_params.get("kiosk") == "1":
        return True
    return st.session_state.get("kiosk_mode", False)


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


# ============================================================================
# Render function (importable, no set_page_config)
# ============================================================================

def render_public_board_readonly() -> None:
    """Render the read-only public tournament board."""
    kiosk = is_kiosk_mode()

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

    st.markdown(
        f"<h1 style='text-align: center;'>🏆 {BRAND['name']} Tournament Board</h1>",
        unsafe_allow_html=True,
    )
    if "active_tournament_id" not in st.session_state:
        st.session_state["active_tournament_id"] = None

    selected_id = st.session_state.get("active_tournament_id")

    # Auto-select from query param if provided
    query_tournament = st.query_params.get("tournament")
    if query_tournament is not None:
        try:
            selected_id = int(query_tournament)
            st.session_state["active_tournament_id"] = selected_id
        except (ValueError, TypeError):
            pass

    # Kiosk auto-refresh
    if kiosk:
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

    # Manual refresh
    if not kiosk:
        if st.button("🔄 Refresh", use_container_width=True, key="public_readonly_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.divider()

    # Load data
    try:
        db = SessionLocal()
        state = get_public_board_state(db, selected_id)
        db.close()
        st.session_state["active_tournament_id"] = state.tournament_id
        selected_id = state.tournament_id
        st.session_state["pb_data_ts"] = time.time()
    except Exception as e:
        render_database_error(e, "tournaments")
        st.stop()

    if not state.all_matches:
        st.info("📭 No tournaments found. Create a tournament to get started.")
        st.stop()

    # --- Live match insights (batch-load point events) ---
    live_match_ids = [m["id"] for m in state.live_matches + state.called_matches if m.get("id")]
    insights = {}
    if live_match_ids:
        try:
            db_insights = SessionLocal()
            try:
                insights = batch_compute_insights(live_match_ids, db_insights)
            finally:
                db_insights.close()
        except Exception:
            insights = {}

    # --- Freshness + Action header ---
    from tournament_platform.config import settings

    stale_seconds = settings.PUBLIC_BOARD_STALE_SECONDS
    ts = st.session_state.get("pb_data_ts")
    loaded_at_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    freshness = compute_freshness(loaded_at_dt, stale_seconds)

    col_name, col_fresh = st.columns([4, 1])
    with col_name:
        st.caption(state.tournament_name)
    with col_fresh:
        chip_color = "green" if freshness.state == "fresh" else "amber" if freshness.state == "stale" else "default"
        render_status_chip(freshness.message, color=chip_color)

    # Action row: Share Live Board + Register/Check-In
    col_share, col_reg = st.columns(2)
    with col_share:
        st.markdown("**Share Live Board**")
        st.caption("Scan to follow scores on your phone")
        share_url = build_public_board_url(_get_app_base_url(), tournament_id=state.tournament_id, kiosk=kiosk)
        st.markdown(f"`{share_url}`")
        if st.button("📋 Copy", key="copy_link_readonly_btn", use_container_width=True):
            st.session_state["copied_url"] = share_url
            st.toast("Link copied!", icon="✅")
        render_qr_code_visible(share_url, width=180)

    if settings.ENABLE_SELF_REGISTRATION:
        with col_reg:
            try:
                db_reg = SessionLocal()
                tournament = db_reg.query(Tournament).filter(Tournament.id == state.tournament_id).first()
                registration_open = bool(tournament.registration_open) if tournament else False
                token_present = bool(tournament.public_registration_token_hash) if tournament else False
                db_reg.close()

                if registration_open:
                    reg_link = None
                    if not token_present:
                        db_reg2 = SessionLocal()
                        try:
                            from tournament_platform.app.services.registration_service import set_registration_token
                            token = set_registration_token(db_reg2, state.tournament_id)
                            reg_link = get_registration_link(token, state.tournament_id, base_url=_get_app_base_url())
                        except Exception:
                            reg_link = None
                        finally:
                            db_reg2.close()
                    else:
                        reg_link = build_public_board_url(_get_app_base_url(), tournament_id=state.tournament_id, kiosk=False).replace("public=1", "public=1&register=1")

                    if reg_link:
                        reg_label = "Register to play" if registration_open else "Check In"
                        st.markdown(f"**{reg_label}**")
                        st.caption("Scan to register or check in")
                        st.markdown(f"`{reg_link}`")
                        if st.button("📋 Copy", key="copy_reg_link_readonly_btn", use_container_width=True):
                            st.session_state["copied_url"] = reg_link
                            st.toast("Registration link copied!", icon="✅")
                        render_qr_code_visible(reg_link, width=180)
                    else:
                        st.caption("Registration closed for this tournament.")
                else:
                    st.caption("Registration is closed for this tournament.")
            except Exception:
                pass

    # --- Now Playing ---
    with st.container():
        st.subheader("🎾 Now Playing" if state.live_matches else "📋 Now Playing")
        if state.live_matches:
            for m in state.live_matches:
                render_public_match_card(m, label="LIVE", game_scores=m.get("game_scores"), insight=insights.get(m.get("id")))
                render_pairing_expander(m)
        elif state.called_matches:
            for m in state.called_matches:
                render_public_match_card(m, label="CALLED", game_scores=m.get("game_scores"), insight=insights.get(m.get("id")))
                render_pairing_expander(m)
        else:
            st.info("No active matches at the moment.")

    # --- Next Match ---
    if state.next_match:
        st.divider()
        st.subheader("⏭️ Next Match")
        render_public_coming_up_card(state.next_match, call_status=state.next_match.get("call_status", "not_called"))
        render_pairing_expander(state.next_match)

    # --- Coming Up ---
    if state.coming_up:
        st.divider()
        st.subheader("⏭️ Coming Up")
        active_locations = {m.get("location") for m in state.live_matches if m.get("location")} | {m.get("location") for m in state.called_matches if m.get("location")}
        for m in state.coming_up:
            render_public_coming_up_card(m, call_status=m.get("call_status", "not_called"))
            render_pairing_expander(m)
            if m.get("location") and m.get("location") in active_locations:
                st.caption("⏳ Waiting for previous match on this table")

    # --- Delayed ---
    if state.delayed_matches:
        st.divider()
        st.subheader("⏸️ Delayed")
        for m in state.delayed_matches:
            render_public_delayed_card(m)

    # --- Recent Results + Rankings ---
    tab_recent, tab_rankings = st.tabs(["📋 Recent Results", "📊 Rankings"])

    with tab_recent:
        if state.recent:
            for m in state.recent:
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
        if state.standings:
            import pandas as pd
            rows = []
            for i, s in enumerate(state.standings, 1):
                rows.append({
                    "Rank": i,
                    "Player": s["name"],
                    "Rating": s.get("rating") or 0,
                    "Matches": s.get("matches_played", 0),
                    "Wins": s.get("wins", 0),
                    "Losses": s.get("losses", 0),
                    "Win Rate": f"{(s.get('wins', 0) / s.get('matches_played', 1) * 100):.0f}%" if s.get("matches_played", 0) > 0 else "0%",
                })
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
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

    # --- Player Lookup ---
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
            found = render_player_path(db, player_name, tournament_id=state.tournament_id, key_prefix="public_lookup")
            if not found:
                st.info(f"No matches found for player '{player_name}'")
        except Exception as e:
            st.error(f"Failed to get player path: {e}")
        finally:
            db.close()

    # --- Announcements ---
    st.divider()
    st.subheader("📢 Announcements")
    try:
        @st.cache_data(ttl=30, show_spinner="Loading announcements...")
        def _load_announcements(limit=10):
            db2 = SessionLocal()
            try:
                from tournament_platform.services.announcement_service import get_announcements
                return get_announcements(db2, limit=limit)
            finally:
                db2.close()

        announcements = _load_announcements(limit=5)
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

    # Footer
    st.divider()
    refresh_note = "Auto-refreshes every 5s (kiosk)" if kiosk else "Use Refresh to update manually"
    st.caption(f"🕐 {refresh_note}")
