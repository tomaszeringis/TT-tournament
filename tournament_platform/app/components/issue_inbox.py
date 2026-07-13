"""
Tournament Health Alert Inbox

Unified alert inbox for Operator Console that surfaces issues from the
health service and allows operators to acknowledge them.
"""

from typing import List, Dict, Any, Optional

import streamlit as st

from tournament_platform.services.health_service import (
    get_tournament_health,
    get_alert_inbox,
    acknowledge_issue,
)
from tournament_platform.models import SessionLocal


def render_issue_inbox(tournament_id: int, max_issues: int = 50) -> List[Dict[str, Any]]:
    """
    Render a compact alert inbox for a tournament.
    
    Args:
        tournament_id: The tournament to display alerts for
        max_issues: Maximum number of issues to render
        
    Returns:
        List of remaining unacknowledged issues
    """
    db = SessionLocal()
    try:
        inbox = get_alert_inbox(db, tournament_id=tournament_id)
    finally:
        db.close()

    inbox = inbox[:max_issues]

    if not inbox:
        st.success("Nothing needs attention.")
        return []

    error_issues = [i for i in inbox if i.get("severity") == "error"]
    warning_issues = [i for i in inbox if i.get("severity") != "error"]

    if error_issues:
        st.error(f"⚠️ {len(error_issues)} error(s) require attention")
    if warning_issues:
        st.warning(f"ℹ️ {len(warning_issues)} warning(s)")

    for issue in inbox:
        with st.container(border=True):
            cols = st.columns([4, 1])
            with cols[0]:
                st.markdown(f"**{issue.get('message', 'Unknown issue')}**")
                st.caption(f"Type: {issue.get('issue_type')} | Match: {issue.get('match_id', 'N/A')}")
            with cols[1]:
                if st.button("Ack", key=f"ack_{issue.get('issue_id')}"):
                    acknowledge_issue(issue.get("issue_id"), actor="operator")
                    st.rerun()

    return inbox
