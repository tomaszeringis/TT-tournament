"""Reliability, state synchronization, and observability tests for Deepgram backend.

Covers:
- Backend lifecycle tests
- State synchronization tests
- Metrics tests
- Audit tests
- Audio-format tests
- Restart test
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tournament_platform.app.services.asr_backends.deepgram_backend import (
    DeepgramASRBackend,
    _AuthError,
    _ConnectionState,
    sanitize_deepgram_error,
    SafeProviderError,
)


# ---------------------------------------------------------------------------
# Mock SDK helpers
# ---------------------------------------------------------------------------

class _MockAlternative:
    def __init__(self, transcript: str = "", confidence: float = 0.95):
        self.transcript = transcript
        self.confidence = confidence


class _MockChannel:
    def __init__(self, alternatives=None):
        self.alternatives = alternatives or [_MockAlternative()]


class _MockResultsMessage:
    type = "Results"

    def __init__(self, transcript: str = "point red", is_final=None, speech_final=None):
        self.channel = _MockChannel([_MockAlternative(transcript)])
        self.is_final = is_final
        self.speech_final = speech_final
        self.duration = 0.1
        self.start = 0.0
        self.channel_index = [0]


class _MockUtteranceEnd:
    type = "UtteranceEnd"
    channel = [0]
    last_word_end = 1.0


class _MockConnection:
    def __init__(self, event_log=None):
        self.send_media_calls = []
        self.send_keep_alive_calls = []
        self.send_finalize_calls = []
        self.send_close_stream_calls = []
        self._on_handlers = {}
        self._event_log = event_log or []
        self._closed = False

    def on(self, event_type, callback):
        self._on_handlers[event_type] = callback

    def send_media(self, message: bytes) -> None:
        if self._closed:
            raise RuntimeError("Connection closed")
        self.send_media_calls.append(message)

    def send_keep_alive(self, message=None) -> None:
        self.send_keep_alive_calls.append(message)

    def send_finalize(self, message=None) -> None:
        self.send_finalize_calls.append(message)

    def send_close_stream(self, message=None) -> None:
        self._closed = True
        self.send_close_stream_calls.append(message)

    def start_listening(self) -> None:
        for event_type, message in self._event_log:
            handler = self._on_handlers.get(event_type)
            if handler is not None:
                handler(message)

    @property
    def closed(self) -> bool:
        return self._closed


class _MockApiError(Exception):
    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(body)


class _MockV1Client:
    def __init__(self, connection_factory=None, connect_error=None):
        self._connection_factory = connection_factory
        self._connect_error = connect_error

    def connect(self, **kwargs):
        if self._connect_error is not None:
            raise self._connect_error
        return _MockContextManager(
            connection_factory=self._connection_factory,
            connect_kwargs=kwargs,
        )


class _MockDeepgramClient:
    def __init__(self, api_key=None, **kwargs):
        self._api_key = api_key
        self._v1_client = None

    @property
    def listen(self):
        return _MockListen(self._v1_client)

    def set_v1_client(self, v1_client):
        self._v1_client = v1_client


class _MockListen:
    def __init__(self, v1_client):
        self.v1 = v1_client


class _MockContextManager:
    def __init__(self, connection_factory=None, connect_kwargs=None):
        self._connection_factory = connection_factory
        self._connect_kwargs = connect_kwargs
        self.connection = None

    def __enter__(self):
        if self._connection_factory is not None:
            self.connection = self._connection_factory(**self._connect_kwargs)
        else:
            self.connection = _MockConnection()
        return self.connection

    def __exit__(self, *args):
        if self.connection is not None:
            self.connection.send_close_stream()


class _EventType:
    OPEN = "open"
    MESSAGE = "message"
    ERROR = "error"
    CLOSE = "close"


@patch.dict("sys.modules", {
    "deepgram": MagicMock(),
    "deepgram.core.api_error": MagicMock(),
    "deepgram.core.events": MagicMock(),
})
def _patch_deepgram_modules():
    pass


# ---------------------------------------------------------------------------
# Backend lifecycle tests
# ---------------------------------------------------------------------------

class TestBackendLifecycle:
    def test_start_session_enters_starting_then_connecting(self):
        backend = DeepgramASRBackend(api_key="test-key")
        assert backend.connection_state() == "disconnected"

        backend.start_session(language="lt")
        time.sleep(0.05)
        assert backend.connection_state() in ("starting", "connecting", "connected", "failed")

    def test_connection_open_event_set_on_connect(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        assert backend.wait_until_ready(timeout_seconds=0.1) is True

    def test_connection_open_event_cleared_on_failure(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        backend._handle_error(RuntimeError("ws error"))
        assert backend._connection_open_event.is_set() is False

    def test_auth_exception_sets_failed_and_category(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._handle_error(_AuthError("401 Unauthorized"))
        assert backend.connection_state() == "failed"
        assert backend._last_error_category == "authentication_failed"

    def test_no_open_before_timeout_sets_failed(self):
        backend = DeepgramASRBackend(api_key="test-key", connect_timeout_seconds=0.05)
        backend._set_connection_state(_ConnectionState.CONNECTING)
        time.sleep(0.1)
        assert backend.connection_state() == "connecting"

    def test_receive_task_crash_sets_failed(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        backend._handle_error(RuntimeError("receive failure"))
        assert backend.connection_state() == "failed"

    def test_send_task_crash_does_not_crash_backend(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        mock_conn = MagicMock()
        mock_conn.send_media.side_effect = RuntimeError("send failure")
        backend._connection = mock_conn
        backend._audio_frame_queue.put_nowait(b"\x00" * 160)
        backend._stop_event.clear()
        thread = threading.Thread(target=backend._send_loop, daemon=True)
        thread.start()
        time.sleep(0.3)
        backend._stop_event.set()
        thread.join(timeout=2.0)
        assert backend.connection_state() == "connected"

    def test_explicit_close_sets_stopped_not_failed(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend.close()
        assert backend.connection_state() == "stopped"


# ---------------------------------------------------------------------------
# State synchronization tests
# ---------------------------------------------------------------------------

class TestStateSynchronization:
    def test_backend_connecting_ui_connecting(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        assert backend.connection_state() == "connecting"

    def test_backend_failed_ui_failed_with_same_reason(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.FAILED)
        backend._last_error_category = "connection_timeout"
        backend._last_error_message_safe = "Connection timed out after 10s."
        info = backend.get_connection_info()
        assert info["last_error_category"] == "connection_timeout"
        assert info["last_error_message_safe"] == "Connection timed out after 10s."

    def test_old_generation_failed_ignored(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._generation = 1
        backend._set_connection_state(_ConnectionState.FAILED)
        backend._session_id = "old-session"
        backend.start_session(language="lt")
        time.sleep(0.05)
        assert backend._generation == 2
        assert backend._session_id != "old-session"


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_audio_queued_before_connected_does_not_increment_sent(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        assert backend.enqueue_audio(b"\x00" * 160) is False
        m = backend.metrics()
        assert m.audio_bytes_sent == 0

    def test_successful_send_media_increments_counters(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        mock_conn = MagicMock()
        backend._connection = mock_conn
        backend._stop_event.clear()
        frame = b"\x00" * 320
        backend._audio_frame_queue.put_nowait(frame)
        thread = threading.Thread(target=backend._send_loop, daemon=True)
        thread.start()
        time.sleep(0.3)
        backend._stop_event.set()
        thread.join(timeout=2.0)
        assert mock_conn.send_media.call_count == 1
        m = backend.metrics()
        assert m.audio_bytes_sent == 320

    def test_send_media_raises_does_not_increment_sent(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()
        mock_conn = MagicMock()
        mock_conn.send_media.side_effect = RuntimeError("send failed")
        backend._connection = mock_conn
        backend._stop_event.clear()
        frame = b"\x00" * 320
        backend._audio_frame_queue.put_nowait(frame)
        thread = threading.Thread(target=backend._send_loop, daemon=True)
        thread.start()
        time.sleep(0.3)
        backend._stop_event.set()
        thread.join(timeout=2.0)
        assert mock_conn.send_media.call_count == 1
        m = backend.metrics()
        assert m.audio_bytes_sent == 0


# ---------------------------------------------------------------------------
# Audit tests
# ---------------------------------------------------------------------------

class TestAuditEvents:
    def test_connection_info_excludes_secrets(self):
        backend = DeepgramASRBackend(api_key="super-secret-key-123")
        info = backend.get_connection_info()
        assert "super-secret-key-123" not in str(info)
        assert info["credentials_configured"] is True

    def test_sanitize_error_removes_api_key(self):
        error = sanitize_deepgram_error(
            RuntimeError("Request failed with api_key=super-secret-key-123")
        )
        assert "super-secret-key-123" not in error.message_safe
        assert error.category == "unknown_provider_error"

    def test_sanitize_auth_error_has_safe_category(self):
        exc = _AuthError("401 Unauthorized")
        error = sanitize_deepgram_error(exc)
        assert error.category == "authentication_failed"
        assert error.code == "401"


# ---------------------------------------------------------------------------
# Audio-format tests
# ---------------------------------------------------------------------------

class TestAudioFormat:
    def test_48khz_stereo_converts_to_mono(self):
        """Synthetic 48 kHz stereo PCM should be converted to mono."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            _audio_frame_to_mono_float32,
            _pcm_float32_to_int16,
        )

        sample_rate = 48000
        channels = 2
        samples = 480
        duration_s = samples / sample_rate

        t = np.linspace(0, duration_s, samples * channels)
        arr = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        arr = arr.reshape(channels, -1)

        mono = _audio_frame_to_mono_float32(arr)
        assert len(mono) == samples

        pcm = _pcm_float32_to_int16(mono)
        assert len(pcm) == samples * 2

    def test_full_pipeline_48khz_stereo_to_16khz_mono(self):
        """Full pipeline should convert 48 kHz stereo to 16 kHz mono int16."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
            VoiceRuntimeMode,
        )
        from tournament_platform.app.services.asr_backends.calibration_policy import (
            ASRCapabilities,
            AudioDeliveryPolicy,
        )

        class _MockBackend:
            backend_name = "mock"
            _connection_state = "connected"
            _sample_rate = 16000
            _channels = 1

            def capabilities(self):
                return ASRCapabilities(
                    supports_streaming=True,
                    requires_speaker_calibration=False,
                    supports_local_vad=False,
                    supports_optional_audio_health_check=True,
                )

            def delivery_policy(self):
                return AudioDeliveryPolicy(
                    mode="continuous",
                    require_vad_calibration=False,
                    allow_degraded_fallback=True,
                )

            def connection_state(self):
                return "connected"

            def enqueue_audio(self, pcm_bytes):
                self._last_pcm = pcm_bytes
                return True

            def health_status(self):
                return "connected"

            def is_available(self):
                return True

        backend = _MockBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "test-session"
        proc.set_streaming_backend(
            backend,
            voice_session_id="test-session",
            match_id=1,
            language="lt",
            sample_rate=16000,
            channels=1,
        )

        sample_rate = 48000
        channels = 2
        samples = 480
        duration_s = samples / sample_rate
        t = np.linspace(0, duration_s, samples * channels)
        arr = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        arr = arr.reshape(-1, channels)

        frame = MagicMock()
        frame.format.name = "flt"
        frame.sample_rate = sample_rate
        frame.channels = channels
        frame.pts = time.time()
        frame.planes = [MagicMock()]
        frame.planes[0].update = lambda data: None
        frame.__len__ = lambda self: samples * channels * 4

        def _to_ndarray():
            return arr

        frame.to_ndarray = _to_ndarray
        proc._ingest_frame(frame)

        assert hasattr(backend, "_last_pcm")
        pcm = backend._last_pcm
        expected_samples = int(samples * 16000 / sample_rate)
        assert len(pcm) == expected_samples * 2

        expected_duration_ms = duration_s * 1000
        actual_duration_ms = len(pcm) / (16000 * 1 * 2) * 1000.0
        assert abs(actual_duration_ms - expected_duration_ms) < expected_duration_ms * 0.1

    def test_no_wav_header_in_output(self):
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            _audio_frame_to_mono_float32,
            _pcm_float32_to_int16,
        )
        arr = np.random.randn(480, 2).astype(np.float32)
        mono = _audio_frame_to_mono_float32(arr)
        pcm = _pcm_float32_to_int16(mono)
        assert pcm[:4] != b"RIFF"


# ---------------------------------------------------------------------------
# Restart test
# ---------------------------------------------------------------------------

class TestRestart:
    def test_failed_session_can_restart(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.FAILED)
        backend._session_id = "failed-session"
        backend._generation = 1

        backend.start_session(language="lt")
        time.sleep(0.05)
        assert backend._generation == 2
        assert backend._session_id != "failed-session"
        assert backend.connection_state() != "failed"


# ---------------------------------------------------------------------------
# Connection timeout test
# ---------------------------------------------------------------------------

class TestConnectionTimeout:
    def test_timeout_category_assigned_on_error(self):
        backend = DeepgramASRBackend(api_key="test-key", connect_timeout_seconds=0.05)
        exc = TimeoutError("Deepgram connection timed out after 0.05s")
        safe_err = sanitize_deepgram_error(exc, connect_timeout_seconds=0.05)
        assert safe_err.category == "connection_timeout"
        assert "0.05" in safe_err.message_safe

    def test_connection_failed_at_set_on_error(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        backend._connection_failed_at = time.monotonic()
        info = backend.get_connection_info()
        assert info["connection_failed_at"] is not None
        assert info["last_error_category"] is None
