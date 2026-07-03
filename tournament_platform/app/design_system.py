"""
Design System for Tournament Platform

This module provides consistent styling, colors, and UI components
for the entire application.
"""

# Color palette
COLORS = {
    "primary": "#007bff",
    "primary_dark": "#0056b3",
    "success": "#28a745",
    "success_dark": "#218838",
    "warning": "#ffc107",
    "warning_dark": "#e0a800",
    "danger": "#dc3545",
    "danger_dark": "#c82333",
    "info": "#17a2b8",
    "info_dark": "#138496",
    "light": "#f8f9fa",
    "dark": "#343a40",
    "background": "#1e1e1e",
    "card_bg": "#2d2d2d",
    "border": "#444444",
    "text_primary": "#ffffff",
    "text_secondary": "#aaaaaa",
}

# Status colors
STATUS_COLORS = {
    "active": "#f44336",  # Red
    "called": "#FFC107",  # Yellow
    "completed": "#4CAF50",  # Green
    "pending": "#2196F3",  # Blue
    "delayed": "#FF9800",  # Orange
}

# Spacing
SPACING = {
    "xs": "0.25rem",
    "sm": "0.5rem",
    "md": "1rem",
    "lg": "1.5rem",
    "xl": "2rem",
}

# Border radius
BORDER_RADIUS = {
    "sm": "4px",
    "md": "8px",
    "lg": "12px",
    "xl": "16px",
}


def get_status_color(status: str) -> str:
    """Get the color for a match status."""
    return STATUS_COLORS.get(status, COLORS["info"])


def get_status_icon(status: str) -> str:
    """Get the icon for a match status."""
    icons = {
        "active": "🔴",
        "called": "🟡",
        "completed": "🟢",
        "pending": "🔵",
        "delayed": "⏸️",
    }
    return icons.get(status, "⚪")


def render_status_badge(status: str, key: str = None) -> None:
    """Render a status badge using Streamlit's built-in status elements."""
    import streamlit as st
    
    color = get_status_color(status)
    icon = get_status_icon(status)
    
    st.markdown(
        f"""
        <div style="
            display: inline-block;
            background-color: {color};
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        ">
            {icon} {status.title()}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_card(
    title: str = None,
    icon: str = None,
    border_color: str = None,
    background_color: str = COLORS["card_bg"],
) -> None:
    """Render a styled card container."""
    import streamlit as st
    
    color = border_color or COLORS["border"]
    
    st.markdown(
        f"""
        <div style="
            border: 2px solid {color};
            border-radius: {BORDER_RADIUS['lg']};
            padding: 16px;
            margin: 8px 0;
            background-color: {background_color};
        ">
        """,
        unsafe_allow_html=True,
    )
    
    if title:
        st.markdown(f"### {icon + ' ' if icon else ''}{title}")


def close_card() -> None:
    """Close a styled card container."""
    import streamlit as st
    st.markdown("</div>", unsafe_allow_html=True)


def render_page_header(
    title: str,
    description: str = None,
    icon: str = None,
) -> None:
    """Render a consistent page header."""
    import streamlit as st
    
    # Intentionally do not render emoji icons in the global page header to keep a clean top bar
    st.title(title)
    if description:
        st.caption(description)


def render_action_button(
    label: str,
    icon: str = None,
    type: str = "secondary",
    use_container_width: bool = False,
    **kwargs,
) -> bool:
    """Render a consistent action button."""
    import streamlit as st
    
    return st.button(
        f"{icon + ' ' if icon else ''}{label}",
        type=type,
        use_container_width=use_container_width,
        **kwargs,
    )


def render_kpi_card(
    label: str,
    value: str,
    icon: str = None,
    delta: str = None,
) -> None:
    """Render a KPI card with consistent styling."""
    import streamlit as st
    
    with st.container(border=True):
        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown(f"<div style='font-size: 24px;'>{icon or '📊'}</div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"**{label}**")
            st.markdown(f"<div style='font-size: 24px; font-weight: bold;'>{value}</div>", unsafe_allow_html=True)
            if delta:
                st.caption(delta)


# CSS styles to be injected into pages
GLOBAL_STYLES = """
<style>
    /* Reduce top padding for cleaner look */
    .block-container {
        padding-top: 1rem;
    }
    
    /* Style buttons with consistent hover effect */
    div.stButton > button {
        transition: all 0.2s ease;
    }
    
    div.stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    
    /* Style containers with border */
    [data-testid="stContainer"] {
        border-radius: 8px;
    }
</style>
"""


def apply_global_styles() -> None:
    """Inject global CSS styles into the Streamlit page."""
    import streamlit as st

    st.markdown(GLOBAL_STYLES, unsafe_allow_html=True)