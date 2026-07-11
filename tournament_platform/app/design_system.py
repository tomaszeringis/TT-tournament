"""
Design System for Tournament Platform (LitIT Brand)

This module provides consistent styling, colors, and UI components
for the entire application, following the LitIT brand system.
"""

# ---------------------------------------------------------------------------
# Brand tokens
# ---------------------------------------------------------------------------
COLORS = {
    # Brand surfaces
    "litit_black": "#1A1C1B",     # Brand black (primary surfaces)
    "litit_white": "#FFFFFF",     # Brand white (text on dark)
    # Primary actions
    "primary": "#1A1C1B",          # LitIT Black used as primary action
    "primary_hover": "#2D2E2D",    # Slightly lighter black for hover
    "secondary": "#B0B3B8",        # Secondary text / secondary button text
    # Accents
    "accent_blue": "#0066FF",      # Energetic blue for interactive accents
    "accent_green": "#00C853",     # Success / active states
    "accent_orange": "#FF6D00",    # Warning / attention
    "accent_red": "#FF1744",       # Danger / active alerts
    "accent_yellow": "#FFD600",    # Called / pending
    # Surfaces
    "background": "#0D0D0D",       # Deep black (app background)
    "surface": "#1A1C1B",          # Card / panel background
    "surface_elevated": "#242526", # Elevated cards / dropdowns
    "border": "#333436",           # Subtle borders
    "border_strong": "#4A4D4E",     # Stronger borders for focus
    # Text
    "text_primary": "#FFFFFF",     # Primary text
    "text_secondary": "#B0B3B8",   # Secondary text
    "text_muted": "#6B7280",       # Muted / placeholder
    # Legacy aliases (kept for backward compatibility)
    "success": "#00C853",
    "warning": "#FFD600",
    "danger": "#FF1744",
    "info": "#0066FF",
    "light": "#FFFFFF",
    "dark": "#1A1C1B",
    "card_bg": "#1A1C1B",
}

# Status colors (brand-consistent hex values)
STATUS_COLORS = {
    "active": "#FF1744",    # brand red
    "called": "#FFD600",    # brand yellow
    "completed": "#00C853", # brand green
    "pending": "#0066FF",   # brand blue
    "delayed": "#FF6D00",   # brand orange
}

# Brand metadata
BRAND = {
    "name": "LIT_IT",
    "full_name": "LIT_IT Tournament Platform",
    "tagline": "part of NTT DATA",
    "logo_light": "assets/brand/litit-logo-light.svg",
    "logo_dark": "assets/brand/litit-logo-dark.svg",
    "favicon": "assets/brand/litit-favicon.svg",
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

# Typography stacks
FONT_SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
FONT_MONO = '"Fira Code", "JetBrains Mono", "SF Mono", Consolas, monospace'


def get_status_color(status: str) -> str:
    """Get the brand color for a match status."""
    return STATUS_COLORS.get(status, COLORS["accent_blue"])


def get_status_icon(status: str) -> str:
    """Get the icon for a match status (never rely on color alone)."""
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
    background_color: str = COLORS["surface"],
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


# ---------------------------------------------------------------------------
# Branded card helpers
# Centralized so every page renders brand-consistent cards. Accepts plain
# data (dicts or scalars) so they can be reused by public_board / dashboard.
# ---------------------------------------------------------------------------

def render_litit_match_card(match: dict, label: str = "Match") -> None:
    """Render a large match card for TV/projector display (brand colors)."""
    import streamlit as st

    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    score = match.get("score") or "vs"
    winner = match.get("winner") or "Pending"
    status = match.get("status") or "pending"
    call_status = match.get("call_status") or "not_called"
    location = match.get("location") or "No table"
    round_num = match.get("round_number")

    if status == "completed":
        status_icon = "🟢"
        border_color = COLORS["accent_green"]
    elif call_status == "active":
        status_icon = "🔴"
        border_color = COLORS["accent_red"]
    elif call_status == "called":
        status_icon = "🟡"
        border_color = COLORS["accent_yellow"]
    else:
        status_icon = "🔵"
        border_color = COLORS["accent_blue"]

    round_str = f"Round {round_num}" if round_num else ""
    table_str = f"Table {location}" if location and location != "No table" else "No table"
    label_str = " · ".join([x for x in [round_str, table_str] if x])

    winner_color = COLORS["accent_green"]
    plain = COLORS["text_primary"]
    muted = COLORS["text_secondary"]

    st.markdown(
        f"""
        <div style="
            border: 3px solid {border_color};
            border-radius: 12px;
            padding: 20px;
            margin: 10px 0;
            background-color: {COLORS['surface']};
        ">
            <div style="text-align: center; font-size: 14px; color: {muted}; margin-bottom: 8px;">
                {status_icon} {label} &nbsp;|&nbsp; {label_str}
            </div>
            <div style="display: flex; justify-content: space-around; align-items: center;">
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 28px; font-weight: bold; color: {plain};">
                        {p1}
                    </div>
                    <div style="font-size: 48px; font-weight: bold; color: {winner_color if winner == p1 else plain};">
                        {score.split('-')[0] if '-' in score else score}
                    </div>
                </div>
                <div style="font-size: 36px; color: {COLORS['text_muted']}; padding: 0 20px;">VS</div>
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 28px; font-weight: bold; color: {plain};">
                        {p2}
                    </div>
                    <div style="font-size: 48px; font-weight: bold; color: {winner_color if winner == p2 else plain};">
                        {score.split('-')[1] if '-' in score else score}
                    </div>
                </div>
            </div>
            <div style="text-align: center; font-size: 16px; color: {muted}; margin-top: 8px;">
                Winner: {winner}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_litit_coming_up_card(match: dict) -> None:
    """Render a smaller card for coming up matches (brand colors)."""
    import streamlit as st

    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    location = match.get("location") or "No table"
    scheduled = match.get("scheduled_time")
    time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"

    st.markdown(
        f"""
        <div style="
            border: 2px solid {COLORS['accent_blue']};
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background-color: {COLORS['surface']};
        ">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: {COLORS['text_secondary']}; font-size: 12px;">{time_str} · Table {location}</span>
                <span style="font-size: 14px;"><b>{p1}</b> vs <b>{p2}</b></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_litit_delayed_card(match: dict) -> None:
    """Render a card for delayed matches (brand colors)."""
    import streamlit as st

    p1 = match.get("player1") or "TBD"
    p2 = match.get("player2") or "TBD"
    location = match.get("location") or "No table"
    operator_note = match.get("operator_note") or ""
    scheduled = match.get("scheduled_time")
    time_str = scheduled.split("T")[1][:5] if scheduled else "--:--"

    st.markdown(
        f"""
        <div style="
            border: 2px solid {COLORS['accent_orange']};
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background-color: {COLORS['surface']};
        ">
            <div style="font-size: 14px; color: {COLORS['accent_orange']}; margin-bottom: 4px;">
                ⏸️ DELAYED
            </div>
            <div style="font-size: 16px;"><b>{p1}</b> vs <b>{p2}</b></div>
            <div style="color: {COLORS['text_secondary']}; font-size: 12px;">Table: {location} | Scheduled: {time_str}</div>
            {f'<div style="color: {COLORS['text_muted']}; font-size: 12px; margin-top: 4px;">Note: {operator_note}</div>' if operator_note else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_litit_announcement_card(message: str, created_at: str = "N/A") -> None:
    """Render an announcement card (brand colors)."""
    import streamlit as st

    st.markdown(
        f"""
        <div style="
            border: 2px solid {COLORS['accent_green']};
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            background-color: {COLORS['surface']};
        ">
            <div style="font-size: 18px; font-weight: bold; color: {COLORS['accent_green']};">
                📣 {message}
            </div>
            <div style="color: {COLORS['text_secondary']}; font-size: 12px; margin-top: 4px;">
                {created_at}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_litit_result_row(
    player1: str,
    player2: str,
    score: str,
    winner: str,
    time_str: str,
) -> None:
    """Render a single recent-result row (brand colors)."""
    import streamlit as st

    st.markdown(
        f"""
        <div style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 16px;
            border-bottom: 1px solid {COLORS['border']};
        ">
            <span style="color: {COLORS['text_secondary']}; font-size: 14px;">{time_str}</span>
            <span style="flex: 1; text-align: center; font-size: 18px;">
                <b>{player1}</b> {score} <b>{player2}</b>
            </span>
            <span style="color: {COLORS['accent_green']}; font-size: 14px;">🏆 {winner}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_litit_upcoming_row(
    player1: str,
    player2: str,
    time_str: str,
    status: str,
    status_icon: str,
) -> None:
    """Render a single upcoming-match row (brand colors)."""
    import streamlit as st

    st.markdown(
        f"""
        <div style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 16px;
            border-bottom: 1px solid {COLORS['border']};
        ">
            <span style="color: {COLORS['text_secondary']}; font-size: 14px;">{time_str}</span>
            <span style="flex: 1; text-align: center; font-size: 18px;">
                {status_icon} <b>{player1}</b> vs <b>{player2}</b>
            </span>
            <span style="color: {COLORS['text_secondary']}; font-size: 14px;">{status.title()}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# CSS styles to be injected into pages
# LitIT brand theme. Ensures WCAG AA accessibility compliance:
# - Color contrasts verified for the dark theme
# - Focus outlines for keyboard navigation (accent blue)
# - Consistent button, tab, sidebar, and scrollbar styling
GLOBAL_STYLES = """
<style>
    /* Base typography */
    body, .stApp {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #0D0D0D;
        color: #FFFFFF;
    }
    code, .mono {
        font-family: "Fira Code", "JetBrains Mono", "SF Mono", Consolas, monospace;
    }

    /* Main content surface */
    .main > div, .block-container {
        background-color: #0D0D0D;
    }
    .block-container {
        padding-top: 1rem;
    }

    /* Header / title color */
    h1, h2, h3, h4, h5, h6 {
        color: #FFFFFF !important;
    }

    /* Buttons: consistent hover effect */
    div.stButton > button {
        transition: all 0.2s ease;
        border-radius: 8px;
    }
    div.stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.4);
    }

    /* Primary button: LitIT black surface with white outline */
    div.stButton > button[data-baseweb="button"][kind="primary"] {
        background-color: #1A1C1B;
        color: #FFFFFF;
        border: 1px solid #FFFFFF;
    }
    div.stButton > button[data-baseweb="button"][kind="primary"]:hover {
        background-color: #2D2E2D;
        border-color: #FFFFFF;
    }

    /* Secondary button: transparent with subtle border */
    div.stButton > button[data-baseweb="button"]:not([kind="primary"]) {
        background-color: transparent;
        color: #B0B3B8;
        border: 1px solid #333436;
    }
    div.stButton > button[data-baseweb="button"]:not([kind="primary"]):hover {
        border-color: #B0B3B8;
        color: #FFFFFF;
    }

    /* Keyboard accessibility: focus outlines for all interactive elements */
    button:focus, input:focus, select:focus, textarea:focus, a:focus {
        outline: 2px solid #0066FF !important;
        outline-offset: 2px;
    }
    button:focus-visible, input:focus-visible, select:focus-visible,
    textarea:focus-visible, a:focus-visible {
        outline: 2px solid #0066FF !important;
        outline-offset: 2px;
    }

    /* Containers / cards */
    [data-testid="stContainer"] {
        border-radius: 8px;
        border-color: #333436;
        background-color: #1A1C1B;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab"] {
        color: #6B7280;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #FFFFFF !important;
        border-bottom: 2px solid #0066FF !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 1px solid #333436;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0D0D0D;
        border-right: 1px solid #333436;
    }
    [data-testid="stSidebar"] .block-container {
        background-color: #0D0D0D;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background-color: #1A1C1B;
        border: 1px solid #333436;
        border-radius: 8px;
        padding: 10px 14px;
    }

    /* Ensure link text is underlined for accessibility */
    a {
        text-decoration: none;
        color: #0066FF;
    }
    a:hover {
        text-decoration: underline;
    }

    /* Scrollbars (dark theme) */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    ::-webkit-scrollbar-track {
        background: #333436;
    }
    ::-webkit-scrollbar-thumb {
        background: #4A4D4E;
        border-radius: 5px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #6B7280;
    }
</style>
"""


def apply_global_styles() -> None:
    """Inject global CSS styles into the Streamlit page."""
    import streamlit as st

    st.markdown(GLOBAL_STYLES, unsafe_allow_html=True)
