"""
Smoke test (Phase 0): import every module touched by the UX redesign so that
any import-time breakage fails fast.

These imports are safe outside the Streamlit runtime because page modules only
call ``set_page_config``/``st.*`` inside their render functions, not at import.
"""

import importlib

MODULES = [
    "tournament_platform.app.design_system",
    "tournament_platform.config",
    "tournament_platform.app.api_client",
    "tournament_platform.app.services.score_engine",
    "tournament_platform.app.pages.events_draws",
    "tournament_platform.app.pages.public_board",
    "tournament_platform.app.pages.operator_console",
    "tournament_platform.app.main",
    "tournament_platform.app.components.participants_panel",
    "tournament_platform.app.components.manual_score_panel",
    "tournament_platform.app.components.csv_import_panel",
    "tournament_platform.app.components.ai_insight_card",
    "tournament_platform.app.components.operator_components",
    "tournament_platform.services.pairing_explanation",
]


def test_all_touched_modules_import():
    for mod in MODULES:
        imported = importlib.import_module(mod)
        assert imported is not None, f"Failed to import {mod}"
