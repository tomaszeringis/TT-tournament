"""
Phase 0B Characterization Tests for voice_scorekeeper.py.

These tests capture the current behavior before Phase 1 in-place decomposition
of `render_voice_sections()` into local helpers. They verify:
- Render order
- Widget key inventories
- Selected-match loading behavior
- Manual scoring mutation paths
- Commentary trigger behavior
- Cloud-safe imports
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = PROJECT_ROOT / "tournament_platform" / "app" / "pages" / "voice_scorekeeper.py"


def _parse_page_source():
    """Return AST of the page module."""
    return ast.parse(PAGE_PATH.read_text(encoding="utf-8"))


def _find_function(tree, name):
    """Find a top-level function definition by name."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name} not found in voice_scorekeeper.py")


def _find_class(tree, name):
    """Find a top-level class definition by name."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Class {name} not found in voice_scorekeeper.py")


def _collect_calls_in_order(func_node):
    """Collect st.* and imported top-level call names in source order within a function body."""

    def _visit(node):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "st":
                    calls.append(func.attr)
            elif isinstance(func, ast.Name):
                calls.append(func.id)
        for child in ast.iter_child_nodes(node):
            _visit(child)

    calls = []
    _visit(func_node)
    return calls


# ---------------------------------------------------------------------------
# 1. Render order
# ---------------------------------------------------------------------------


class TestRenderOrder:
    """Verify `_render_ui` calls sections in the expected order."""

    def test_render_voice_sections_is_called_at_end_of_render_ui(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_ui")
        source_lines = ast.unparse(func).splitlines()
        # Find the last call expression in the function body (excluding `if` guards)
        last_call_line = max(
            node.lineno
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_voice_sections"
        )
        # The function should end shortly after the last render_voice_sections call.
        # The footer (announcements toggle, heartbeat, voice commands) now lives
        # inside _render_ui() after render_voice_sections(), so allow a larger gap.
        func_end_line = func.end_lineno if hasattr(func, "end_lineno") else max(n.lineno for n in ast.walk(func) if isinstance(n, ast.AST))
        gap = func_end_line - last_call_line
        assert gap < 60, (
            f"render_voice_sections() is not near the end of _render_ui(); "
            f"gap={gap} lines from last call to function end."
        )

    def test_expected_sections_appear_in_render_ui(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_ui")
        expected_calls = [
            "render_page_header",
            "render_tour",
            "render_commentary_settings",
            "render_active_match_selector",
            "render_selected_match_summary",
            "render_voice_sections",
        ]
        actual_calls = _collect_calls_in_order(func)
        for expected in expected_calls:
            assert expected in actual_calls, f"Expected call '{expected}' missing from _render_ui"


# ---------------------------------------------------------------------------
# 2. Widget key inventories (source-level)
# ---------------------------------------------------------------------------


class TestWidgetKeyInventories:
    """Verify specific widget keys exist in the source."""

    def test_player_selection_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="player_a_select"' in source
        assert 'key="player_b_select"' in source

    def test_scoreboard_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        expected_keys = [
            "add_point_a",
            "sub_point_a",
            "add_point_b",
            "sub_point_b",
            "undo_point_center",
            "undo_game_center",
            "reset_game_center",
            "reset_match_center",
            "next_game_btn",
            "submit_result_btn",
            "rematch_btn",
            "new_match_btn",
        ]
        for key in expected_keys:
            assert f'key="{key}"' in source, f"Widget key '{key}' missing from source"

    def test_setup_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="setup_points"' in source
        assert 'key="setup_games_to_win"' in source
        assert 'key="setup_firstserver"' in source

    def test_voice_input_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="voice_push_to_talk_input"' in source
        assert 'key="push_to_talk_btn"' in source
        assert 'key="continuous_mode_btn"' in source

    def test_voice_settings_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="noise_recommend_btn"' in source
        assert 'key="speaker_select"' in source

    def test_observability_keys_present(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="asr_test_imports"' in source
        assert 'key="asr_test_load"' in source
        assert 'key="asr_refresh"' in source
        assert 'key="voice_debug_process_btn"' in source
        assert 'key="clear_voice_log"' in source
        assert 'key="export_audit_log"' in source
        assert 'key="clear_audit_log"' in source

    def test_webrtc_component_key_stable(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="voice_scorekeeper_continuous_webrtc"' in source


# ---------------------------------------------------------------------------
# 3. Selected-match loading behavior
# ---------------------------------------------------------------------------


class TestSelectedMatchLoading:
    """Verify selected-match loading contracts."""

    def test_apply_selected_match_to_session_importable(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            apply_selected_match_to_session,
        )

    def test_clear_selected_match_importable(self):
        from tournament_platform.app.pages.voice_scorekeeper import clear_selected_match

    def test_active_match_selector_importable(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            render_active_match_selector,
        )


# ---------------------------------------------------------------------------
# 4. Cloud-safe imports
# ---------------------------------------------------------------------------


class _AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


class TestCloudSafeImports:
    """Verify the page can be imported with optional deps mocked."""

    def test_page_importable_with_mock_streamlit(self):
        import importlib

        # Ensure clean slate
        for mod in list(sys.modules.keys()):
            if "voice_scorekeeper" in mod:
                del sys.modules[mod]

        mock_st = MagicMock()
        mock_st.session_state = _AttrDict()
        mock_st.runtime = MagicMock()
        mock_st.runtime.scriptrunner = MagicMock()
        mock_st.runtime.scriptrunner.get_script_run_ctx = MagicMock(return_value=None)
        mock_st.runtime.metrics_util = MagicMock()
        mock_st.runtime.metrics_util.gather_metrics = MagicMock(return_value=lambda f: f)
        mock_st.components = MagicMock()
        mock_st.components.v1 = MagicMock()
        mock_st.set_page_config = MagicMock()

        mock_modules = {
            "streamlit": mock_st,
            "streamlit.runtime": mock_st.runtime,
            "streamlit.runtime.scriptrunner": mock_st.runtime.scriptrunner,
            "streamlit.runtime.metrics_util": mock_st.runtime.metrics_util,
            "streamlit.components": mock_st.components,
            "streamlit.components.v1": mock_st.components.v1,
        }

        with patch.dict(sys.modules, mock_modules):
            mod = importlib.import_module(
                "tournament_platform.app.pages.voice_scorekeeper"
            )
            assert mod is not None


# ---------------------------------------------------------------------------
# 5. Manual scoring mutation paths
# ---------------------------------------------------------------------------


class TestManualScoringPaths:
    """Verify manual scoring mutation paths."""

    def test_add_point_a_button_key_exists(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="add_point_a"' in source

    def test_undo_reset_buttons_exist(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="undo_point_center"' in source
        assert 'key="reset_game_center"' in source
        assert 'key="reset_match_center"' in source

    def test_match_manager_methods_importable(self):
        from tournament_platform.services.match_manager import MatchManager, MatchState

    def test_apply_score_event_and_refresh_ui_importable(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            apply_score_event_and_refresh_ui,
        )


# ---------------------------------------------------------------------------
# 6. Layout and scope regression tests
# ---------------------------------------------------------------------------


class TestLayoutAndScope:
    """Verify the Phase 4 layout and scope fixes."""

    def test_teams_recap_accepts_selection_parameter(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_teams_recap")
        args = [arg.arg for arg in func.args.args]
        assert "selection" in args

    def test_render_voice_sections_called_once_in_render_ui(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_ui")
        calls = [
            node.func.id
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "render_voice_sections"
        ]
        assert len(calls) == 1, f"render_voice_sections() should be called exactly once in _render_ui(), found {len(calls)}"

    def test_voice_scoring_heading_rendered_once(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        count = source.count('st.subheader("🎤 Voice Scoring")')
        assert count == 1, f"Expected exactly one 'Voice Scoring' heading, found {count}"

    def test_render_voice_sections_outside_column_context(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_ui")
        source_lines = ast.unparse(func).splitlines()
        render_voice_line = None
        column_context = False
        column_keywords = ("columns", "column")
        for i, line in enumerate(source_lines):
            if "render_voice_sections()" in line:
                render_voice_line = i
                break
        assert render_voice_line is not None, "render_voice_sections() not found in _render_ui()"
        before_lines = source_lines[:render_voice_line]
        for line in before_lines:
            stripped = line.strip()
            if stripped.startswith("with ") and any(k in stripped for k in column_keywords):
                column_context = True
            if column_context and stripped == "":
                column_context = False
        assert not column_context, "render_voice_sections() appears to still be inside a column context"

    def test_render_voice_sections_composes_subsections(self):
        tree = _parse_page_source()
        func = _find_function(tree, "render_voice_sections")
        calls = _collect_calls_in_order(func)
        expected = [
            "_render_voice_scoring_settings",
            "_render_voice_input",
            "_render_match_analytics",
            "_render_teams_recap",
        ]
        actual = [c for c in calls if c in set(expected)]
        assert actual == expected, f"Expected subsection renderers in order, got {actual}"

    def test_announcements_after_teams_recap_in_page_order(self):
        tree = _parse_page_source()
        func = _find_function(tree, "render_voice_sections")
        source_lines = ast.unparse(func).splitlines()
        analytics_line = None
        recap_line = None
        announcements_line = None
        for i, line in enumerate(source_lines):
            if "_render_match_analytics" in line:
                analytics_line = i
            if "_render_teams_recap" in line:
                recap_line = i
            if "Announcements" in line and "st.subheader" in line:
                announcements_line = i
        assert analytics_line is not None, "_render_match_analytics not found in render_voice_sections"
        assert recap_line is not None, "_render_teams_recap not found in render_voice_sections"
        assert announcements_line is not None, "Announcements not found in render_voice_sections"
        assert analytics_line < recap_line < announcements_line, (
            f"Expected Analytics ({analytics_line}) < Recap ({recap_line}) < Announcements ({announcements_line})"
        )

    def test_completed_match_selection_dataclass_exists(self):
        tree = _parse_page_source()
        cls = _find_class(tree, "CompletedMatchSelection")
        assert cls is not None
        fields = [a.target.id for a in cls.body if isinstance(a, ast.AnnAssign) and isinstance(a.target, ast.Name)]
        assert "source" in fields
        assert "match" in fields
        assert "match_id" in fields

    def test_match_analytics_returns_completed_match_selection(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_match_analytics")
        assert func.returns is not None
        assert isinstance(func.returns, ast.Name) and func.returns.id == "CompletedMatchSelection"

    def test_teams_recap_receives_selection_parameter(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_teams_recap")
        args = [arg.arg for arg in func.args.args]
        assert "selection" in args


# ---------------------------------------------------------------------------
# 7. WebRTC duplicate-render and stale-listening regression tests
# ---------------------------------------------------------------------------


class TestWebRtcLifecycle:
    """Verify single WebRTC render owner and correct listening-state transitions."""

    def test_webrtc_streamer_called_exactly_once(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        call_count = source.count("ctx = webrtc_streamer(")
        assert call_count == 1, (
            f"Expected exactly one webrtc_streamer() call site, found {call_count}. "
            "There must be a single rendering owner to avoid StreamlitDuplicateElementKey."
        )

    def test_webrtc_component_key_stable_and_unique(self):
        source = PAGE_PATH.read_text(encoding="utf-8")
        assert 'key="voice_scorekeeper_continuous_webrtc"' in source
        assert source.count('key="voice_scorekeeper_continuous_webrtc"') == 1

    def test_continuous_listening_expander_is_single_owner(self):
        tree = _parse_page_source()
        func = _find_function(tree, "_render_voice_scoring_settings")
        source = ast.unparse(func)
        assert source.count("webrtc_streamer(") == 1

    def test_refresh_streaming_diagnostics_clears_listening_when_mic_stops(self):
        from tournament_platform.app.pages.voice_scorekeeper import _refresh_streaming_diagnostics
        import time as _time

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "batch"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"

        _past_ts = _time.time() - 3.0
        mock_ss = MagicMock()
        mock_ss.get.side_effect = lambda k, d=None: {
            "voice_webrtc_ctx": {"processor": mock_proc},
            "voice_streaming_state": "listening",
            "streaming_ui_state": "listening",
            "voice_streaming_config_frozen": True,
            "voice_streaming_session_id": "sess-123",
            "voice_streaming_backend_gen": 1,
            "streaming_processor_id": 1,
            "streaming_processor_generation": 1,
            "voice_listening": False,
            "voice_events_enabled": True,
            "voice_capture_requested": True,
            "voice_continuous_requested": True,
            "voice_webrtc_streamer_state": {"playing": False, "signalling": True},
            "voice_streaming_diagnostics": {},
            "_voice_current_processor_id": id(mock_proc),
            "unexpected_webrtc_stop_ts": _past_ts,
        }.get(k, d)
        mock_ss._voice_current_processor_id = id(mock_proc)

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            mock_ss,
        ), patch("tournament_platform.app.pages.voice_scorekeeper.time.time", return_value=_time.time()):
            _refresh_streaming_diagnostics()

        assert mock_backend.close.called, "Backend must be closed when webrtc_playing=False after grace period"
        assert mock_proc.clear_streaming_backend.called, "Processor backend must be cleared"
        assert mock_ss.voice_streaming_state == "failed"
        assert mock_ss.streaming_ui_state == "failed"
        assert mock_ss.voice_streaming_config_frozen is False
        assert mock_ss.voice_listening is False

    def test_continuous_trace_uses_frozen_language(self):
        from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace

        class SessionState(dict):
            def __getattr__(self, name):
                try:
                    return self[name]
                except KeyError:
                    raise AttributeError(name)

            def __setattr__(self, name, value):
                self[name] = value

            def setdefault(self, key, default=None):
                if key not in self:
                    self[key] = default
                return self[key]

        mock_ss = SessionState({
            "voice_audit_events": [],
            "voice_streaming_language": "lt",
        })

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            mock_ss,
        ):
            _append_continuous_trace("test_stage", "test_note")

        assert len(mock_ss["voice_audit_events"]) == 1
        entry = mock_ss["voice_audit_events"][0]
        assert entry["language"] == "lt", (
            f"Continuous trace event should use frozen language 'lt', got '{entry['language']}'"
        )
        assert entry["source"] == "continuous"
        assert entry["stage"] == "test_stage"

    def test_continuous_trace_defaults_to_lt_when_no_frozen_language(self):
        from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace

        class SessionState(dict):
            def __getattr__(self, name):
                try:
                    return self[name]
                except KeyError:
                    raise AttributeError(name)

            def __setattr__(self, name, value):
                self[name] = value

            def setdefault(self, key, default=None):
                if key not in self:
                    self[key] = default
                return self[key]

        mock_ss = SessionState({
            "voice_audit_events": [],
        })

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            mock_ss,
        ):
            _append_continuous_trace("test_stage")

        entry = mock_ss["voice_audit_events"][0]
        assert entry["language"] == "lt", (
            f"Continuous trace event should default to 'lt', got '{entry['language']}'"
        )
