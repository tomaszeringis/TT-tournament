"""
LITIT brand asset helper.

Thin wrapper around :mod:`tournament_platform.app.components.brand_assets` that
exposes the rendering helpers (sidebar logo, footer mark) and the legacy
``logo_path`` / ``icon_path`` accessors still used by ``design_system`` and
``main``. Paths are repository-relative, so no absolute machine-specific paths
are committed into the code.
"""

from tournament_platform.app.components.brand_assets import (
    BRAND_ASSETS_DIR,
    DEFAULT_ICON,
    ICON_DIR,
    LOGO_DIR,
    PAGE_ICON_FILES,
    SIDEBAR_LOGO,
    get_brand_icon,
    get_sidebar_logo,
)

# Primary logo (sidebar / header) = the exact official LITIT logo file.
LOGO = SIDEBAR_LOGO

# Compact brand mark (favicon / footer / generic page icon).
ICON = DEFAULT_ICON

# Brand metadata
TAGLINE = "part of NTT DATA"
APP_NAME = "TT Tournament Platform"

# Navigation icon mapping (Streamlit st.Page does not support image-file icons,
# so we use Material Symbols - built into Streamlit 1.58 - for a consistent,
# polished look). The LITIT icon marks are used as the favicon and on page
# content via ``brand_assets.render_brand_icon`` / ``get_brand_icon``).
PAGE_ICONS = {
    "home": ":material/sports_tennis:",
    "dashboard": ":material/dashboard:",
    "participants": ":material/group:",
    "tournament": ":material/emoji_events:",
    "public_board": ":material/leaderboard:",
    "operator_console": ":material/settings_remote:",
    "voice_scorekeeper": ":material/mic:",
    "video_scorekeeper": ":material/videocam:",
    "ai_assistant": ":material/smart_toy:",
    "dataset_catalog": ":material/dataset:",
    "coaching_lab": ":material/fitness_center:",
    "experiment_dashboard": ":material/science:",
    "admin": ":material/admin_panel_settings:",
}


def get_brand_asset_path(name: str) -> str:
    """Return the absolute path to a named brand asset (logo or icon)."""
    key = name.lower()
    if key in ("logo", "sidebar_logo.png"):
        return str(LOGO)
    if key in ("icon", "litit_icon.png"):
        return str(ICON)
    return get_brand_icon(name)


def logo_path() -> str:
    """Absolute path to the primary LITIT logo (sidebar / hero)."""
    return str(LOGO)


def icon_path() -> str:
    """Absolute path to the compact LITIT icon (favicon / app icon)."""
    return str(ICON)


def render_sidebar_logo(width: int = 160) -> None:
    """Render the official LITIT logo in the app shell (sidebar / header).

    Uses a controlled display width (120-180px) so the wordmark is never
    stretched, cropped, or oversized. ``st.logo`` is intentionally not used here
    because it does not allow an explicit width and can render the large source
    logo at full sidebar width.
    """
    import streamlit as st

    if not LOGO.exists():
        return

    st.sidebar.image(str(LOGO), width=width)


def render_brand_footer(width: int = 36) -> None:
    """Render a subtle, centered LITIT brand lockup (icon + NTT DATA tagline).

    Intended for page footers (e.g. the Public Board) where live match
    information must remain the focus. The mark is small and never dominates.
    """
    import streamlit as st

    if not ICON.exists():
        return

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(str(ICON), width=width)
        st.markdown(
            f"<div style='text-align:center; font-size:11px; color:#6B7280; "
            f"margin-top:-6px;'>{TAGLINE}</div>",
            unsafe_allow_html=True,
        )
