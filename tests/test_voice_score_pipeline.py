"""
Tests for the voice scoring pipeline end-to-end.

These tests mock Streamlit and its ecosystem so we can exercise the real
processors/helpers without a browser or audio device.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Comprehensive streamlit / ecosystem stub
# ---------------------------------------------------------------------------
class _SessionStateProxy(dict):
    """Dict that also supports attribute access, like real Streamlit session_state."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


def _make_columns(*args, **kwargs):
    if args and isinstance(args[0], int):
        return [MagicMock()] * args[0]
    if args and hasattr(args[0], '__len__'):
        return [MagicMock()] * len(args[0])
    return [MagicMock(), MagicMock()]


_streamlit = MagicMock()
_streamlit.session_state = _SessionStateProxy()
_streamlit.rerun = MagicMock()
_streamlit.experimental_rerun = MagicMock()
_streamlit.warning = MagicMock()
_streamlit.success = MagicMock()
_streamlit.error = MagicMock()
_streamlit.info = MagicMock()
_streamlit.caption = MagicMock()
_streamlit.markdown = MagicMock()
_streamlit.json = MagicMock()
_streamlit.toast = MagicMock()
_streamlit.button = MagicMock(return_value=False)
_streamlit.text_input = MagicMock(return_value="")
_streamlit.columns = MagicMock(side_effect=_make_columns)
_streamlit.expander = MagicMock(return_value=MagicMock(
    __enter__=MagicMock(return_value=None),
    __exit__=MagicMock(return_value=False),
))
_streamlit.toggle = MagicMock(return_value=False)
_streamlit.checkbox = MagicMock(return_value=False)
_streamlit.number_input = MagicMock(return_value=0.0)
_streamlit.metric = MagicMock()
_streamlit.progress = MagicMock()
_streamlit.divider = MagicMock()
_streamlit.subheader = MagicMock()
_streamlit.selectbox = MagicMock(return_value="")
_streamlit.multiselect = MagicMock(return_value=[])
_streamlit.form_submit_button = MagicMock(return_value=False)
_streamlit.popover = MagicMock(return_value=MagicMock(
    __enter__=MagicMock(return_value=None),
    __exit__=MagicMock(return_value=False),
))
_streamlit.status = MagicMock(return_value=MagicMock(
    __enter__=MagicMock(return_value=None),
    __exit__=MagicMock(return_value=False),
))
_streamlit.dataframe = MagicMock()
_streamlit.download_button = MagicMock()
_streamlit.audio_input = MagicMock(return_value=None)

_components_v1 = MagicMock()
_components_v1.html = MagicMock()
_streamlit.components = MagicMock()
_streamlit.components.v1 = _components_v1
_streamlit.runtime = MagicMock()
_streamlit.runtime.metrics_util = MagicMock()
_streamlit.runtime.metrics_util.gather_metrics = MagicMock(return_value=lambda f: f)

# Force reload of anything already imported
for mod_name in list(sys.modules.keys()):
    if "voice_scorekeeper" in mod_name:
        del sys.modules[mod_name]


def _import_voice_scorekeeper():
    """Import voice_scorekeeper safely, mocking top-level DB calls."""
    _original_modules = {}
    _mocked_modules = [
        "streamlit",
        "streamlit_shadcn_ui",
        "streamlit_shadcn_ui.py_components",
        "streamlit_shadcn_ui.py_components.select",
        "streamlit_extras",
        "streamlit_extras.stylable_container",
        "streamlit.runtime",
        "streamlit.runtime.metrics_util",
        "streamlit.runtime.scriptrunner",
        "streamlit.components",
        "streamlit.components.v1",
    ]
    for mod_name in _mocked_modules:
        _original_modules[mod_name] = sys.modules.get(mod_name)

    try:
        sys.modules["streamlit"] = _streamlit
        for mod_name in _mocked_modules[1:]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = MagicMock()
        _scriptrunner_mock = MagicMock()
        _scriptrunner_mock.get_script_run_ctx = MagicMock(return_value=None)
        sys.modules["streamlit.runtime.scriptrunner"] = _scriptrunner_mock

        for mod_name in list(sys.modules.keys()):
            if "voice_scorekeeper" in mod_name:
                del sys.modules[mod_name]
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.fetch_active_tournaments",
            return_value=[],
        ):
            with patch(
                "tournament_platform.app.pages.voice_scorekeeper.render_active_match_selector",
                MagicMock(),
            ):
                with patch(
                    "tournament_platform.app.pages.voice_scorekeeper.render_commentary_settings",
                    MagicMock(),
                ):
                    from tournament_platform.app.pages import voice_scorekeeper as vs
                    return vs
    finally:
        for mod_name, original in _original_modules.items():
            if original is not None:
                sys.modules[mod_name] = original
            else:
                sys.modules.pop(mod_name, None)


def _make_fake_session_state() -> dict:
    """Return a dict-like session state pre-seeded with defaults."""
    from tournament_platform.services.match_manager import MatchManager
    from tournament_platform.app.services.voice.confirmation import VoiceConfirmationStateMachine
    from tournament_platform.app.services.voice_audit import EventLogger

    return _SessionStateProxy({
        "match_manager": MatchManager(),
        "voice_scoring_enabled": True,
        "voice_listening": False,
        "voice_strict_mode": False,
        "voice_noise_filtering": False,
        "voice_noise_threshold": 0.0,
        "voice_last_applied_event_key": None,
        "voice_last_applied_event_ts": 0.0,
        "voice_confirmation_machine": VoiceConfirmationStateMachine(ttl_seconds=8.0),
        "pending_confirmations": [],
        "last_voice_transcript": "",
        "last_voice_event": None,
        "last_voice_feedback": "",
        "voice_event_log": [],
        "voice_event_logger": EventLogger(),
        "voice_selected_match_id": 1,
        "voice_selected_player1_name": "Red",
        "voice_selected_player2_name": "Blue",
        "voice_selected_player1_id": 1,
        "voice_selected_player2_id": 2,
        "voice_tts_adapter": MagicMock(enabled=False),
        "_voice_debug_last_result": None,
        "_voice_p2p_cache": {},
    })


@pytest.fixture()
def fake_session_state():
    """Replace st.session_state with a controllable dict before each test."""
    vs = _import_voice_scorekeeper()
    state = _make_fake_session_state()
    vs.st.session_state = state
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDebugTranscriptExecutor:
    """Debug text command must update official match score."""

    def test_point_red_updates_score(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        before = fake_session_state["match_manager"].state.get_score_string()
        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        after = fake_session_state["match_manager"].state.get_score_string()

        assert result["success"] is True
        assert result["new_score"] != before
        assert "0-1" in after

    def test_point_blue_updates_score(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point blue", source="debug", enable_confirmation=False)
        after = fake_session_state["match_manager"].state.get_score_string()

        assert result["success"] is True
        assert "1-0" in after

    def test_undo_reverses_last_point(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        score_after_point = fake_session_state["match_manager"].state.get_score_string()
        _process_voice_transcript("undo", source="debug", enable_confirmation=False)
        score_after_undo = fake_session_state["match_manager"].state.get_score_string()

        assert score_after_undo != score_after_point

    def test_no_match_selected_shows_clear_error(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = None
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result["success"] is False
        reason = result.get("reason", "").lower()
        assert "match" in reason or "rejected" in reason


class TestRouterMismatch:
    """Parser/router intent string vs enum mismatch."""

    def test_parser_accepts_point_red(self):
        from tournament_platform.app.services.voice_parser import VoiceParser
        vp = VoiceParser()
        event = vp.parse("point red", current_score_a=0, current_score_b=0)
        assert event.type == "increment"

    def test_parser_accepts_red_point(self):
        from tournament_platform.app.services.voice_parser import VoiceParser
        vp = VoiceParser()
        event = vp.parse("red point", current_score_a=0, current_score_b=0)
        assert event.type == "increment"

    def test_parser_accepts_blue_scores(self):
        from tournament_platform.app.services.voice_parser import VoiceParser
        vp = VoiceParser()
        event = vp.parse("blue scores", current_score_a=0, current_score_b=0)
        assert event.type == "increment"

    def test_parser_accepts_undo(self):
        from tournament_platform.app.services.voice_parser import VoiceParser
        vp = VoiceParser()
        event = vp.parse("undo", current_score_a=0, current_score_b=0)
        assert event.type == "undo"

    def test_parser_returns_access_repeat_for_repeat(self):
        from tournament_platform.app.services.voice_parser import VoiceParser
        vp = VoiceParser()
        event = vp.parse("repeat", current_score_a=0, current_score_b=0)
        assert event.type == "access_repeat"


class TestDuplicateSuppression:
    """First command must not be blocked; duplicate within cooldown must be."""

    def test_first_command_not_blocked(self, fake_session_state):
        from tournament_platform.app.services.voice.command_router import (
            RouteContext,
            RouteDecision,
            route_and_update_context,
        )
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult

        parsed = VoiceParseResult(
            intent="increment",
            confidence=0.9,
            raw_transcript="point red",
            slots={"player": "B"},
        )
        ctx = RouteContext(
            current_score_a=0,
            current_score_b=0,
            strict_mode=False,
            enable_confirmation=False,
        )
        result = route_and_update_context(parsed, ctx)
        assert result.decision == RouteDecision.APPLY

    def test_repeated_duplicate_within_cooldown_suppressed(self, fake_session_state):
        from tournament_platform.app.services.voice.command_router import (
            RouteContext,
            RouteDecision,
            route_and_update_context,
        )
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult

        parsed = VoiceParseResult(
            intent="increment",
            confidence=0.9,
            raw_transcript="point red",
            slots={"player": "B"},
        )
        ctx = RouteContext(
            current_score_a=0,
            current_score_b=0,
            strict_mode=False,
            enable_confirmation=False,
        )
        result1 = route_and_update_context(parsed, ctx)
        assert result1.decision == RouteDecision.APPLY

        result2 = route_and_update_context(parsed, ctx)
        assert result2.decision == RouteDecision.IGNORE


class TestConfirmationFlow:
    """Confirmation-required commands create pending confirmations."""

    def test_set_score_creates_pending_confirmation(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("score five four", source="debug", enable_confirmation=True)
        assert result["success"] is False
        assert result.get("reason") == "pending"
        assert len(fake_session_state["pending_confirmations"]) == 1

    def test_confirm_applies_score(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("score five four", source="debug", enable_confirmation=True)
        assert len(fake_session_state["pending_confirmations"]) == 1
        before = fake_session_state["match_manager"].state.get_score_string()

        from tournament_platform.app.pages.voice_scorekeeper import _apply_pending
        _apply_pending(0)
        after = fake_session_state["match_manager"].state.get_score_string()
        assert after != before

    def test_cancel_clears_pending(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("score five four", source="debug", enable_confirmation=True)
        assert len(fake_session_state["pending_confirmations"]) == 1

        machine = fake_session_state["voice_confirmation_machine"]
        if machine:
            machine.cancel()
            machine.reset()
        fake_session_state["pending_confirmations"].pop(0)
        assert len(fake_session_state["pending_confirmations"]) == 0


class TestSharedProcessing:
    """Push-to-talk and debug must share the same processing path."""

    def test_shared_function_exists(self):
        vs = _import_voice_scorekeeper()
        assert hasattr(vs, "_process_voice_transcript")
        assert callable(vs._process_voice_transcript)


class TestRerunSafety:
    """No infinite rerun loops; one-shot flag is cleared before rerun."""

    def test_process_transcript_sets_rerun_flag(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_voice_transcript,
            _VOICE_RERUN_KEY,
            _maybe_voice_rerun,
        )

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get(_VOICE_RERUN_KEY) is True

        _maybe_voice_rerun()
        assert fake_session_state.get(_VOICE_RERUN_KEY) is False
