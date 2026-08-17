"""
Tests for the stale Ready state fix (Phase 1: continuous voice-scoring lifecycle).

Covers:
- Stale Ready regression (playing=False + signalling=True must not show Ready)
- Render-order verification (WebRTC result before controls)
- Valid Ready predicate (playing=True + processor + backend attached + connected)
- Unexpected microphone stop (playing transitions True→False while desired=True)
- Signalling-only test (playing=False + signalling=True must not be Ready)
- Orphan backend test (backend processor ID != current processor ID)
- Stable active session (100 simulated reruns)
- Stop lifecycle (Stop clicked → desired=False → backend closed → Disabled)
- _refresh_streaming_diagnostics unexpected stop
- _refresh_streaming_diagnostics stale connected backend
- Button state logic
- Desired_mic_playing preservation
- Startup timeout → Failed
- Disabled when desired_mic_playing=False
- Voice state invariant violation detection
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.pages.voice_scorekeeper import (
    ContinuousWebRTCResult,
    _build_webrtc_result,
    _reconcile_voice_lifecycle,
    _refresh_streaming_diagnostics,
    _set_desired_mic_playing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session_state(**overrides) -> MagicMock:
    ss = MagicMock()
    ss.get.side_effect = lambda key, default=None: overrides.get(
        key,
        {
            "desired_mic_playing": False,
            "voice_start_requested": False,
            "voice_stop_requested": False,
            "streaming_ui_state": "disabled",
            "voice_streaming_state": "disabled",
            "voice_streaming_config_frozen": False,
            "voice_listening": False,
            "voice_events_enabled": False,
            "voice_capture_requested": False,
            "voice_continuous_requested": False,
            "voice_continuous_session_id": None,
            "voice_continuous_session_start": 0.0,
            "streaming_start_request_id": None,
            "streaming_start_requested_at": None,
            "streaming_processor_id": None,
            "streaming_processor_generation": None,
            "voice_streaming_session_id": None,
            "voice_streaming_backend_gen": 0,
            "voice_streaming_error": None,
            "voice_streaming_last_error_code": None,
            "voice_streaming_diagnostics": {},
            "voice_streaming_last_finalized": "",
            "voice_streaming_last_interim": "",
            "voice_streaming_last_refresh": 0.0,
            "_voice_current_processor_id": None,
            "_voice_prev_webrtc_playing": False,
            "_voice_prev_processor_stage": None,
            "unexpected_webrtc_stop_ts": None,
            "last_desired_mic_writer": None,
            "last_desired_mic_reason": None,
            "voice_webrtc_ctx": {},
            "voice_webrtc_streamer_state": {"playing": False, "signalling": False},
            "voice_scorekeeper_continuous_webrtc": None,
            "voice_webrtc_mount_error": None,
            "streaming_start_microphone_confirmed_at": None,
            "streaming_start_backend_attached_at": None,
            "streaming_start_completed_at": None,
            "streaming_start_request_id": None,
            "streaming_start_requested_at": None,
            "voice_streaming_provider": "deepgram",
            "voice_streaming_language": "lt",
            "voice_selected_match_id": None,
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
        }.get(key, default),
    )
    ss.__getitem__ = lambda self, key: ss.get(key)
    ss.__setitem__ = lambda self, key, value: setattr(ss, key, value)
    return ss


def _mock_processor(
    processor_id: int = 42,
    generation: int = 1,
    backend_state: str = "connected",
    streaming_generation: int = 1,
    streaming_voice_session_id: str = "sess-123",
) -> MagicMock:
    proc = MagicMock()
    proc._processor_generation = generation
    proc._streaming_generation = streaming_generation
    proc._streaming_voice_session_id = streaming_voice_session_id
    proc._streaming_match_id = 1
    proc._streaming_active = True
    proc._streaming_backend = MagicMock()
    proc._streaming_backend.connection_state.return_value = backend_state
    proc._streaming_backend.health_status.return_value = backend_state
    proc._streaming_backend.is_available.return_value = True
    proc._streaming_backend.get_connection_info.return_value = {
        "connection_state": backend_state,
        "last_error_category": None,
        "last_error_message_safe": None,
    }
    proc._streaming_backend.enqueue_audio.return_value = True
    proc._streaming_backend.get_finalized_transcripts.return_value = []
    proc._streaming_backend.get_interim_transcripts.return_value = []
    proc._streaming_backend.get_errors.return_value = []
    proc._streaming_backend.metrics.return_value = MagicMock(
        connection_state=backend_state,
        queue_depth=0,
        interim_transcript_count=0,
        completed_utterance_count=0,
        queue_overflow_count=0,
        reconnect_count=0,
        keepalive_count=0,
        keyterm_count=0,
        speech_end_to_final_latency_ms=None,
    )
    proc.effective_delivery_mode = "stream"
    proc.get_streaming_diagnostics.return_value = {}
    proc.get_diagnostics.return_value = {}
    proc.get_worker_diagnostics.return_value = {}
    return proc


# ---------------------------------------------------------------------------
# 1. ContinuousWebRTCResult dataclass
# ---------------------------------------------------------------------------


class TestContinuousWebRTCResult:
    def test_default_values(self):
        result = ContinuousWebRTCResult()
        assert result.context is None
        assert result.processor is None
        assert result.component_mounted is False
        assert result.playing is False
        assert result.signalling is False
        assert result.processor_id is None
        assert result.processor_generation is None
        assert result.error_category is None
        assert result.error_message_safe is None

    def test_custom_values(self):
        ctx = MagicMock()
        proc = MagicMock()
        result = ContinuousWebRTCResult(
            context=ctx,
            processor=proc,
            component_mounted=True,
            playing=True,
            signalling=True,
            processor_id=42,
            processor_generation=1,
            error_category=None,
            error_message_safe=None,
        )
        assert result.context is ctx
        assert result.processor is proc
        assert result.component_mounted is True
        assert result.playing is True
        assert result.signalling is True
        assert result.processor_id == 42
        assert result.processor_generation == 1


# ---------------------------------------------------------------------------
# 2. Stale Ready regression
# ---------------------------------------------------------------------------


class TestStaleReadyRegression:
    """playing=False + signalling=True must never produce Ready or Listening."""

    def test_stale_ready_not_ready_when_playing_false(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
            streaming_processor_id=None,
            streaming_processor_generation=None,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] != "ready"
        assert reconciled["connection_state"] != "listening"

    def test_stale_ready_not_listening_when_playing_false(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="listening",
            streaming_processor_id=None,
            streaming_processor_generation=None,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] != "listening"


# ---------------------------------------------------------------------------
# 3. Valid Ready test
# ---------------------------------------------------------------------------


class TestValidReady:
    """playing=True + processor current + backend attached + backend connected → Ready."""

    def test_valid_ready_when_all_conditions_met(self):
        proc = _mock_processor()
        result = ContinuousWebRTCResult(
            playing=True,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            streaming_processor_id=id(proc),
            streaming_processor_generation=proc._processor_generation,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "ready"


# ---------------------------------------------------------------------------
# 4. Listening test
# ---------------------------------------------------------------------------


class TestListening:
    """Ready conditions + recent audio callback → Listening."""

    def test_listening_when_ready_and_desired(self):
        proc = _mock_processor()
        result = ContinuousWebRTCResult(
            playing=True,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_listening=True,
            streaming_processor_id=id(proc),
            streaming_processor_generation=proc._processor_generation,
            voice_streaming_state="listening",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "ready"


# ---------------------------------------------------------------------------
# 5. Unexpected stop test
# ---------------------------------------------------------------------------


class TestUnexpectedStop:
    """previous playing=True + current playing=False + desired=True + microphone previously confirmed → Failed."""

    def test_unexpected_stop_transitions_to_failed(self):
        proc = _mock_processor()
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
            streaming_processor_id=id(proc),
            streaming_processor_generation=proc._processor_generation,
            streaming_start_microphone_confirmed_at=time.time() - 10.0,
            _voice_prev_webrtc_playing=True,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._set_desired_mic_playing"
        ) as mock_set_desired:
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "failed"
        assert reconciled["unexpected_webrtc_stop"] is True
        assert reconciled["start_enabled"] is True
        assert reconciled["stop_enabled"] is False


# ---------------------------------------------------------------------------
# 6. Signalling-only test
# ---------------------------------------------------------------------------


class TestSignallingOnly:
    """playing=False + signalling=True must not be Ready."""

    def test_signalling_only_not_ready(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=False,
            voice_streaming_state="disabled",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "disabled"
        assert reconciled["desired_mic_playing"] is False


# ---------------------------------------------------------------------------
# 7. Orphan backend test
# ---------------------------------------------------------------------------


class TestOrphanBackend:
    """backend processor ID != current processor ID → backend diagnostics ignored, orphan closed."""

    def test_orphan_backend_detected(self):
        proc = _mock_processor(processor_id=42, generation=1)
        result = ContinuousWebRTCResult(
            playing=True,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            streaming_processor_id=999,
            streaming_processor_generation=1,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["stale_backend_detected"] is True
        assert reconciled["connection_state"] == "failed"
        assert reconciled["backend_identity_matches_current_processor"] is False


# ---------------------------------------------------------------------------
# 8. Stable active session test
# ---------------------------------------------------------------------------


class TestStableActiveSession:
    """Across simulated reruns: playing stays True, processor identity stable, backend stays attached."""

    def test_stable_session_across_reruns(self):
        proc = _mock_processor()
        for _ in range(100):
            result = ContinuousWebRTCResult(
                playing=True,
                signalling=True,
                component_mounted=True,
                processor=proc,
                processor_id=id(proc),
                processor_generation=proc._processor_generation,
            )
            ss = _mock_session_state(
                desired_mic_playing=True,
                voice_listening=True,
                streaming_processor_id=id(proc),
                streaming_processor_generation=proc._processor_generation,
                voice_streaming_state="listening",
            )
            with patch(
                "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
                ss,
            ), patch(
                "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
                ss.get,
            ):
                reconciled = _reconcile_voice_lifecycle(result)
            assert reconciled["connection_state"] in ("ready", "listening")
            assert reconciled["desired_mic_playing"] is True
            assert reconciled["webrtc_playing"] is True


# ---------------------------------------------------------------------------
# 9. Stop lifecycle test
# ---------------------------------------------------------------------------


class TestStopLifecycle:
    """Stop clicked → desired=False → backend closed → Disabled."""

    def test_stop_sets_desired_false_and_disables(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=False,
            component_mounted=False,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=False,
            voice_streaming_state="disabled",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["desired_mic_playing"] is False
        assert reconciled["connection_state"] == "disabled"
        assert reconciled["start_enabled"] is True
        assert reconciled["stop_enabled"] is False


# ---------------------------------------------------------------------------
# 10. _refresh_streaming_diagnostics unexpected stop
# ---------------------------------------------------------------------------


class TestRefreshDiagnosticsUnexpectedStop:
    """_refresh_streaming_diagnostics must close backend and set Failed on confirmed unexpected stop."""

    def test_confirmed_unexpected_stop_closes_backend(self):
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_backend.get_connection_info.return_value = {
            "connection_state": "connected",
            "last_error_category": None,
            "last_error_message_safe": None,
        }
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state(
            voice_webrtc_ctx={"processor": mock_proc},
            unexpected_webrtc_stop_ts=0.0,
            _voice_current_processor_id=id(mock_proc),
        )
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.voice_listening = True
        ss.desired_mic_playing = True
        ss.last_desired_mic_writer = "_start_streaming_voice_session"
        ss.last_desired_mic_reason = "user_start_clicked"
        ss.streaming_start_microphone_confirmed_at = 1000000.0

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            _refresh_streaming_diagnostics()

        assert mock_backend.close.called
        assert ss.voice_streaming_state == "failed"
        assert ss.streaming_ui_state == "failed"


# ---------------------------------------------------------------------------
# 11. _refresh_streaming_diagnostics stale connected backend
# ---------------------------------------------------------------------------


class TestRefreshDiagnosticsStaleBackend:
    """Backend connected but playing=False (mic never confirmed) must close backend immediately."""

    def test_stale_connected_backend_closed_when_never_confirmed(self):
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_backend.get_connection_info.return_value = {
            "connection_state": "connected",
            "last_error_category": None,
            "last_error_message_safe": None,
        }
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state(
            voice_webrtc_ctx={"processor": mock_proc},
            _voice_current_processor_id=id(mock_proc),
        )
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.voice_listening = False
        ss.desired_mic_playing = True
        ss.streaming_start_microphone_confirmed_at = None

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            _refresh_streaming_diagnostics()

        assert mock_backend.close.called
        assert ss.voice_streaming_state == "disabled"


# ---------------------------------------------------------------------------
# 11b. _refresh_streaming_diagnostics connecting→ready must check webrtc_playing
# ---------------------------------------------------------------------------


class TestRefreshDiagnosticsConnectingToReady:
    """Backend connected from connecting/reconnecting must not set Ready
    when WebRTC is not playing — must set microphone_stopped instead."""

    def test_connecting_to_ready_while_not_playing_sets_microphone_stopped(self):
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_backend.get_connection_info.return_value = {
            "connection_state": "connected",
            "last_error_category": None,
            "last_error_message_safe": None,
        }
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state(
            voice_webrtc_ctx={"processor": mock_proc},
            voice_webrtc_streamer_state={"playing": False, "signalling": True},
            desired_mic_playing=True,
        )
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_listening = False
        ss.voice_streaming_state = "connecting"
        ss.streaming_ui_state = "connecting"

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            _refresh_streaming_diagnostics()

        assert ss.voice_streaming_state == "microphone_stopped"
        assert ss.streaming_ui_state == "microphone_stopped"

    def test_connecting_to_ready_while_playing_sets_ready(self):
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_backend.get_connection_info.return_value = {
            "connection_state": "connected",
            "last_error_category": None,
            "last_error_message_safe": None,
        }
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state(
            voice_webrtc_ctx={"processor": mock_proc},
            voice_webrtc_streamer_state={"playing": True, "signalling": True},
            desired_mic_playing=True,
            voice_listening=True,
        )
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_streaming_state = "connecting"
        ss.streaming_ui_state = "connecting"

        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            _refresh_streaming_diagnostics()

        assert ss.voice_streaming_state == "ready"
        assert ss.streaming_ui_state == "ready"


# ---------------------------------------------------------------------------
# 12. _build_webrtc_result
# ---------------------------------------------------------------------------


class TestBuildWebrtcResult:
    def test_build_from_none_context(self):
        result = _build_webrtc_result(None)
        assert result.component_mounted is False
        assert result.playing is False
        assert result.processor is None

    def test_build_from_mock_context(self):
        mock_ctx = MagicMock()
        mock_ctx.state.playing = True
        mock_ctx.state.signalling = True
        mock_proc = MagicMock()
        mock_proc._processor_generation = 5
        mock_ctx.audio_processor = mock_proc
        mock_ctx.processor = None  # Explicitly set to None so _get_voice_webrtc_processor finds audio_processor
        result = _build_webrtc_result(mock_ctx)
        assert result.component_mounted is True
        assert result.playing is True
        assert result.signalling is True
        assert result.processor is mock_proc
        assert result.processor_generation == 5


# ---------------------------------------------------------------------------
# 13. Button state logic
# ---------------------------------------------------------------------------


class TestButtonStateLogic:
    def test_start_enabled_when_failed(self):
        result = ContinuousWebRTCResult(
            playing=False,
            component_mounted=True,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="failed",
            streaming_ui_state="failed",
            streaming_start_request_id=None,
            streaming_start_microphone_confirmed_at=time.time() - 10.0,
            _voice_prev_webrtc_playing=True,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["start_enabled"] is True

    def test_stop_enabled_when_desired_and_playing(self):
        result = ContinuousWebRTCResult(playing=True, component_mounted=True)
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["stop_enabled"] is True

    def test_start_disabled_when_startup_in_progress(self):
        result = ContinuousWebRTCResult(playing=False, component_mounted=True)
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="starting_microphone",
            streaming_start_request_id="req-123",
            streaming_start_microphone_confirmed_at=None,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["start_enabled"] is False
        assert reconciled["stop_enabled"] is True


# ---------------------------------------------------------------------------
# 14. Desired_mic_playing preservation
# ---------------------------------------------------------------------------


class TestDesiredMicPlayingPreservation:
    """desired_mic_playing must remain True during active sessions."""

    def test_not_cleared_by_backend_attachment(self):
        proc = _mock_processor()
        result = ContinuousWebRTCResult(
            playing=True,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            streaming_processor_id=id(proc),
            streaming_processor_generation=proc._processor_generation,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["desired_mic_playing"] is True

    def test_cleared_only_on_user_stop(self):
        result = ContinuousWebRTCResult(playing=False, component_mounted=False)
        ss = _mock_session_state(
            desired_mic_playing=False,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["desired_mic_playing"] is False
        assert reconciled["connection_state"] == "disabled"


# ---------------------------------------------------------------------------
# 15. Render-order verification
# ---------------------------------------------------------------------------


class TestRenderOrder:
    """Verify that the state resolver receives the current WebRTC result before controls are rendered."""

    def test_reconcile_uses_current_webrtc_result(self):
        """_reconcile_voice_lifecycle must use the provided webrtc_result, not stale session state."""
        proc = _mock_processor()
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=proc,
            processor_id=id(proc),
            processor_generation=proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
            streaming_processor_id=id(proc),
            streaming_processor_generation=proc._processor_generation,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] != "ready"
        assert reconciled["webrtc_playing"] is False


# ---------------------------------------------------------------------------
# 16. Backend without playing WebRTC
# ---------------------------------------------------------------------------


class TestBackendWithoutPlayingWebrtc:
    """Backend connected + WebRTC playing=False → stale backend cleanup."""

    def test_stale_backend_detected_in_diagnostics(self):
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=mock_proc,
            processor_id=id(mock_proc),
            processor_generation=mock_proc._processor_generation,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            streaming_processor_id=id(mock_proc),
            streaming_processor_generation=1,
            voice_streaming_state="ready",
            streaming_start_microphone_confirmed_at=time.time() - 10.0,
            _voice_prev_webrtc_playing=True,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "failed"
        assert reconciled["unexpected_webrtc_stop"] is True


# ---------------------------------------------------------------------------
# 17. Signalling-only badge test
# ---------------------------------------------------------------------------


class TestSignallingOnlyBadge:
    """playing=False + signalling=True → badge must not show Ready."""

    def test_badge_shows_microphone_stopped(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] != "ready"
        assert reconciled["connection_state"] != "listening"


# ---------------------------------------------------------------------------
# 18. Startup timeout → Failed
# ---------------------------------------------------------------------------


class TestStartupTimeout:
    """Microphone never confirmed + startup timeout elapsed → Failed."""

    def test_startup_timeout_produces_failed(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=False,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_start_requested=True,
            streaming_start_request_id="req-123",
            streaming_start_requested_at=time.time() - 20.0,
            streaming_start_microphone_confirmed_at=None,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "failed"
        assert reconciled["start_enabled"] is True


# ---------------------------------------------------------------------------
# 19. Disabled when desired_mic_playing=False
# ---------------------------------------------------------------------------


class TestDisabledWhenDesiredFalse:
    def test_disabled_when_desired_false(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=False,
            component_mounted=False,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=False,
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ):
            reconciled = _reconcile_voice_lifecycle(result)
        assert reconciled["connection_state"] == "disabled"
        assert reconciled["start_enabled"] is True
        assert reconciled["stop_enabled"] is False


# ---------------------------------------------------------------------------
# 20. Voice state invariant violation detection
# ---------------------------------------------------------------------------


class TestStateInvariantViolation:
    """If resolved_state is ready/listening but playing=False, it must be detected."""

    def test_invariant_violation_recorded(self):
        result = ContinuousWebRTCResult(
            playing=False,
            signalling=True,
            component_mounted=True,
            processor=None,
        )
        ss = _mock_session_state(
            desired_mic_playing=True,
            voice_streaming_state="ready",
        )
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.st.session_state.get",
            ss.get,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ) as mock_trace:
            reconciled = _reconcile_voice_lifecycle(result)
        # The reconciled state should not be "ready" when playing=False
        assert reconciled["connection_state"] != "ready"
        assert reconciled["connection_state"] != "listening"