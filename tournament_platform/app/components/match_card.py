"""
Match Details Flyout

Provides a compact, reusable match details panel that can be expanded
inline (expander/flyout) without navigating away from the current view.
"""

from typing import Any, Dict, Optional

import streamlit as st

from tournament_platform.models import SessionLocal, Match, Player


def _load_match_details(match_id: int) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        m = db.query(Match).filter(Match.id == match_id).first()
        if not m:
            return None
        p1 = db.query(Player).filter(Player.id == m.player1_id).first()
        p2 = db.query(Player).filter(Player.id == m.player2_id).first()
        winner = db.query(Player).filter(Player.id == m.winner_id).first() if m.winner_id else None
        return {
            "id": m.id,
            "player1": m.player1,
            "player2": m.player2,
            "player1_id": m.player1_id,
            "player2_id": m.player2_id,
            "player1_email": p1.email if p1 else None,
            "player2_email": p2.email if p2 else None,
            "score": m.score,
            "status": m.status.value if m.status else "pending",
            "call_status": m.call_status or "not_called",
            "winner": m.winner,
            "winner_id": m.winner_id,
            "winner_name": winner.name if winner else None,
            "location": m.location,
            "round_number": m.round_number,
            "bracket_index": m.bracket_index,
            "scheduled_time": m.scheduled_time,
            "tournament_name": m.tournament.name if m.tournament else None,
            "stage_name": m.stage.name if m.stage else None,
            "game_scores": m.game_scores,
            "operator_note": m.operator_note,
        }
    finally:
        db.close()


def render_match_card(match: Dict[str, Any], key_prefix: str = "mc") -> None:
    """
    Render a match details flyout/expander for a match dict.

    If ``match`` is a DB id, load details from the database.
    """
    if isinstance(match, int):
        match = _load_match_details(match)
        if match is None:
            st.warning("Match not found.")
            return

    match_id = match.get("id")
    if match_id is None:
        return

    with st.expander(f"📋 Match {match_id}: {match.get('player1')} vs {match.get('player2')}", expanded=False):
        cols = st.columns([1, 1])
        with cols[0]:
            st.markdown(f"**Player 1:** {match.get('player1') or 'TBD'}")
            if match.get("player1_email"):
                st.caption(f"Email: {match['player1_email']}")
        with cols[1]:
            st.markdown(f"**Player 2:** {match.get('player2') or 'TBD'}")
            if match.get("player2_email"):
                st.caption(f"Email: {match['player2_email']}")

        st.divider()
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            st.metric("Score", match.get("score") or "—")
        with col_s2:
            st.metric("Status", match.get("status", "pending").title())
        with col_s3:
            st.metric("Winner", match.get("winner") or "—")

        details = {
            "Call Status": match.get("call_status"),
            "Table": match.get("location"),
            "Round": match.get("round_number"),
            "Bracket Index": match.get("bracket_index"),
            "Scheduled": match.get("scheduled_time"),
            "Tournament": match.get("tournament_name"),
            "Stage": match.get("stage_name"),
            "Game Scores": match.get("game_scores"),
            "Operator Note": match.get("operator_note"),
        }
        st.json({k: v for k, v in details.items() if v is not None})
