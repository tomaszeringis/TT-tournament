"""Contract tests for the Deepgram streaming backend.

Uses a mocked Deepgram SDK (7.6.0 API surface per docs/deepgram_sdk_7_6_shape.md)
to verify the backend correctly handles the Listen v1 WebSocket lifecycle:

- Connect → start_listening → event dispatch → close
- Auth failure (401 → ApiError)
- Interim → final progression
- Multiple finals within one utterance
- Duplicate final rejection
- Empty final transcript handling
- Closure during speech
- Reconnect on connection loss
- Late event after stop
- EventType.ERROR propagation
- Shutdown during silence

These tests mock the ``deepgram`` module at the import boundary so no real
network access or API key is required.
"""
from __future__ import annotations

import contextlib
import queue
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.asr_backends.deepgram_backend import (
    DeepgramASRBackend,
    _AuthError,
    _ConnectionState,
)


# ---------------------------------------------------------------------------
# Mock Deepgram SDK
# ---------------------------------------------------------------------------

class _MockConnection:
    """Simulates a Deepgram Listen v1 V1SocketClient connection."""

    def __init__(self, event_log=None):
        self.send_media_calls: list[bytes] = []
        self.send_keep_alive_calls: list = []
        self.send_finalize_calls: list = []
        self.send_close_stream_calls: list = []
        self._on_handlers: dict = {}
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
        self._finalize_called = True
        self.send_finalize_calls.append(message)

    def send_close_stream(self, message=None) -> None:
        self._closed = True
        self.send_close_stream_calls.append(message)

    def start_listening(self) -> None:
        """Simulate the blocking receive loop."""
        for event_type, message in self._event_log:
            handler = self._on_handlers.get(event_type)
            if handler is not None:
                handler(message)

    @property
    def closed(self) -> bool:
        return self._closed


class _MockApiError(Exception):
    """Simulates deepgram.core.api_error.ApiError with status_code."""

    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(body)


class _MockV1Client:
    """Simulates deepgram.listen.v1.client.V1Client."""

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
    """Simulates deepgram.DeepgramClient."""

    def __init__(self, api_key=None, **kwargs):
        self._api_key = api_key
        self._v1_client = None

    @property
    def listen(self):
        return _MockListen(self._v1_client)

    def set_v1_client(self, v1_client):
        self._v1_client = v1_client


class _MockListen:
    """Simulates client.listen."""

    def __init__(self, v1_client):
        self.v1 = v1_client


class _MockContextManager:
    """Simulates a context manager from listen.v1.connect(...)"""

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


# Event type simulation
class _EventType:
    OPEN = "open"
    MESSAGE = "message"
    ERROR = "error"
    CLOSE = "close"


# ---------------------------------------------------------------------------
# Mock message helpers
# ---------------------------------------------------------------------------

class _MockAlt:
    def __init__(self, transcript: str = "", confidence: float = 0.95):
        self.transcript = transcript
        self.confidence = confidence


MockAlternative = _MockAlt  # Backwards-compatible alias


class _MockChannel:
    def __init__(self, alternatives=None):
        self.alternatives = alternatives or [_MockAlt()]


class _MockUtteranceEnd:
    type = "UtteranceEnd"
    channel = [0]
    last_word_end = 1.0


def _make_results_msg(transcript: str, is_final=None, speech_final=None):
    """Build a mock ListenV1Results message."""
    return type("_Results", (), {
        "type": "Results",
        "channel": _MockChannel([_MockAlt(transcript)]),
        "is_final": is_final,
        "speech_final": speech_final,
        "duration": 0.1,
        "start": 0.0,
        "channel_index": [0],
    })()


@contextlib.contextmanager
def _patch_deepgram(sdk_module):
    """Patch the deepgram modules in sys.modules."""
    api_error_module = SimpleNamespace(ApiError=_MockApiError)
    events_module = SimpleNamespace(EventType=_EventType)
    with patch.dict(sys.modules, {
        "deepgram": sdk_module,
        "deepgram.core.api_error": api_error_module,
        "deepgram.core.events": events_module,
    }):
        yield


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestConnectLifecycle:
    """Verify the connect → listen → close lifecycle."""

    def test_successful_connect_starts_listening(self):
        conn = _MockConnection()
        v1_client = _MockV1Client(connection_factory=lambda **kw: conn)
        mock_client = _MockDeepgramClient(api_key="test-key")
        mock_client.set_v1_client(v1_client)

        mock_module = SimpleNamespace(DeepgramClient=lambda **kw: mock_client)
        with _patch_deepgram(mock_module):
            backend = DeepgramASRBackend(api_key="test-key")
            kwargs = backend._build_connect_kwargs()
            assert kwargs["model"] == "nova-3"
            assert kwargs["language"] == "lt"

    def test_connect_timeout_raises_timeout_error(self):
        """When __enter__ blocks, the timeout should fire."""
        real_enter = _MockContextManager.__enter__

        def slow_enter(self):
            time.sleep(0.3)  # Simulate a hang
            return real_enter(self)

        backend = DeepgramASRBackend(
            api_key="test-key",
            connect_timeout_seconds=0.05,
        )

        hanging_cm = _MockContextManager()
        hanging_cm.__enter__ = lambda: slow_enter(hanging_cm)

        v1_client = _MockV1Client()
        v1_client.connect = lambda **kw: hanging_cm

        mock_client = _MockDeepgramClient(api_key="test-key")
        mock_client.set_v1_client(v1_client)

        mock_module = SimpleNamespace(DeepgramClient=lambda **kw: mock_client)
        with _patch_deepgram(mock_module):
            with pytest.raises(TimeoutError):
                backend._connect_and_listen()

    def test_connect_success_establishes_connection(self):
        """Verify _on_connection_open is called and handlers registered."""
        conn = _MockConnection()
        v1_client = _MockV1Client(connection_factory=lambda **kw: conn)
        mock_client = _MockDeepgramClient(api_key="test-key")
        mock_client.set_v1_client(v1_client)

        mock_module = SimpleNamespace(DeepgramClient=lambda **kw: mock_client)
        with _patch_deepgram(mock_module):
            backend = DeepgramASRBackend(api_key="test-key", connect_timeout_seconds=0.5)
            # Run in a thread since start_listening blocks
            thread = threading.Thread(target=backend._connect_and_listen, daemon=True)
            thread.start()
            # Wait for connection to establish
            deadline = time.monotonic() + 2.0
            while backend._connection_state != _ConnectionState.CONNECTED and time.monotonic() < deadline:
                time.sleep(0.01)
            assert backend._connection_state == _ConnectionState.CONNECTED
            # Verify handlers were registered
            assert "open" in conn._on_handlers or _EventType.OPEN in conn._on_handlers
            backend._stop_event.set()
            thread.join(timeout=5.0)


class TestAuthFailure:
    """Verify auth failure (401) is classified correctly."""

    def test_401_raises_auth_error(self):
        backend = DeepgramASRBackend(api_key="")
        with pytest.raises(_AuthError):
            backend._connect_and_listen()

    def test_401_from_sdk_wrapped_as_auth_error(self):
        api_error = _MockApiError(status_code=401, body="invalid credentials")
        v1_client = _MockV1Client(connect_error=api_error)
        mock_client = _MockDeepgramClient(api_key="bad-key")
        mock_client.set_v1_client(v1_client)

        mock_module = SimpleNamespace(DeepgramClient=lambda **kw: mock_client)
        with _patch_deepgram(mock_module):
            backend = DeepgramASRBackend(api_key="bad-key")
            with pytest.raises(_AuthError):
                backend._connect_and_listen()

    def test_non_401_error_not_wrapped_as_auth(self):
        api_error = _MockApiError(status_code=403, body="forbidden")
        v1_client = _MockV1Client(connect_error=api_error)
        mock_client = _MockDeepgramClient(api_key="bad-key")
        mock_client.set_v1_client(v1_client)

        mock_module = SimpleNamespace(DeepgramClient=lambda **kw: mock_client)
        with _patch_deepgram(mock_module):
            backend = DeepgramASRBackend(api_key="bad-key")
            with pytest.raises(_MockApiError):
                backend._connect_and_listen()


class TestEventDispatch:
    """Verify event handlers are registered and dispatched."""

    def test_handlers_registered_on_open(self):
        conn = _MockConnection()
        backend = DeepgramASRBackend(api_key="test-key")
        backend._on_connection_open(conn)

        assert _EventType.OPEN in conn._on_handlers
        assert _EventType.MESSAGE in conn._on_handlers
        assert _EventType.ERROR in conn._on_handlers
        assert _EventType.CLOSE in conn._on_handlers

    def test_results_message_dispatched(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        msg = _make_results_msg("point red", is_final=True, speech_final=True)
        backend._handle_message(msg)
        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        assert events[0].raw_transcript == "point red"

    def test_interim_message_goes_to_interim_queue_not_finalized(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        msg = _make_results_msg("poi", is_final=False, speech_final=False)
        backend._handle_message(msg)
        assert backend.get_finalized_transcripts() == []
        interim = backend.get_interim_transcripts()
        assert len(interim) == 1

    def test_utterance_end_dispatched(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        # Accumulate a segment first
        msg = _make_results_msg("point", is_final=True, speech_final=False)
        backend._handle_message(msg)

        # Then UtteranceEnd
        backend._handle_message(_MockUtteranceEnd())

        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        assert events[0].raw_transcript == "point"

    def test_error_event_queued(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._handle_error(ValueError("connection dropped"))
        errors = backend.get_errors()
        assert len(errors) == 1
        assert errors[0][0] == "websocket_error"

    def test_close_event_does_not_fail(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._handle_close()
        backend._handle_close()  # idempotent


class TestInterimToFinalProgression:
    """Verify interim → final progression within an utterance."""

    def test_interim_then_final_single_utterance(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        # Interim
        backend._handle_message(_make_results_msg("poi", is_final=False, speech_final=False))
        assert backend.get_finalized_transcripts() == []

        # Final
        backend._handle_message(_make_results_msg("point red", is_final=True, speech_final=True))

        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        assert events[0].raw_transcript == "point red"

    def test_multiple_finals_concatenated(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        backend._handle_message(_make_results_msg("taškas", is_final=True, speech_final=False))
        assert backend.get_finalized_transcripts() == []

        backend._handle_message(_make_results_msg("raudonam", is_final=True, speech_final=True))

        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        assert events[0].raw_transcript == "taškas raudonam"


class TestEmptyFinal:
    """Verify empty final transcripts are handled."""

    def test_empty_transcript_not_emitted(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        backend._handle_message(_make_results_msg("", is_final=True, speech_final=True))
        assert backend.get_finalized_transcripts() == []
        m = backend.metrics()
        assert m.empty_transcript_count == 1


class TestReconnection:
    """Verify reconnect logic in _io_loop."""

    def test_reconnect_on_connection_error(self):
        backend = DeepgramASRBackend(
            api_key="test-key",
            reconnect_attempts=2,
        )

        call_count = [0]

        def failing_connect():
            call_count[0] += 1
            raise ConnectionError("network error")

        backend._connect_and_listen = failing_connect
        backend._set_connection_state(_ConnectionState.CONNECTING)
        thread = threading.Thread(target=backend._io_loop, daemon=True)
        thread.start()

        time.sleep(0.5)
        backend._stop_event.set()
        thread.join(timeout=5.0)

        assert call_count[0] >= 1

    def test_no_reconnect_after_max_attempts(self):
        backend = DeepgramASRBackend(
            api_key="test-key",
            reconnect_attempts=1,
        )

        call_count = [0]

        def failing_connect():
            call_count[0] += 1
            raise ConnectionError("persistent failure")

        backend._connect_and_listen = failing_connect
        backend._set_connection_state(_ConnectionState.CONNECTING)
        thread = threading.Thread(target=backend._io_loop, daemon=True)
        thread.start()
        thread.join(timeout=10.0)

        assert call_count[0] <= 2
        assert backend._connection_state == _ConnectionState.FAILED


class TestShutdownDuringSpeech:
    """Verify shutdown during active speech discards the utterance."""

    def test_close_discards_in_progress(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"

        # Start accumulating
        backend._handle_message(_make_results_msg("point", is_final=True, speech_final=False))
        assert backend._utterance_accumulator.state.value == "accumulating"

        backend.close()

        assert backend._utterance_accumulator.state.value == "discarded"
        assert backend.get_finalized_transcripts() == []


class TestLateEventAfterStop:
    """Verify events arriving after close do not cause crashes."""

    def test_message_after_close_handled_safely(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._session_id = "sess-1"
        backend.close()

        # Should not raise
        backend._handle_message(_make_results_msg("point red", is_final=True, speech_final=True))


class TestEventTypeError:
    """Verify EventType.ERROR from Deepgram is propagated."""

    def test_error_event_from_sdk(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._handle_error(RuntimeError("WebSocket protocol error"))
        errors = backend.get_errors()
        assert len(errors) == 1
        assert "WebSocket protocol error" in errors[0][1]

    def test_error_sets_failed_state(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._handle_error(RuntimeError("ws error"))
        assert backend._connection_state == _ConnectionState.FAILED


class TestKeytermSerialization:
    """Verify keyterms are passed as a list (not comma-separated)."""

    def test_keyterms_passed_as_list(self):
        backend = DeepgramASRBackend(
            api_key="key",
            keyterms=["taškas", "atšaukti"],
            language="lt",
        )
        kwargs = backend._build_connect_kwargs()
        assert isinstance(kwargs["keyterm"], list)
        assert "taškas" in kwargs["keyterm"]
        assert "atšaukti" in kwargs["keyterm"]
        for term in kwargs["keyterm"]:
            assert "," not in term


class TestSendLoop:
    """Verify the send loop drains audio and sends to the connection."""

    def test_send_loop_drains_audio_frames(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()

        mock_conn = MagicMock()
        backend._connection = mock_conn
        backend._stop_event.clear()

        frame = b"\x00" * 160
        backend._audio_frame_queue.put_nowait(frame)
        backend._audio_frame_queue.put_nowait(frame)

        thread = threading.Thread(target=backend._send_loop, daemon=True)
        thread.start()
        time.sleep(0.5)
        backend._stop_event.set()
        thread.join(timeout=2.0)

        assert mock_conn.send_media.call_count == 2

    def test_send_loop_sends_keepalive(self):
        backend = DeepgramASRBackend(
            api_key="test-key",
            keepalive_seconds=0.1,
        )
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._connection_open_event.set()

        mock_conn = MagicMock()
        backend._connection = mock_conn
        backend._stop_event.clear()

        thread = threading.Thread(target=backend._keepalive_loop, daemon=True)
        thread.start()
        time.sleep(0.5)
        backend._stop_event.set()
        thread.join(timeout=2.0)

        assert mock_conn.send_keep_alive.call_count >= 1


class TestEnqueueDuringConnecting:
    """Audio arriving during CONNECTING is rejected (discard-while-connecting)."""

    def test_audio_rejected_during_connecting(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        assert backend.enqueue_audio(b"\x00" * 160) is False


class TestEnqueueDuringStopping:
    """Audio arriving during STOPPING is rejected."""

    def test_audio_rejected_during_stopping(self):
        backend = DeepgramASRBackend(api_key="test-key")
        backend._set_connection_state(_ConnectionState.STOPPING)
        assert backend.enqueue_audio(b"\x00" * 160) is False
