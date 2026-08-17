"""Unit tests for the Deepgram streaming ASR backend.

Covers plan §9.2 (test_deepgram_backend.py):
- Utterance state machine (IDLE → ACCUMULATING → SEALED → IDLE, FINALIZING, DISCARDED)
- enqueue_audio back-pressure and state gating
- close / shutdown lifecycle
- Secret redaction (API key never in diagnostics)
- Error classification (auth_failure, connection_error, timeout)
- Metrics tracking
- _build_connect_kwargs construction
- health_status / get_status
"""
from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.asr_backends.deepgram_backend import (
    DeepgramASRBackend,
    _AuthError,
    _ConnectionState,
    _UtteranceAccumulator,
    _UtteranceState,
    _is_interim_message,
)


# ---------------------------------------------------------------------------
# Mock message helpers
# ---------------------------------------------------------------------------

class _MockAlternative:
    def __init__(self, transcript: str = "", confidence: float = 0.95):
        self.transcript = transcript
        self.confidence = confidence


class _MockChannel:
    def __init__(self, alternatives=None):
        self.alternatives = alternatives or [_MockAlternative()]


class _MockResultsMessage:
    """Simulates a ListenV1Results message."""
    type = "Results"

    def __init__(
        self,
        transcript: str = "point red",
        is_final=None,
        speech_final=None,
        channel=None,
    ):
        self.channel = channel or _MockChannel([_MockAlternative(transcript)])
        self.is_final = is_final
        self.speech_final = speech_final
        self.duration = 0.1
        self.start = 0.0
        self.channel_index = [0]


class _MockUtteranceEnd:
    type = "UtteranceEnd"
    channel = [0]
    last_word_end = 1.0


# ---------------------------------------------------------------------------
# _UtteranceAccumulator state machine
# ---------------------------------------------------------------------------

class TestUtteranceStateMachine:
    def _make(self):
        return _UtteranceAccumulator()

    def test_idle_to_accumulating_on_final(self):
        acc = self._make()
        result = acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert result is None
        assert acc.state == _UtteranceState.ACCUMULATING
        assert acc.segments == ["point"]

    def test_accumulating_to_sealed_on_speech_final(self):
        acc = self._make()
        # First segment: IDLE → ACCUMULATING
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.9,
        )
        # Second segment with speech_final: ACCUMULATING → SEALED → IDLE
        result = acc.on_message(
            text="red", is_final=True, speech_final=True,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.8,
        )
        assert result == ("point red", pytest.approx(0.85))
        assert acc.state == _UtteranceState.IDLE

    def test_immediate_seal_from_idle(self):
        """is_final=True + speech_final=True in a single message."""
        acc = self._make()
        result = acc.on_message(
            text="point red", is_final=True, speech_final=True,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.95,
        )
        assert result == ("point red", 0.95)
        assert acc.state == _UtteranceState.IDLE

    def test_interim_returns_none_no_state_change(self):
        acc = self._make()
        result = acc.on_message(
            text="point", is_final=False, speech_final=False,
            is_interim=True, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert result is None
        assert acc.state == _UtteranceState.IDLE
        assert acc.segments == []

    def test_non_final_returns_none(self):
        acc = self._make()
        result = acc.on_message(
            text="point", is_final=False, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert result is None
        assert acc.state == _UtteranceState.IDLE

    def test_utterance_end_seals_accumulated(self):
        acc = self._make()
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.9,
        )
        result = acc.on_utterance_end()
        assert result == ("point", 0.9)
        assert acc.state == _UtteranceState.IDLE

    def test_utterance_end_idle_returns_none(self):
        acc = self._make()
        assert acc.on_utterance_end() is None
        assert acc.state == _UtteranceState.IDLE

    def test_utterance_end_after_sealed_returns_none(self):
        acc = self._make()
        acc.on_message(
            text="point red", is_final=True, speech_final=True,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert acc.on_utterance_end() is None

    def test_done_receives_no_more_segments(self):
        acc = self._make()
        acc.on_message(
            text="point red", is_final=True, speech_final=True,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert acc.state == _UtteranceState.IDLE
        result = acc.on_message(
            text="taškas", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert result is None

    def test_discarded_receives_no_more_segments(self):
        acc = self._make()
        acc.invalidate()
        result = acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        assert result is None

    def test_timeout_transitions_to_finalizing(self):
        acc = self._make()
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=10, max_utterance_ms=10000,
        )
        assert acc.state == _UtteranceState.ACCUMULATING

        time.sleep(0.02)  # 20ms > 10ms timeout
        result = acc.check_timeout(finalize_timeout_ms=10)
        assert result is None
        assert acc.state == _UtteranceState.FINALIZING
        assert acc.needs_finalize() is True

    def test_fallback_seal_after_timeout(self):
        acc = self._make()
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=10, max_utterance_ms=10000,
        )
        
        # Advance time past fallback (50ms > 20ms)
        time.sleep(0.05)
        res = acc.check_fallback_seal(fallback_ms=20)
        assert res is not None
        text, conf = res
        assert text == "point"
        assert acc.state == _UtteranceState.IDLE

    def test_multiple_segments_fallback_seal(self):
        acc = self._make()
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=100, max_utterance_ms=10000,
        )
        
        time.sleep(0.05)
        acc.on_message(
            text="red", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=100, max_utterance_ms=10000,
        )
        
        # 50ms after second segment -> not yet 100ms fallback
        time.sleep(0.05)
        assert acc.check_fallback_seal(fallback_ms=100) is None
            
        # 120ms after second segment -> seal
        time.sleep(0.12)
        res = acc.check_fallback_seal(fallback_ms=100)
        assert res is not None
        assert res[0] == "point red"

    def test_timeout_does_not_trigger_when_not_accumulating(self):
        acc = self._make()
        assert acc.check_timeout(finalize_timeout_ms=10) is None
        assert acc.state == _UtteranceState.IDLE

    def test_max_utterance_duration_truncates(self):
        acc = self._make()
        acc.on_message(
            text="start", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=5000, max_utterance_ms=0,
        )
        assert acc.state == _UtteranceState.ACCUMULATING

    def test_invalidate_discards_state(self):
        acc = self._make()
        acc.on_message(
            text="point", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
        )
        acc.invalidate()
        assert acc.state == _UtteranceState.DISCARDED
        assert acc.segments == []

    def test_multiple_segments_concatenated(self):
        acc = self._make()
        acc.on_message(
            text="taškas", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.8,
        )
        acc.on_message(
            text="raudonam", is_final=True, speech_final=False,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=0.9,
        )
        result = acc.on_message(
            text="žaidėjui", is_final=True, speech_final=True,
            is_interim=False, finalize_timeout_ms=1200, max_utterance_ms=10000,
            confidence=1.0,
        )
        assert result == ("taškas raudonam žaidėjui", 0.9)
        assert acc.state == _UtteranceState.IDLE

    def test_empty_segments_seal_returns_none(self):
        acc = self._make()
        # Force SEALED state with no segments
        acc.state = _UtteranceState.SEALED
        result = acc._seal(time.monotonic())
        assert result is None
        assert acc.state == _UtteranceState.IDLE


# ---------------------------------------------------------------------------
# _is_interim_message helper
# ---------------------------------------------------------------------------

class TestIsInterimMessage:
    def test_is_final_false_is_interim(self):
        msg = type("_Msg", (), {"is_final": False})()
        assert _is_interim_message(msg) is True

    def test_is_final_true_is_not_interim(self):
        msg = type("_Msg", (), {"is_final": True})()
        assert _is_interim_message(msg) is False

    def test_is_final_none_is_not_interim(self):
        msg = type("_Msg", (), {"is_final": None})()
        assert _is_interim_message(msg) is False

    def test_missing_is_final_is_not_interim(self):
        msg = type("_Msg", (), {})()
        assert _is_interim_message(msg) is False


# ---------------------------------------------------------------------------
# DeepgramASRBackend — initialization and status
# ---------------------------------------------------------------------------

class TestBackendInit:
    def test_defaults(self):
        backend = DeepgramASRBackend(api_key="test-key")
        assert backend._api_key == "test-key"
        assert backend._model == "nova-3"
        assert backend._language == "lt"
        assert backend._endpointing_ms == 300
        assert backend._interim_results is True
        assert backend._max_keyterms == 100
        assert backend.backend_name == "deepgram"

    def test_no_api_key_not_available(self):
        backend = DeepgramASRBackend(api_key=None)
        assert backend.is_available() is False

    def test_with_api_key_available(self):
        backend = DeepgramASRBackend(api_key="secret-key")
        assert backend.is_available() is True

    def test_capabilities(self):
        backend = DeepgramASRBackend(api_key="key")
        caps = backend.capabilities()
        assert caps.supports_streaming is True
        assert caps.requires_speaker_calibration is False
        assert caps.supports_local_vad is False
        assert caps.supports_optional_audio_health_check is True

    def test_delivery_policy(self):
        backend = DeepgramASRBackend(api_key="key")
        policy = backend.delivery_policy()
        assert policy.mode == "continuous"
        assert policy.require_vad_calibration is False
        assert policy.allow_degraded_fallback is True


class TestBackendStatus:
    def test_status_available(self):
        backend = DeepgramASRBackend(api_key="key")
        status = backend.get_status()
        assert status.backend_name == "deepgram"
        assert status.available is True
        assert status.load_error is None
        caps = status.model_info.get("capabilities")
        assert caps is not None
        assert caps.supports_streaming is True

    def test_status_not_available(self):
        backend = DeepgramASRBackend(api_key=None)
        status = backend.get_status()
        assert status.available is False
        assert "VOICE_DEEPGRAM_API_KEY" in status.setup_instructions


class TestBackendHealth:
    def test_no_api_key_failed(self):
        backend = DeepgramASRBackend(api_key=None)
        assert backend.health_status() == "failed"

    def test_disconnected_skipped(self):
        backend = DeepgramASRBackend(api_key="key")
        assert backend.health_status() == "connecting"

    def test_connecting_ready(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        assert backend.health_status() == "connecting"

    def test_connected_ready(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        assert backend.health_status() == "connected"

    def test_failed_state(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.FAILED)
        assert backend.health_status() == "failed"


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

class TestSecretRedaction:
    def test_api_key_not_in_status(self):
        backend = DeepgramASRBackend(api_key="super-secret-key-123")
        status = backend.get_status()
        status_str = str(status.__dict__) + str(status.model_info)
        assert "super-secret-key-123" not in status_str

    def test_api_key_not_in_metrics(self):
        backend = DeepgramASRBackend(api_key="super-secret-key-123")
        m = backend.metrics()
        metrics_str = str(m.__dict__)
        assert "super-secret-key-123" not in metrics_str


# ---------------------------------------------------------------------------
# Enqueue audio and queue behavior
# ---------------------------------------------------------------------------

class TestEnqueueAudio:
    def test_enqueue_empty_returns_true(self):
        backend = DeepgramASRBackend(api_key="key")
        assert backend.enqueue_audio(b"") is True

    def test_enqueue_when_disconnected_returns_false(self):
        backend = DeepgramASRBackend(api_key="key")
        assert backend.enqueue_audio(b"\x00" * 160) is False

    def test_enqueue_when_connecting_returns_false(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTING)
        assert backend.enqueue_audio(b"\x00" * 160) is False

    def test_enqueue_when_connected_returns_true(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        assert backend.enqueue_audio(b"\x00" * 160) is True
        assert backend._audio_frame_queue.qsize() == 1

    def test_enqueue_backpressure_on_full_queue(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        frame = b"\x00" * 160
        # Fill the queue
        for _ in range(256):
            backend._audio_frame_queue.put_nowait(frame)
        assert backend._audio_frame_queue.full()
        # Next enqueue should fail
        assert backend.enqueue_audio(frame) is False
        m = backend.metrics()
        assert m.queue_overflow_count >= 1

    def test_enqueue_increments_frame_metric(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend.enqueue_audio(b"\x00" * 160)
        m = backend.metrics()
        assert m.audio_frames_received == 1


# ---------------------------------------------------------------------------
# Finalize utterance
# ---------------------------------------------------------------------------

class TestFinalizeUtterance:
    def test_finalize_sets_timestamp(self):
        backend = DeepgramASRBackend(api_key="key")
        before = backend._last_finalize_request
        backend.finalize_utterance()
        assert backend._last_finalize_request > before


# ---------------------------------------------------------------------------
# Close / shutdown
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_sets_stopping_state(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend.close()
        assert backend._connection_state == _ConnectionState.STOPPED
        assert backend._stop_event.is_set()

    def test_close_drains_queues(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._set_connection_state(_ConnectionState.CONNECTED)
        backend._finalized_queue.put_nowait(("raw", "norm", "utt-id"))
        backend._interim_queue.put_nowait(("text", "sess"))
        backend._error_queue.put_nowait(("err", "msg"))
        backend.close()
        assert backend._finalized_queue.empty()
        assert backend._interim_queue.empty()
        assert backend._error_queue.empty()

    def test_close_invalidates_accumulator(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._utterance_accumulator.state = _UtteranceState.ACCUMULATING
        backend.close()
        assert backend._utterance_accumulator.state == _UtteranceState.DISCARDED

    def test_close_idempotent(self):
        backend = DeepgramASRBackend(api_key="key")
        backend.close()
        backend.close()  # should not raise


# ---------------------------------------------------------------------------
# Drain methods
# ---------------------------------------------------------------------------

class TestDrainMethods:
    def test_drain_finalized(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._finalized_queue.put_nowait(("raw1", "norm1", "utt1"))
        backend._finalized_queue.put_nowait(("raw2", "norm2", "utt2"))
        events = backend.get_finalized_transcripts()
        assert len(events) == 2
        assert events[0] == ("raw1", "norm1", "utt1")
        assert backend._finalized_queue.empty()

    def test_drain_empty_finalized(self):
        backend = DeepgramASRBackend(api_key="key")
        assert backend.get_finalized_transcripts() == []

    def test_drain_interim(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._interim_queue.put_nowait(("text1", "sess"))
        events = backend.get_interim_transcripts()
        assert len(events) == 1

    def test_drain_errors(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._error_queue.put_nowait(("auth_failure", "bad key"))
        errors = backend.get_errors()
        assert len(errors) == 1
        assert errors[0] == ("auth_failure", "bad key")


# ---------------------------------------------------------------------------
# _build_connect_kwargs
# ---------------------------------------------------------------------------

class TestBuildConnectKwargs:
    def test_minimal_kwargs(self):
        backend = DeepgramASRBackend(api_key="key")
        kwargs = backend._build_connect_kwargs()
        assert kwargs["model"] == "nova-3"
        assert kwargs["language"] == "lt"
        assert kwargs["encoding"] == "linear16"
        assert kwargs["sample_rate"] == 16000
        assert kwargs["channels"] == 1
        assert kwargs["interim_results"] is True
        assert kwargs["endpointing"] == 300
        assert kwargs["vad_events"] is True
        assert kwargs["utterance_end_ms"] == 1000
        assert kwargs["smart_format"] is True
        assert kwargs["punctuate"] is False
        assert kwargs["numerals"] is True

    def test_no_keyterms_when_disabled(self):
        backend = DeepgramASRBackend(api_key="key", keyterms=[])
        kwargs = backend._build_connect_kwargs()
        assert "keyterm" not in kwargs

    def test_keyterms_when_provided(self):
        backend = DeepgramASRBackend(
            api_key="key",
            keyterms=["taškas", "atšaukti"],
            language="lt",
        )
        kwargs = backend._build_connect_kwargs()
        assert "keyterm" in kwargs
        assert "taškas" in kwargs["keyterm"]
        assert "atšaukti" in kwargs["keyterm"]

    def test_keyterms_respect_max(self):
        backend = DeepgramASRBackend(
            api_key="key",
            keyterms=["term" + str(i) for i in range(200)],
            max_keyterms=50,
            language="lt",
        )
        kwargs = backend._build_connect_kwargs()
        assert len(kwargs["keyterm"]) <= 50

    def test_kwargs_language_overridable_via_start_session(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._language = "en"
        kwargs = backend._build_connect_kwargs()
        assert kwargs["language"] == "en"


# ---------------------------------------------------------------------------
# Emit finalized
# ---------------------------------------------------------------------------

class TestEmitFinalized:
    def test_empty_text_not_emitted(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._session_id = "sess-1"
        backend._emit_finalized("")
        assert backend._finalized_queue.empty()
        m = backend.metrics()
        assert m.empty_transcript_count == 1

    def test_nonempty_text_emitted(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._session_id = "sess-1"
        backend._emit_finalized("point red")
        events = backend.get_finalized_transcripts()
        assert len(events) == 1
        utt = events[0]
        assert utt.raw_transcript == "point red"
        assert utt.transcript == "point red"
        assert utt.utterance_id == "sess-1:0:1"
        assert utt.voice_session_id == "sess-1"
        assert utt.backend_generation == backend._generation
        assert utt.language == backend._language
        assert utt.finalization_reason == "speech_final"

    def test_lithuanian_text_normalized(self):
        backend = DeepgramASRBackend(api_key="key")
        backend._session_id = "sess-1"
        backend._emit_finalized("taškas")
        events = backend.get_finalized_transcripts()
        assert events[0].transcript == "taškas"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_initial_metrics_zero(self):
        backend = DeepgramASRBackend(api_key="key")
        m = backend.metrics()
        assert m.audio_frames_received == 0
        assert m.queue_overflow_count == 0
        assert m.audio_bytes_sent == 0
        assert m.keepalive_count == 0
        assert m.reconnect_count == 0

    def test_metrics_returns_copy(self):
        backend = DeepgramASRBackend(api_key="key")
        m1 = backend.metrics()
        m2 = backend.metrics()
        assert m1 is not m2
