"""
LITIT brand asset paths (repository-relative).

Centralizes the locations of the official LITIT brand assets so the Streamlit
app can load the sidebar logo and page-level icons regardless of the current
working directory. No absolute, machine-specific paths are committed here -
everything is resolved relative to this file:

    app/components/brand_assets.py
        -> app/assets/brand/logo/sidebar_logo.png
        -> app/assets/brand/icons/<name>.png

Source assets were copied from the official LITIT brand delivery
(``assets/brand/LIT_IT logo-01 (1) (1).png`` and the ``LITIT Icons`` folder).
"""

from pathlib import Path

# Repo-local brand asset root.
BRAND_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand"

# Logo / icon sub-directories.
LOGO_DIR = BRAND_ASSETS_DIR / "logo"
ICON_DIR = BRAND_ASSETS_DIR / "icons"

# The exact official LITIT logo used in the sidebar / app header branding area.
SIDEBAR_LOGO = LOGO_DIR / "sidebar_logo.png"

# Default brand mark (used for favicon / footer / generic page icon).
DEFAULT_ICON = ICON_DIR / "litit_icon.png"

# Logical name -> cleaned file name inside ICON_DIR.
# Exact semantic matches could not be visually verified (assets are generic
# Figma exports), so each page is mapped to a distinct, brand-consistent LITIT
# icon mark. All assets come from the official LITIT Icons folder.
PAGE_ICON_FILES = {
    "tt_tournament_platform": "litit_icon.png",
    "tournament": "tournament.png",
    "dashboard": "dashboard.png",
    "ai_assistant": "ai_assistant.png",
    "admin_operator": "admin_operator.png",
    "voice_scorekeeper": "microphone.png",
    "video_scorekeeper": "video_scorekeeper.png",
    "dataset_catalog": "dataset_catalog.png",
    "coaching_lab": "coaching_lab.png",
    "experiment_dashboard": "experiment_dashboard.png",
    "public_board": "public_board.png",
    "participants": "participants.png",
    "events_draws": "events_draws.png",
}


def get_brand_icon(name: str) -> str:
    """Return the absolute path to a page-level LITIT icon.

    ``name`` may be a logical key from :data:`PAGE_ICON_FILES` or a bare file
    name. ``icon_name`` values used in ``render_page_header`` should match the
    logical keys.
    """
    fname = PAGE_ICON_FILES.get(name, name)
    return str(ICON_DIR / fname)


def get_sidebar_logo() -> str:
    """Return the absolute path to the official LITIT sidebar logo."""
    return str(SIDEBAR_LOGO)


def render_brand_icon(icon_name: str, width: int = 40) -> None:
    """Render a small LITIT icon on a page (headers, cards, section labels).

    Intended for page *content* only - never for the Streamlit navigation menu.
    The icon is kept small and is skipped silently if the asset is missing.
    """
    import streamlit as st

    path = get_brand_icon(icon_name)
    if not Path(path).exists():
        return
    st.image(path, width=width)
