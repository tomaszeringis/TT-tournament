"""
Operator Console Sub-components

Modular components for the Match Center page.
"""

import streamlit as st
import pandas as pd
from typing import Dict, Any, List, Optional, Callable


def render_match_queue_item(
    match: Dict[str, Any],
    on_call: Callable[[int], None],
    on_start: Callable[[int], None],
    on_complete: Callable[[int], None],
    on_delay: Callable[[int], None],
    on_reset: Callable[[int], None],
) -> None:
    """Render a single match in the queue with action buttons."""
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
                if st.button("📢 Call", key=f"call_{match_id}", on_click=lambda: on_call(match_id)):
                    pass
            elif call_status == "called":
                if st.button("▶️ Start", key=f"start_{match_id}", on_click=lambda: on_start(match_id)):
                    pass
            elif call_status == "active":
                if st.button("✅ Complete", key=f"complete_{match_id}", on_click=lambda: on_complete(match_id)):
                    pass

            if st.button("⏸ Delay", key=f"delay_{match_id}", on_click=lambda: on_delay(match_id)):
                pass

            if st.button("🔄 Reset", key=f"reset_{match_id}", on_click=lambda: on_reset(match_id)):
                pass


def render_table_status_card(table: Dict[str, Any]) -> None:
    """Render a table status card."""
    status = table.get("status", "available")
    is_active = table.get("is_active")

    if is_active:
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
    else:
        st.markdown(f"⚪ **{table['table_name']}** (inactive)")

        current = table.get("current_match")
        if current:
            st.markdown(f"🎮 **Current:** {current['player1']} vs {current['player2']}")

        next_m = table.get("next_match")
        if next_m:
            st.markdown(f"⏭️ **Next:** {next_m['player1']} vs {next_m['player2']}")


def render_health_kpi(health: Dict[str, Any]) -> None:
    """Render health dashboard KPIs."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Matches", health.get("match_counts", {}).get("active", 0))
    with col2:
        st.metric("Called Matches", health.get("match_counts", {}).get("called", 0))
    with col3:
        st.metric("Delayed Matches", health.get("match_counts", {}).get("delayed", 0))
    with col4:
        st.metric("Table Utilization", f"{health.get('table_utilization', {}).get('utilization_percent', 0)}%")


def render_issues_table(issues: List[Dict[str, Any]]) -> None:
    """Render issues table with severity indicators."""
    if issues:
        st.markdown("**Detected Issues**")

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

        error_issues = [i for i in issues if i.get("severity") == "error"]
        if error_issues:
            st.error(f"⚠️ {len(error_issues)} error(s) require attention")


def render_quick_actions(
    on_call_next: Callable[[], None],
    on_start_next: Callable[[], None],
    on_complete_next: Callable[[], None],
    on_delay_next: Callable[[], None],
) -> None:
    """Render the quick actions section."""
    st.subheader("⚡ Quick Actions")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.button("📢 Call Next Match", use_container_width=True, type="primary", on_click=on_call_next)
    with col2:
        st.button("▶️ Start Next Match", use_container_width=True, on_click=on_start_next)
    with col3:
        st.button("✅ Complete Next Match", use_container_width=True, on_click=on_complete_next)
    with col4:
        st.button("⏸ Delay Next Match", use_container_width=True, on_click=on_delay_next)


def render_command_bar(
    on_command_submit: Callable[[str, int], None],
    tournament_id: int,
) -> None:
    """Render the command bar section."""
    st.subheader("⌨️ Command Bar")
    st.caption("Type commands like: 'call match 12 to table 3', 'show player path John Smith', 'next available table'")

    command_text = st.text_input(
        "Enter command",
        key="operator_command_input",
        placeholder="e.g., call match 12 to table 3, show player path John Smith, next available table",
    )

    if command_text:
        on_command_submit(command_text, tournament_id)


def render_voice_shortcut(
    on_voice_command: Callable[[str, int], None],
    tournament_id: int,
) -> None:
    """Render the voice shortcut section."""
    with st.expander("🎙️ Voice Shortcut (Optional)", expanded=False):
        from tournament_platform.services.voice_transcription import (
            is_vosk_available,
            get_vosk_setup_instructions,
            transcribe_wav_bytes,
        )

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
                        on_voice_command(text, tournament_id)
                    else:
                        st.warning("No speech detected in audio file.")


def render_table_status_section(
    table_availability: Dict[str, Any],
    on_set_max_tables: Callable[[int, int, bool], None],
    on_create_tables: Callable[[int], None],
) -> None:
    """Render the table status section."""
    st.subheader("📍 Table Status")

    # Available table limit control block
    with st.container(border=True):
        st.markdown("**Available table limit**")

        col_limit, col_btn = st.columns([2, 1])

        with col_limit:
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
                on_set_max_tables(int(max_available), total_tables, keep_busy_active)

            if max_available > total_tables:
                if st.button("Create missing tables", key="create_missing_tables_btn"):
                    on_create_tables(int(max_available))

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("**Table Overview**")
        tables = table_availability.get("tables", [])
        if tables:
            for table in tables:
                render_table_status_card(table)
        else:
            st.info("No tables configured yet.")

    with col2:
        st.markdown("**Queue**")
        # Queue rendering will be handled by parent


def render_audit_log(audit: List[Dict[str, Any]]) -> None:
    """Render the audit log section."""
    st.subheader("📜 Audit Log")

    if audit:
        for entry in audit:
            with st.container(border=True):
                st.markdown(f"**{entry.get('action', 'unknown')}** by {entry.get('actor', 'system')}")
                st.markdown(f"🕒 {entry.get('created_at', 'N/A')}")
                if entry.get("payload"):
                    st.json(entry.get("payload"))
    else:
        st.info("No audit entries yet.")


def render_announcements_section(tournament_id: int, tournament_name: str) -> None:
    """Render the announcements section."""
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

        if st.form_submit_button("📢 Create Announcement"):
            if announcement_message or announcement_stage:
                import requests
                try:
                    msg = announcement_message
                    if announcement_stage:
                        msg = f"{announcement_stage} starting now in {tournament_name}! Good luck to all players."

                    resp = requests.post(
                        "http://localhost:8000/api/announcements",
                        json={
                            "message": msg,
                            "tournament_id": tournament_id,
                            "channel": "local",
                        },
                    )
                    result = resp.json()

                    if result.get("status") == "success":
                        st.success(f"Announcement created: {msg}")

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