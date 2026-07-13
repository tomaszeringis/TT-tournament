"""
Report Preview Component

UI renderer for structured event and match reports.
"""

from typing import Any, Dict, Optional

import streamlit as st
import pandas as pd


def render_event_report(report: Dict[str, Any]) -> None:
    """Render a structured event report."""
    if "error" in report:
        st.error(report["error"])
        return

    tournament = report.get("tournament", {})
    summary = report.get("summary", {})

    st.subheader(f"📋 Event Report: {tournament.get('name', 'Unknown')}")
    cols = st.columns(4)
    with cols[0]:
        st.metric("Total Matches", summary.get("total_matches", 0))
    with cols[1]:
        st.metric("Completed", summary.get("completed", 0))
    with cols[2]:
        st.metric("Active", summary.get("active", 0))
    with cols[3]:
        st.metric("Players", summary.get("player_count", 0))

    st.caption(f"Completion rate: {summary.get('completion_rate', 0)}%")

    recent = report.get("recent_results", [])
    if recent:
        st.markdown("**Recent Results**")
        df = pd.DataFrame([
            {
                "Match": r["id"],
                "Player 1": r["player1"],
                "Player 2": r["player2"],
                "Score": r["score"] or "—",
                "Winner": r["winner"] or "—",
            }
            for r in recent
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_match_report(report: Dict[str, Any]) -> None:
    """Render a structured match report."""
    if "error" in report:
        st.error(report["error"])
        return

    match = report.get("match", {})
    participants = report.get("participants", {})

    st.subheader(f"🎾 Match Report: {match.get('id')}")
    st.markdown(f"**{participants.get('player1', {}).get('name', 'TBD')} vs {participants.get('player2', {}).get('name', 'TBD')}**")

    cols = st.columns(3)
    with cols[0]:
        st.metric("Score", match.get("score") or "—")
    with cols[1]:
        st.metric("Status", match.get("status", "pending").title())
    with cols[2]:
        st.metric("Winner", match.get("winner") or "—")

    details = {
        "Tournament": match.get("tournament_name"),
        "Location": match.get("location"),
        "Round": match.get("round_number"),
        "Scheduled": match.get("scheduled_time"),
        "Started": match.get("started_at"),
        "Completed": match.get("completed_at"),
        "Game Scores": match.get("game_scores"),
        "Operator Note": match.get("operator_note"),
    }
    st.json({k: v for k, v in details.items() if v is not None})
