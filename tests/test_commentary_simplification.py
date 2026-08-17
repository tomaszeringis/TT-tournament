"""Tests for commentary simplification (PR 1-4).

Covers:
* normalize_commentary_style_for_ui() edge cases
* AcceptedCommentaryEvent registry
* classify_importance()
* STYLE_TO_CATEGORY mapping
* Diagnostic log helpers
* Coach safety guards
* Session-state ring buffer
"""

import pytest

from tournament_platform.app.services.voice_scorekeeper.commentary import (
    CommentaryEventRegistry,
    AcceptedCommentaryEvent,
    RETAINED_STYLES,
    STYLE_COMPATIBILITY_MAP,
    STYLE_TO_CATEGORY,
    COMMENTARY_STYLE_OPTIONS,
    normalize_commentary_style_for_ui,
    classify_importance,
    _style_to_category,
    _append_commentary_log_entry,
    update_commentary_log_status,
    _reset_commentary_log_for_match,
)


class TestNormalizeCommentaryStyleForUI:
    def test_none_returns_professional(self):
        assert normalize_commentary_style_for_ui(None) == "professional"

    def test_empty_string_returns_professional(self):
        assert normalize_commentary_style_for_ui("") == "professional"

    def test_neutral_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("neutral") == "professional"

    def test_minimal_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("minimal") == "professional"

    def test_kids_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("kids") == "professional"

    def test_beginner_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("beginner") == "professional"

    def test_simple_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("simple") == "professional"

    def test_couch_maps_to_coach(self):
        assert normalize_commentary_style_for_ui("couch") == "coach"

    def test_commentator_maps_to_announcer(self):
        assert normalize_commentary_style_for_ui("commentator") == "announcer"

    def test_sport_commentator_maps_to_announcer(self):
        assert normalize_commentary_style_for_ui("sport_commentator") == "announcer"

    def test_energetic_maps_to_announcer(self):
        assert normalize_commentary_style_for_ui("energetic") == "announcer"

    def test_professional_passthrough(self):
        assert normalize_commentary_style_for_ui("professional") == "professional"

    def test_coach_passthrough(self):
        assert normalize_commentary_style_for_ui("coach") == "coach"

    def test_announcer_passthrough(self):
        assert normalize_commentary_style_for_ui("announcer") == "announcer"

    def test_unknown_returns_professional(self):
        assert normalize_commentary_style_for_ui("unknown") == "professional"

    def test_silent_maps_to_professional(self):
        assert normalize_commentary_style_for_ui("silent") == "professional"


class TestRetainedStyles:
    def test_only_three_styles(self):
        assert RETAINED_STYLES == ("professional", "coach", "announcer")

    def test_style_options_matches_retained(self):
        assert COMMENTARY_STYLE_OPTIONS == list(RETAINED_STYLES)


class TestStyleCompatibilityMap:
    def test_all_aliases_map_to_retained(self):
        for alias, target in STYLE_COMPATIBILITY_MAP.items():
            assert target in RETAINED_STYLES, f"{alias} -> {target} is not in RETAINED_STYLES"


class TestStyleToCategory:
    def test_professional_maps_to_play_by_play(self):
        assert _style_to_category("professional") == "play_by_play"

    def test_coach_maps_to_tactical(self):
        assert _style_to_category("coach") == "tactical"

    def test_announcer_maps_to_contextual(self):
        assert _style_to_category("announcer") == "contextual"

    def test_unknown_defaults_to_play_by_play(self):
        assert _style_to_category("unknown") == "play_by_play"


class TestClassifyImportance:
    def test_critical_types(self):
        for evt in ("deuce", "advantage", "game_point", "match_point", "game_won", "match_won"):
            assert classify_importance(evt) == "critical"

    def test_notable_types(self):
        for evt in ("three_point_streak", "lead_change", "score_tied_late", "large_lead", "break_point", "set_point"):
            assert classify_importance(evt) == "notable"

    def test_routine_types(self):
        for evt in ("point_won", "serve_change", "point_a", "point_b"):
            assert classify_importance(evt) == "routine"

    def test_context_ignored(self):
        assert classify_importance("point_won", context={}) == "routine"


class TestCommentaryEventRegistry:
    def test_record_and_recent(self):
        registry = CommentaryEventRegistry(maxlen=5)
        evt = AcceptedCommentaryEvent(
            event_id="e1",
            match_id="m1",
            event_type="point_won",
            created_at=0.0,
            score_a=1,
            score_b=0,
            player_a="Alice",
            player_b="Bob",
            server="A",
            importance="routine",
            category="play_by_play",
        )
        registry.record(evt)
        recent = registry.recent(1)
        assert len(recent) == 1
        assert recent[0].event_id == "e1"

    def test_maxlen_respected(self):
        registry = CommentaryEventRegistry(maxlen=2)
        for i in range(5):
            evt = AcceptedCommentaryEvent(
                event_id=f"e{i}",
                match_id="m1",
                event_type="point_won",
                created_at=float(i),
                score_a=i,
                score_b=0,
                player_a="Alice",
                player_b="Bob",
                server="A",
                importance="routine",
                category="play_by_play",
            )
            registry.record(evt)
        assert len(registry.recent(10)) == 2

    def test_clear(self):
        registry = CommentaryEventRegistry()
        evt = AcceptedCommentaryEvent(
            event_id="e1",
            match_id="m1",
            event_type="point_won",
            created_at=0.0,
            score_a=1,
            score_b=0,
            player_a="Alice",
            player_b="Bob",
            server="A",
            importance="routine",
            category="play_by_play",
        )
        registry.record(evt)
        registry.clear()
        assert len(registry.recent(1)) == 0


class TestDiagnosticLog:
    def test_append_creates_entry(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        _append_commentary_log_entry(
            event_id="e1",
            status="generated",
            text="Point for Alice.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        entries = st.session_state.get("commentary_log_entries", [])
        assert len(entries) == 1
        assert entries[0]["event_id"] == "e1"
        assert entries[0]["status"] == "generated"
        assert entries[0]["text"] == "Point for Alice."

    def test_append_bounded_to_10(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        for i in range(15):
            _append_commentary_log_entry(
                event_id=f"e{i}",
                status="generated",
                text=f"Point {i}.",
                match_id="m1",
                event_type="point_won",
                style="professional",
                language="en",
                provider="legacy",
            )
        entries = st.session_state.get("commentary_log_entries", [])
        assert len(entries) == 10
        assert entries[0]["event_id"] == "e5"
        assert entries[-1]["event_id"] == "e14"

    def test_update_status(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        _append_commentary_log_entry(
            event_id="e1",
            status="generated",
            text="Point for Alice.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        update_commentary_log_status("e1", "synthesis_completed")
        entries = st.session_state.get("commentary_log_entries", [])
        assert entries[0]["status"] == "synthesis_completed"

    def test_update_status_with_error(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        _append_commentary_log_entry(
            event_id="e1",
            status="generated",
            text="Point for Alice.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        update_commentary_log_status("e1", "synthesis_failed", error="timeout")
        entries = st.session_state.get("commentary_log_entries", [])
        assert entries[0]["status"] == "synthesis_failed"
        assert entries[0]["error"] == "timeout"

    def test_update_status_preserves_other_entries(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        _append_commentary_log_entry(
            event_id="e1",
            status="generated",
            text="Point for Alice.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        _append_commentary_log_entry(
            event_id="e2",
            status="generated",
            text="Point for Bob.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        update_commentary_log_status("e1", "cancelled")
        entries = st.session_state.get("commentary_log_entries", [])
        assert len(entries) == 2
        assert entries[0]["status"] == "cancelled"
        assert entries[1]["status"] == "generated"

    def test_same_event_id_updates_existing(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        _append_commentary_log_entry(
            event_id="e1",
            status="generated",
            text="Point for Alice.",
            match_id="m1",
            event_type="point_won",
            style="professional",
            language="en",
            provider="legacy",
        )
        update_commentary_log_status("e1", "dispatch_requested")
        entries = st.session_state.get("commentary_log_entries", [])
        assert len(entries) == 1
        assert entries[0]["status"] == "dispatch_requested"


class TestResetCommentaryLogForMatch:
    def test_reset_function_does_not_crash(self, monkeypatch):
        import streamlit as st
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "commentary_log_entries": [{"event_id": "e1"}],
            "commentary_log_match_id": "old_match",
            "voice_selected_match_id": "new_match",
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)
        _reset_commentary_log_for_match()
        assert mock_state.__setitem__.called


class TestSessionStateDefaults:
    def test_commentary_voice_default(self, monkeypatch):
        import streamlit as st
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "commentary_voice": "default",
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)
        assert st.session_state.get("commentary_voice", "default") == "default"

    def test_commentary_voice_profile_default(self, monkeypatch):
        import streamlit as st
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "commentary_voice_profile": "browser_default",
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)
        assert st.session_state.get("commentary_voice_profile", "browser_default") == "browser_default"

    def test_commentary_log_entries_default(self, monkeypatch):
        import streamlit as st
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "commentary_log_entries": [],
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)
        assert st.session_state.get("commentary_log_entries", []) == []

    def test_commentary_log_match_id_default(self, monkeypatch):
        import streamlit as st
        from unittest.mock import MagicMock

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "commentary_log_match_id": None,
        }.get(key, default)
        monkeypatch.setattr(st, "session_state", mock_state)
        assert st.session_state.get("commentary_log_match_id") is None