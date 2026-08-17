"""UI Render Helpers (Phase 7)"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

logger = logging.getLogger(__name__)


def render_active_match_selector() -> None:
    """Render the active tournament match selector UI."""
    from tournament_platform.app.pages.voice_scorekeeper import (
        fetch_active_tournaments,
        fetch_active_matches,
        get_all_players,
        format_match_option,
        apply_selected_match_to_session,
        clear_selected_match,
        _render_match_diagnostics,
    )

    st.subheader("🎯 Active Tournament Matches")
    st.caption("Select a match to prefill players and score the result.")

    tournaments = fetch_active_tournaments()
    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        return

    tournament_options = {t["name"]: t["id"] for t in tournaments}
    current_tournament_id = st.session_state.voice_selected_tournament_id

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
            key="voice_tournament_select",
        )
    with col_f:
        status_filter = st.multiselect(
            "Status filter",
            options=["active", "pending"],
            default=["active", "pending"],
            key="voice_status_filter",
        )
    with col_r:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="voice_refresh_matches", use_container_width=True):
            fetch_active_matches.clear()
            fetch_active_tournaments.clear()
            st.rerun()

    tournament_id = tournament_options[selected_tournament_name]
    st.session_state.voice_selected_tournament_id = tournament_id

    matches = fetch_active_matches(tournament_id, statuses=status_filter)
    st.session_state.voice_match_options = matches

    if not matches:
        # Manual player selection (rendered later on the page) is the fallback
        # path, but only when the tournament has at least 2 registered players.
        _players = get_all_players()
        if len(_players) >= 2:
            st.info(
                "No scheduled matches yet. Select two players below to start a "
                "manual match."
            )
        else:
            st.info("No active or pending matches found for this tournament.")
        _render_match_diagnostics(tournament_id, status_filter, matches)
        return

    # Build options list, disabling incomplete matches
    match_labels = []
    match_disabled = []
    for m in matches:
        label = format_match_option(m)
        match_labels.append(label)
        match_disabled.append(m.get("incomplete", False))

    # Find current selection index
    current_match_id = st.session_state.voice_selected_match_id
    selected_index = 0
    for i, m in enumerate(matches):
        if m.get("match_id") == current_match_id:
            selected_index = i
            break

    selected_label = st.selectbox(
        "Select a match",
        options=match_labels,
        index=selected_index,
        key="voice_match_select",
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
            apply_selected_match_to_session(selected_match)

    # Clear button
    if st.button("🗑️ Clear selected match", key="voice_clear_match"):
        clear_selected_match()
        st.rerun()

    _render_match_diagnostics(tournament_id, status_filter, matches)


def render_selected_match_summary() -> None:
    """Render a compact summary of the currently selected match."""
    if not st.session_state.voice_selected_match_id:
        return
    p1 = st.session_state.voice_selected_player1_name or "TBD"
    p2 = st.session_state.voice_selected_player2_name or "TBD"
    st.info(f"**Selected Match:** {p1} vs {p2} (ID: {st.session_state.voice_selected_match_id})")


def _render_match_diagnostics(tournament_id: int, status_filter: List[str], matches: List[Dict]) -> None:
    """Render a collapsed diagnostics expander for match-loading verification."""
    from tournament_platform.models import SessionLocal, Tournament, Player, Match
    from tournament_platform.app.components.match_selector import _normalize_status

    with st.expander("🔍 Match loading diagnostics", expanded=False):
        db = SessionLocal()
        try:
            tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
            t_name = tournament.name if tournament else None
            player_count = db.query(Player).count()
            generated = list(tournament.matches) if tournament else []
            generated_count = len(generated)
            repo_matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
            repo_count = len(repo_matches)
            statuses_found = sorted({_normalize_status(m.status.value) for m in repo_matches})
        except Exception as e:
            t_name = None
            player_count = 0
            generated_count = 0
            repo_count = 0
            statuses_found = [f"error: {e}"]
        finally:
            db.close()

        st.write(f"- selected tournament ID: `{tournament_id}`")
        st.write(f"- selected tournament name: `{t_name}`")
        st.write(f"- number of players: `{player_count}`")
        st.write(f"- number of generated matches (Tournament page source): `{generated_count}`")
        st.write(f"- number of DB/repository matches: `{repo_count}`")
        st.write(f"- number of pending/active matches after filter: `{len(matches)}`")
        st.write(f"- statuses found: `{statuses_found}`")
        st.write(f"- status filter applied: `{status_filter}`")


def _render_dataset_panel(
    match_id: int,
) -> None:
    """Render the opt-in dataset recorder panel (Phase 4)."""
    from tournament_platform.app.services.voice.dataset_recorder import VoiceDatasetRecorder
    from tournament_platform.services.settings import VOICE_DATASET_OPT_IN

    if not VOICE_DATASET_OPT_IN:
        st.caption("Dataset recorder is disabled. Set VOICE_DATASET_OPT_IN=1 to enable.")
        return

    recorder: VoiceDatasetRecorder = st.session_state.get("voice_dataset_recorder")
    if recorder is None:
        return

    st.markdown("### 🧪 Voice Dataset Recorder")
    st.caption(
        "Opt-in capture of transcripts, parsed intents, and operator corrections "
        "for grammar evaluation. No audio is stored unless explicitly enabled below."
    )


def _render_confirm_panel(
    pending: List[Dict[str, Any]],
) -> None:
    """Render confirmation panel for pending voice actions."""
    from tournament_platform.app.pages.voice_scorekeeper import _apply_pending
    from tournament_platform.app.services.voice.confirmation import VoiceConfirmationStateMachine

    _machine = VoiceConfirmationStateMachine()

    if not pending:
        _machine = st.session_state.get("voice_confirmation_machine")
        if _machine and not _machine.is_idle():
            _machine.reset()
        return

    st.markdown("### ⏳ Pending Voice Confirmations")
    for idx, item in enumerate(pending):
        with st.container(border=True):
            col_a, col_b, col_c = st.columns([2, 1, 1])
            with col_a:
                st.markdown(f"**Intent:** {item['intent']}")
                st.caption(f"Transcript: {item['raw_transcript']}")
                st.caption(f"Confidence: {item['confidence']:.0%}")
                st.caption(f"{item['predicted_score_before']} → {item['predicted_score_after']}")
            with col_b:
                if st.button("✅ Confirm", key=f"confirm_voice_{idx}", use_container_width=True):
                    _apply_pending(idx)
            with col_c:
                if st.button("✖ Cancel", key=f"cancel_voice_{idx}", use_container_width=True):
                    _machine = st.session_state.get("voice_confirmation_machine")
                    if _machine:
                        _machine.cancel()


def _render_audio_rally_insights(summaries: List[Any]) -> None:
    """Render the audio rally insights panel."""
    if not summaries:
        return

    st.markdown("### 🏓 Audio Rally Insights (experimental)")
    for s in summaries[-5:]:
        st.caption(
            f"Rally {getattr(s, 'rally_id', '???')[:8]}: "
            f"{getattr(s, 'point_count', 0)} points, "
            f"winner={getattr(s, 'winner', '???')}, "
            f"confidence={getattr(s, 'confidence', 0):.0%}"
        )
