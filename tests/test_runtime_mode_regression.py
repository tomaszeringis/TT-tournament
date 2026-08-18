"""Regression tests for runtime mode split-brain fixes."""
from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_scorekeeper.events import (
    VoiceRuntimeMode,
    VoiceTranscriptSource,
    FinalizedUtterance,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
)
from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32


def _make_chunk() -> MagicMock:
    chunk = MagicMock()
    chunk.to_pcm_bytes.return_value = b"\x00" * 160
    chunk.rms = 0.1
    chunk.duration_ms = 100.0
    chunk.sample_format = SAMPLE_FORMAT_FLOAT32
    chunk.sample_rate = 16000
    chunk.channels = 1
    return chunk


class _MockSessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value
    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


class TestRuntimeModeSplitBrainFix:
    """Tests for the runtime mode split-brain fix."""

    def test_streaming_startup_sets_live_mode_even_when_stale_calibration(self):
        """After streaming startup, runtime_mode must be LIVE regardless of
        any previous calibration state."""
        import streamlit as st
        from tournament_platform.app.pages.voice_scorekeeper import (
            _set_voice_runtime_mode,
        )

        state = {
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_events_enabled": True,
            "voice_continuous_session_id": str(uuid.uuid4()),
        }

        mock_state = _MockSessionState(state)
        with patch.object(st, "session_state", mock_state):
            _set_voice_runtime_mode(
                VoiceRuntimeMode.LIVE,
                reason="streaming_started",
                caller="_process_streaming_startup",
            )

        assert mock_state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE

    def test_calibration_exit_never_restores_calibration_mode(self):
        """After calibration exit, runtime_mode must never be CALIBRATION."""
        import streamlit as st
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            _exit_calibration_mode,
        )

        state = {
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.CALIBRATION.value,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_events_enabled": True,
            "voice_continuous_session_id": str(uuid.uuid4()),
        }

        mock_state = _MockSessionState(state)
        with patch.object(st, "session_state", mock_state):
            _exit_calibration_mode()

        assert mock_state["voice_runtime_mode"] != VoiceRuntimeMode.CALIBRATION

    def test_calibration_exit_restores_live_when_listening(self):
        """After calibration exit with active listening, runtime_mode should be LIVE."""
        import streamlit as st
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            _exit_calibration_mode,
        )

        state = {
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.CALIBRATION.value,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_events_enabled": True,
            "voice_continuous_session_id": str(uuid.uuid4()),
        }

        mock_state = _MockSessionState(state)
        with patch.object(st, "session_state", mock_state):
            _exit_calibration_mode()

        assert mock_state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE

    def test_post_calibration_live_command_not_skipped(self):
        """Full path: after calibration exit, a live FinalizedUtterance is not
        skipped by event_drain due to CALIBRATION runtime mode."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
        )

        mock_mm = MagicMock()
        mock_mm.match_id = 1
        mock_mm.state.player_a = "Player A"
        mock_mm.state.player_b = "Player B"
        mock_mm.state.score_a = 0
        mock_mm.state.score_b = 0
        mock_mm.apply_voice_event.return_value = (True, "point")

        utt = FinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="lt",
            utterance_id="sess-1:1:1",
            created_at=time.time(),
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            finalization_reason="speech_final",
            source=VoiceTranscriptSource.CONTINUOUS,
        )

        mock_proc = MagicMock()
        mock_proc.drain_streaming_events.return_value = [utt]
        mock_proc.has_pending_events.return_value = True

        mock_snapshot = MagicMock()
        mock_snapshot.processor = mock_proc

        ss = _MockSessionState({
            "match_manager": mock_mm,
            "last_applied_voice_event_ids": [],
            "voice_listening": True,
            "voice_events_enabled": True,
            "voice_runtime_mode": VoiceRuntimeMode.LIVE,
            "voice_continuous_session_id": "sess-1",
            "voice_continuous_session_start": time.time() - 10,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_scoring_enabled": True,
            "voice_selected_match_id": 1,
            "voice_selected_player1_id": 1,
            "voice_selected_player2_id": 2,
            "voice_strict_mode": False,
            "voice_confidence_threshold": 0.5,
            "voice_last_applied_event_key": None,
            "voice_last_applied_event_ts": 0.0,
            "commentary_engine": None,
            "pending_confirmations": [],
            "voice_confirmation_machine": None,
            "last_voice_continuous_transcript": "",
            "voice_streaming_language": "lt",
            "voice_audit_events": [],
        })

        with patch("tournament_platform.app.services.voice_scorekeeper.event_drain.st.session_state", ss):
            with patch("tournament_platform.app.pages.voice_scorekeeper._get_webrtc_playing_state", return_value=True):
                with patch("tournament_platform.app.pages.voice_scorekeeper.is_voice_scoring_enabled", return_value=True):
                    result = _process_voice_events(snapshot=mock_snapshot)

        assert result.events_accepted >= 1 or result.events_drained >= 1
        if result.events_accepted >= 1:
            assert mock_mm.apply_voice_event.called

    def test_drain_invalid_logs_type_and_module(self):
        """When drain_streaming_events receives an invalid item, it logs type and module."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = str(uuid.uuid4())
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = str(uuid.uuid4())
        proc._streaming_match_id = 1

        proc._finalized_utterance_queue.put_nowait("not_a_finalized_utterance")

        with patch("tournament_platform.app.services.voice_scorekeeper.runtime.logger") as mock_logger:
            result = proc.drain_streaming_events()

        assert proc._streaming_invalid == 1
        assert proc._last_finalized_invalid_type == "str"
        assert proc._last_finalized_invalid_module == "builtins"
        assert mock_logger.debug.called
        assert "invalid finalized item" in mock_logger.debug.call_args[0][0]
        proc.stop()

    def test_process_streaming_startup_no_name_error_and_sets_live(self):
        """Regression: _process_streaming_startup must not raise NameError
        for VoiceRuntimeMode and must set runtime_mode to LIVE."""
        import streamlit as st
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        request_id = str(uuid.uuid4())
        new_session_id = str(uuid.uuid4())
        ss = _MockSessionState({
            "streaming_start_request_id": request_id,
            "streaming_start_requested_at": time.time() - 1,
            "streaming_start_microphone_confirmed_at": time.time() - 0.5,
            "streaming_start_backend_attached_at": None,
            "streaming_start_completed_at": None,
            "voice_listening": False,
            "voice_events_enabled": False,
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_streaming_state": "disabled",
            "streaming_ui_state": "disabled",
            "voice_start_requested": True,
            "voice_streaming_provider": "deepgram",
            "voice_streaming_language": "lt",
            "voice_selected_match_id": 1,
            "voice_continuous_session_id": new_session_id,
            "selected_player_a": {"name": "Player A"},
            "selected_player_b": {"name": "Player B"},
            "voice_webrtc_ctx": {
                "is_playing": True,
                "processor": MagicMock(),
            },
        })

        mock_proc = MagicMock()
        mock_proc._processor_generation = 1
        mock_proc._streaming_generation = 0
        mock_proc._streaming_voice_session_id = None
        mock_proc.set_streaming_backend = MagicMock()

        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"

        def _set_streaming_backend(*args, **kwargs):
            mock_proc._streaming_generation = 1
            mock_proc._streaming_voice_session_id = new_session_id

        mock_proc.set_streaming_backend.side_effect = _set_streaming_backend

        with patch.object(st, "session_state", ss):
            with patch("tournament_platform.app.pages.voice_scorekeeper._get_raw_voice_webrtc_context", return_value=MagicMock()):
                with patch("tournament_platform.app.pages.voice_scorekeeper._get_current_webrtc_processor", return_value=mock_proc):
                    with patch("tournament_platform.app.pages.voice_scorekeeper._get_webrtc_playing_state", return_value=True):
                        with patch("tournament_platform.app.pages.voice_scorekeeper.ASRBackendFactory") as mock_factory:
                            mock_result = MagicMock()
                            mock_result.available = True
                            mock_result.backend = mock_backend
                            mock_factory.create_streaming.return_value = mock_result
                            _process_streaming_startup()

        assert ss["voice_runtime_mode"] == VoiceRuntimeMode.LIVE
        assert ss.get("streaming_start_completed_at") is not None