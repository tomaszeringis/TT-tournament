"""
Pairing Explanation UI component.

Renders a small "Why this pairing?" expander for a match, using the existing
``pairing_explanation`` service and adding UI confidence labels.

Confidence tiers:
- ``stored`` — pairing metadata was persisted at generation time
- ``derived`` — computed from current standings, match history, seeds, stage
- ``partial`` — only some facts are available
- ``unavailable`` — no supporting data exists
"""

from typing import List, Optional

import streamlit as st

from tournament_platform.models import Match, SessionLocal
from tournament_platform.services.pairing_explanation import explain_pairing


class PairingExplanation:
    def __init__(self, reasons: List[str], confidence: str):
        self.reasons = reasons
        self.confidence = confidence

    @property
    def is_available(self) -> bool:
        return bool(self.reasons)


def _derive_confidence(match: Match, reasons: List[str]) -> str:
    if not reasons:
        return "unavailable"

    has_stored = bool(
        getattr(match, "stage_id", None)
        or (getattr(match, "stage", None) and getattr(match.stage, "stage_type", None))
        or getattr(match, "bracket_index", None)
    )

    has_derived = any(
        keyword in r.lower()
        for r in reasons
        for keyword in ["wins", "record", "rematch", "difference"]
    )

    if has_stored and has_derived:
        return "partial"
    if has_stored:
        return "stored"
    if has_derived:
        return "derived"
    return "partial"


def get_pairing_explanation(match_id: int, db_session) -> PairingExplanation:
    match = db_session.query(Match).filter(Match.id == match_id).first()
    if not match:
        return PairingExplanation(reasons=[], confidence="unavailable")
    reasons = explain_pairing(match, db_session)
    confidence = _derive_confidence(match, reasons)
    return PairingExplanation(reasons=reasons, confidence=confidence)


def render_pairing_expander(match: dict, label: str = "ℹ️ Why this pairing?") -> None:
    match_id = match.get("id")
    if not match_id:
        return

    with st.expander(label, expanded=False):
        db = SessionLocal()
        try:
            explanation = get_pairing_explanation(match_id, db)
        finally:
            db.close()

        if not explanation.is_available:
            st.caption("Pairing explanation unavailable for this legacy/generated match.")
            return

        confidence = explanation.confidence
        confidence_colors = {
            "stored": "green",
            "derived": "blue",
            "partial": "amber",
            "unavailable": "default",
        }
        st.markdown(f"**Confidence:** `{confidence}`")
        for reason in explanation.reasons:
            st.markdown(f"- {reason}")
