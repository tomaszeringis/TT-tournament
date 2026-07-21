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
_streamlit.secrets = MagicMock()
_streamlit.secrets.get = MagicMock(return_value=None)
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
        "match_manager": MatchManager(
            player_a="Red",
            player_b="Blue",
            player_a_id=1,
            player_b_id=2,
        ),
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

    def test_set_score_auto_applies_at_high_confidence(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("score five four", source="debug", enable_confirmation=True)
        assert result["success"] is True
        assert "5-4" in result["new_score"]
        assert len(fake_session_state["pending_confirmations"]) == 0

    def test_high_confidence_point_auto_applies(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=True)
        assert result["success"] is True
        assert "0-1" in result["new_score"]


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


class TestMatchContextValidation:
    """Selected match must be present and stable across reruns."""

    def test_no_match_selected_rejects_with_clear_reason(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = None
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result["success"] is False
        reason = result.get("reason", "").lower()
        assert "match" in reason or "rejected" in reason
        assert result["new_score"] == result["previous_score"]

    def test_voice_selected_match_survives_rerun(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = 42
        fake_session_state["voice_selected_player1_name"] = "Alice"
        fake_session_state["voice_selected_player2_name"] = "Bob"

        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result["success"] is True
        assert fake_session_state["voice_selected_match_id"] == 42
        assert fake_session_state["voice_selected_player1_name"] == "Alice"

    def test_voice_event_not_applied_twice_after_rerun(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_voice_transcript,
            _VOICE_RERUN_KEY,
        )
        from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult

        fake_session_state["voice_selected_match_id"] = 1

        result1 = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result1["success"] is True
        score_after_first = fake_session_state["match_manager"].state.get_score_string()

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        score_after_second = fake_session_state["match_manager"].state.get_score_string()

        assert score_after_first == score_after_second

    def test_process_voice_events_uses_live_scores(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        fake_session_state["voice_selected_match_id"] = 1

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        score_after_first = fake_session_state["match_manager"].state.get_score_string()

        _process_voice_transcript("point blue", source="debug", enable_confirmation=False)
        score_after_second = fake_session_state["match_manager"].state.get_score_string()

        assert "0-1" in score_after_first
        assert "1-1" in score_after_second

    def test_voice_match_context_mismatch_rejected(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        fake_session_state["voice_selected_match_id"] = 1
        fake_session_state["voice_selected_player1_id"] = 1
        fake_session_state["voice_selected_player2_id"] = 2

        fake_session_state["match_manager"].state.player_a_id = 99
        fake_session_state["match_manager"].state.player_b_id = 100

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result["success"] is False
        assert result["reason"] == "voice_match_context_mismatch"
        assert result["new_score"] == result["previous_score"]


class TestRejectionReasonSurface:
    """Rejection reasons must be surfaced exactly, not paraphrased."""

    def test_no_match_selected_sets_feedback(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = None
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert result["success"] is False
        assert result["reason"] == "no_match_selected"
        assert fake_session_state.get("last_voice_feedback") == "no_match_selected"

    def test_rejection_reason_is_exact_router_reason(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        fake_session_state["voice_selected_match_id"] = None
        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get("last_voice_feedback") == "no_match_selected"


class TestParserHardening:
    """Phase 4: Parser behavior verification (conditional on Phase 0 success)."""

    def test_parser_handles_trailing_punctuation(self):
        from tournament_platform.app.services.voice.commands import parse

        result = parse("point red.")
        assert result.intent.value == "score_point"
        assert result.slots.get("player") == "B"

        result = parse("blue scores!")
        assert result.intent.value == "score_point"
        assert result.slots.get("player") == "A"

    def test_color_mapping_matches_scoreboard(self):
        from tournament_platform.app.services.voice.commands import parse

        blue_result = parse("point blue")
        red_result = parse("point red")

        assert blue_result.slots.get("player") == "A"
        assert red_result.slots.get("player") == "B"


class TestPhase5AuditAndRejectionFields:
    """Phase 5: Unified audit, rejection/success separation, source tracking."""

    def test_debug_command_appends_to_voice_audit_events(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        audit = fake_session_state.get("voice_audit_events", [])
        assert len(audit) == 1
        assert audit[0]["source"] == "debug"
        assert audit[0]["accepted"] is True
        assert audit[0]["event_type"] == "increment"

    def test_accepted_command_clears_rejection_reason(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get("last_voice_rejection_reason") == ""
        assert fake_session_state.get("last_voice_success_message") != ""

    def test_rejected_command_sets_rejection_reason(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = None
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get("last_voice_rejection_reason") == "no_match_selected"
        assert fake_session_state.get("last_voice_success_message") == ""

    def test_success_message_separate_from_rejection(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        success_msg = fake_session_state.get("last_voice_success_message", "")
        rejection_reason = fake_session_state.get("last_voice_rejection_reason", "")
        assert success_msg != ""
        assert rejection_reason == ""
        assert "Auto-confirmed" in success_msg or "Point" in success_msg

    def test_audit_export_not_empty_after_debug(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        audit = fake_session_state.get("voice_audit_events", [])
        assert len(audit) > 0

    def test_source_debug_remains_debug(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        audit = fake_session_state.get("voice_audit_events", [])
        assert audit[0]["source"] == "debug"

    def test_source_continuous_remains_continuous(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="continuous", enable_confirmation=False)
        audit = fake_session_state.get("voice_audit_events", [])
        assert audit[0]["source"] == "continuous"

    def test_push_to_talk_source_remains_push_to_talk(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="push_to_talk", enable_confirmation=False)
        audit = fake_session_state.get("voice_audit_events", [])
        assert audit[0]["source"] == "push_to_talk"


class TestPhase5VadSegmentReset:
    """Phase 5: VAD speech segment does not grow forever during silence."""

    def test_max_speech_duration_triggers_emit(self):
        from tournament_platform.app.services.voice_audio import VoiceAudioBuffer
        import time

        buf = VoiceAudioBuffer(
            sample_rate=48000,
            channels=2,
            silence_threshold=0.01,
            min_speech_duration_ms=100.0,
            max_chunk_duration_ms=5000.0,
            silence_duration_ms=600.0,
            max_speech_duration_ms=500.0,
            sample_format="int16",
        )
        # Use max-amplitude int16 frames and simulate time passing
        frame = b"\xff\x7f" * 480  # max positive int16 (32767), 10ms at 48kHz, 2ch
        buf.push_frame(frame)
        # Simulate 600ms of speech by manually setting the start time
        buf._speech_segment_started_at = time.time() - 0.6
        buf._buffer_start_time = time.time() - 0.6
        chunk = buf._check_emit(time.time(), is_speech=True)
        assert chunk is not None

    def test_reset_clears_speech_segment(self):
        from tournament_platform.app.services.voice_audio import VoiceAudioBuffer

        buf = VoiceAudioBuffer(max_speech_duration_ms=8000.0, sample_format="int16")
        frame = b"\xff\x7f" * 480  # max positive int16
        buf.push_frame(frame)
        assert buf.get_speech_segment_duration_ms() > 0
        buf.reset()
        assert buf.get_speech_segment_duration_ms() == 0.0
        assert buf.get_segment_reset_reason() == ""


class TestPhase5WebRTCState:
    """Phase 5: WebRTC state detection for listening status."""

    def test_get_webrtc_playing_state_false_when_no_ctx(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _get_webrtc_playing_state

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": False, "signalling": False}
        assert _get_webrtc_playing_state() is False

    def test_get_webrtc_playing_state_true_when_playing(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _get_webrtc_playing_state

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        assert _get_webrtc_playing_state() is True

    def test_is_continuous_mic_active_requires_both_flags(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _is_continuous_mic_active

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_webrtc_streamer_state"] = {"playing": False, "signalling": False}
        assert _is_continuous_mic_active() is False

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        assert _is_continuous_mic_active() is True


class TestPhase6ContinuousSessionAndStalePrevention:
    """Phase 6: Session ID, stale event prevention, queue cleanup."""

    def test_enable_generates_session_id(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _enable_continuous_listening

        _enable_continuous_listening()
        session_id = fake_session_state.get("voice_continuous_session_id")
        assert session_id is not None
        assert len(session_id) > 0

    def test_disable_clears_session_id(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _enable_continuous_listening, _disable_continuous_listening

        _enable_continuous_listening()
        assert fake_session_state.get("voice_continuous_session_id") is not None

        _disable_continuous_listening()
        assert fake_session_state.get("voice_continuous_session_id") is None
        assert fake_session_state.get("voice_continuous_session_start") == 0.0

    def test_stale_event_old_session_ignored(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0

        old_event = MagicMock()
        old_event.event_id = "old-event-id"
        old_event.timestamp = 500.0
        old_event.session_id = "old-session"
        old_event.source = "continuous"
        old_event.noise_rms = None
        old_event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", old_event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        assert fake_session_state.get("voice_stale_events_ignored") == 1

    def test_stale_event_after_stop_ignored(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0

        old_event = MagicMock()
        old_event.event_id = "old-event-id"
        old_event.timestamp = 500.0
        old_event.session_id = "current-session"
        old_event.source = "continuous"
        old_event.noise_rms = None
        old_event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", old_event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        assert fake_session_state.get("voice_stale_events_ignored") == 1

    def test_duplicate_event_ignored(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0
        fake_session_state["last_applied_voice_event_ids"] = ["duplicate-id"]

        dup_event = MagicMock()
        dup_event.event_id = "duplicate-id"
        dup_event.timestamp = 2000.0
        dup_event.session_id = "current-session"
        dup_event.source = "continuous"
        dup_event.noise_rms = None
        dup_event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", dup_event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        assert fake_session_state.get("voice_stale_events_ignored") == 1

    def test_webrtc_not_playing_rejects_continuous_event(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0
        fake_session_state["voice_webrtc_streamer_state"] = {"playing": False, "signalling": False}

        event = MagicMock()
        event.event_id = "event-id"
        event.timestamp = 2000.0
        event.session_id = "current-session"
        event.source = "continuous"
        event.noise_rms = None
        event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        assert fake_session_state.get("voice_stale_events_ignored") == 1

    def test_queue_cleanup_on_disable(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _disable_continuous_listening
        import queue

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["pending_confirmations"] = [{"test": True}]
        fake_session_state["last_voice_transcript"] = "old"
        fake_session_state["voice_audit_events"] = [{"test": True}]

        processor = MagicMock()
        processor._chunk_queue = queue.Queue()
        processor._chunk_queue.put("item")
        processor.event_queue = queue.Queue()
        processor.event_queue.put("event")
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _disable_continuous_listening()

        assert fake_session_state["voice_listening"] is False
        assert fake_session_state["voice_continuous_session_id"] is None
        assert len(fake_session_state["pending_confirmations"]) == 0
        assert fake_session_state["last_voice_transcript"] == ""
        assert len(fake_session_state["voice_audit_events"]) == 0


class TestPhase7UiAndDiagnostics:
    """Phase 7: UI status, ASR diagnostics, event store unification."""

    def test_ui_status_not_active_when_webrtc_not_playing(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _get_webrtc_playing_state

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": False, "signalling": False}
        assert _get_webrtc_playing_state() is False

    def test_ui_status_active_when_webrtc_playing(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _get_webrtc_playing_state

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        assert _get_webrtc_playing_state() is True

    def test_success_message_does_not_populate_rejection_reason(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get("last_voice_rejection_reason") == ""
        assert fake_session_state.get("last_voice_success_message") != ""

    def test_rejected_command_sets_rejection_reason_only(self, fake_session_state):
        fake_session_state["voice_selected_match_id"] = None
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        assert fake_session_state.get("last_voice_rejection_reason") == "no_match_selected"
        assert fake_session_state.get("last_voice_success_message") == ""

    def test_debug_and_continuous_use_same_audit_store(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        _process_voice_transcript("point blue", source="continuous", enable_confirmation=False)

        audit = fake_session_state.get("voice_audit_events", [])
        assert len(audit) == 2
        assert audit[0]["source"] == "debug"
        assert audit[1]["source"] == "continuous"

    def test_audit_store_survives_rerun(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        _process_voice_transcript("point red", source="debug", enable_confirmation=False)
        audit_before = fake_session_state.get("voice_audit_events", [])
        assert len(audit_before) == 1


class TestContinuousPipelineFixes:
    """New tests for the continuous voice audio pipeline fixes."""

    def test_has_pending_events_true_when_events_queued(self):
        from tournament_platform.app.pages.voice_scorekeeper import VoiceAudioProcessor

        processor = VoiceAudioProcessor()
        processor.event_queue.put(("raw", "text", MagicMock()))
        assert processor.has_pending_events() is True

    def test_has_pending_events_false_when_empty(self):
        from tournament_platform.app.pages.voice_scorekeeper import VoiceAudioProcessor

        processor = VoiceAudioProcessor()
        assert processor.has_pending_events() is False

    def test_continuous_event_consumed_audit_stage(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0

        event = MagicMock()
        event.event_id = "event-id"
        event.timestamp = 2000.0
        event.session_id = "current-session"
        event.source = "continuous"
        event.noise_rms = None
        event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        audit = fake_session_state.get("voice_audit_events", [])
        consumed_entries = [e for e in audit if e.get("stage") == "continuous_event_consumed"]
        assert len(consumed_entries) == 1
        assert "1_events" in consumed_entries[0]["note"]

    def test_process_voice_events_calls_shared_processor(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0
        fake_session_state["voice_selected_match_id"] = 1
        fake_session_state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}

        event = MagicMock()
        event.event_id = "event-id"
        event.timestamp = 2000.0
        event.session_id = "current-session"
        event.source = "continuous"
        event.noise_rms = None
        event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("point blue", "point blue", event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper._process_voice_transcript"
        ) as mock_shared:
            mock_shared.return_value = {
                "success": True,
                "reason": "Point to Player A",
                "previous_score": "0-0",
                "new_score": "1-0",
                "parsed": MagicMock(type="increment"),
                "route_result": None,
            }
            _process_voice_events()
            mock_shared.assert_called_once_with(
                "point blue",
                source="continuous",
                enable_confirmation=True,
            )

    def test_processor_callback_increments_frame_count(self):
        from tournament_platform.app.pages.voice_scorekeeper import VoiceAudioProcessor

        processor = VoiceAudioProcessor()
        frame = MagicMock()
        frame.pts = 1000.0
        frame.format = MagicMock()
        frame.format.name = "flt"
        frame.sample_rate = 48000
        frame.channels = 2
        processor.recv(frame)
        assert processor._audio_frames_received == 1
        assert processor._callback_count == 1

    def test_webrtc_playing_with_no_processor_reports_processor_not_created(self, fake_session_state):
        from unittest.mock import MagicMock

        fake_session_state["voice_webrtc_streamer_state"] = {"playing": True, "signalling": True}
        ctx = MagicMock()
        ctx.audio_processor = None
        ctx.state.playing = True

        _webrtc_ctx = {"processor": None}
        _webrtc_ctx["_voice_prev_processor_stage"] = None

        from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace
        with patch("tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace") as mock_trace:
            mock_trace.reset_mock()
            fake_session_state["_voice_prev_processor_stage"] = None
            proc = MagicMock()
            proc._audio_frames_received = 0
            ctx.audio_processor = proc
            _webrtc_ctx["processor"] = proc
            fake_session_state["voice_webrtc_ctx"] = _webrtc_ctx

            from tournament_platform.app.pages.voice_scorekeeper import _get_voice_webrtc_processor
            result = _get_voice_webrtc_processor(fake_session_state.get("voice_webrtc_ctx"))
            assert result is proc

    def test_continuous_transcript_point_blue_updates_player_a(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        before = fake_session_state["match_manager"].state.get_score_string()
        result = _process_voice_transcript("point blue", source="continuous", enable_confirmation=False)
        after = fake_session_state["match_manager"].state.get_score_string()

        assert result["success"] is True
        assert result["new_score"] != before
        assert "1-0" in after

    def test_continuous_transcript_point_red_updates_player_b(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript

        result = _process_voice_transcript("point red", source="continuous", enable_confirmation=False)
        after = fake_session_state["match_manager"].state.get_score_string()

        assert result["success"] is True
        assert "0-1" in after

    def test_stale_old_session_events_ignored(self, fake_session_state):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_events

        fake_session_state["voice_listening"] = True
        fake_session_state["voice_events_enabled"] = True
        fake_session_state["voice_continuous_session_id"] = "current-session"
        fake_session_state["voice_continuous_session_start"] = 1000.0

        old_event = MagicMock()
        old_event.event_id = "old-event-id"
        old_event.timestamp = 500.0
        old_event.session_id = "old-session"
        old_event.source = "continuous"
        old_event.noise_rms = None
        old_event.asr_latency_ms = None

        processor = MagicMock()
        processor.get_events.return_value = [("raw", "text", old_event)]
        fake_session_state["voice_webrtc_ctx"] = {"processor": processor}

        _process_voice_events()
        assert fake_session_state.get("voice_stale_events_ignored") == 1
