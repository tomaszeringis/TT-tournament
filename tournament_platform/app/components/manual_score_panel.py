"""
Manual Score Panel — draft + undo scoring for the Operator Console.

This wraps the pure ``score_engine.MatchState`` to give a manual operator a local
draft with one-tap undo. Nothing is written to the database until the operator
clicks **Confirm**; at that point the result is committed via the existing
``api_client.report_match`` endpoint.

Completed matches are always protected: if the source match is already completed
in the database (reflected in the passed ``match`` dict), scoring controls are
disabled and undo is refused with a toast.
"""

import streamlit as st

from tournament_platform.app.services.score_engine import (
    MatchState,
    add_point,
    undo_last_action,
    reset_match,
)
from tournament_platform.app.api_client import api_client


def _state_key(match_id: int, key_prefix: str) -> str:
    return f"{key_prefix}_{match_id}_draft"


def _get_or_init_state(match: dict, key_prefix: str) -> MatchState:
    """Return the persisted draft MatchState for this match, creating it if needed."""
    key = _state_key(match["id"], key_prefix)
    existing = st.session_state.get(key)
    if existing is not None:
        return MatchState.from_dict(existing)

    p1 = match.get("player1") or "Player A"
    p2 = match.get("player2") or "Player B"
    state = MatchState(
        player_a_name=p1,
        player_b_name=p2,
        player_a_id=match.get("player1_id"),
        player_b_id=match.get("player2_id"),
    )
    st.session_state[key] = state.to_dict()
    return state


def _save_state(match_id: int, key_prefix: str, state: MatchState) -> None:
    st.session_state[_state_key(match_id, key_prefix)] = state.to_dict()


def compute_final_report(state: MatchState) -> dict:
    """Compute the (score, winner) to commit from a finished draft.

    For best-of-N matches the committed ``score`` is the games-won tally
    (e.g. ``"3-1"``). For a single-game match it is the point score.
    """
    if state.best_of > 1:
        score = f"{state.games_won_a}-{state.games_won_b}"
    else:
        score = f"{state.score_a}-{state.score_b}"

    if state.games_won_a > state.games_won_b:
        winner = state.player_a_name
    elif state.games_won_b > state.games_won_a:
        winner = state.player_b_name
    else:
        # Fall back to current-game points for single-game / tied-game cases.
        if state.score_a > state.score_b:
            winner = state.player_a_name
        elif state.score_b > state.score_a:
            winner = state.player_b_name
        else:
            winner = None

    return {"score": score, "winner": winner}


def render_manual_score_panel(match: dict, key_prefix: str = "msp") -> bool:
    """Render the draft + undo scoring panel for a single match.

    Args:
        match: match dict (must include ``id``, ``player1``, ``player2``; optionally
            ``player1_id``/``player2_id`` and ``status``).
        key_prefix: unique prefix to avoid widget key collisions.

    Returns:
        ``True`` if a report was committed during this render, else ``False``.
    """
    match_id = match["id"]
    is_completed = match.get("status") == "completed"

    with st.container(border=True):
        st.markdown(f"**{match.get('player1', '?')} vs {match.get('player2', '?')}**")

        if is_completed:
            st.info("🔒 This match is already completed. Scoring is locked.")
            return False

        state = _get_or_init_state(match, key_prefix)

        # Live scoreboard
        col_a, col_mid, col_b = st.columns([2, 1, 2])
        with col_a:
            st.markdown(
                f"<div style='text-align:center;font-size:20px;font-weight:bold;'>"
                f"{state.player_a_name}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='text-align:center;font-size:40px;font-weight:bold;'>"
                f"{state.score_a}</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Games: {state.games_won_a}")
        with col_mid:
            serving = "🅰️" if state.serving_player == "A" else "🅱️"
            st.markdown(
                f"<div style='text-align:center;font-size:24px;'>{serving}</div>",
                unsafe_allow_html=True,
            )
            st.caption("serving")
        with col_b:
            st.markdown(
                f"<div style='text-align:center;font-size:20px;font-weight:bold;'>"
                f"{state.player_b_name}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='text-align:center;font-size:40px;font-weight:bold;'>"
                f"{state.score_b}</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Games: {state.games_won_b}")

        draft_done = state.match_status == "match_won"

        # Controls
        c_point_a, c_point_b, c_undo, c_reset = st.columns([1, 1, 1, 1])
        with c_point_a:
            if st.button("+ Point A", key=f"{key_prefix}_{match_id}_pa", use_container_width=True,
                         disabled=draft_done, type="primary"):
                res = add_point(state, "A")
                if not res.ok:
                    st.toast(res.rejected_reason, icon="⚠️")
                _save_state(match_id, key_prefix, state)
                st.rerun()
        with c_point_b:
            if st.button("+ Point B", key=f"{key_prefix}_{match_id}_pb", use_container_width=True,
                         disabled=draft_done, type="primary"):
                res = add_point(state, "B")
                if not res.ok:
                    st.toast(res.rejected_reason, icon="⚠️")
                _save_state(match_id, key_prefix, state)
                st.rerun()
        with c_undo:
            if st.button("↶ Undo", key=f"{key_prefix}_{match_id}_undo", use_container_width=True,
                         disabled=not state.history):
                res = undo_last_action(state)
                if not res.ok:
                    st.toast(res.rejected_reason, icon="⚠️")
                else:
                    st.toast("Undo", icon="↶")
                _save_state(match_id, key_prefix, state)
                st.rerun()
        with c_reset:
            if st.button("🔄 Reset", key=f"{key_prefix}_{match_id}_reset", use_container_width=True):
                reset_match(state)
                _save_state(match_id, key_prefix, state)
                st.toast("Draft reset", icon="🔄")
                st.rerun()

        if draft_done:
            st.success("✅ Match decided in draft — confirm to commit.")

        # Confirm / commit
        if st.button("✅ Confirm & Report", key=f"{key_prefix}_{match_id}_confirm",
                     type="primary", use_container_width=True, disabled=not draft_done):
            report = compute_final_report(state)
            if not report["winner"]:
                st.error("Cannot determine a winner from the draft.")
                return False
            result = api_client.report_match(
                match_id=match_id,
                score1=int(report["score"].split("-")[0]),
                score2=int(report["score"].split("-")[1]),
                winner=report["winner"],
            )
            if result and result.get("status") == "success":
                st.toast("Match reported!", icon="✅")
                _save_state(match_id, key_prefix, MatchState(
                    player_a_name=state.player_a_name,
                    player_b_name=state.player_b_name,
                ))
                st.cache_data.clear()
                st.rerun()
                return True
            else:
                st.error(f"Failed to report: {result.get('message', 'Unknown error') if result else 'API unreachable'}")
    return False
