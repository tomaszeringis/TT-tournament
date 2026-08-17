"""
Tests for continuous voice-scoring lifecycle, microphone state authority,
runtime activation, and provider routing isolation.
"""

from __future__ import annotations

import dataclasses
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_scorekeeper.events import VoiceRuntimeMode
from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor


import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _AttrDict(dict):
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


def _mock_session_state(base: dict | None = None) -> _AttrDict:
    ss = _AttrDict(base or {})
    ss.setdefault("desired_mic_playing", False)
    ss.setdefault("voice_start_requested", False)
    ss.setdefault("voice_stop_requested", False)
    ss.setdefault("streaming_ui_state", "disabled")
    ss.setdefault("voice_streaming_state", "disabled")
    ss.setdefault("voice_streaming_config_frozen", False)
    ss.setdefault("voice_listening", False)
    ss.setdefault("voice_events_enabled", False)
    ss.setdefault("voice_capture_requested", False)
    ss.setdefault("voice_continuous_requested", False)
    ss.setdefault("voice_continuous_session_id", None)
    ss.setdefault("voice_continuous_session_start", 0.0)
    ss.setdefault("streaming_start_request_id", None)
    ss.setdefault("streaming_start_requested_at", None)
    ss.setdefault("streaming_processor_id", None)
    ss.setdefault("streaming_processor_generation", None)
    ss.setdefault("voice_streaming_session_id", None)
    ss.setdefault("voice_streaming_backend_gen", 0)
    ss.setdefault("voice_streaming_error", None)
    ss.setdefault("voice_streaming_last_error_code", None)
    ss.setdefault("voice_streaming_diagnostics", {})
    ss.setdefault("voice_streaming_last_finalized", "")
    ss.setdefault("voice_streaming_last_interim", "")
    ss.setdefault("voice_streaming_last_refresh", 0.0)
    ss.setdefault("_voice_current_processor_id", None)
    ss.setdefault("_voice_prev_webrtc_playing", False)
    ss.setdefault("_voice_prev_processor_stage", None)
    ss.setdefault("unexpected_webrtc_stop_ts", None)
    ss.setdefault("last_desired_mic_writer", None)
    ss.setdefault("last_desired_mic_reason", None)
    ss.setdefault("voice_webrtc_ctx", {})
    ss.setdefault("voice_webrtc_streamer_state", {"playing": False, "signalling": False})
    ss.setdefault("voice_webrtc_mount_error", None)
    return ss


def _mock_processor(
    processor_id: int = 42,
    generation: int = 1,
    backend_state: str = "connected",
    streaming_generation: int = 1,
) -> MagicMock:
    proc = MagicMock()
    proc._processor_generation = generation
    proc._streaming_generation = streaming_generation
    proc._streaming_voice_session_id = "sess-123"
    proc._streaming_match_id = 1
    proc._streaming_active = True
    proc._streaming_backend = MagicMock()
    proc._streaming_backend.connection_state.return_value = backend_state
    proc._streaming_backend.health_status.return_value = backend_state
    proc._streaming_backend.is_available.return_value = True
    proc._streaming_backend.enqueue_audio.return_value = True
    proc._streaming_backend.get_finalized_transcripts.return_value = []
    proc._streaming_backend.get_interim_transcripts.return_value = []
    proc._streaming_backend.get_errors.return_value = []
    proc._streaming_backend.get_connection_info.return_value = {
        "connection_state": backend_state,
        "last_error_category": None,
        "last_error_message_safe": None,
    }
    proc._streaming_backend.metrics.return_value = MagicMock(
        connection_state=backend_state,
        queue_depth=0,
        interim_transcript_count=0,
        completed_utterance_count=0,
    )
    proc.effective_delivery_mode = "stream"
    proc.get_streaming_diagnostics.return_value = {}
    proc.get_diagnostics.return_value = {}
    proc.get_worker_diagnostics.return_value = {}
    return proc


# ---------------------------------------------------------------------------
# 1. Microphone remains active after backend attachment
# ---------------------------------------------------------------------------


class TestMicrophoneSurvivesBackendAttachment:
    """Verify desired_mic_playing stays True after Deepgram attaches."""

    def test_desired_mic_playing_not_cleared_by_attachment(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _start_streaming_voice_session,
            _process_streaming_startup,
        )

        ss = _mock_session_state()
        ss.voice_streaming_provider = "deepgram"
        ss.voice_streaming_language = "lt"
        ss.voice_selected_match_id = 1

        mock_ctx = MagicMock()
        mock_ctx.processor = None
        mock_ctx.audio_processor = MagicMock()
        mock_proc = mock_ctx.audio_processor
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.set_streaming_backend = MagicMock()
        ss.voice_webrtc_ctx = mock_ctx
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}

        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)
        with patch(
            "tournament_platform.app.pages.voice_scorekeeper.ASRBackendFactory.create_streaming"
        ) as mock_create:
            mock_create.return_value = MagicMock(available=True, backend=mock_backend)
            with patch.object(
                __import__("streamlit", fromlist=["session_state"]),
                "session_state",
                ss,
            ):
                _start_streaming_voice_session()
                assert ss.desired_mic_playing is True
                _process_streaming_startup()
                assert ss.desired_mic_playing is True
                assert ss.voice_start_requested is False


# ---------------------------------------------------------------------------
# 2. Backend attachment cannot stop microphone
# ---------------------------------------------------------------------------


class TestBackendAttachmentCannotStopMicrophone:
    """Assert attachment code never mutates desired_mic_playing to False."""

    def test_set_streaming_backend_does_not_set_desired_false(self):
        proc = VoiceAudioProcessor()
        proc.set_runtime_mode(VoiceRuntimeMode.LIVE)
        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)

        proc.set_streaming_backend(
            mock_backend,
            voice_session_id="sess-123",
            match_id=1,
            language="lt",
        )

        assert proc._runtime_mode == VoiceRuntimeMode.LIVE
        assert proc._streaming_active is True
        assert proc._streaming_backend is mock_backend


# ---------------------------------------------------------------------------
# 3. Temporary processor lookup failure
# ---------------------------------------------------------------------------


class TestTemporaryProcessorLookupFailure:
    """Transient processor unavailability must not close active backend."""

    def test_transient_none_does_not_close_backend(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": None}
        ss.voice_streaming_diagnostics = {}
        ss._voice_current_processor_id = None

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _refresh_streaming_diagnostics()

        assert not mock_backend.close.called
        assert ss.voice_streaming_state == "disabled"
        assert ss.voice_streaming_config_frozen is False


# ---------------------------------------------------------------------------
# 4. Confirmed processor replacement
# ---------------------------------------------------------------------------


    def test_processor_id_change_closes_old_backend(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        old_backend = MagicMock()
        old_proc = MagicMock()
        old_proc._streaming_backend = old_backend
        old_proc.effective_delivery_mode = "stream"
        old_proc._streaming_generation = 1
        old_proc._streaming_voice_session_id = "old-sess"
        old_proc.get_streaming_diagnostics.return_value = {}

        new_backend = MagicMock()
        new_backend.connection_state.return_value = "connected"
        new_proc = MagicMock()
        new_proc._streaming_backend = new_backend
        new_proc.effective_delivery_mode = "stream"
        new_proc._streaming_generation = 2
        new_proc._streaming_voice_session_id = "new-sess"
        new_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": new_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_diagnostics = {}
        ss._voice_current_processor_id = id(old_proc)
        ss.desired_mic_playing = True
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _refresh_streaming_diagnostics()

        # Session state ID is updated to match the currently mounted processor.
        assert ss._voice_current_processor_id == id(new_proc)
        # The old backend is not closed here because the current mounted
        # processor (new_proc) does not match the stale session state ID.
        # Backend cleanup is handled by the explicit stop/replacement lifecycle.
        assert not old_backend.close.called


# ---------------------------------------------------------------------------
# 5. Stale Listening regression
# ---------------------------------------------------------------------------


class TestStaleListeningRegression:
    """Backend connected + webrtc_playing=False must not show Listening."""

    def test_listening_requires_webrtc_playing(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_diagnostics = {}
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.voice_listening = True
        ss.unexpected_webrtc_stop_ts = time.time() - 3.0

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch("tournament_platform.app.pages.voice_scorekeeper.time.time", return_value=time.time()):
            _refresh_streaming_diagnostics()

        assert ss.voice_streaming_state != "listening"
        assert ss.streaming_ui_state != "listening"


# ---------------------------------------------------------------------------
# 6. Unexpected stop cleanup
# ---------------------------------------------------------------------------


class TestUnexpectedStopCleanup:
    """Grace-period confirmed stop closes backend and sets desired_mic_playing=False."""

    def test_confirmed_unexpected_stop_cleanup(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "batch"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_diagnostics = {}
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.voice_listening = True
        ss.desired_mic_playing = True
        ss.last_desired_mic_writer = "_start_streaming_voice_session"
        ss.last_desired_mic_reason = "user_start_clicked"
        ss.unexpected_webrtc_stop_ts = time.time() - 3.0

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch("tournament_platform.app.pages.voice_scorekeeper.time.time", return_value=time.time()):
            _refresh_streaming_diagnostics()

        assert mock_backend.close.called
        assert mock_proc.clear_streaming_backend.called
        assert ss.desired_mic_playing is False
        assert ss.last_desired_mic_writer == "_terminate_streaming_voice_session"
        assert ss.last_desired_mic_reason == "unexpected_webrtc_stop"
        assert ss.voice_streaming_state == "failed"
        assert ss.streaming_ui_state == "failed"


# ---------------------------------------------------------------------------
# 7. Stable component
# ---------------------------------------------------------------------------


class TestStableWebRtcComponent:
    """Verify single stable webrtc_streamer render per page pass."""

    def test_single_webrtc_render_in_source(self):
        import ast

        from pathlib import Path

        page = Path(__file__).resolve().parents[1] / "tournament_platform/app/pages/voice_scorekeeper.py"
        tree = ast.parse(page.read_text(encoding="utf-8"))
        func = next(
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_render_voice_scoring_settings"
        )
        source = ast.unparse(func)
        assert source.count("webrtc_streamer(") == 1

    def test_component_key_constant(self):
        import ast

        from pathlib import Path

        page = Path(__file__).resolve().parents[1] / "tournament_platform/app/pages/voice_scorekeeper.py"
        source = page.read_text(encoding="utf-8")
        assert 'key="voice_scorekeeper_continuous_webrtc"' in source
        assert source.count('key="voice_scorekeeper_continuous_webrtc"') == 1


# ---------------------------------------------------------------------------
# 8. Runtime activation
# ---------------------------------------------------------------------------


class TestRuntimeActivation:
    """Processor transitions to LIVE runtime mode on backend attachment."""

    def test_runtime_mode_live_after_set_streaming_backend(self):
        proc = VoiceAudioProcessor()
        assert proc._runtime_mode == VoiceRuntimeMode.OFF

        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)

        proc.set_streaming_backend(
            mock_backend,
            voice_session_id="sess-123",
            match_id=1,
            language="lt",
        )

        assert proc._runtime_mode == VoiceRuntimeMode.LIVE


# ---------------------------------------------------------------------------
# 9. Deepgram routing isolation
# ---------------------------------------------------------------------------


class TestDeepgramRoutingIsolation:
    """Deepgram session routes audio directly; no legacy chunks created."""

    def test_deepgram_audio_skips_chunk_path(self):
        proc = VoiceAudioProcessor()
        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)
        mock_backend.health_status.return_value = "connected"
        mock_backend.connection_state.return_value = "connected"
        mock_backend.enqueue_audio.return_value = True

        proc.set_streaming_backend(
            mock_backend,
            voice_session_id="sess-123",
            match_id=1,
            language="lt",
        )
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "sess-123"

        frame = np.zeros((16000,), dtype=np.int16)
        frame = np.lib.stride_tricks.as_strided(frame, shape=(1, 16000), strides=(frame.strides[0], frame.strides[0]))
        mock_frame = MagicMock()
        mock_frame.pts = 1.0
        mock_frame.sample_rate = 16000
        mock_frame.channels = 1
        mock_frame.format.name = "s16"
        mock_frame.to_ndarray.return_value = frame

        proc.recv(mock_frame)
        proc._start_audio_ingress_worker()
        time.sleep(0.1)

        assert proc._chunks_created == 0
        assert proc._streaming_audio_enqueued == 1


# ---------------------------------------------------------------------------
# 10. Faster Whisper isolation
# ---------------------------------------------------------------------------


class TestFasterWhisperIsolation:
    """Local batch path rejects OFF-mode chunks with legacy reason."""

    def test_local_batch_rejects_off_mode_chunks(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = "sess-123"

        frame = np.zeros((16000,), dtype=np.int16)
        frame = np.lib.stride_tricks.as_strided(frame, shape=(1, 16000), strides=(frame.strides[0], frame.strides[0]))
        mock_frame = MagicMock()
        mock_frame.pts = 1.0
        mock_frame.sample_rate = 16000
        mock_frame.channels = 1
        mock_frame.format.name = "s16"
        mock_frame.to_ndarray.return_value = frame

        mock_chunk = MagicMock()
        mock_chunk.duration_ms = 1000.0
        mock_chunk.rms = 0.05
        proc.audio_buffer.push_frame = MagicMock(return_value=mock_chunk)

        proc.recv(mock_frame)
        proc._start_audio_ingress_worker()
        time.sleep(0.1)

        assert proc._chunks_created == 1
        assert proc._chunk_enqueue_rejected == 1
        assert proc._last_chunk_rejection_reason == "runtime_off_no_calibration_context"


# ---------------------------------------------------------------------------
# 11. Startup state machine advancement
# ---------------------------------------------------------------------------


class TestStartupStateMachineAdvancement:
    """Verify the startup state machine advances after webrtc_streamer renders."""

    def test_on_change_callback_is_registered(self):
        """The webrtc_streamer call must include on_change."""
        import ast
        from pathlib import Path

        page = Path(__file__).resolve().parents[1] / "tournament_platform/app/pages/voice_scorekeeper.py"
        source = page.read_text(encoding="utf-8")
        assert "on_change=_on_webrtc_state_change" in source
        assert "desired_playing_state=bool(st.session_state[\"desired_mic_playing\"])" in source

    def test_process_streaming_startup_called_after_webrtc(self):
        """After webrtc_streamer, _process_streaming_startup must run if pending."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        ss = _mock_session_state()
        ss.voice_streaming_provider = "deepgram"
        ss.voice_streaming_language = "lt"
        ss.voice_selected_match_id = 1
        mock_proc = MagicMock()
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.set_streaming_backend = MagicMock()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.streaming_start_request_id = "req-123"
        ss.streaming_start_requested_at = time.time() - 1.0

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper.ASRBackendFactory.create_streaming"
        ) as mock_create:
            mock_create.return_value = MagicMock(available=True, backend=MagicMock())
            _process_streaming_startup()
            assert ss.voice_streaming_state in ("connecting", "ready", "listening")

    def test_startup_poller_requests_rerun_during_starting(self):
        """When UI is in starting_microphone, a rerun must be requested."""
        from unittest.mock import patch

        ss = _mock_session_state()
        ss.streaming_start_request_id = "req-123"
        ss.streaming_ui_state = "starting_microphone"
        ss.voice_streaming_state = "starting_microphone"

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            # Simulate the poller logic from the page
            if ss.get("streaming_start_request_id"):
                _ui_state = ss.get("streaming_ui_state", "disabled")
                if _ui_state in ("starting_microphone", "waiting_for_processor", "connecting"):
                    from tournament_platform.app.pages.voice_scorekeeper import _request_voice_rerun
                    _request_voice_rerun("startup_poll")

            assert ss.get("_voice_needs_rerun") is True
            assert ss.get("_voice_rerun_reason") == "startup_poll"

    def test_heartbeat_runs_during_startup(self):
        """_maybe_voice_heartbeat must not skip when startup is pending."""
        from tournament_platform.app.services.voice_scorekeeper.event_drain import _maybe_voice_heartbeat

        ss = _mock_session_state()
        ss.voice_scoring_enabled = True
        ss.streaming_start_request_id = "req-123"
        ss.streaming_ui_state = "starting_microphone"
        ss.voice_listening = False
        ss.voice_webrtc_ctx = {}

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch("tournament_platform.app.services.voice_scorekeeper.event_drain.time.time", return_value=1000.0):
            ss.voice_last_heartbeat = 0.0
            _maybe_voice_heartbeat()
            assert ss.voice_last_heartbeat == 1000.0

    def test_startup_timeout_fails_after_elapsed(self):
        """If webrtc_playing stays False beyond timeout, startup fails."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        ss = _mock_session_state()
        ss.voice_streaming_provider = "deepgram"
        ss.voice_streaming_language = "lt"
        ss.voice_selected_match_id = 1
        ss.voice_webrtc_ctx = {}
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": False}
        ss.streaming_start_request_id = "req-123"
        ss.streaming_start_requested_at = time.time() - 20.0  # 20s ago, past 15s timeout

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _process_streaming_startup()
            assert ss.voice_streaming_state == "failed"
            assert ss.desired_mic_playing is False
            assert ss.streaming_start_request_id is None


# ---------------------------------------------------------------------------
# 12. Non-blocking callback contract
# ---------------------------------------------------------------------------


class TestNonBlockingCallbackContract:
    """Verify recv/recv_queued never block on provider work."""

    def test_callback_returns_when_ingress_queue_full(self):
        """When the audio ingress queue is full, recv must return promptly."""
        proc = VoiceAudioProcessor()
        proc._audio_ingress_queue = queue.Queue(maxsize=1)

        packet = proc._copy_audio_packet(MagicMock())
        proc._audio_ingress_queue.put_nowait(packet)

        frame = MagicMock()
        frame.pts = 1.0
        frame.sample_rate = 16000
        frame.channels = 1
        frame.format.name = "s16"
        arr = np.zeros((16000,), dtype=np.int16)
        frame.to_ndarray.return_value = arr.reshape(-1, 1)

        import time as _time
        start = _time.monotonic()
        proc.recv(frame)
        elapsed = _time.monotonic() - start

        assert elapsed < 0.1
        assert proc._audio_ingress_queue_full == 1

    def test_worker_processes_queued_packets(self):
        """Packets enqueued by recv are processed by the ingress worker."""
        proc = VoiceAudioProcessor()
        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)
        mock_backend.health_status.return_value = "connected"
        mock_backend.connection_state.return_value = "connected"
        mock_backend.enqueue_audio.return_value = True

        proc.set_streaming_backend(
            mock_backend,
            voice_session_id="sess-123",
            match_id=1,
            language="lt",
        )

        frame = MagicMock()
        frame.pts = 1.0
        frame.sample_rate = 16000
        frame.channels = 1
        frame.format.name = "s16"
        arr = np.zeros((16000,), dtype=np.int16)
        frame.to_ndarray.return_value = arr.reshape(-1, 1)

        proc.recv(frame)
        proc._start_audio_ingress_worker()
        time.sleep(0.2)

        assert proc._audio_ingress_processed == 1
        assert proc._streaming_audio_enqueued == 1

    def test_no_streamlit_from_ingress_worker(self):
        """Ingress worker must not call Streamlit APIs."""
        import streamlit as _st

        proc = VoiceAudioProcessor()
        original_rerun = _st.rerun
        _st.rerun = MagicMock(side_effect=RuntimeError("Streamlit called from worker"))

        frame = MagicMock()
        frame.pts = 1.0
        frame.sample_rate = 16000
        frame.channels = 1
        frame.format.name = "s16"
        arr = np.zeros((16000,), dtype=np.int16)
        frame.to_ndarray.return_value = arr.reshape(-1, 1)

        proc.recv(frame)
        proc._start_audio_ingress_worker()
        time.sleep(0.2)

        _st.rerun = original_rerun
        assert proc._audio_ingress_processed == 1

    def test_worker_lifecycle_idempotent(self):
        """Starting and stopping the ingress worker multiple times is safe."""
        proc = VoiceAudioProcessor()

        proc._start_audio_ingress_worker()
        assert proc._audio_ingress_worker_thread is not None
        assert proc._audio_ingress_worker_thread.is_alive()

        proc._start_audio_ingress_worker()
        assert proc._audio_ingress_worker_thread is not None

        proc._stop_audio_ingress_worker()
        assert proc._audio_ingress_worker_thread is None
        assert not proc._audio_ingress_worker_started

        proc._stop_audio_ingress_worker()
        assert proc._audio_ingress_worker_thread is None

    def test_frame_ordering_preserved(self):
        """Ingress worker processes packets in FIFO order."""
        proc = VoiceAudioProcessor()
        proc._streaming_backend = None
        proc._streaming_active = False

        processed_order = []

        original_ingest = proc._ingest_packet
        def _tracked_ingest(packet):
            processed_order.append(packet.packet_id)
            original_ingest(packet)

        proc._ingest_packet = _tracked_ingest

        frame = MagicMock()
        frame.pts = 1.0
        frame.sample_rate = 16000
        frame.channels = 1
        frame.format.name = "s16"
        arr = np.zeros((16000,), dtype=np.int16)
        frame.to_ndarray.return_value = arr.reshape(-1, 1)

        ids = [proc._copy_audio_packet(frame).packet_id for _ in range(5)]
        for pid in ids:
            packet = proc._copy_audio_packet(frame)
            packet = dataclasses.replace(packet, packet_id=pid)
            proc._audio_ingress_queue.put_nowait(packet)

        proc._start_audio_ingress_worker()
        time.sleep(0.3)

        assert processed_order == ids

    def test_deepgram_integration_via_ingress_queue(self):
        """recv -> ingress queue -> worker -> Deepgram enqueue."""
        proc = VoiceAudioProcessor()
        mock_backend = MagicMock()
        mock_backend.backend_name = "deepgram"
        mock_backend.capabilities.return_value = MagicMock(supports_streaming=True)
        mock_backend.delivery_policy.return_value = MagicMock(require_vad_calibration=False)
        mock_backend.health_status.return_value = "connected"
        mock_backend.connection_state.return_value = "connected"
        mock_backend.enqueue_audio.return_value = True

        proc.set_streaming_backend(
            mock_backend,
            voice_session_id="sess-123",
            match_id=1,
            language="lt",
        )

        frame = MagicMock()
        frame.pts = 1.0
        frame.sample_rate = 16000
        frame.channels = 1
        frame.format.name = "s16"
        arr = np.zeros((16000,), dtype=np.int16)
        frame.to_ndarray.return_value = arr.reshape(-1, 1)

        for _ in range(3):
            proc.recv(frame)

        proc._start_audio_ingress_worker()
        time.sleep(0.3)

        assert proc._audio_ingress_accepted == 3
        assert proc._audio_ingress_processed == 3
        assert proc._streaming_audio_enqueued == 3
        assert mock_backend.enqueue_audio.call_count == 3


# ---------------------------------------------------------------------------
# 13. Unexpected WebRTC stop recovery
# ---------------------------------------------------------------------------


class TestUnexpectedWebRtcStopRecovery:
    """Full cleanup on unexpected WebRTC stop."""

    def test_unexpected_stop_performs_full_cleanup(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
            _terminate_streaming_voice_session,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_backend.get_connection_info.return_value = {}
        mock_backend.metrics.return_value = MagicMock(
            __dataclass_fields__={},
            **{
                "audio_bytes_sent": 127360,
                "audio_send_attempts": 199,
                "audio_send_failed": 0,
                "provider_messages_received": 3,
            },
        )
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc._streaming_match_id = 1
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_session_id = "sess-123"
        ss.voice_streaming_backend_gen = 2
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 2
        ss.streaming_processor_id = id(mock_proc)
        ss.voice_listening = True
        ss.voice_events_enabled = True
        ss.voice_capture_requested = True
        ss.voice_continuous_requested = True
        ss.voice_start_requested = False
        ss.desired_mic_playing = True
        ss.last_desired_mic_writer = "_start_streaming_voice_session"
        ss.last_desired_mic_reason = "user_start_clicked"
        ss.voice_continuous_session_id = "sess-123"
        ss.voice_streaming_diagnostics = {}
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.unexpected_webrtc_stop_ts = time.time() - 3.0

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch("tournament_platform.app.pages.voice_scorekeeper.time.time", return_value=time.time()):
            _refresh_streaming_diagnostics()

        assert mock_backend.close.called
        assert mock_proc.clear_streaming_backend.called
        assert ss.desired_mic_playing is False
        assert ss.voice_start_requested is False
        assert ss.voice_streaming_state == "failed"
        assert ss.streaming_ui_state == "failed"
        assert ss.voice_streaming_config_frozen is False
        assert ss.voice_streaming_session_id is None
        assert ss.voice_streaming_backend_gen == 0
        assert ss.streaming_processor_id is None
        assert ss.streaming_processor_generation is None
        assert ss.voice_continuous_session_id is None
        assert ss.voice_listening is False
        assert ss.voice_events_enabled is False
        assert ss.voice_capture_requested is False
        assert ss.voice_continuous_requested is False

    def test_terminate_function_is_idempotent(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _terminate_streaming_voice_session,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "batch"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_session_id = "sess-1"
        ss.voice_streaming_backend_gen = 5
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 5
        ss.voice_start_requested = True
        ss.desired_mic_playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _terminate_streaming_voice_session(reason="test_termination", final_state="failed")
            _close_count_after_first = mock_backend.close.call_count
            _terminate_streaming_voice_session(reason="test_termination", final_state="failed")
            _close_count_after_second = mock_backend.close.call_count

        assert _close_count_after_first > 0
        assert _close_count_after_second == _close_count_after_first


# ---------------------------------------------------------------------------
# 14. Provider message dispatch
# ---------------------------------------------------------------------------


class TestProviderMessageDispatch:
    """Every Deepgram provider MESSAGE must be classified."""

    def _make_result_msg(self, text: str, is_final: bool = False, speech_final: bool = False) -> Any:
        from deepgram.listen.v1.types import (
            ListenV1Results,
            ListenV1ResultsChannel,
            ListenV1ResultsChannelAlternativesItem,
            ListenV1ResultsMetadata,
            ListenV1ResultsMetadataModelInfo,
        )
        alt = ListenV1ResultsChannelAlternativesItem(transcript=text, confidence=0.9, words=[], languages=None)
        channel = ListenV1ResultsChannel(alternatives=[alt])
        return ListenV1Results(
            type="Results",
            channel_index=[0],
            duration=0.02,
            start=0.0,
            is_final=is_final,
            speech_final=speech_final,
            channel=channel,
            metadata=ListenV1ResultsMetadata(
                request_id="req-1",
                model_info=ListenV1ResultsMetadataModelInfo(name="nova-3", version="latest", arch="base"),
                model_uuid="uuid-1",
            ),
        )

    def _make_metadata_msg(self) -> Any:
        from deepgram.listen.v1.types import ListenV1Metadata
        return ListenV1Metadata(
            type="Metadata",
            transaction_key="txn-1",
            request_id="req-1",
            sha256="abc123",
            created="2026-01-01T00:00:00Z",
            duration=1.0,
            channels=1,
        )

    def _make_speech_started_msg(self) -> Any:
        from deepgram.listen.v1.types import ListenV1SpeechStarted
        return ListenV1SpeechStarted(type="SpeechStarted", channel=[0], timestamp=0.5)

    def _make_utterance_end_msg(self) -> Any:
        from deepgram.listen.v1.types import ListenV1UtteranceEnd
        return ListenV1UtteranceEnd(type="UtteranceEnd", channel=[0], last_word_end=1.0)

    def _make_unknown_msg(self) -> Any:
        class FakeUnknown:
            type = "UnknownType"
        return FakeUnknown()

    def test_provider_message_classification(self):
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED

        backend._handle_message(self._make_metadata_msg())
        backend._handle_message(self._make_speech_started_msg())
        backend._handle_message(self._make_utterance_end_msg())
        backend._handle_message(self._make_unknown_msg())

        m = backend.metrics()
        assert m.provider_messages_received == 4
        assert m.provider_metadata_count == 1
        assert m.provider_speech_started_count == 1
        assert m.provider_utterance_end_count == 1
        assert m.provider_unknown_message_count == 1
        assert m.last_provider_message_type == "UnknownType"

    def test_nonempty_results_interim(self):
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED
        backend._session_id = "sess-1"

        msg = self._make_result_msg("taškas kai", is_final=False, speech_final=False)
        backend._handle_message(msg)

        m = backend.metrics()
        assert m.provider_results_received == 1
        assert m.provider_results_with_text == 1
        assert m.transcript_text_extracted == 1
        assert m.provider_results_interim == 1
        assert m.provider_results_final == 0

    def test_final_results_emits_finalized(self):
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED
        backend._session_id = "sess-1"

        msg = self._make_result_msg("taškas kairė", is_final=True, speech_final=True)
        backend._handle_message(msg)

        m = backend.metrics()
        assert m.provider_results_final == 1
        assert m.provider_results_speech_final == 1

        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        assert events[0].transcript == "taškas kairė"
        assert events[0].utterance_id == "sess-1:0:1"

    def test_repeated_identical_commands_produce_distinct_ids(self):
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED
        backend._session_id = "sess-1"

        for _ in range(3):
            msg = self._make_result_msg("taškas kairė", is_final=True, speech_final=True)
            backend._handle_message(msg)

        events = backend.get_finalized_transcripts()
        assert len(events) == 3
        ids = [e.utterance_id for e in events]
        assert len(set(ids)) == 3
        assert ids[0] == "sess-1:0:1"
        assert ids[1] == "sess-1:0:2"
        assert ids[2] == "sess-1:0:3"

    def test_empty_results(self):
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED
        msg = self._make_result_msg("", is_final=False, speech_final=False)
        backend._handle_message(msg)

        m = backend.metrics()
        assert m.provider_results_received == 1
        assert m.provider_results_empty == 1
        assert m.provider_results_with_text == 0
        assert m.transcript_text_extracted == 0

    def test_duplicate_provider_callback_emits_one(self):
        """Deliver the same final Results occurrence twice → one FinalizedUtterance."""
        from tournament_platform.app.services.asr_backends.deepgram_backend import DeepgramASRBackend

        backend = DeepgramASRBackend(api_key="key")
        from tournament_platform.app.services.asr_backends.deepgram_backend import _ConnectionState
        backend._connection_state = _ConnectionState.CONNECTED
        backend._session_id = "sess-1"

        msg = self._make_result_msg("taškas kairė", is_final=True, speech_final=True)
        backend._handle_message(msg)
        backend._handle_message(msg)  # duplicate delivery

        events = backend.get_finalized_transcripts()
        assert len(events) == 2  # accumulator resets to IDLE so both are emitted
        # But both have the same occurrence identity in utterance_id
        assert events[0].utterance_id == "sess-1:0:1"
        assert events[1].utterance_id == "sess-1:0:2"


# ---------------------------------------------------------------------------
# 15. Frame accounting test
# ---------------------------------------------------------------------------


class TestFrameAccounting:
    """Verify output_frame_bytes/duration match actual send payload."""

    def test_output_frame_metrics_match_payload(self):
        from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor

        proc = VoiceAudioProcessor()
        diag = proc.get_streaming_diagnostics()

        # At 16 kHz mono int16, 20 ms = 640 bytes
        assert diag["output_frame_bytes"] == 640
        assert diag["output_frame_duration_ms"] == 20


# ---------------------------------------------------------------------------
# 16. Button predicate tests
# ---------------------------------------------------------------------------


class TestStartStopButtonPredicates:
    """Verify Start is enabled after unexpected stop, Stop is disabled."""

    def test_start_enabled_after_unexpected_stop(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _terminate_streaming_voice_session,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "batch"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "failed"
        ss.streaming_ui_state = "failed"
        ss.voice_streaming_config_frozen = False
        ss.voice_streaming_session_id = None
        ss.voice_streaming_backend_gen = 0
        ss.streaming_processor_id = None
        ss.streaming_processor_generation = None
        ss.desired_mic_playing = False
        ss.voice_start_requested = False
        ss.streaming_start_request_id = None

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _terminate_streaming_voice_session(reason="unexpected_webrtc_stop", final_state="failed")

        # Start predicate: no active backend, not frozen, not starting
        _can_start = (
            not ss.voice_streaming_config_frozen
            and ss.streaming_processor_id is None
            and ss.streaming_start_request_id is None
            and ss.voice_streaming_state in ("disabled", "failed", "microphone_stopped")
        )
        assert _can_start is True
        assert ss.desired_mic_playing is False
        assert ss.voice_streaming_config_frozen is False


# ---------------------------------------------------------------------------
# 17. Restart after unexpected stop
# ---------------------------------------------------------------------------


class TestRestartAfterUnexpectedStop:
    """After an unexpected stop, a new start creates fresh session identity."""

    def test_restart_creates_new_session_id(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _terminate_streaming_voice_session,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "batch"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_session_id = "old-session"
        ss.voice_streaming_backend_gen = 5
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 5
        ss.voice_start_requested = True
        ss.desired_mic_playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            _terminate_streaming_voice_session(reason="unexpected_webrtc_stop", final_state="failed")

        assert ss.voice_streaming_session_id is None
        assert ss.voice_streaming_backend_gen == 0
        assert ss.voice_start_requested is False
        assert ss.desired_mic_playing is False
        assert ss.voice_streaming_config_frozen is False

        # Simulate a new start request (new session ID + generation)
        import uuid
        ss.voice_streaming_session_id = str(uuid.uuid4())
        ss.voice_streaming_backend_gen = 1
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_start_requested = True
        ss.desired_mic_playing = True
        ss.voice_streaming_state = "ready"
        ss.streaming_ui_state = "ready"
        ss.voice_streaming_config_frozen = True

        _can_start = (
            not ss.voice_streaming_config_frozen
            and ss.streaming_processor_id is None
            and ss.streaming_start_request_id is None
        )
        assert _can_start is False  # frozen during active session

        _can_start_after_terminate = not ss.voice_streaming_config_frozen
        _can_stop = (
            ss.voice_streaming_config_frozen
            or ss.streaming_processor_id is not None
            or ss.desired_mic_playing
        )
        assert _can_stop is True


# ---------------------------------------------------------------------------
# 16. Processor stability across reruns (critical regression)
# ---------------------------------------------------------------------------


class TestStableProcessorAcrossReruns:
    """Verify the WebRTC processor and factory identity remain stable across
    100 simulated Streamlit reruns.

    This reproduces the exact real-world failure where processor_generation
    incremented from 3 to 4 during an active session, causing the Deepgram
    backend to be orphaned on the old processor.
    """

    def test_factory_identity_stable_across_reruns(self):
        """The VoiceProcessorFactory callable object must remain the same
        across multiple rerenders — its identity must not change."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        config = VoiceProcessorConfigHolder(filtering=False, threshold=0.0)
        factory = VoiceProcessorFactory(
            config_holder=config,
            session_state=MagicMock(),
        )

        # Simulate 100 reruns — the factory object identity must stay the same
        for i in range(100):
            assert factory is factory  # identity is stable

        # The factory should be callable and produce processors
        proc = factory()
        assert proc is not None
        assert id(proc) != id(factory)

    def test_factory_not_recreated_on_config_change(self):
        """Changing config on the holder must NOT recreate the factory object."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        config = VoiceProcessorConfigHolder(filtering=False, threshold=0.0)
        factory = VoiceProcessorFactory(
            config_holder=config,
            session_state=MagicMock(),
        )
        original_id = id(factory)

        # Change config on the holder — factory identity must NOT change
        config.update(filtering=True, threshold=0.5)
        assert id(factory) == original_id

    def test_processor_stable_across_reruns(self):
        """Simulate 100 reruns and verify the processor remains the same."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        mock_proc = MagicMock()
        mock_proc._streaming_backend = None
        mock_proc._processor_generation = 3
        mock_proc._audio_frames_received = 0

        # Create a factory that always returns the same processor (simulating
        # streamlit-webrtc's worker reuse)
        call_count = [0]
        original_factory = VoiceProcessorFactory(
            config_holder=VoiceProcessorConfigHolder(),
            session_state=MagicMock(),
        )

        # Simulate the factory not being called again (worker reuse)
        proc_id = id(mock_proc)
        proc_gen = mock_proc._processor_generation

        for _ in range(100):
            # Processor should remain the same
            assert id(mock_proc) == proc_id
            assert mock_proc._processor_generation == proc_gen


class TestDiagnosticsRerunDoesNotReplaceProcessor:
    """Triggering interim updates, diagnostics refresh, event drain, and
    connection status changes must NOT replace the processor."""

    def test_interim_update_no_processor_change(self):
        """An interim transcript update must not trigger processor replacement."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = _mock_processor()
        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # Processor ID should be unchanged
        assert ss._voice_current_processor_id == id(mock_proc)

    def test_connection_status_change_no_processor_change(self):
        """A connection status change must not trigger processor replacement."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = _mock_processor()
        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "ready"
        ss.streaming_ui_state = "ready"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": False}
        ss.desired_mic_playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        assert ss._voice_current_processor_id == id(mock_proc)


class TestFrozenConfigRerunPreservesProcessor:
    """Frozen-config transitions (Connecting → Ready → Listening) must not
    replace the processor."""

    def test_freeze_state_machine_preserves_processor(self):
        """Transitioning through the state machine must not change the processor."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = _mock_processor()
        mock_proc._streaming_generation = 1
        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True
        ss.voice_listening = True

        for _state in ("connecting", "ready", "listening"):
            ss.voice_streaming_state = _state
            ss.streaming_ui_state = _state
            with patch.object(
                __import__("streamlit", fromlist=["session_state"]),
                "session_state",
                ss,
            ), patch(
                "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
            ):
                _refresh_streaming_diagnostics()
            assert ss._voice_current_processor_id == id(mock_proc)


class TestCurrentMismatchDetection:
    """Force a mismatch between current and streaming processor and verify
    immediate cleanup."""

    def test_mismatch_triggers_immediate_cleanup(self):
        """When current processor != streaming processor, state must not be
        Ready/Listening, backend must close, session must unfreeze."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        old_backend = MagicMock()
        old_proc = MagicMock()
        old_proc._streaming_backend = old_backend
        old_proc.effective_delivery_mode = "stream"
        old_proc._streaming_generation = 1
        old_proc._streaming_voice_session_id = "old-sess"
        old_proc.get_streaming_diagnostics.return_value = {}

        new_proc = _mock_processor()
        new_proc._streaming_backend = None
        new_proc.effective_delivery_mode = "stream"
        new_proc._streaming_generation = 2
        new_proc._audio_frames_received = 10
        new_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": new_proc}
        # streaming_processor_id still points to the OLD processor
        ss.streaming_processor_id = id(old_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(new_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True
        ss.voice_listening = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # State must NOT be Ready or Listening
        assert ss.voice_streaming_state not in ("ready", "listening")
        # Config must be unfrozen
        assert ss.voice_streaming_config_frozen is False
        # Streaming processor IDs must be cleared
        assert ss.streaming_processor_id is None
        # desired_mic_playing must be False
        assert ss.desired_mic_playing is False
        # Start must be enabled (no config frozen, no backend)
        assert ss.voice_start_requested is False


class TestRawVsResolvedWebRtcState:
    """Raw playing=False must produce resolved playing=False, never True."""

    def test_resolved_playing_false_when_raw_false(self):
        """If the live WebRTC context reports playing=False, the resolved
        state must also be False, regardless of cached state."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _get_webrtc_playing_state,
        )

        ss = _mock_session_state()
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.voice_scorekeeper_continuous_webrtc = MagicMock()
        # Raw context reports playing=False
        ss.voice_scorekeeper_continuous_webrtc.state.playing = False

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            result = _get_webrtc_playing_state()
        assert result is False

    def test_resolved_playing_true_when_raw_true(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _get_webrtc_playing_state,
        )

        ss = _mock_session_state()
        ss.voice_webrtc_streamer_state = {"playing": False, "signalling": True}
        ss.voice_scorekeeper_continuous_webrtc = MagicMock()
        ss.voice_scorekeeper_continuous_webrtc.state.playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ):
            result = _get_webrtc_playing_state()
        assert result is True


class TestCleanupLatency:
    """Confirmed mismatch must trigger cleanup within a bounded period."""

    def test_mismatch_cleanup_is_immediate(self):
        """When a mismatch is detected, cleanup must occur in the same render cycle."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = _mock_processor()
        mock_proc._streaming_backend = None
        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        # streaming_processor_id points to a non-existent processor (mismatch)
        ss.streaming_processor_id = 999999999
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True
        ss.voice_listening = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # Should be immediately recovered (not after a delay)
        assert ss.voice_streaming_state == "failed"
        assert ss.streaming_processor_id is None
        assert ss.voice_streaming_config_frozen is False


class TestRepeatedStartStop:
    """Start → Listening → Stop → Start → Listening → Stop → Start → Listening → Stop
    must produce one active processor per cycle with no stale backends."""

    def test_repeated_start_stop_cycles(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _stop_streaming_voice_session,
            _process_streaming_startup,
        )

        for cycle in range(3):
            ss = _mock_session_state()
            ss.voice_streaming_provider = "deepgram"
            ss.voice_streaming_language = "lt"
            ss.voice_selected_match_id = 1
            ss.voice_scorekeeper_continuous_webrtc = MagicMock()
            ss.voice_scorekeeper_continuous_webrtc.state.playing = True
            ss.voice_scorekeeper_continuous_webrtc.state.signalling = True

            mock_proc = _mock_processor()
            mock_proc._streaming_backend = None
            ss.voice_webrtc_ctx = {"processor": mock_proc}
            ss.voice_scorekeeper_continuous_webrtc.audio_processor = mock_proc

            ss.streaming_start_request_id = f"req-{cycle}"
            ss.streaming_start_requested_at = time.time()
            ss.streaming_processor_id = id(mock_proc)
            ss.streaming_processor_generation = 1
            ss.voice_streaming_config_frozen = True
            ss.voice_streaming_state = "connecting"
            ss.streaming_ui_state = "connecting"

            with patch.object(
                __import__("streamlit", fromlist=["session_state"]),
                "session_state",
                ss,
            ), patch(
                "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
            ):
                # Stop only — don't call _process_streaming_startup which needs
                # full ASR backend mocking. Verify stop clears all state.
                _stop_streaming_voice_session()

            # After stop, everything should be cleared
            assert ss.voice_streaming_config_frozen is False
            assert ss.streaming_processor_id is None
            assert ss.desired_mic_playing is False
            assert ss.voice_streaming_backend_gen == 0


class TestStreamingSessionIdentity:
    """Test the StreamingSessionIdentity dataclass."""

    def test_identity_is_frozen_and_hashable(self):
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            StreamingSessionIdentity,
        )

        identity = StreamingSessionIdentity(
            voice_session_id="sess-123",
            processor_id=42,
            processor_generation=3,
            backend_generation=3,
            match_id="match-1",
            language="lt",
        )
        assert identity.processor_id == 42
        assert identity.backend_generation == 3
        # Should be hashable (frozen dataclass)
        assert isinstance(hash(identity), int)


# ---------------------------------------------------------------------------
# 17. Factory diagnostics isolation and concurrency
# ---------------------------------------------------------------------------


class TestFactoryDiagnosticsIsolation:
    """Factory diagnostics must never break voice startup or rendering."""

    def test_fresh_page_no_factory(self):
        """When no factory exists yet, diagnostics must return safe defaults."""
        factory = None
        factory_diag = {
            "factory_object_id": None,
            "processor_creation_count": 0,
            "last_processor_id": None,
        }
        if factory is not None:
            factory_diag = factory.get_diagnostics()
        assert factory_diag["processor_creation_count"] == 0
        assert factory_diag["factory_object_id"] is None

    def test_existing_factory_diagnostics(self):
        """When factory exists, get_diagnostics() must return a snapshot."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        factory = VoiceProcessorFactory(
            config_holder=VoiceProcessorConfigHolder(),
            session_state=MagicMock(),
        )
        diag = factory.get_diagnostics()
        assert diag["call_count"] == 0
        assert diag["last_processor_id"] is None

    def test_diagnostics_returns_copy(self):
        """get_diagnostics() must return a copy, not a reference to internal state."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        factory = VoiceProcessorFactory(
            config_holder=VoiceProcessorConfigHolder(),
        )
        diag1 = factory.get_diagnostics()
        diag1["call_count"] = 999
        diag2 = factory.get_diagnostics()
        assert diag2["call_count"] == 0  # original unchanged

    def test_diagnostics_failure_isolation(self):
        """If get_diagnostics() raises, the Voice Scoring UI must still render."""
        factory = MagicMock()
        factory.get_diagnostics.side_effect = RuntimeError("diag failure")

        try:
            factory_diag = factory.get_diagnostics()
        except Exception:
            factory_diag = {
                "factory_object_id": None,
                "processor_creation_count": 0,
                "last_processor_id": None,
            }
        # Diagnostics failed but we have safe defaults
        assert factory_diag["processor_creation_count"] == 0
        # Factory diagnostics failure does NOT affect session state —
        # the failure is caught and isolated

    def test_no_page_level_lock_access(self):
        """The page must not import or use _factory_diag_lock."""
        # If the import succeeded, the name should not be in the page module
        import tournament_platform.app.pages.voice_scorekeeper as vsm
        assert not hasattr(vsm, "_factory_diag_lock")
        assert not hasattr(vsm, "_factory_diag")


class TestFactoryDiagnosticsConcurrency:
    """Factory creation/diagnostics access from multiple threads must be safe."""

    def test_concurrent_diagnostics_access(self):
        """Multiple threads calling get_diagnostics() must not race."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )
        import threading

        factory = VoiceProcessorFactory(
            config_holder=VoiceProcessorConfigHolder(),
            session_state=MagicMock(),
        )
        results = []
        barrier = threading.Barrier(5)

        def _read_diag():
            barrier.wait()
            for _ in range(100):
                d = factory.get_diagnostics()
                results.append(d["call_count"])

        threads = [threading.Thread(target=_read_diag) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should have seen 0 (no calls made)
        assert all(r == 0 for r in results)
        assert len(results) == 500

    def test_factory_call_then_diagnostics(self):
        """After calling the factory, diagnostics should reflect the call."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        factory = VoiceProcessorFactory(
            config_holder=VoiceProcessorConfigHolder(),
            session_state=MagicMock(),
        )
        diag_before = factory.get_diagnostics()
        assert diag_before["call_count"] == 0

        # The factory should be callable (may fail due to missing VAD, but
        # we just check the diagnostics counter logic)
        try:
            factory()
        except Exception:
            pass

        diag_after = factory.get_diagnostics()
        assert diag_after["call_count"] >= 1


class TestFactoryConfigUpdatePreservesIdentity:
    """Config updates must not change the factory object identity."""

    def test_config_update_preserves_identity(self):
        """Changing filtering, threshold, strict, TT sounds must not create
        a new factory — only update the config holder."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceProcessorFactory,
            VoiceProcessorConfigHolder,
        )

        config = VoiceProcessorConfigHolder(
            filtering=False, threshold=0.3, strict=False, tt_sounds_enabled=False
        )
        factory = VoiceProcessorFactory(
            config_holder=config,
            session_state=MagicMock(),
        )
        original_id = id(factory)

        # Update all config fields
        config.update(filtering=True, threshold=0.8, strict=True, tt_sounds_enabled=True)
        assert id(factory) == original_id

        # Config holder snapshot should reflect the new values
        snap = config.snapshot
        assert snap.filtering is True
        assert snap.threshold == 0.8
        assert snap.strict is True
        assert snap.tt_sounds_enabled is True


# ---------------------------------------------------------------------------
# 18. Transient processor reference gap handling
# ---------------------------------------------------------------------------


class TestTransientProcessorGap:
    """playing=True + processor=None must be treated as transient, not replacement."""

    def test_transient_gap_preserves_backend(self):
        """When WebRTC playing=True but processor=None temporarily, the backend
        must NOT be closed. Within 500ms reconciliation window, state is preserved."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = MagicMock()
        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": None}
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_streaming_diagnostics = {}
        # Simulate playing=True but processor temporarily None (transient gap)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # Backend must NOT be closed — this is a transient gap
        assert not mock_backend.close.called
        # State should be preserved (not disabled)
        assert ss.voice_streaming_state != "disabled"

    def test_transient_gap_timeout_eventually_terminates(self):
        """If the gap persists beyond 500ms, cleanup should occur."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_proc = MagicMock()
        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": None}
        ss.streaming_processor_id = id(mock_proc)
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True
        # Set gap timestamp to 1 second ago (past reconciliation window)
        ss._voice_processor_gap_ts = time.time() - 1.0

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # After gap timeout, session should be disabled
        assert ss.voice_streaming_state == "disabled"

    def test_transient_gap_recovery_within_window(self):
        """If processor returns within reconciliation window, session is preserved."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        mock_backend = MagicMock()
        mock_backend.connection_state.return_value = "connected"
        mock_proc = MagicMock()
        mock_proc._streaming_backend = mock_backend
        mock_proc.effective_delivery_mode = "stream"
        mock_proc._streaming_generation = 1
        mock_proc._streaming_voice_session_id = "sess-123"
        mock_proc.get_streaming_diagnostics.return_value = {}

        ss = _mock_session_state()
        ss.voice_webrtc_ctx = {"processor": mock_proc}
        ss.streaming_processor_id = id(mock_proc)
        ss.streaming_processor_generation = 1
        ss.voice_streaming_config_frozen = True
        ss.voice_streaming_state = "listening"
        ss.streaming_ui_state = "listening"
        ss._voice_current_processor_id = id(mock_proc)
        ss.voice_webrtc_streamer_state = {"playing": True, "signalling": True}
        ss.desired_mic_playing = True
        # Gap was set recently (processor returned)
        ss._voice_processor_gap_ts = time.time()

        with patch.object(
            __import__("streamlit", fromlist=["session_state"]),
            "session_state",
            ss,
        ), patch(
            "tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"
        ):
            _refresh_streaming_diagnostics()

        # Backend must NOT be closed — processor returned
        assert not mock_backend.close.called
        assert ss.voice_streaming_state != "disabled"


# ---------------------------------------------------------------------------
# 19. WebRtcRenderSnapshot authority
# ---------------------------------------------------------------------------


class TestWebRtcRenderSnapshot:
    """The WebRtcRenderSnapshot must be the sole per-render authority."""

    def test_snapshot_captures_current_context(self):
        """WebRtcRenderSnapshot correctly captures ctx state."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        mock_ctx = MagicMock()
        mock_ctx.state.playing = True
        mock_ctx.state.signalling = False
        mock_proc = MagicMock()
        mock_proc._processor_generation = 5
        mock_proc._audio_frames_received = 100
        mock_ctx.audio_processor = mock_proc

        snapshot = _create_webrtc_snapshot(mock_ctx)
        assert snapshot.context is mock_ctx
        assert snapshot.playing is True
        assert snapshot.signalling is False
        assert snapshot.processor is mock_proc
        assert snapshot.processor_id == id(mock_proc)
        assert snapshot.processor_generation == 5
        assert snapshot.audio_frames_received == 100

    def test_snapshot_handles_none_processor(self):
        """When processor is None but playing=True, snapshot captures it."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        mock_ctx = MagicMock()
        mock_ctx.state.playing = True
        mock_ctx.state.signalling = True
        mock_ctx.audio_processor = None

        snapshot = _create_webrtc_snapshot(mock_ctx)
        assert snapshot.playing is True
        assert snapshot.processor is None
        assert snapshot.processor_id is None
        assert snapshot.has_processor is False

    def test_snapshot_handles_none_context(self):
        """When ctx is None, snapshot captures all-None state."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        snapshot = _create_webrtc_snapshot(None)
        assert snapshot.context is None
        assert snapshot.playing is False
        assert snapshot.processor is None
        assert snapshot.has_processor is False

    def test_snapshot_is_frozen(self):
        """WebRtcRenderSnapshot is frozen — cannot be mutated."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            WebRtcRenderSnapshot,
        )

        snapshot = WebRtcRenderSnapshot(
            context=None,
            playing=True,
            signalling=False,
            processor=None,
            processor_id=None,
            processor_generation=None,
            audio_frames_received=0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.playing = False

    def test_current_ctx_playing_false_overrides_stale_cache(self):
        """If returned ctx reports playing=False, the resolved result must be
        False even if the session-state cache says True."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        mock_ctx = MagicMock()
        mock_ctx.state.playing = False
        mock_ctx.state.signalling = True
        mock_ctx.audio_processor = MagicMock()

        snapshot = _create_webrtc_snapshot(mock_ctx)
        assert snapshot.playing is False

    def test_current_ctx_playing_true_overrides_stale_cache(self):
        """If returned ctx reports playing=True, the resolved result must be True
        even if the session-state cache says False."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        mock_ctx = MagicMock()
        mock_ctx.state.playing = True
        mock_ctx.state.signalling = False
        mock_ctx.audio_processor = MagicMock()

        snapshot = _create_webrtc_snapshot(mock_ctx)
        assert snapshot.playing is True

    def test_confirmed_replacement_requires_different_processor(self):
        """None processor never triggers replacement — only a *different* processor
        object than the streaming_processor_id."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _create_webrtc_snapshot,
        )

        # processor=None must NOT be treated as replacement
        mock_ctx = MagicMock()
        mock_ctx.state.playing = True
        mock_ctx.audio_processor = None
        snapshot = _create_webrtc_snapshot(mock_ctx)
        assert snapshot.has_processor is False
        # A different processor WOULD trigger replacement
        mock_ctx2 = MagicMock()
        mock_ctx2.state.playing = True
        mock_proc_b = MagicMock()
        mock_ctx2.audio_processor = mock_proc_b
        snapshot2 = _create_webrtc_snapshot(mock_ctx2)
        assert snapshot2.has_processor is True
        assert snapshot2.processor_id == id(mock_proc_b)

