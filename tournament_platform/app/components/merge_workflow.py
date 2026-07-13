"""
Merge Workflow Component

Reusable UI for the duplicate-player detection and merge flow.
Integrates with the existing duplicate_players service.
"""

from typing import Any, Dict, List, Optional

import streamlit as st

from tournament_platform.models import SessionLocal
from tournament_platform.services.duplicate_players import (
    find_duplicate_candidates,
    preview_player_merge,
    merge_players,
)
from tournament_platform.app.components.confirmation_dialog import ConfirmationDialog


def _render_candidate_card(candidate: Dict[str, Any], index: int) -> None:
    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.markdown(f"**{candidate.get('player1_name', '?')}**")
            if candidate.get('player1_email'):
                st.caption(f"Email: {candidate['player1_email']}")
        with col2:
            st.markdown(f"**{candidate.get('player2_name', '?')}**")
            if candidate.get('player2_email'):
                st.caption(f"Email: {candidate['player2_email']}")
        with col3:
            st.metric("Similarity", f"{candidate.get('similarity_score', 0)}%")
            st.caption(candidate.get('reason', ''))

        if st.button("Preview Merge", key=f"preview_merge_{index}"):
            db = SessionLocal()
            try:
                preview = preview_player_merge(
                    db,
                    target_player_id=candidate['player1_id'],
                    source_player_id=candidate['player2_id'],
                )
                st.session_state[f"merge_preview_{index}"] = preview
            except Exception as e:
                st.error(f"Failed to preview merge: {e}")
            finally:
                db.close()

        if f"merge_preview_{index}" in st.session_state:
            preview = st.session_state[f"merge_preview_{index}"]
            if preview.get("success"):
                st.info(
                    f"Would transfer {preview['matches_to_transfer']} matches, "
                    f"{preview['rating_history_to_transfer']} rating history entries"
                )
                for warning in preview.get("warnings", []):
                    st.warning(warning)

                dialog = ConfirmationDialog(key_prefix=f"merge_{index}")
                dialog.confirm(
                    action_label="Confirm Merge",
                    description=f"Merge {candidate.get('player2_name')} into {candidate.get('player1_name')}",
                    on_confirm=lambda: _execute_merge(candidate, index),
                )
            else:
                st.error(preview.get("error", "Merge preview failed"))


def _execute_merge(candidate: Dict[str, Any], index: int) -> None:
    db = SessionLocal()
    try:
        result = merge_players(
            db,
            target_player_id=candidate['player1_id'],
            source_player_id=candidate['player2_id'],
            actor="operator",
        )
        if result.get("success"):
            st.success(f"Merged! Transferred {result['matches_transferred']} matches")
            if f"merge_preview_{index}" in st.session_state:
                del st.session_state[f"merge_preview_{index}"]
            st.rerun()
        else:
            st.error(result.get("error", "Merge failed"))
    except Exception as e:
        st.error(f"Merge error: {e}")
    finally:
        db.close()


def render_merge_workflow(limit: int = 10) -> None:
    """
    Render the duplicate detection and merge workflow.

    Args:
        limit: Maximum number of duplicate candidates to render
    """
    if st.button("🔍 Scan for Duplicates", key="scan_duplicates_btn"):
        st.session_state.pop("duplicate_candidates", None)
        st.rerun()

    if "duplicate_candidates" not in st.session_state:
        db = SessionLocal()
        try:
            st.session_state["duplicate_candidates"] = find_duplicate_candidates(db)
        finally:
            db.close()

    candidates = st.session_state.get("duplicate_candidates", [])[:limit]

    if not candidates:
        st.info("No duplicate candidates found.")
        return

    st.markdown(f"**Found {len(candidates)} potential duplicate(s)**")
    for idx, candidate in enumerate(candidates):
        _render_candidate_card(candidate, idx)
