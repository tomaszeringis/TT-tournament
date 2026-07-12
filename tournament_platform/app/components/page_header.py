"""
Page Header component for Streamlit UI.

Reusable header component with title, description, and optional actions.
"""

import streamlit as st


def render_page_header(
    title: str,
    description: str = "",
    icon: str = "",
    icon_name: str = None,
    actions: list = None,
):
    """
    Render a consistent page header with title, description, and optional actions.

    Args:
        title: The main page title
        description: Optional description/subtitle text
        icon: Optional emoji or icon to display before title
        icon_name: Optional logical LITIT icon key (e.g. ``"dashboard"``) rendered
            as a small brand mark above the title via ``brand_assets``.
        actions: Optional list of (label, key) tuples for action buttons
    """
    if icon_name:
        try:
            from tournament_platform.app.components.brand_assets import render_brand_icon
            render_brand_icon(icon_name, width=40)
        except Exception:
            pass

    # Title
    st.title(f"{icon + ' ' if icon else ''}{title}")

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