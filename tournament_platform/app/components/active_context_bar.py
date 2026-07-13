"""
Active Tournament Context Bar

Provides a persistent tournament selector in the sidebar so operators
never operate on the wrong tournament.

Session state:
- st.session_state["active_tournament_id"] — persists across pages.
"""

from typing import Optional, Dict, Any, List

import streamlit as st

from tournament_platform.models import SessionLocal, Tournament
from tournament_platform.services.health_service import get_tournament_health


def _load_tournaments() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        tournaments = db.query(Tournament).order_by(Tournament.name.asc()).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "tournament_type": t.tournament_type.value if t.tournament_type else "knockout",
            }
            for t in tournaments
        ]
    finally:
        db.close()


def render_active_context_bar() -> Optional[int]:
    """
    Render the active tournament selector in the sidebar.

    Returns the currently active tournament id or None if no tournaments exist.
    """
    tournaments = _load_tournaments()

    if not tournaments:
        st.sidebar.warning("No tournaments yet.")
        return None

    options = {t["name"]: t["id"] for t in tournaments}
    names = list(options.keys())

    active_id = st.session_state.get("active_tournament_id")
    if active_id not in options.values():
        active_id = tournaments[0]["id"]
        st.session_state["active_tournament_id"] = active_id

    active_name = next((n for n, tid in options.items() if tid == active_id), names[0])

    st.sidebar.markdown("### 🎯 Active Tournament")
    selected_name = st.sidebar.selectbox(
        "Select tournament",
        options=names,
        index=names.index(active_name),
        key="active_tournament_select",
    )
    selected_id = options[selected_name]
    st.session_state["active_tournament_id"] = selected_id

    db = SessionLocal()
    try:
        health = get_tournament_health(db, tournament_id=selected_id)
    finally:
        db.close()

    issue_count = len(health.get("issues", []))
    active_matches = health.get("match_counts", {}).get("active", 0)

    if active_matches:
        st.sidebar.caption(f"🎾 Active matches: **{active_matches}**")
    if issue_count:
        st.sidebar.caption(f"⚠️ Issues: **{issue_count}**")
    elif active_matches == 0:
        st.sidebar.caption("✅ No active issues")

    return selected_id
