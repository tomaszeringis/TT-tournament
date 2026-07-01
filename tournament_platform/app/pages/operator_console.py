"""
Operator Console

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
# UI Rendering
# ============================================================================

def render_operator_console() -> None:
    """Render the operator console page."""
    st.set_page_config(
        page_title="Operator Console",
        page_icon="🎛️",
        layout="wide",
    )

    st.title("🎛️ Operator Console")
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
    # Command Bar Section
    # -------------------------------------------------------------------------
    st.subheader("⌨️ Command Bar")
    st.caption("Type commands like: 'call match 12 to table 3', 'show player path John Smith', 'next available table'")

    command_text = st.text_input(
        "Enter command",
        key="operator_command_input",
        placeholder="e.g., call match 12 to table 3, show player path John Smith, next available table",
    )

    if command_text:
        # Parse the command
        parsed = parse_operator_command(command_text)

        # Show parsed intent
        if parsed.intent.value == "unknown":
            st.error(f"Unknown command: '{command_text}'")
        else:
            st.info(f"Intent: **{parsed.intent.value}** | Confidence: {parsed.confidence:.0%}")
            st.markdown(f"**Preview:** {parsed.preview}")

            # For read-only commands, show result immediately
            if not parsed.requires_confirmation:
                db = SessionLocal()
                try:
                    result = apply_operator_command(
                        db,
                        parsed,
                        confirmed=True,
                        tournament_id=selected_id,
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
                # For state-changing commands, show confirmation button
                if st.button("✅ Confirm Action", key="confirm_command"):
                    db = SessionLocal()
                    try:
                        result = apply_operator_command(
                            db,
                            parsed,
                            confirmed=True,
                            tournament_id=selected_id,
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

    st.divider()

    # -------------------------------------------------------------------------
    # Voice Shortcut Section
    # -------------------------------------------------------------------------
    with st.expander("🎙️ Voice Shortcut (Optional)", expanded=False):
        if not is_vosk_available():
            st.info("Voice recognition is optional. " + get_vosk_setup_instructions())
        else:
            st.caption("Upload a short WAV audio file (16-bit mono, 16kHz) with your command")
            audio_file = st.file_uploader(
                "Upload audio command",
                type=["wav"],
                key="voice_audio_upload",
                label_visibility="collapsed",
            )
            if audio_file is not None:
                with st.spinner("Transcribing..."):
                    audio_bytes = audio_file.read()
                    text, error = transcribe_wav_bytes(audio_bytes)
                    
                    if error:
                        st.error(error)
                    elif text:
                        st.success(f"Transcribed: **{text}**")
                        
                        # Parse the transcribed command
                        parsed = parse_operator_command(text)
                        
                        if parsed.intent.value == "unknown":
                            st.error(f"Unknown command: '{text}'")
                        else:
                            st.info(f"Intent: **{parsed.intent.value}** | Confidence: {parsed.confidence:.0%}")
                            st.markdown(f"**Preview:** {parsed.preview}")
                            
                            if not parsed.requires_confirmation:
                                # For read-only commands, show result immediately
                                db = SessionLocal()
                                try:
                                    result = apply_operator_command(
                                        db,
                                        parsed,
                                        confirmed=True,
                                        tournament_id=selected_id,
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
                                # For state-changing commands, require confirmation
                                if st.button("✅ Confirm Voice Command", key="confirm_voice_command"):
                                    db = SessionLocal()
                                    try:
                                        result = apply_operator_command(
                                            db,
                                            parsed,
                                            confirmed=True,
                                            tournament_id=selected_id,
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
                    else:
                        st.warning("No speech detected in audio file.")

    st.divider()

    # -------------------------------------------------------------------------
    # Table Status Section
    # -------------------------------------------------------------------------
    st.subheader("📍 Table Status")

    # Load table availability for the control block
    try:
        table_availability = load_table_availability(selected_id)
    except Exception as e:
        st.error(f"Failed to load table availability: {e}")
        table_availability = {"total_tables": 0, "active_tables": 0, "tables": []}

    # Available table limit control block
    with st.container(border=True):
        st.markdown("**Available table limit**")

        col_limit, col_btn = st.columns([2, 1])

        with col_limit:
            # Default to current active count
            current_active = table_availability.get("active_tables", 0)
            total_tables = table_availability.get("total_tables", 0)
            default_max = current_active if current_active > 0 else total_tables

            max_available = st.number_input(
                "Max available tables",
                min_value=0,
                value=default_max,
                step=1,
                key="max_available_tables_input",
                help="Set the maximum number of tables that should be marked as available/active"
            )

            keep_busy_active = st.checkbox(
                "Keep tables with active/called matches available",
                value=True,
                key="keep_busy_tables_checkbox",
                help="When checked, tables with ongoing matches will stay active even if they exceed the limit"
            )

        with col_btn:
            st.markdown("###")
            if st.button("Set max available tables", key="set_max_available_btn"):
                db = SessionLocal()
                try:
                    result = set_max_available_tables(
                        db,
                        max_tables=int(max_available),
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

            # Optional: Create missing tables button
            if max_available > total_tables:
                if st.button("Create missing tables", key="create_missing_tables_btn"):
                    db = SessionLocal()
                    try:
                        create_result = ensure_minimum_venue_tables(
                            db,
                            count=int(max_available),
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

    col1, col2 = st.columns([2, 1])

    with col1:
        try:
            table_status = load_table_status(selected_id)
        except Exception as e:
            st.error(f"Failed to load table status: {e}")
            table_status = []

        if table_status:
            # Separate active and inactive tables
            active_tables = [t for t in table_status if t.get("is_active")]
            inactive_tables = [t for t in table_status if not t.get("is_active")]

            # Show active tables first
            if active_tables:
                st.markdown("**Active Tables**")
                for table in active_tables:
                    with st.container(border=True):
                        status = table.get("status", "available")
                        if status == "busy":
                            st.markdown(f"🔴 **{table['table_name']}** (busy)")
                        else:
                            st.markdown(f"🟢 **{table['table_name']}** (available)")

                        current = table.get("current_match")
                        if current:
                            st.markdown(f"🎮 **Current:** {current['player1']} vs {current['player2']}")

                        next_m = table.get("next_match")
                        if next_m:
                            st.markdown(f"⏭️ **Next:** {next_m['player1']} vs {next_m['player2']}")

            # Show inactive tables
            if inactive_tables:
                st.markdown("**Inactive Tables**")
                for table in inactive_tables:
                    with st.container(border=True):
                        st.markdown(f"⚪ **{table['table_name']}** (inactive)")

                        current = table.get("current_match")
                        if current:
                            st.markdown(f"🎮 **Current:** {current['player1']} vs {current['player2']}")

                        next_m = table.get("next_match")
                        if next_m:
                            st.markdown(f"⏭️ **Next:** {next_m['player1']} vs {next_m['player2']}")
        else:
            st.info("No tables configured. Add tables in tournament setup.")

    with col2:
        st.markdown("### Next Available")
        try:
            available = load_next_available_table(selected_id)
        except Exception as e:
            st.error(f"Failed to get available table: {e}")
            available = None

        if available:
            if available.get("status") == "free":
                st.success(f"✅ {available['table_name']} is free")
            else:
                st.warning(f"⏳ {available['table_name']} (busy, oldest: {available.get('oldest_match_scheduled', 'N/A')})")
        else:
            st.info("No active tables")

    st.divider()

    # -------------------------------------------------------------------------
    # Match Queue Section
    # -------------------------------------------------------------------------
    st.subheader("📋 Match Queue")

    try:
        queue = load_operator_queue(selected_id)
    except Exception as e:
        st.error(f"Failed to load match queue: {e}")
        queue = []

    if queue:
        for match in queue:
            conflict_flags = match.get("conflict_flags", [])
            has_conflict = "table_conflict" in conflict_flags
            missing_table = "missing_table" in conflict_flags

            with st.container(border=True):
                col_info, col_actions = st.columns([3, 1])

                with col_info:
                    st.markdown(f"**{match.get('player1', '?')} vs {match.get('player2', '?')}**")
                    st.markdown(f"📍 {match.get('location', 'No table')}")
                    st.markdown(f"⏰ {match.get('scheduled_time', 'No time')}")
                    st.markdown(f"🏷️ {match.get('display_label', 'Match')}")

                    if has_conflict:
                        st.error("⚠️ Table conflict detected!")
                    if missing_table:
                        st.warning("⚠️ No table assigned")

                with col_actions:
                    match_id = match.get("id")
                    call_status = match.get("call_status", "not_called")

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
                        st.info(f"Call reset: {result.get('message', '')}")
                        st.cache_data.clear()
                        st.rerun()

                    if st.button("📅 Reschedule", key=f"reschedule_{match_id}"):
                        st.session_state[f"show_reschedule_{match_id}"] = True

                # Reschedule dialog
                if st.session_state.get(f"show_reschedule_{match_id}"):
                    with st.form(key=f"reschedule_form_{match_id}"):
                        new_time = st.text_input(
                            "New time (ISO format)",
                            value=datetime.now(timezone.utc).isoformat(),
                            key=f"new_time_{match_id}"
                        )
                        new_table = st.text_input(
                            "New table (optional)",
                            key=f"new_table_{match_id}"
                        )
                        submitted = st.form_submit_button("Save")
                        if submitted:
                            result = reschedule_match(match_id, new_time, new_table or None)
                            st.success(f"Match rescheduled: {result.get('message', '')}")
                            st.session_state[f"show_reschedule_{match_id}"] = False
                            st.cache_data.clear()
                            st.rerun()
    else:
        st.info("No matches in queue.")

    st.divider()

    # -------------------------------------------------------------------------
    # Health Dashboard Section
    # -------------------------------------------------------------------------
    st.subheader("🏥 Tournament Health")

    # Load health data
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

    # KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Matches", health.get("match_counts", {}).get("active", 0))
    with col2:
        st.metric("Called Matches", health.get("match_counts", {}).get("called", 0))
    with col3:
        st.metric("Delayed Matches", health.get("match_counts", {}).get("delayed", 0))
    with col4:
        st.metric("Table Utilization", f"{health.get('table_utilization', {}).get('utilization_percent', 0)}%")

    # Issues table
    issues = health.get("issues", [])
    if issues:
        st.markdown("**Detected Issues**")
        
        # Sortable issues table
        issue_data = []
        for issue in issues:
            issue_data.append({
                "Type": issue.get("issue_type", "unknown"),
                "Match ID": issue.get("match_id", "N/A"),
                "Severity": issue.get("severity", "warning"),
                "Message": issue.get("message", ""),
            })
        
        issue_df = pd.DataFrame(issue_data)
        st.dataframe(
            issue_df,
            use_container_width=True,
            hide_index=True,
        )
        
        # Alert inbox - show error issues prominently
        error_issues = [i for i in issues if i.get("severity") == "error"]
        if error_issues:
            st.error(f"⚠️ {len(error_issues)} error(s) require attention")
    else:
        st.success("✅ No issues detected")

    st.divider()

    # -------------------------------------------------------------------------
    # Duplicate Players Section
    # -------------------------------------------------------------------------
    st.subheader("👥 Duplicate Player Detection")

    # Load duplicate candidates
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
        
        for i, candidate in enumerate(candidates[:10]):  # Show top 10
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
                
                # Merge preview button
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
                
                # Show merge preview if available
                if f"merge_preview_{i}" in st.session_state:
                    preview = st.session_state[f"merge_preview_{i}"]
                    if preview.get("success"):
                        st.info(f"Would transfer {preview['matches_to_transfer']} matches, {preview['rating_history_to_transfer']} rating history entries")
                        for warning in preview.get("warnings", []):
                            st.warning(warning)
                        
                        # Confirm merge button
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
    st.subheader("📜 Audit Log")

    try:
        audit = load_audit_log(limit=50)
    except Exception as e:
        st.error(f"Failed to load audit log: {e}")
        audit = []

    if audit:
        for entry in audit:
            with st.container(border=True):
                st.markdown(f"**{entry.get('action', 'unknown')}** by {entry.get('actor', 'system')}")
                st.markdown(f"🕒 {entry.get('created_at', 'N/A')}")
                if entry.get("payload"):
                    st.json(entry.get("payload"))
    else:
        st.info("No audit entries yet.")

    st.divider()

    # -------------------------------------------------------------------------
    # Announcements Section
    # -------------------------------------------------------------------------
    st.subheader("📢 Announcements")

    # Create announcement form
    with st.form(key="create_announcement_form", clear_on_submit=True):
        announcement_message = st.text_input(
            "Announcement message",
            key="announcement_message_input",
            placeholder="e.g., Semifinals starting now!",
        )
        announcement_stage = st.selectbox(
            "Or select a stage to announce",
            options=["", "Semifinals", "Finals", "Round 1", "Round 2"],
            key="announcement_stage_select",
        )
        send_immediately = st.checkbox("Send to webhook (if configured)", value=False, key="send_webhook_checkbox")

        if st.form_submit_button("📣 Create Announcement"):
            if announcement_message or announcement_stage:
                import requests
                try:
                    # Use stage message if selected, otherwise use custom message
                    msg = announcement_message
                    if announcement_stage:
                        msg = f"{announcement_stage} starting now in {selected_name}! Good luck to all players."

                    resp = requests.post(
                        "http://localhost:8000/api/announcements",
                        json={
                            "message": msg,
                            "tournament_id": selected_id,
                            "channel": "local",
                        },
                    )
                    result = resp.json()

                    if result.get("status") == "success":
                        st.success(f"Announcement created: {msg}")

                        # Send to webhook if requested
                        if send_immediately:
                            send_resp = requests.post(
                                f"http://localhost:8000/api/announcements/{result['announcement_id']}/send"
                            )
                            send_result = send_resp.json()
                            if send_result.get("status") == "success":
                                st.success("Announcement sent to webhook!")
                            elif send_result.get("status") == "skipped":
                                st.info(f"Webhook not configured: {send_result.get('message')}")
                            else:
                                st.warning(f"Webhook send failed: {send_result.get('message')}")
                    else:
                        st.error(f"Failed to create announcement: {result.get('message')}")
                except Exception as e:
                    st.error(f"Error creating announcement: {e}")
            else:
                st.warning("Please enter a message or select a stage.")

    # Show recent announcements
    st.caption("Recent announcements:")
    try:
        import requests
        resp = requests.get("http://localhost:8000/api/announcements?limit=10")
        ann_data = resp.json()
        announcements = ann_data.get("announcements", [])
    except Exception:
        announcements = []

    if announcements:
        for ann in announcements:
            with st.container(border=True):
                st.markdown(f"**{ann.get('message', '')}**")
                st.caption(f"Status: {ann.get('sent_status', 'unknown')} | {ann.get('created_at', 'N/A')}")
    else:
        st.info("No announcements yet.")


if __name__ == "__main__":
    render_operator_console()