"""
Page Header component for Streamlit UI.

Reusable header component with title, description, and optional actions.
"""

import streamlit as st


def render_page_header(
    title: str,
    description: str = "",
    icon: str = "",
    actions: list = None,
):
    """
    Render a consistent page header with title, description, and optional actions.

    Args:
        title: The main page title
        description: Optional description/subtitle text
        icon: Optional emoji or icon to display before title
        actions: Optional list of (label, key) tuples for action buttons
    """
    # Title with optional icon
    if icon:
        st.title(f"{icon} {title}")
    else:
        st.title(title)

    # Description
    if description:
        st.caption(description)

    # Action buttons
    if actions:
        cols = st.columns(len(actions))
        for i, (label, key) in enumerate(actions):
            with cols[i]:
                if st.button(label, key=key, use_container_width=True):
                    st.session_state[f"action_{key}"] = True

    st.space("medium")