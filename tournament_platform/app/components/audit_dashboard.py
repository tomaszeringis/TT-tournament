"""
Audit Dashboard Component

Displays audit logs with filtering and search capabilities for admin users.
"""

from typing import Optional, List, Dict, Any

import streamlit as st
import pandas as pd

from tournament_platform.models import SessionLocal
from tournament_platform.services.audit_service import get_audit_logs


def render_audit_dashboard(limit: int = 100) -> None:
    """
    Render the audit dashboard.

    Args:
        limit: Maximum number of audit log entries to display
    """
    st.subheader("📋 Audit Dashboard")

    db = SessionLocal()
    try:
        audit_logs = get_audit_logs(db, limit=limit)
    finally:
        db.close()

    if not audit_logs:
        st.info("No audit logs found.")
        return

    df_data = []
    for log in audit_logs:
        df_data.append({
            "ID": log.get("id"),
            "Timestamp": log.get("created_at"),
            "Action": log.get("action"),
            "Actor": log.get("actor"),
            "Entity": log.get("entity_type"),
            "Entity ID": log.get("entity_id"),
        })

    df = pd.DataFrame(df_data)

    with st.expander("🔍 Filter Audit Logs", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            action_filter = st.text_input("Filter by action", key="audit_action_filter")
        with col2:
            actor_filter = st.text_input("Filter by actor", key="audit_actor_filter")

        if action_filter:
            df = df[df["Action"].str.contains(action_filter, case=False, na=False)]
        if actor_filter:
            df = df[df["Actor"].str.contains(actor_filter, case=False, na=False)]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "Timestamp": st.column_config.TextColumn("Timestamp", width="medium"),
            "Action": st.column_config.TextColumn("Action", width="medium"),
            "Actor": st.column_config.TextColumn("Actor", width="small"),
            "Entity": st.column_config.TextColumn("Entity", width="small"),
            "Entity ID": st.column_config.NumberColumn("Entity ID", width="small"),
        },
    )
