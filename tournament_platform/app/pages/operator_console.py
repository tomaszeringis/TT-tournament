"""
Match Center

A control panel for tournament operators to manage match flow.
Features:
- Lane-based match flow (Now Playing, Up Next, Needs Attention, Table Status, Recent Results)
- Quick actions, command bar, and voice shortcut
- Manual score entry with draft + undo
- Rescheduling, duplicate detection, health, audit, and announcements
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from tournament_platform.models import SessionLocal, Tournament, Match, MatchStatus, VenueTable
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_operator_queue,
    get_table_status,
    get_next_available_table,
)
from tournament_platform.services.audit_service import get_audit_logs, log_audit
from tournament_platform.services.table_availability_service import (
    get_table_availability_summary,
    set_max_available_tables,
    ensure_minimum_venue_tables,
)
from tournament_platform.services.operator_commands import (
    parse_operator_command,
    apply_operator_command,
)
from tournament_platform.services.voice_transcription import (
    is_vosk_available,
    get_vosk_setup_instructions,
    transcribe_wav_bytes,
)
from tournament_platform.app.components.player_path import render_player_path
from tournament_platform.app.components.operator_components import (
    render_quick_actions,
    render_command_bar,
    render_voice_shortcut,
    render_table_status_section,
    render_audit_log,
    render_announcements_section,
    render_issues_table,
    render_health_kpi,
    render_now_playing_lane,
    render_up_next_lane,
    render_needs_attention_lane,
    render_recent_results_lane,
)
from tournament_platform.app.components.manual_score_panel import render_manual_score_panel

# Import the centralized API client
from tournament_platform.app.api_client import api_client
from tournament_platform.app.design_system import apply_global_styles


# ============================================================================
# Data Loading (cached for performance)
# ============================================================================

@st.cache_data(ttl=10, show_spinner="Loading tournaments...")
def load_tournaments() -> List[Dict[str, Any]]:
    """Load all tournaments from the database."""
    db = SessionLocal()
    try:
        return list_tournaments(db)
    finally:
        db.close()


@st.cache_data(ttl=5, show_spinner="Loading operator queue...")
def load_operator_queue(tournament_id: int) -> List[Dict[str, Any]]:
    """Load operator queue for a tournament."""
    db = SessionLocal()
    try:
        return get_operator_queue(db, tournament_id=tournament_id)
    finally:
        db.close()


@st.cache_data(ttl=5, show_spinner="Loading table status...")
def load_table_status(tournament_id: int) -> List[Dict[str, Any]]:
    """Load table status for a tournament."""
    db = SessionLocal()
    try:
        return get_table_status(db, tournament_id=tournament_id)
    finally:
        db.close()


@st.cache_data(ttl=5, show_spinner="Loading available table...")
def load_next_available_table(tournament_id: int) -> Optional[Dict[str, Any]]:
    """Load next available table for a tournament."""
    db = SessionLocal()
    try:
        return get_next_available_table(db, tournament_id=tournament_id)
    finally:
        db.close()


@st.cache_data(ttl=5, show_spinner="Loading table availability...")
def load_table_availability(tournament_id: int) -> Dict[str, Any]:
    """Load table availability summary for a tournament."""
    db = SessionLocal()
    try:
        return get_table_availability_summary(db, tournament_id=tournament_id)
    finally:
        db.close()


@st.cache_data(ttl=30, show_spinner="Loading audit log...")
def load_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    """Load recent audit log entries."""
    db = SessionLocal()
    try:
        return get_audit_logs(db, limit=limit)
    finally:
        db.close()


# ============================================================================
# API Helper Functions
# ============================================================================

def call_match(match_id: int, table: Optional[str] = None) -> Dict[str, Any]:
    """Call a match via API."""
    result = api_client.call_match(match_id, table)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def start_match(match_id: int) -> Dict[str, Any]:
    """Start a match via API."""
    result = api_client.start_match(match_id)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def complete_match(match_id: int) -> Dict[str, Any]:
    """Complete a match via API."""
    result = api_client.complete_match(match_id)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def delay_match(match_id: int, delay_minutes: int = 15) -> Dict[str, Any]:
    """Delay a match via API."""
    result = api_client.delay_match(match_id, delay_minutes)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def reschedule_match(match_id: int, scheduled_time: str, table: Optional[str] = None) -> Dict[str, Any]:
    """Reschedule a match via API."""
    result = api_client.reschedule_match(match_id, scheduled_time, table)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def reset_call_match(match_id: int) -> Dict[str, Any]:
    """Reset call status to pending via API."""
    result = api_client.reset_call_match(match_id)
    return result if result is not None else {"status": "error", "message": "API request failed"}


def _dispatch(fn, match_id: int, verb: str) -> None:
    """Run an operator action then clear cache and rerun (mirrors prior behavior)."""
    try:
        fn(match_id)
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Failed to {verb} match: {e}")


def _build_callbacks() -> Dict[str, Any]:
    """Build the action-callback dict used by the lane renderers."""
    return {
        "call": lambda mid: _dispatch(call_match, mid, "call"),
        "start": lambda mid: _dispatch(start_match, mid, "start"),
        "complete": lambda mid: _dispatch(complete_match, mid, "complete"),
        "delay": lambda mid: _dispatch(delay_match, mid, "delay"),
        "reset": lambda mid: _dispatch(reset_call_match, mid, "reset"),
        "reschedule": lambda mid, iso, tbl: _dispatch(
            lambda m=mid: reschedule_match(m, iso, tbl), mid, "reschedule"
        ),
    }


def _partition_queue(queue: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Partition the operator queue into lane buckets.

    - now_playing: active or called (plus delayed surfaced as attention elsewhere)
    - up_next: queued/pending/not_called
    - completed: status == completed
    Each match appears in exactly one primary lane bucket.
    """
    now_playing = [m for m in queue if m.get("call_status") in ("active", "called")]
    up_next = [m for m in queue if m.get("call_status") in ("not_called", "queued", "pending")]
    delayed = [m for m in queue if m.get("call_status") == "delayed"]
    completed = [m for m in queue if m.get("status") == "completed"]
    return {
        "now_playing": now_playing,
        "delayed": delayed,
        "up_next": up_next,
        "completed": completed,
    }


def render_table_status_tab(selected_id: int) -> None:
    """Render the Table Status tab content."""
    try:
        table_availability = load_table_availability(selected_id)
    except Exception as e:
        st.error(f"Failed to load table availability: {e}")
        table_availability = {"total_tables": 0, "active_tables": 0, "tables": []}

    def on_set_max_tables(max_available: int, total_tables: int, keep_busy_active: bool):
        db = SessionLocal()
        try:
            result = set_max_available_tables(
                db,
                max_tables=max_available,
                tournament_id=selected_id,
                actor="operator",
                prefer_keep_busy_tables_active=keep_busy_active,
            )
            if result.get("warnings"):
                for warning in result["warnings"]:
                    st.warning(warning)
            st.success(f"Set {result['resulting_active_tables']} tables as active")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Error setting max available tables: {e}")
        finally:
            db.close()

    def on_create_tables(max_available: int):
        db = SessionLocal()
        try:
            create_result = ensure_minimum_venue_tables(
                db,
                count=max_available,
                actor="operator"
            )
            if create_result.get("created_tables", 0) > 0:
                st.success(f"Created {create_result['created_tables']} tables")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No tables needed to be created")
        except Exception as e:
            st.error(f"Error creating tables: {e}")
        finally:
            db.close()

    render_table_status_section(table_availability, on_set_max_tables, on_create_tables)


def render_match_queue_tab(selected_id: int) -> None:
    """Render the Match Queue lane view (used by Admin and Operator Console).

    Kept as a stable entry point for ``admin.py`` and tests; it reuses the same
    lane renderers and manual score panel as the full console.
    """
    try:
        queue = load_operator_queue(selected_id)
        table_status = load_table_status(selected_id)
    except Exception as e:
        st.error(f"Failed to load queue: {e}")
        return

    for m in queue:
        m["_table_status"] = table_status

    partitions = _partition_queue(queue)
    callbacks = _build_callbacks()

    render_now_playing_lane(
        partitions["now_playing"] + partitions["delayed"], callbacks, key_prefix="adm_now"
    )

    st.divider()

    render_up_next_lane(partitions["up_next"], callbacks, key_prefix="adm_upnext")

    st.divider()

    st.subheader("✍️ Manual Score Entry")
    st.caption("Draft the score with undo. Only confirmed results are committed.")
    active_only = [m for m in partitions["now_playing"] if m.get("call_status") == "active"]
    if active_only:
        for m in active_only:
            render_manual_score_panel(m, key_prefix="adm_msp")
    else:
        st.info("No active matches to score. Start a match first.")


def render_operator_console() -> None:
    """Render the operator console page with lane-based organization."""
    st.set_page_config(
        page_title="LIT_IT Match Center",
        page_icon="🎛️",
        layout="wide",
    )

    apply_global_styles()

    from tournament_platform.app.components.brand_assets import render_brand_icon
    render_brand_icon("admin_operator")
    st.title("🎛️ LIT_IT Match Center")
    st.caption("Manage match flow and table assignments")

    # Load tournaments
    try:
        tournaments = load_tournaments()
    except Exception as e:
        st.error(f"Failed to load tournaments: {e}")
        st.stop()

    if not tournaments:
        st.info("No tournaments found. Create a tournament first.")
        st.stop()

    # Tournament selector
    tournament_options = {t["name"]: t["id"] for t in tournaments}
    selected_name = st.selectbox(
        "Select Tournament",
        options=list(tournament_options.keys()),
        index=0,
        key="operator_tournament_select",
    )
    selected_id = tournament_options[selected_name]

    # Manual refresh
    if st.button("🔄 Refresh", key="operator_refresh"):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # -------------------------------------------------------------------------
    # Load shared data once (fixes the previous `queue` name-resolution bug)
    # -------------------------------------------------------------------------
    try:
        queue = load_operator_queue(selected_id)
        table_status = load_table_status(selected_id)
    except Exception as e:
        st.error(f"Failed to load queue: {e}")
        queue = []
        table_status = []

    # Attach table status so lane reschedule forms can offer tables.
    for m in queue:
        m["_table_status"] = table_status

    active = [m for m in queue if m.get("call_status") in ("active", "called")]
    delayed = [m for m in queue if m.get("call_status") == "delayed"]
    up_next = [m for m in queue if m.get("call_status") in ("not_called", "queued", "pending")]
    completed = [m for m in queue if m.get("status") == "completed"]

    partitions = _partition_queue(queue)
    active = partitions["now_playing"]
    delayed = partitions["delayed"]
    up_next = partitions["up_next"]
    completed = partitions["completed"]

    # Tournament health (for issues lane + KPIs)
    @st.cache_data(ttl=10, show_spinner="Loading health data...")
    def load_tournament_health(tournament_id: int) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            from tournament_platform.services.health_service import get_tournament_health
            return get_tournament_health(db, tournament_id=tournament_id)
        finally:
            db.close()

    try:
        health = load_tournament_health(selected_id)
    except Exception as e:
        st.error(f"Failed to load health data: {e}")
        health = {"match_counts": {}, "table_utilization": {}, "issues": []}

    issues = health.get("issues", [])
    callbacks = _build_callbacks()

    # -------------------------------------------------------------------------
    # Lanes
    # -------------------------------------------------------------------------
    tabs = st.tabs(["Now Playing", "Up Next", "Needs Attention", "Table Status", "Recent Results"])

    with tabs[0]:
        # Quick actions (Call/Start/Complete/Delay Next)
        def on_call_next():
            nxt = next((m for m in queue if m.get("call_status") == "not_called"), None)
            if nxt:
                _dispatch(call_match, nxt["id"], "call")
            else:
                st.info("No matches ready to call")

        def on_start_next():
            nxt = next((m for m in queue if m.get("call_status") == "called"), None)
            if nxt:
                _dispatch(start_match, nxt["id"], "start")
            else:
                st.info("No matches ready to start")

        def on_complete_next():
            nxt = next((m for m in queue if m.get("call_status") == "active"), None)
            if nxt:
                _dispatch(complete_match, nxt["id"], "complete")
            else:
                st.info("No active matches to complete")

        def on_delay_next():
            nxt = next((m for m in queue if m.get("call_status") in ("not_called", "called", "active")), None)
            if nxt:
                _dispatch(delay_match, nxt["id"], "delay")
            else:
                st.info("No matches to delay")

        render_quick_actions(on_call_next, on_start_next, on_complete_next, on_delay_next)

        st.divider()

        def on_command_submit(command_text: str, tournament_id: int):
            _apply_command(command_text, tournament_id)

        render_command_bar(on_command_submit, selected_id)

        st.divider()

        def on_voice_command(text: str, tournament_id: int):
            _apply_command(text, tournament_id)

        render_voice_shortcut(on_voice_command, selected_id)

        st.divider()

        render_now_playing_lane(active + delayed, callbacks, key_prefix="now")

        st.divider()

        # Manual score entry (draft + undo) for active matches
        st.subheader("✍️ Manual Score Entry")
        st.caption("Draft the score with undo. Only confirmed results are committed.")
        active_only = [m for m in active if m.get("call_status") == "active"]
        if active_only:
            for m in active_only:
                render_manual_score_panel(m, key_prefix="msp")
        else:
            st.info("No active matches to score. Start a match first.")

    with tabs[1]:
        render_up_next_lane(up_next, callbacks, key_prefix="upnext")

    with tabs[2]:
        render_needs_attention_lane(issues, queue, callbacks, key_prefix="attn")

    with tabs[3]:
        render_table_status_tab(selected_id)

    with tabs[4]:
        render_recent_results_lane(completed)

    st.divider()

    # -------------------------------------------------------------------------
    # Tournament Health KPIs (compact, always visible)
    # -------------------------------------------------------------------------
    st.subheader("📊 Tournament Health")
    render_health_kpi(health)

    st.divider()

    # -------------------------------------------------------------------------
    # Duplicate Player Detection
    # -------------------------------------------------------------------------
    st.subheader("🔍 Duplicate Player Detection")

    @st.cache_data(ttl=30, show_spinner="Scanning for duplicates...")
    def load_duplicate_candidates() -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            from tournament_platform.services.duplicate_players import find_duplicate_candidates
            return find_duplicate_candidates(db)
        finally:
            db.close()

    if st.button("🔍 Scan for Duplicates", key="scan_duplicates_btn"):
        st.cache_data.clear()
        st.rerun()

    try:
        candidates = load_duplicate_candidates()
    except Exception as e:
        st.error(f"Failed to scan for duplicates: {e}")
        candidates = []

    if candidates:
        st.markdown(f"**Found {len(candidates)} potential duplicate(s)**")

        for i, candidate in enumerate(candidates[:10]):
            with st.container(border=True):
                col1, col2, col3 = st.columns([2, 2, 1])

                with col1:
                    st.markdown(f"**{candidate['player1_name']}**")
                    if candidate.get('player1_email'):
                        st.caption(f"Email: {candidate['player1_email']}")

                with col2:
                    st.markdown(f"**{candidate['player2_name']}**")
                    if candidate.get('player2_email'):
                        st.caption(f"Email: {candidate['player2_email']}")

                with col3:
                    st.metric("Similarity", f"{candidate['similarity_score']}%")
                    st.caption(candidate.get('reason', ''))

                if st.button("Preview Merge", key=f"preview_merge_{i}"):
                    db = SessionLocal()
                    try:
                        from tournament_platform.services.duplicate_players import preview_player_merge
                        preview = preview_player_merge(
                            db,
                            target_player_id=candidate['player1_id'],
                            source_player_id=candidate['player2_id'],
                        )
                        st.session_state[f"merge_preview_{i}"] = preview
                    except Exception as e:
                        st.error(f"Failed to preview merge: {e}")
                    finally:
                        db.close()

                if f"merge_preview_{i}" in st.session_state:
                    preview = st.session_state[f"merge_preview_{i}"]
                    if preview.get("success"):
                        st.info(f"Would transfer {preview['matches_to_transfer']} matches, {preview['rating_history_to_transfer']} rating history entries")
                        for warning in preview.get("warnings", []):
                            st.warning(warning)

                        if st.button("✅ Confirm Merge", key=f"confirm_merge_{i}"):
                            db = SessionLocal()
                            try:
                                from tournament_platform.services.duplicate_players import merge_players
                                result = merge_players(
                                    db,
                                    target_player_id=candidate['player1_id'],
                                    source_player_id=candidate['player2_id'],
                                    actor="operator",
                                )
                                if result.get("success"):
                                    st.success(f"Merged! Transferred {result['matches_transferred']} matches")
                                    del st.session_state[f"merge_preview_{i}"]
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(result.get("error", "Merge failed"))
                            except Exception as e:
                                st.error(f"Merge error: {e}")
                            finally:
                                db.close()
    else:
        st.info("No duplicate candidates found. Click 'Scan for Duplicates' to check.")

    st.divider()

    # -------------------------------------------------------------------------
    # Player Path
    # -------------------------------------------------------------------------
    st.subheader("🎯 Player Path")

    player_name = st.text_input("Enter player name to see path", key="player_path_input")
    if player_name:
        db = SessionLocal()
        try:
            found = render_player_path(db, player_name, tournament_id=selected_id, key_prefix="operator_path")
            if not found:
                st.info(f"No matches found for player '{player_name}'")
        except Exception as e:
            st.error(f"Failed to get player path: {e}")
        finally:
            db.close()

    st.divider()

    # -------------------------------------------------------------------------
    # Audit Log
    # -------------------------------------------------------------------------
    try:
        audit = load_audit_log(limit=50)
    except Exception as e:
        st.error(f"Failed to load audit log: {e}")
        audit = []

    render_audit_log(audit)

    st.divider()

    # -------------------------------------------------------------------------
    # Announcements
    # -------------------------------------------------------------------------
    render_announcements_section(selected_id, selected_name)


def _apply_command(command_text: str, tournament_id: int) -> None:
    """Parse and apply an operator command (from command bar or voice)."""
    parsed = parse_operator_command(command_text)

    if parsed.intent.value == "unknown":
        st.error(f"Unknown command: '{command_text}'")
        return

    st.info(f"Intent: **{parsed.intent.value}** | Confidence: {parsed.confidence:.0%}")
    st.markdown(f"**Preview:** {parsed.preview}")

    if not parsed.requires_confirmation:
        db = SessionLocal()
        try:
            result = apply_operator_command(
                db,
                parsed,
                confirmed=True,
                tournament_id=tournament_id,
            )
            if result.get("status") == "success":
                st.success(result.get("message", "Command executed"))
                if result.get("data"):
                    st.json(result.get("data"))
            else:
                st.error(result.get("message", "Command failed"))
        except Exception as e:
            st.error(f"Error executing command: {e}")
        finally:
            db.close()
    else:
        if st.button("✅ Confirm Action", key="confirm_command"):
            db = SessionLocal()
            try:
                result = apply_operator_command(
                    db,
                    parsed,
                    confirmed=True,
                    tournament_id=tournament_id,
                )
                if result.get("status") == "success":
                    st.success(result.get("message", "Command executed"))
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(result.get("message", "Command failed"))
            except Exception as e:
                st.error(f"Error executing command: {e}")
            finally:
                db.close()


if __name__ == "__main__":
    render_operator_console()
