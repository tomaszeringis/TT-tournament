"""
Empty State component for Streamlit UI.

Reusable empty state component for when no data is available.
"""

import streamlit as st

from tournament_platform.app.design_system import COLORS


def render_empty_state(
    icon: str = "📭",
    title: str = "No data available",
    description: str = "",
    cta_label: str = "",
    cta_key: str = "",
):
    """
    Render a consistent empty state with icon, message, and optional CTA.

    Args:
        icon: Emoji or icon to display
        title: Main message title
        description: Optional description text
        cta_label: Optional call-to-action button label
        cta_key: Optional key for the CTA button
    """
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"<div style='text-align: center; padding: 2rem;'>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size: 48px;'>{icon}</div>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='margin: 0; color: {COLORS['text_primary']};'>{title}</h3>", unsafe_allow_html=True)
        if description:
            st.markdown(
                f"<p style='color: {COLORS['text_secondary']}; margin: 0.5rem 0;'>{description}</p>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        if cta_label and cta_key:
            if st.button(cta_label, key=cta_key, use_container_width=True, type="primary"):
                st.session_state[f"empty_state_action_{cta_key}"] = True