"""
Reusable match selector component for video/voice scorekeeper pages.
Provides cached data loaders and UI renderers that operate on a configurable
session_state prefix (e.g., 'video' or 'voice').

This allows both pages to reuse identical logic without duplication.
"""

from typing import List, Dict, Optional

import streamlit as st

from tournament_platform.models import SessionLocal, Tournament
from tournament_platform.app.utils import api_request, format_match_option


@st.cache_data(ttl=60)
def fetch_active_tournaments() -> List[Dict]:
    """Return all tournaments as plain dicts for selectbox options."""
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).order_by(Tournament.name).all()
        return [
            {"id": t.id, "name": t.name, "type": t.tournament_type.value if t.tournament_type else None}
            for t in tournaments
        ]
    finally:
        db.close()


@st.cache_data(ttl=30)
def fetch_active_matches(tournament_id: int, statuses: Optional[List[str]] = None) -> List[Dict]:
    """Fetch scorable matches for a tournament via the API."""
    params = {"limit": 100}
    if statuses:
        params["statuses"] = ",".join(statuses)
    response = api_request(
        "get",
        f"/api/tournaments/{tournament_id}/matches/active",
        params=params,
        parse_json=True,
        error_context="fetching active matches",
    )
    if response and isinstance(response, dict):
        return response.get("matches", [])
    return []


def apply_selected_match_to_session(prefix: str, match: Dict) -> None:
    """Apply a selected match dict to session state using the given prefix."""
    st.session_state[f"{prefix}_selected_match_id"] = match.get("match_id")
    st.session_state[f"{prefix}_selected_player1_id"] = match.get("player1_id")
    st.session_state[f"{prefix}_selected_player1_name"] = match.get("player1_name")
    st.session_state[f"{prefix}_selected_player2_id"] = match.get("player2_id")
    st.session_state[f"{prefix}_selected_player2_name"] = match.get("player2_name")

    # Also update the MatchManager state for live scoring if available
    match_manager = st.session_state.get("match_manager")
    if match_manager:
        if (
            match_manager.state.player_a_id != match.get("player1_id")
            or match_manager.state.player_b_id != match.get("player2_id")
        ):
            match_manager.set_player_names(
                match.get("player1_name") or "Player A",
                match.get("player2_name") or "Player B",
                match.get("player1_id"),
                match.get("player2_id"),
            )


def clear_selected_match(prefix: str) -> None:
    """Clear the selected match-related session keys for the given prefix."""
    # Core keys
    core_keys = [
        f"{prefix}_selected_match_id",
        f"{prefix}_selected_player1_id",
        f"{prefix}_selected_player1_name",
        f"{prefix}_selected_player2_id",
        f"{prefix}_selected_player2_name",
        f"{prefix}_match_options",
    ]
    for k in core_keys:
        if k in st.session_state:
            # Use None for scalar keys, empty list for options
            st.session_state[k] = [] if k.endswith("_match_options") else None

    # Optional keys used by pages (safe to clear if present)
    optional_keys = [f"{prefix}_suggestion", f"{prefix}_parsed_result", f"{prefix}_score_input"]
    for k in optional_keys:
        if k in st.session_state:
            if k == f"{prefix}_score_input":
                st.session_state[k] = "0-0"
            else:
                st.session_state[k] = None


def render_active_match_selector(prefix: str, title: str = "🎯 Active Tournament Matches") -> None:
    """Render the active tournament match selector UI for the provided prefix."""
    st.subheader(title)
    st.caption("Select a match to prefill players and score the result.")

    tournaments = fetch_active_tournaments()
    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        return

    tournament_options = {t["name"]: t["id"] for t in tournaments}
    current_tournament_id = st.session_state.get(f"{prefix}_selected_tournament_id")

    # Find index for current selection
    selected_tournament_name = None
    for name, tid in tournament_options.items():
        if tid == current_tournament_id:
            selected_tournament_name = name
            break

    col_t, col_f, col_r = st.columns([2, 2, 1])
    with col_t:
        selected_tournament_name = st.selectbox(
            "Tournament",
            options=list(tournament_options.keys()),
            index=list(tournament_options.keys()).index(selected_tournament_name) if selected_tournament_name else 0,
            key=f"{prefix}_tournament_select",
        )
    with col_f:
        status_filter = st.multiselect(
            "Status filter",
            options=["active", "pending"],
            default=["active", "pending"],
            key=f"{prefix}_status_filter",
        )
    with col_r:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key=f"{prefix}_refresh_matches", use_container_width=True):
            fetch_active_matches.clear()
            fetch_active_tournaments.clear()
            st.rerun()

    tournament_id = tournament_options[selected_tournament_name]
    st.session_state[f"{prefix}_selected_tournament_id"] = tournament_id

    matches = fetch_active_matches(tournament_id, statuses=status_filter)
    st.session_state[f"{prefix}_match_options"] = matches

    if not matches:
        st.info("No active or pending matches found for this tournament.")
        return

    # Build options list
    match_labels = [format_match_option(m) for m in matches]

    # Find current selection index
    current_match_id = st.session_state.get(f"{prefix}_selected_match_id")
    selected_index = 0
    for i, m in enumerate(matches):
        if m.get("match_id") == current_match_id:
            selected_index = i
            break

    selected_label = st.selectbox(
        "Select a match",
        options=match_labels,
        index=selected_index,
        key=f"{prefix}_match_select",
        help="Incomplete matches (missing players) are disabled unless byes are supported.",
    )

    # Find the selected match dict
    selected_match = None
    for i, label in enumerate(match_labels):
        if label == selected_label:
            selected_match = matches[i]
            break

    if selected_match:
        if selected_match.get("incomplete"):
            st.warning("⚠️ This match is missing a player and cannot be scored yet.")
        else:
            apply_selected_match_to_session(prefix, selected_match)

    # Clear button
    if st.button("🗑️ Clear selected match", key=f"{prefix}_clear_match"):
        clear_selected_match(prefix)
        st.rerun()


def render_selected_match_summary(prefix: str) -> None:
    """Render a compact summary of the currently selected match for the prefix."""
    if not st.session_state.get(f"{prefix}_selected_match_id"):
        return
    p1 = st.session_state.get(f"{prefix}_selected_player1_name") or "TBD"
    p2 = st.session_state.get(f"{prefix}_selected_player2_name") or "TBD"
    st.info(f"**Selected Match:** {p1} vs {p2} (ID: {st.session_state.get(f'{prefix}_selected_match_id')})")
