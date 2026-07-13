"""
Page Header component for Streamlit UI.

Reusable header component with an inline icon, title, description/subtitle,
and optional actions. The icon is rendered on the same horizontal line as the
title (vertically centered) so it never floats above the heading.
"""

import base64
import streamlit as st
from pathlib import Path

from tournament_platform.app.components.brand_assets import get_brand_icon

_PAGE_HEADER_CSS = """
<style>
.page-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 0 0 0.25rem 0;
    padding: 0;
}
.page-header-icon {
    width: 40px;
    height: 40px;
    object-fit: contain;
    flex: 0 0 auto;
    display: block;
}
.page-header-emoji {
    font-size: 34px;
    line-height: 1;
    flex: 0 0 auto;
    display: block;
}
.page-header-title {
    margin: 0;
    padding: 0;
    line-height: 1.1;
    font-size: 1.75rem;
    font-weight: 600;
}
.page-header-subtitle {
    margin: 0.4rem 0 0 0;
    color: var(--text-muted, #a3a3a3);
    font-size: 0.95rem;
    line-height: 1.4;
}
</style>
"""


def _brand_icon_html(icon_name: str, size: int = 40) -> str:
    """Return an <img> tag for a LITIT brand icon, or empty string if missing."""
    try:
        path = Path(get_brand_icon(icon_name))
        if not path.exists():
            return ""
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return (
            f'<img class="page-header-icon" src="data:image/png;base64,{data}" '
            f'width="{size}" height="{size}" alt="" aria-hidden="true" />'
        )
    except Exception:
        return ""


def render_page_header(
    title: str,
    description: str = "",
    icon: str = "",
    icon_name: str = None,
    actions: list = None,
    icon_size: int = 40,
):
    """
    Render a consistent page header with an inline icon, title and subtitle.

    The icon (emoji ``icon`` or brand ``icon_name``) is rendered on the same
    line as the title, vertically centered, with a consistent gap. The
    subtitle appears below the title, aligned to the title text.

    Args:
        title: The main page title
        description: Optional description/subtitle text
        icon: Optional emoji/text icon rendered inline before the title
        icon_name: Optional logical LITIT icon key (e.g. ``"dashboard"``)
            rendered as an inline brand mark before the title.
        actions: Optional list of (label, key) tuples for action buttons
        icon_size: Pixel size for the brand icon (default 40)
    """
    st.markdown(_PAGE_HEADER_CSS, unsafe_allow_html=True)

    icon_html = ""
    if icon:
        icon_html = f'<span class="page-header-emoji" aria-hidden="true">{icon}</span>'
    elif icon_name:
        icon_html = _brand_icon_html(icon_name, size=icon_size)

    st.markdown(
        f"""
        <div class="page-header">
            {icon_html}
            <h1 class="page-header-title">{title}</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if description:
        st.markdown(
            f'<div class="page-header-subtitle">{description}</div>',
            unsafe_allow_html=True,
        )

    # Action buttons
    if actions:
        cols = st.columns(len(actions))
        for i, (label, key) in enumerate(actions):
            with cols[i]:
                if st.button(label, key=key, use_container_width=True):
                    st.session_state[f"action_{key}"] = True

    st.space("medium")
