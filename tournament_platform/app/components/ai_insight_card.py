"""
AI Insight Card — optional, flag-gated, offline-safe post-match insight.

Shows an AI-generated summary for a completed match, clearly labeled as
*not* the official result. The feature is disabled by default
(``settings.ENABLE_AI_MATCH_INSIGHTS``) and never writes scores or winners.
If Ollama is unavailable, it degrades gracefully and renders nothing.
Insights are cached per ``(match_id, score_hash)`` to avoid repeated LLM calls.
"""

import hashlib
import json
import streamlit as st
from typing import Optional

from tournament_platform.app.design_system import COLORS
from tournament_platform.config import settings


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_insight(match_id: int, score_hash: str, match_json: str) -> Optional[dict]:
    """Call the AI engine once per (match_id, score) and cache the result.

    Returns a dict with ``summary``, ``key_play``, ``predicted_winner`` or None
    if the engine is unavailable/offline.
    """
    try:
        from tournament_platform.services.ai_engine import AIEngine

        engine = AIEngine()
        report = engine.generate_report(json.loads(match_json))
        if report is None:
            return None
        return {
            "summary": getattr(report, "summary", None),
            "key_play": getattr(report, "key_play", None),
            "predicted_winner": getattr(report, "predicted_winner", None),
        }
    except Exception:
        # Offline / Ollama unavailable / parse failure — never block the UI.
        return None


def get_match_insight(match_data: dict) -> Optional[dict]:
    """Return the AI insight dict for a match, or None if disabled/offline."""
    if not settings.ENABLE_AI_MATCH_INSIGHTS:
        return None

    match_id = match_data.get("id") or match_data.get("match_id")
    score = match_data.get("score") or match_data.get("winner") or ""
    score_hash = hashlib.sha1(str(score).encode("utf-8")).hexdigest()[:12]
    match_json = json.dumps(match_data, default=str)
    try:
        return _cached_insight(int(match_id) if match_id is not None else 0, score_hash, match_json)
    except Exception:
        return None


def render_ai_insight_card(match_data: dict) -> None:
    """Render the labeled AI insight card for a completed match, if available."""
    insight = get_match_insight(match_data)
    if not insight:
        return

    summary = insight.get("summary")
    key_play = insight.get("key_play")
    predicted = insight.get("predicted_winner")

    with st.container(border=True):
        st.markdown(
            f"<div style='font-size: 13px; font-weight: bold; color: {COLORS['accent_blue']}; "
            f"margin-bottom: 4px;'>🤖 AI-generated insight — not the official result</div>",
            unsafe_allow_html=True,
        )
        if summary:
            st.markdown(summary)
        if key_play:
            st.caption(f"**Key play:** {key_play}")
        if predicted:
            st.caption(f"**Predicted winner:** {predicted}")
