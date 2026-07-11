"""
Match Center

A control panel for tournament operators to manage match flow.
Features:
- Match call queue with conflict detection
- Table status overview
- Rescheduling interface
- Audit log viewer
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
)


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

# Import the centralized API client
from tournament_platform.app.api_client import api_client
from tournament_platform.app.design_system import apply_global_styles


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


# ============================================================================
# UI Rendering - Tab-based Organization
# ============================================================================

def render_match_queue_tab(selected_id: int) -> None:
    """Render the Match Queue tab content."""
    # -------------------------------------------------------------------------
    # Quick Actions Section
    # -------------------------------------------------------------------------
    def on_call_next():
        try:
            queue = load_operator_queue(selected_id)
            next_match = next((m for m in queue if m.get("call_status") == "not_called"), None)
            if next_match:
                result = call_match(next_match["id"])
                st.success(f"Match called: {result.get('message', '')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No matches ready to call")
        except Exception as e:
            st.error(f"Failed to call match: {e}")

    def on_start_next():
        try:
            queue = load_operator_queue(selected_id)
            next_match = next((m for m in queue if m.get("call_status") == "called"), None)
            if next_match:
                result = start_match(next_match["id"])
                st.success(f"Match started: {result.get('message', '')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No matches ready to start")
        except Exception as e:
            st.error(f"Failed to start match: {e}")

    def on_complete_next():
        try:
            queue = load_operator_queue(selected_id)
            next_match = next((m for m in queue if m.get("call_status") == "active"), None)
            if next_match:
                result = complete_match(next_match["id"])
                st.success(f"Match completed: {result.get('message', '')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No active matches to complete")
        except Exception as e:
            st.error(f"Failed to complete match: {e}")

    def on_delay_next():
        try:
            queue = load_operator_queue(selected_id)
            next_match = next((m for m in queue if m.get("call_status") in ("not_called", "called", "active")), None)
            if next_match:
                result = delay_match(next_match["id"])
                st.info(f"Match delayed: {result.get('message', '')}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No matches to delay")
        except Exception as e:
            st.error(f"Failed to delay match: {e}")

    render_quick_actions(on_call_next, on_start_next, on_complete_next, on_delay_next)

    st.divider()

    # -------------------------------------------------------------------------
    # Command Bar Section
    # -------------------------------------------------------------------------
    def on_command_submit(command_text: str, tournament_id: int):
        parsed = parse_operator_command(command_text)

        if parsed.intent.value == "unknown":
            st.error(f"Unknown command: '{command_text}'")
        else:
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

    render_command_bar(on_command_submit, selected_id)

    st.divider()

    # -------------------------------------------------------------------------
    # Voice Shortcut Section
    # -------------------------------------------------------------------------
    def on_voice_command(text: str, tournament_id: int):
        parsed = parse_operator_command(text)

        if parsed.intent.value == "unknown":
            st.error(f"Unknown command: '{text}'")
        else:
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
                if st.button("✅ Confirm Voice Command", key="confirm_voice_command"):
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

    render_voice_shortcut(on_voice_command, selected_id)

    st.divider()

    # -------------------------------------------------------------------------
    # Match Queue List Section
    # -------------------------------------------------------------------------
    st.subheader("📋 Match Queue")

    try:
        queue = load_operator_queue(selected_id)
        table_status = load_table_status(selected_id)
    except Exception as e:
        st.error(f"Failed to load queue: {e}")
        queue = []
        table_status = []

    if queue:
        for match in queue:
            match_id = match.get("id")
            call_status = match.get("call_status", "not_called")

            with st.container(border=True):
                col_info, col_actions = st.columns([3, 1])

                with col_info:
                    st.markdown(f"**{match.get('player1', '?')} vs {match.get('player2', '?')}**")
                    st.markdown(f"📍 {match.get('location', 'No table')}")
                    st.markdown(f"⏰ {match.get('scheduled_time', 'No time')}")
                    st.markdown(f"🏷️ {match.get('display_label', 'Match')}")

                    conflict_flags = match.get("conflict_flags", [])
                    if "table_conflict" in conflict_flags:
                        st.error("⚠️ Table conflict detected!")
                    if "missing_table" in conflict_flags:
                        st.warning("⚠️ No table assigned")

                with col_actions:
                    if call_status == "not_called":
                        if st.button("📢 Call", key=f"call_{match_id}"):
                            result = call_match(match_id)
                            st.success(f"Match called: {result.get('message', '')}")
                            st.cache_data.clear()
                            st.rerun()
                    elif call_status == "called":
                        if st.button("▶️ Start", key=f"start_{match_id}"):
                            result = start_match(match_id)
                            st.success(f"Match started: {result.get('message', '')}")
                            st.cache_data.clear()
                            st.rerun()
                    elif call_status == "active":
                        if st.button("✅ Complete", key=f"complete_{match_id}"):
                            result = complete_match(match_id)
                            st.success(f"Match completed: {result.get('message', '')}")
                            st.cache_data.clear()
                            st.rerun()

                    if st.button("⏸ Delay", key=f"delay_{match_id}"):
                        result = delay_match(match_id)
                        st.info(f"Match delayed: {result.get('message', '')}")
                        st.cache_data.clear()
                        st.rerun()

                    if st.button("🔄 Reset", key=f"reset_{match_id}"):
                        result = reset_call_match(match_id)
                        st.info(f"Match reset: {result.get('message', '')}")
                        st.cache_data.clear()
                        st.rerun()

                    if st.button("📅 Reschedule", key=f"reschedule_{match_id}"):
                        st.session_state[f"show_reschedule_{match_id}"] = True

                    if st.session_state.get(f"show_reschedule_{match_id}"):
                        with st.form(key=f"reschedule_form_{match_id}"):
                            col_date, col_time = st.columns([1, 1])
                            with col_date:
                                new_date = st.date_input(
                                    "Date",
                                    value=datetime.now(timezone.utc).date(),
                                    key=f"new_date_{match_id}"
                                )
                            with col_time:
                                new_time_input = st.time_input(
                                    "Time",
                                    value=datetime.now(timezone.utc).time(),
                                    key=f"new_time_{match_id}"
                                )

                            table_options = [""] + [t["table_name"] for t in table_status]
                            new_table = st.selectbox(
                                "Table (optional)",
                                options=table_options,
                                index=0,
                                key=f"new_table_{match_id}"
                            )

                            submitted = st.form_submit_button("Save")
                            if submitted:
                                combined_dt = datetime.combine(new_date, new_time_input)
                                combined_dt = combined_dt.replace(tzinfo=timezone.utc)

                                if combined_dt < datetime.now(timezone.utc):
                                    st.error("Please select a date/time in the future")
                                else:
                                    iso_time = combined_dt.isoformat()
                                    result = reschedule_match(match_id, iso_time, new_table if new_table else None)
                                    st.success(f"Match rescheduled: {result.get('message', '')}")
                                    st.session_state[f"show_reschedule_{match_id}"] = False
                                    st.cache_data.clear()
                                    st.rerun()
    else:
        st.info("No matches in queue.")


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


def render_operator_console() -> None:
    """Render the operator console page with tabs."""
    st.set_page_config(
        page_title="LIT_IT Match Center",
        page_icon="🎛️",
        layout="wide",
    )

    apply_global_styles()

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

    # Tabs for Match Center
    tabs = st.tabs(["Match Queue", "Table Status"])

    with tabs[0]:
        render_match_queue_tab(selected_id)

    with tabs[1]:
        render_table_status_tab(selected_id)

    st.divider()

    # -------------------------------------------------------------------------
    # Match Reporting Section
    # -------------------------------------------------------------------------
    st.subheader("📊 Match Reporting")
    st.caption("Quick score entry for completed matches")

    active_matches = [m for m in queue if m.get("call_status") == "active"]

    if active_matches:
        for match in active_matches:
            match_id = match.get("id")
            p1 = match.get("player1", "?")
            p2 = match.get("player2", "?")
            current_score = match.get("score", "0-0")

            with st.container(border=True):
                st.markdown(f"**{p1} vs {p2}**")

                col_score, col_winner, col_report = st.columns([2, 2, 1])

                with col_score:
                    score_input = st.text_input(
                        "Score (e.g., 11-9)",
                        value=current_score,
                        key=f"score_input_{match_id}",
                        label_visibility="collapsed",
                    )

                with col_winner:
                    winner_options = [p1, p2, "Not decided"]
                    winner = st.selectbox(
                        "Winner",
                        options=winner_options,
                        key=f"winner_select_{match_id}",
                        label_visibility="collapsed",
                    )

                with col_report:
                    st.markdown("###")
                    if st.button("Report", key=f"report_{match_id}", type="primary"):
                        try:
                            s1, s2 = map(int, score_input.split("-"))
                            if s1 < 0 or s2 < 0:
                                st.error("Scores must be non-negative")
                            else:
                                result = api_client.report_match(
                                    match_id=match_id,
                                    score1=s1,
                                    score2=s2,
                                    winner=winner if winner != "Not decided" else None,
                                )
                                if result and result.get("status") == "success":
                                    st.success("Match reported!")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Failed to report: {result.get('message', 'Unknown error')}")
                        except ValueError:
                            st.error("Invalid score format. Use '11-9' format.")
    else:
        st.info("No active matches to report. Start a match first.")

    st.divider()

    # -------------------------------------------------------------------------
    # Health Dashboard Section
    # -------------------------------------------------------------------------
    st.subheader("📊 Tournament Health")

    @st.cache_data(ttl=10, show_spinner="Loading health data...")
    def load_tournament_health(tournament_id: int) -> Dict[str, Any]:
        """Load tournament health data."""
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

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Matches", health.get("match_counts", {}).get("active", 0))
    with col2:
        st.metric("Called Matches", health.get("match_counts", {}).get("called", 0))
    with col3:
        st.metric("Delayed Matches", health.get("match_counts", {}).get("delayed", 0))
    with col4:
        st.metric("Table Utilization", f"{health.get('table_utilization', {}).get('utilization_percent', 0)}%")

    issues = health.get("issues", [])
    render_issues_table(issues)

    st.divider()

    # -------------------------------------------------------------------------
    # Duplicate Players Section
    # -------------------------------------------------------------------------
    st.subheader("🔍 Duplicate Player Detection")

    @st.cache_data(ttl=30, show_spinner="Scanning for duplicates...")
    def load_duplicate_candidates() -> List[Dict[str, Any]]:
        """Load duplicate player candidates."""
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
    # Player Path Section
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
    # Audit Log Section
    # -------------------------------------------------------------------------
    try:
        audit = load_audit_log(limit=50)
    except Exception as e:
        st.error(f"Failed to load audit log: {e}")
        audit = []

    render_audit_log(audit)

    st.divider()

    # -------------------------------------------------------------------------
    # Announcements Section
    # -------------------------------------------------------------------------
    render_announcements_section(selected_id, selected_name)


if __name__ == "__main__":
    render_operator_console()