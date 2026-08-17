"""
Regression tests for one-click automatic microphone and Deepgram startup.

Covers:
- Start button behavior without processor
- Two-phase startup (microphone then Deepgram)
- Idempotency across reruns
- Stop lifecycle
- Browser-side microphone termination
- Processor replacement
- Audio routing during startup
- Language propagation
"""
from __future__ import annotations

import queue
import time
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import streamlit as st

from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
    VoiceRuntimeMode,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class _MockStreamingBackend:
    backend_name = "deepgram"

    def __init__(self, available=True, connection_state="disconnected"):
        self._available = available
        self._connection_state = connection_state
        self._language = None
        self._session_id = None
        self._started = False

    def is_available(self):
        return self._available

    def capabilities(self):
        from tournament_platform.app.services.asr_backends.calibration_policy import ASRCapabilities
        return ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=False,
            supports_optional_audio_health_check=True,
        )

    def delivery_policy(self):
        from tournament_platform.app.services.asr_backends.calibration_policy import AudioDeliveryPolicy
        return AudioDeliveryPolicy(
            mode="continuous",
            require_vad_calibration=False,
            allow_degraded_fallback=True,
        )

    def start_session(self, **kwargs):
        self._started = True
        self._language = kwargs.get("language")
        self._session_id = f"dg-{uuid.uuid4().hex[:12]}"
        self._connection_state = "connecting"

    def connection_state(self):
        return self._connection_state

    def health_status(self):
        return self._connection_state

    def get_connection_info(self):
        return {
            "connection_state": self._connection_state,
            "last_error_category": None,
            "last_error_message_safe": None,
        }

    def close(self):
        self._connection_state = "stopped"
        self._started = False


class _MockWebRTCContext:
    def __init__(self, processor=None, playing=False):
        self.audio_processor = processor
        self.state = _MockState(playing)


class _MockState:
    def __init__(self, playing=False):
        self.playing = playing
        self.signalling = playing


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStartButtonBehavior:
    """Start button should be enabled without an audio processor."""

    def test_start_enabled_without_processor(self):
        """Start must not require an existing WebRTC processor."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _start_streaming_voice_session,
        )

        # Simulate no processor, Deepgram available
        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            mock_create.return_value = MagicMock(
                available=True,
                backend=_MockStreamingBackend(),
                safe_message="",
                reason_code=None,
            )
            # This should not raise
            _start_streaming_voice_session()

            assert st.session_state.voice_start_requested is True
            assert st.session_state.desired_mic_playing is True
            assert st.session_state.streaming_ui_state == "starting_microphone"


class TestTwoPhaseStartup:
    """Deepgram is only created after microphone and processor are ready."""

    def test_deepgram_not_created_before_mic_playing(self):
        """Deepgram backend should not be created while microphone is not playing."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time()
        st.session_state.voice_webrtc_streamer_state = {"playing": False}

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            _process_streaming_startup()
            mock_create.assert_not_called()

    def test_deepgram_not_created_before_processor_exists(self):
        """Deepgram backend should not be created while processor is missing."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time()
        st.session_state.voice_webrtc_streamer_state = {"playing": True}
        st.session_state.voice_webrtc_ctx = {}

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            _process_streaming_startup()
            mock_create.assert_not_called()
            assert st.session_state.streaming_ui_state == "waiting_for_processor"

    def test_deepgram_created_after_mic_and_processor_ready(self):
        """Deepgram backend is created only after mic playing and processor exists."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        proc = VoiceAudioProcessor()
        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time()
        st.session_state.voice_webrtc_streamer_state = {"playing": True}
        st.session_state.voice_webrtc_ctx = {"processor": proc}
        st.session_state.voice_streaming_provider = "deepgram"
        st.session_state.voice_streaming_language = "lt"
        st.session_state.voice_selected_match_id = 1

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            mock_create.return_value = MagicMock(
                available=True,
                backend=_MockStreamingBackend(),
                safe_message="",
                reason_code=None,
            )
            _process_streaming_startup()
            mock_create.assert_called_once_with(backend_name="deepgram")


class TestStartupIdempotency:
    """Reruns during startup must not duplicate backend creation."""

    def test_rerun_during_starting_microphone(self):
        """Repeated calls during starting_microphone should not create backend."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time()
        st.session_state.voice_webrtc_streamer_state = {"playing": False}

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            _process_streaming_startup()
            _process_streaming_startup()
            mock_create.assert_not_called()

    def test_deepgram_starts_exactly_once_after_readiness(self):
        """After mic and processor are ready, backend starts exactly once."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
        )

        proc = VoiceAudioProcessor()
        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time()
        st.session_state.voice_webrtc_streamer_state = {"playing": True}
        st.session_state.voice_webrtc_ctx = {"processor": proc}
        st.session_state.voice_streaming_provider = "deepgram"
        st.session_state.voice_streaming_language = "lt"
        st.session_state.voice_selected_match_id = 1

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            mock_create.return_value = MagicMock(
                available=True,
                backend=_MockStreamingBackend(),
                safe_message="",
                reason_code=None,
            )
            _process_streaming_startup()
            _process_streaming_startup()
            assert mock_create.call_count == 1


class TestMicrophoneTimeout:
    """Microphone start timeout should produce Failed and allow retry."""

    def test_mic_start_timeout_produces_failed(self):
        """If microphone does not become active, state should be Failed."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _process_streaming_startup,
            VOICE_MIC_START_TIMEOUT_SECONDS,
        )

        st.session_state.voice_start_requested = True
        st.session_state.desired_mic_playing = True
        st.session_state.streaming_ui_state = "starting_microphone"
        st.session_state.streaming_start_request_id = str(uuid.uuid4())
        st.session_state.streaming_start_microphone_confirmed_at = None
        st.session_state.streaming_start_backend_attached_at = None
        st.session_state.streaming_start_completed_at = None
        st.session_state.streaming_start_requested_at = time.time() - (VOICE_MIC_START_TIMEOUT_SECONDS + 1)
        st.session_state.voice_webrtc_streamer_state = {"playing": False}

        with patch.object(ASRBackendFactory, "create_streaming") as mock_create:
            _process_streaming_startup()
            mock_create.assert_not_called()
            assert st.session_state.streaming_ui_state == "failed"
            assert st.session_state.voice_streaming_state == "failed"
            assert st.session_state.voice_start_requested is False
            assert st.session_state.desired_mic_playing is False


class TestStopLifecycle:
    """Stop must close backend and reset state."""

    def test_stop_closes_backend_and_clears_state(self):
        """Stop should clear backend, reset state, and allow retry."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _stop_streaming_voice_session,
        )

        proc = VoiceAudioProcessor()
        backend = _MockStreamingBackend()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        st.session_state.voice_webrtc_ctx = {"processor": proc}
        st.session_state.voice_streaming_config_frozen = True
        st.session_state.voice_streaming_state = "ready"
        st.session_state.voice_listening = True
        st.session_state.voice_events_enabled = True

        _stop_streaming_voice_session()

        assert backend._connection_state == "stopped"
        assert proc._streaming_backend is None
        assert st.session_state.voice_streaming_config_frozen is False
        assert st.session_state.voice_streaming_state == "disabled"
        assert st.session_state.streaming_ui_state == "disabled"
        assert st.session_state.desired_mic_playing is False
        assert st.session_state.voice_listening is False


class TestBrowserMicTermination:
    """Browser-side microphone stop should close Deepgram."""

    def test_browser_mic_stop_closes_deepgram(self):
        """When WebRTC stops playing, the attached backend should be closed."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _get_voice_webrtc_processor,
        )

        proc = VoiceAudioProcessor()
        backend = _MockStreamingBackend()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        st.session_state.voice_webrtc_ctx = {"processor": proc}
        st.session_state.voice_continuous_requested = True
        st.session_state.voice_events_enabled = True
        st.session_state.voice_listening = True
        st.session_state._voice_prev_webrtc_playing = True
        st.session_state.voice_webrtc_streamer_state = {"playing": False}

        # Simulate the browser-side stop handler
        _current_playing = False
        _prev_playing = True
        if not _current_playing and _prev_playing:
            _mic_proc = _get_voice_webrtc_processor(st.session_state.get("voice_webrtc_ctx"))
            if _mic_proc is not None and hasattr(_mic_proc, "clear_streaming_backend"):
                try:
                    _mic_proc.clear_streaming_backend()
                except Exception:
                    pass

        assert backend._connection_state == "stopped"
        assert proc._streaming_backend is None


class TestProcessorReplacement:
    """Processor replacement should invalidate old backend ownership."""

    def test_processor_replacement_during_disabled(self):
        """Replacement while disabled should keep UI disabled and Start enabled."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        proc_a = VoiceAudioProcessor()
        st.session_state.voice_webrtc_ctx = {"processor": proc_a}
        st.session_state.voice_streaming_config_frozen = False
        st.session_state.voice_streaming_state = "disabled"
        st.session_state._voice_current_processor_id = id(proc_a)

        proc_b = VoiceAudioProcessor()
        st.session_state.voice_webrtc_ctx = {"processor": proc_b}

        _refresh_streaming_diagnostics()

        assert st.session_state.voice_streaming_state == "disabled"
        assert st.session_state.voice_streaming_config_frozen is False

    def test_processor_replacement_during_active_session(self):
        """Replacement during active session should reset UI state."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            _refresh_streaming_diagnostics,
        )

        proc_a = VoiceAudioProcessor()
        backend = _MockStreamingBackend()
        backend._connection_state = "connected"
        proc_a.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        st.session_state.voice_webrtc_ctx = {"processor": proc_a}
        st.session_state.voice_streaming_config_frozen = True
        st.session_state.voice_streaming_state = "ready"
        st.session_state._voice_current_processor_id = id(proc_a)

        proc_b = VoiceAudioProcessor()
        st.session_state.voice_webrtc_ctx = {"processor": proc_b}

        _refresh_streaming_diagnostics()

        # Old backend may not be closed if processor reference is lost,
        # but UI state must be reset
        assert st.session_state.voice_streaming_config_frozen is False
        assert st.session_state.voice_streaming_state == "disabled"


class TestAudioRoutingDuringStartup:
    """Audio delivery mode must reflect actual backend attachment."""

    def test_effective_delivery_mode_batch_without_backend(self):
        """Without a backend, effective_delivery_mode must be batch."""
        proc = VoiceAudioProcessor()
        assert proc.effective_delivery_mode == "batch"

    def test_effective_delivery_mode_stream_with_backend(self):
        """With an active backend, effective_delivery_mode must be stream."""
        proc = VoiceAudioProcessor()
        backend = _MockStreamingBackend()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        assert proc.effective_delivery_mode == "stream"

    def test_get_streaming_diagnostics_reconciles_delivery_mode(self):
        """Diagnostics must reflect actual delivery mode from processor."""
        proc = VoiceAudioProcessor()
        diag = proc.get_streaming_diagnostics()
        assert diag["audio_delivery_mode"] == "batch"

        backend = _MockStreamingBackend()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        diag = proc.get_streaming_diagnostics()
        assert diag["audio_delivery_mode"] == "stream"


class TestLanguagePropagation:
    """Lithuanian must remain 'lt' from UI through Deepgram."""

    def test_language_lt_propagates_to_backend(self):
        """Language 'lt' should reach the Deepgram backend."""
        backend = _MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="lt"
        )
        assert backend._language == "lt"

    def test_language_en_propagates_to_backend(self):
        """Language 'en' should reach the Deepgram backend."""
        backend = _MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc.set_streaming_backend(
            backend, voice_session_id="sess-1", match_id=1, language="en"
        )
        assert backend._language == "en"
