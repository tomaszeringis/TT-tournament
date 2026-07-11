"""
Tests for the LitIT brand design system tokens.

Verifies that ``tournament_platform.app.design_system`` exposes the LitIT
brand color palette, status colors, brand metadata, and the global CSS
theme block (``GLOBAL_STYLES``).
"""

import ast
import os

import pytest

from tournament_platform.app import design_system as ds


EXPECTED_BRAND_COLORS = {
    "litit_black": "#1A1C1B",
    "litit_white": "#FFFFFF",
    "primary": "#1A1C1B",
    "accent_blue": "#0066FF",
    "accent_green": "#00C853",
    "accent_orange": "#FF6D00",
    "accent_red": "#FF1744",
    "accent_yellow": "#FFD600",
    "background": "#0D0D0D",
    "surface": "#1A1C1B",
    "border": "#333436",
    "text_primary": "#FFFFFF",
    "text_secondary": "#B0B3B8",
    "text_muted": "#6B7280",
}

EXPECTED_STATUS_COLORS = {
    "active": "#FF1744",
    "called": "#FFD600",
    "completed": "#00C853",
    "pending": "#0066FF",
    "delayed": "#FF6D00",
}

EXPECTED_GLOBAL_STYLE_RULES = [
    "background-color: #0D0D0D",
    "outline: 2px solid #0066FF",
    "border-bottom: 2px solid #0066FF",
    "font-family: -apple-system",
    "::-webkit-scrollbar",
]


def test_brand_color_tokens_present():
    for key, value in EXPECTED_BRAND_COLORS.items():
        assert key in ds.COLORS, f"Missing brand color token: {key}"
        assert ds.COLORS[key].lower() == value.lower(), (
            f"Brand color {key} expected {value}, got {ds.COLORS[key]}"
        )


def test_status_colors_brand_consistent():
    for key, value in EXPECTED_STATUS_COLORS.items():
        assert key in ds.STATUS_COLORS, f"Missing status color: {key}"
        assert ds.STATUS_COLORS[key].lower() == value.lower(), (
            f"Status color {key} expected {value}, got {ds.STATUS_COLORS[key]}"
        )


def test_get_status_color_falls_back_to_blue():
    # Unknown status should fall back to the brand blue accent, not raise.
    assert ds.get_status_color("unknown_status").lower() == "#0066ff"


def test_brand_metadata():
    assert ds.BRAND["name"] == "LIT_IT"
    assert ds.BRAND["tagline"] == "part of NTT DATA"
    assert ds.BRAND["favicon"].endswith("litit-favicon.svg")
    assert ds.BRAND["logo_dark"].endswith("litit-logo-dark.svg")
    assert ds.BRAND["logo_light"].endswith("litit-logo-light.svg")


def test_global_styles_contains_brand_rules():
    assert isinstance(ds.GLOBAL_STYLES, str)
    for rule in EXPECTED_GLOBAL_STYLE_RULES:
        assert rule in ds.GLOBAL_STYLES, f"GLOBAL_STYLES missing rule: {rule}"


def test_branded_card_helpers_exist():
    for helper in (
        "render_litit_match_card",
        "render_litit_coming_up_card",
        "render_litit_delayed_card",
        "render_litit_announcement_card",
        "render_litit_result_row",
        "render_litit_upcoming_row",
    ):
        assert callable(getattr(ds, helper)), f"Missing brand card helper: {helper}"
