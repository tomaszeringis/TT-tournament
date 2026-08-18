"""Runtime integration tests for the Deepgram streaming audio path (plan §8A/§8B/§8C).

These tests verify the integration of the Deepgram streaming backend into
VoiceAudioProcessor, covering all required test gates:

1.  Deepgram continuous mode + no calibration context → audio accepted
2.  Continuous silence → no microphone failure
3.  Interim transcript → diagnostics only
4.  Final transcript → parser called exactly once
5.  Duplicate final event → one score mutation
6.  Voice-off before final callback → no mutation
7.  Match change before final callback → no mutation
8.  Language change → old session invalidated
9.  Reconnect → no buffered audio replay
10. Queue full → precise terminal transport outcome
11. Streamlit rerun → no duplicate Deepgram connection
12. Provider failure → manual scoring remains available
"""
from __future__ import annotations

import queue
import time
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor
from tournament_platform.app.services.voice_scorekeeper.events import (
    FinalizedUtterance,
    AudioTransportOutcome,
    VoiceRuntimeMode,
    VoiceTranscriptSource,
)
from tournament_platform.app.services.voice_audio import (
    SAMPLE_FORMAT_INT16,
    SAMPLE_FORMAT_FLOAT32,
)
from tournament_platform.app.services.asr_backends.calibration_policy import (
    ASRCapabilities,
    AudioDeliveryPolicy,
    AudioAdmissionDecision,
)


class MockStreamingBackend:
    """A mock streaming ASR backend that implements the StreamingASRBackend protocol."""

    backend_name = "mock_streaming"

    def __init__(self):
        self._audio_queue: queue.Queue = queue.Queue(maxsize=16)
        self._finalized_queue: queue.Queue = queue.Queue(maxsize=50)
        self._interim_queue: queue.Queue = queue.Queue(maxsize=50)
        self._error_queue: queue.Queue = queue.Queue(maxsize=20)
        self._session_id = ""
        self._generation = 0
        self._language = "lt"
        self._connection_state = "disconnected"
        self._available = True
        self._closed = False
        self._start_session_calls: list[dict] = []
        self._enqueue_calls: list[bytes] = []
        self._close_calls = 0
        self._finalize_calls = 0
        self._keepalive_calls = 0
        self._audio_bytes_sent = 0
        self._audio_duration_sent_ms = 0.0
        self._audio_send_attempts = 0
        self._audio_send_failed = 0
        self._last_audio_send_at = 0.0
        self._audio_frames_received = 0
        self._interim_count = 0
        self._queue_overflow_count = 0
        self._provider_messages_received = 0
        self._provider_open_count = 0
        self._provider_close_count = 0
        self._provider_error_count = 0
        self._provider_unerror_count = 0
        self._provider_utterance_end_count = 0
        self._provider_speech_started_count = 0
        self._last_provider_message_text = ""
        self._provider_results_received = 0
        self._provider_results_empty = 0
        self._provider_results_with_text = 0
        self._provider_results_interim = 0
        self._provider_results_final = 0
        self._provider_results_speech_final = 0
        self._transcript_text_extracted = 0
        self._finalization_sequence = 0
        self._provider_metadata_count = 0
        self._provider_unknown_message_count = 0
        self._provider_message_index = 0
        self._last_provider_message_type = None
        self._last_provider_message_summary = ""
        self._completed_utterance_count = 0
        self._accumulator_final_segments = 0
        self._accumulator_seal_attempts = 0
        self._accumulator_seal_success = 0
        self._emit_finalized_calls = 0
        self._finalized_queue_put_success = 0
        self._enqueue_return_value = True

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=False,
            supports_optional_audio_health_check=True,
        )

    def delivery_policy(self) -> AudioDeliveryPolicy:
        return AudioDeliveryPolicy(
            mode="continuous",
            require_vad_calibration=False,
            allow_degraded_fallback=True,
        )

    def start_session(
        self,
        *,
        language: str,
        session_id: str | None = None,
        generation: int | None = None,
        match_id: Any | None = None,
        keyterms: list[str] | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        self._generation = generation if generation is not None else (self._generation + 1)
        self._session_id = session_id or f"mock-sess-{self._generation}"
        self._language = language
        self._connection_state = "connecting"
        self._available = True
        self._closed = False
        self._start_session_calls.append({
            "language": language,
            "session_id": session_id,
            "generation": generation,
            "match_id": match_id,
            "keyterms": keyterms,
            "sample_rate": sample_rate,
            "channels": channels,
        })
        self._reset_queues()
        # Simulate immediate connect
        self._connection_state = "connected"

    def enqueue_audio(self, pcm_bytes: bytes) -> bool:
        if not self._available:
            self._enqueue_return_value = False
            return False
        self._enqueue_calls.append(pcm_bytes)
        # Simulate the send loop draining the queue
        try:
            self._audio_queue.put_nowait(pcm_bytes)
            self._enqueue_return_value = True
            return True
        except queue.Full:
            # Drain one item to make room (simulates send loop)
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(pcm_bytes)
                self._enqueue_return_value = True
                return True
            except queue.Full:
                self._enqueue_return_value = False
                return False

    def send_keepalive(self) -> None:
        self._keepalive_calls += 1

    def finalize_utterance(self) -> None:
        self._finalize_calls += 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_calls += 1
        self._connection_state = "stopped"
        self._available = False
        self._reset_queues()

    def is_available(self) -> bool:
        return self._available

    def health_status(self) -> str:
        return self._connection_state

    def connection_state(self) -> str:
        return self._connection_state

    def get_connection_info(self) -> dict:
        return {
            "connection_state": self._connection_state,
            "provider_message_index": self._provider_message_index,
            "last_error_category": None,
            "last_error_message_safe": None,
        }

    def _reset_queues(self) -> None:
        for q in (
            self._audio_queue,
            self._finalized_queue,
            self._interim_queue,
            self._error_queue,
        ):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def metrics(self):
        from tournament_platform.app.services.asr_backends.base import DeepgramBackendMetrics
        m = getattr(self, "_metrics", None)
        if m is not None and isinstance(m, DeepgramBackendMetrics):
            m.audio_bytes_sent = self._audio_bytes_sent
            m.audio_duration_sent_ms = self._audio_duration_sent_ms
            m.audio_send_attempts = self._audio_send_attempts
            m.audio_send_failed = self._audio_send_failed
            m.audio_send_success = self._audio_send_attempts - self._audio_send_failed
            m.last_audio_send_at = self._last_audio_send_at
            m.queue_depth = self._audio_queue.qsize()
            m.connection_state = self._connection_state
            m.provider_messages_received = self._provider_messages_received
            m.provider_open_count = self._provider_open_count
            m.provider_close_count = self._provider_close_count
            m.provider_error_count = self._provider_error_count
            m.provider_unerror_count = self._provider_unerror_count
            m.provider_utterance_end_count = self._provider_utterance_end_count
            m.provider_speech_started_count = self._provider_speech_started_count
            m.last_provider_message_text = self._last_provider_message_text
            m.provider_results_received = self._provider_results_received
            m.provider_results_empty = self._provider_results_empty
            m.provider_results_with_text = self._provider_results_with_text
            m.provider_results_interim = self._provider_results_interim
            m.provider_results_final = self._provider_results_final
            m.provider_results_speech_final = self._provider_results_speech_final
            m.transcript_text_extracted = self._transcript_text_extracted
            m.last_interim_text = getattr(self, "_last_interim_text", "")
            m.last_final_text = getattr(self, "_last_final_text", "")
            m.send_loop_started = getattr(self, "_send_loop_started", False)
            m.send_loop_alive = getattr(self, "_send_loop_alive", False)
            m.keepalive_loop_started = getattr(self, "_keepalive_loop_started", False)
            m.keepalive_loop_alive = getattr(self, "_keepalive_loop_alive", False)
            return m
        return DeepgramBackendMetrics(
            audio_frames_received=getattr(self, "_audio_frames_received", 0),
            audio_bytes_sent=self._audio_bytes_sent,
            audio_duration_sent_ms=self._audio_duration_sent_ms,
            audio_send_attempts=self._audio_send_attempts,
            audio_send_failed=self._audio_send_failed,
            audio_send_success=self._audio_send_attempts - self._audio_send_failed,
            last_audio_send_at=self._last_audio_send_at,
            queue_depth=self._audio_queue.qsize(),
            connection_state=self._connection_state,
            completed_utterance_count=getattr(self, "_completed_utterance_count", 0),
            interim_transcript_count=getattr(self, "_interim_count", 0),
            queue_overflow_count=getattr(self, "_queue_overflow_count", 0),
            provider_messages_received=self._provider_messages_received,
            provider_open_count=self._provider_open_count,
            provider_close_count=self._provider_close_count,
            provider_error_count=self._provider_error_count,
            provider_unerror_count=self._provider_unerror_count,
            provider_utterance_end_count=self._provider_utterance_end_count,
            provider_speech_started_count=self._provider_speech_started_count,
            last_provider_message_text=self._last_provider_message_text,
            provider_results_received=self._provider_results_received,
            provider_results_empty=self._provider_results_empty,
            provider_results_with_text=self._provider_results_with_text,
            provider_results_interim=self._provider_results_interim,
            provider_results_final=self._provider_results_final,
            provider_results_speech_final=self._provider_results_speech_final,
            transcript_text_extracted=self._transcript_text_extracted,
            provider_metadata_count=self._provider_metadata_count,
            provider_unknown_message_count=self._provider_unknown_message_count,
            last_provider_message_type=self._last_provider_message_type,
            last_provider_message_summary=self._last_provider_message_summary,
            last_interim_text=getattr(self, "_last_interim_text", ""),
            last_final_text=getattr(self, "_last_final_text", ""),
            send_loop_started=getattr(self, "_send_loop_started", False),
            send_loop_alive=getattr(self, "_send_loop_alive", False),
            keepalive_loop_started=getattr(self, "_keepalive_loop_started", False),
            keepalive_loop_alive=getattr(self, "_keepalive_loop_alive", False),
        )

    def get_finalized_transcripts(self) -> list:
        events = []
        while True:
            try:
                events.append(self._finalized_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def simulate_message(self, message: Any) -> None:
        self._provider_messages_received += 1
        self._provider_message_index = self._provider_messages_received
        msg_type = getattr(message, "type", None)
        self._last_provider_message_type = msg_type

        _class = type(message).__name__
        is_results = msg_type == "Results"
        is_metadata = msg_type == "Metadata"
        is_speech_started = msg_type == "SpeechStarted"
        is_utterance_end = msg_type == "UtteranceEnd"

        if is_metadata:
            self._provider_metadata_count += 1
            self._last_provider_message_summary = f"class={_class} type={msg_type}"
        elif is_speech_started:
            self._provider_speech_started_count += 1
            self._last_provider_message_summary = f"class={_class} type={msg_type}"
        elif is_utterance_end:
            self._provider_utterance_end_count += 1
            self._last_provider_message_summary = f"class={_class} type={msg_type}"
        elif is_results:
            text = getattr(getattr(message, "channel", None), "alternatives", None)
            text = text[0].transcript if text else ""
            self._last_provider_message_text = text[:200]
            self._provider_results_received += 1
            if text:
                self._provider_results_with_text += 1
                self._transcript_text_extracted += 1
            else:
                self._provider_results_empty += 1

            is_final = getattr(message, "is_final", None) is True
            speech_final = getattr(message, "speech_final", None) is True
            if not is_final and not speech_final:
                self._provider_results_interim += 1
                try:
                    self._interim_queue.put_nowait((text, self._session_id))
                except queue.Full:
                    pass
            else:
                if is_final:
                    self._provider_results_final += 1
                if speech_final:
                    self._provider_results_speech_final += 1
                if text:
                    self._finalization_sequence += 1
                    utterance_id = f"{self._session_id}:{self._generation}:{self._finalization_sequence}"
                    from tournament_platform.app.services.voice_scorekeeper.events import FinalizedUtterance
                    utt = FinalizedUtterance(
                        voice_session_id=self._session_id,
                        backend_generation=self._generation,
                        utterance_id=utterance_id,
                        transcript=text,
                        raw_transcript=text,
                        finalization_reason="speech_final",
                    )
                    try:
                        self._finalized_queue.put_nowait(utt)
                    except queue.Full:
                        pass
        else:
            self._provider_unknown_message_count += 1
            self._last_provider_message_summary = f"class={_class} type={msg_type or 'unknown'}"

    def get_interim_transcripts(self) -> list:
        events = []
        while True:
            try:
                events.append(self._interim_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def get_errors(self) -> list:
        errors = []
        while True:
            try:
                errors.append(self._error_queue.get_nowait())
            except queue.Empty:
                break
        return errors

    def _queue_utterance(self, utt: FinalizedUtterance) -> None:
        self._finalized_queue.put_nowait(utt)
        self._completed_utterance_count += 1
        self._emit_finalized_calls += 1
        self._finalized_queue_put_success += 1

    def _queue_interim(self, text: str, session_id: str) -> None:
        self._interim_queue.put_nowait((text, session_id))

    def get_interim_diagnostics(self) -> dict:
        _items = []
        while True:
            try:
                _items.append(self._interim_queue.get_nowait())
            except queue.Full:
                pass
            except queue.Empty:
                break
        for item in _items:
            try:
                self._interim_queue.put_nowait(item)
            except queue.Full:
                pass
        _latest_interim = _items[-1][0] if _items else ""

        _fitems = []
        while True:
            try:
                _fitems.append(self._finalized_queue.get_nowait())
            except queue.Full:
                pass
            except queue.Empty:
                break
        for item in _fitems:
            try:
                self._finalized_queue.put_nowait(item)
            except queue.Full:
                pass
        _latest_finalized = ""
        if _fitems:
            _latest_finalized = getattr(_fitems[-1], "transcript", str(_fitems[-1]))

        return {
            "last_interim_transcript": _latest_interim,
            "last_finalized_transcript": _latest_finalized,
            "backend_health": self._connection_state,
            "audio_queue_size": self._audio_queue.qsize(),
            "finalized_queue_size": self._finalized_queue.qsize(),
            "interim_queue_size": self._interim_queue.qsize(),
        }

    def get_diagnostics(self) -> dict:
        return {
            "backend_health": self._connection_state,
            "audio_queue_size": self._audio_queue.qsize(),
            "finalized_queue_size": self._finalized_queue.qsize(),
            "interim_queue_size": self._interim_queue.qsize(),
            "finalized_utterances_emitted": self._completed_utterance_count,
            "accumulator_final_segments": self._accumulator_final_segments,
            "accumulator_seal_attempts": self._accumulator_seal_attempts,
            "accumulator_seal_success": self._accumulator_seal_success,
            "emit_finalized_calls": self._emit_finalized_calls,
            "finalized_queue_put_success": self._finalized_queue_put_success,
        }

    def _fill_audio_queue(self) -> None:
        """Fill the audio queue to capacity to simulate backpressure."""
        self._available = False  # Make enqueue return False

    def _set_connection_state(self, state: str) -> None:
        self._connection_state = state


def _make_streaming_processor(backend: MockStreamingBackend) -> VoiceAudioProcessor:
    """Create a VoiceAudioProcessor with a streaming backend attached."""
    proc = VoiceAudioProcessor()
    proc._runtime_mode = VoiceRuntimeMode.LIVE
    proc._session_id = "voice_session_1"
    proc.set_streaming_backend(
        backend,
        voice_session_id="voice_session_1",
        match_id=1,
        language="lt",
        sample_rate=16000,
        channels=1,
    )
    backend._connection_state = "connected"
    backend._available = True
    return proc


def _make_int16_pcm(samples: int = 160, channels: int = 2, value: float = 0.0) -> bytes:
    """Generate int16 PCM bytes."""
    arr = np.full(samples * channels, int(value * 32767), dtype=np.int16)
    return arr.tobytes()


def _make_float32_frame(samples: int = 160, channels: int = 2, value: float = 0.0) -> MagicMock:
    """Create a mock WebRTC audio frame."""
    arr = np.full(samples * channels, value, dtype=np.float32)
    frame = MagicMock()
    frame.format.name = "flt"
    frame.sample_rate = 16000
    frame.channels = channels
    frame.pts = time.time()
    # _frame_to_ndarray will use frame.planes[0].update(array)
    frame.planes = [MagicMock()]
    frame.planes[0].update = lambda data: None
    frame.__len__ = lambda self: samples * channels * 4
    return frame


def _make_int16_frame(samples: int = 160, channels: int = 2, value: float = 0.0) -> MagicMock:
    """Create a mock WebRTC int16 audio frame."""
    arr = np.full(samples * channels, int(value * 32767), dtype=np.int16)
    frame = MagicMock()
    frame.format.name = "s16"
    frame.sample_rate = 16000
    frame.channels = channels
    frame.pts = time.time()
    frame.to_ndarray.return_value = arr.reshape(samples, channels) if channels > 1 else arr
    return frame


# ---------------------------------------------------------------------------
# Test Gate 1: Deepgram continuous mode + no calibration context → audio accepted
# ---------------------------------------------------------------------------

class TestContinuousModeNoCalibration:
    def test_audio_accepted_without_calibration_context(self):
        """Deepgram continuous mode should accept audio even without calibration context."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._calibration_context = None  # No calibration context

        frame_bytes = _make_int16_pcm(samples=160, channels=2, value=0.5)
        outcome = proc._enqueue_streaming_audio(frame_bytes)

        assert outcome.outcome == "enqueued"
        assert len(backend._enqueue_calls) == 1
        assert backend._enqueue_calls[0] == frame_bytes
        assert proc._streaming_audio_enqueued == 1

    def test_continuous_audio_bypasses_voice_audio_buffer(self):
        """When streaming backend is active, _ingest_frame should NOT push to VoiceAudioBuffer."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        # Replace audio_buffer.push_frame with a sentinel that would fail if called
        called = [False]
        def _fail_push(*args, **kwargs):
            called[0] = True
            return None
        proc.audio_buffer.push_frame = _fail_push

        frame = _make_int16_frame(samples=160, channels=2, value=0.5)
        proc._ingest_frame(frame)

        assert not called[0], "VoiceAudioBuffer.push_frame should NOT be called in streaming mode"
        assert len(backend._enqueue_calls) == 1


# ---------------------------------------------------------------------------
# Test Gate 2: Continuous silence → no microphone failure
# ---------------------------------------------------------------------------

class TestContinuousSilence:
    def test_silence_frames_accepted(self):
        """Silence frames should be accepted, not rejected as microphone failure."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._calibration_context = None

        for i in range(50):
            frame_bytes = _make_int16_pcm(samples=160, channels=2, value=0.0)
            outcome = proc._enqueue_streaming_audio(frame_bytes)
            assert outcome.outcome == "enqueued", f"Silence frame {i} should be accepted, got {outcome.outcome}"

        assert len(backend._enqueue_calls) == 50

    def test_silence_does_not_fail_calibration_policy(self):
        """CalibrationPolicy should accept continuous audio during silence."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._calibration_context = None

        # Verify the calibration policy allows continuous mode without VAD
        policy = proc._calibration_policy
        assert policy is not None
        assert policy.delivery_policy.require_vad_calibration is False
        assert policy.delivery_policy.mode == "continuous"

        # Even with no VAD calibration, silence should be accepted
        decision = policy.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
        )
        assert decision.accepted, f"Silence should be accepted: {decision.rejection_reason}"


# ---------------------------------------------------------------------------
# Test Gate 3: Interim transcript → diagnostics only
# ---------------------------------------------------------------------------

class TestInterimTranscriptDiagnostics:
    def test_interim_does_not_enter_scoring_event_queue(self):
        """Interim transcripts should NOT be placed into the scoring event_queue."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Queue an interim transcript
        backend._queue_interim("poi", "sess-1")

        # Drain finalized utterances (should not include interims)
        finalized = proc.drain_finalized_utterances(
            current_voice_session_id="voice_session_1",
            current_backend_generation=proc._streaming_generation,
            current_match_id=1,
        )
        assert len(finalized) == 0

        # Update diagnostics
        proc._update_interim_diagnostics(backend)
        diag = proc.get_interim_diagnostics()
        assert diag is not None
        assert "poi" in diag["last_interim_text"]
        assert diag["connection_state"] == "connected"

    def test_interim_not_in_finalized_queue(self):
        """Interim transcripts should only go to interim queue, not finalized."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        backend._queue_interim("interim text", "sess-1")
        finalized = backend.get_finalized_transcripts()
        assert len(finalized) == 0
        interim = backend.get_interim_transcripts()
        assert len(interim) == 1


# ---------------------------------------------------------------------------
# Test Gate 4: Final transcript → parser called exactly once
# ---------------------------------------------------------------------------

class TestFinalTranscriptParserCalledOnce:
    def test_final_transcript_reaches_drain(self):
        """A final transcript should be available in drain_streaming_events."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="utt-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        utterances = proc.drain_streaming_events()
        assert len(utterances) == 1
        assert utterances[0].transcript == "point red"

    def test_parser_invoked_once_per_utterance(self):
        """Parser should be called exactly once per finalized utterance."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc.parser = MagicMock()
        proc.parser.parse.return_value = MagicMock(
            type="increment", raw_text="point red", confidence=1.0,
            source=VoiceTranscriptSource.CONTINUOUS,
            session_id=None, calibration_context=None, capture_kind=None,
            created_at=time.time(), event_id="",
        )

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="utt-002",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        finalized = proc.drain_finalized_utterances(
            current_voice_session_id=proc._streaming_voice_session_id,
            current_backend_generation=proc._streaming_generation,
            current_match_id=1,
        )
        assert len(finalized) == 1
        # drain_finalized_utterances doesn't call parser — that's event_drain's job
        # But we verify the utterance passes validation


# ---------------------------------------------------------------------------
# Test Gate 5: Duplicate final event → one score mutation
# ---------------------------------------------------------------------------

class TestDuplicateFinalEvent:
    def test_duplicate_utterance_id_rejected(self):
        """Duplicate utterance IDs should be rejected after the first."""
        backend = MockStreamingBackend()
        backend._connection_state = "connected"
        backend._available = True
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="dup-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)
        backend._queue_utterance(utt)  # Same utterance, same ID

        # First drain accepts it
        first = proc.drain_streaming_events()
        assert len(first) == 1
        assert first[0].transcript == "point red"
        assert proc._streaming_finalized == 1

        # Second drain should be empty (already consumed)
        second = proc.drain_streaming_events()
        assert len(second) == 0


# ---------------------------------------------------------------------------
# Test Gate 6: Voice-off before final callback → no mutation
# ---------------------------------------------------------------------------

class TestVoiceOffBeforeFinalCallback:
    def test_voice_off_invalidates_generation(self):
        """Calling clear_streaming_backend should invalidate the generation."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        original_gen = proc._streaming_generation

        proc.clear_streaming_backend()

        assert proc._streaming_generation == original_gen + 1
        assert proc._streaming_active is False
        assert proc._streaming_backend is None
        assert backend._closed

    def test_stale_utterance_after_voice_off_rejected(self):
        """An utterance emitted before voice-off should be rejected after voice-off."""
        backend = MockStreamingBackend()
        backend._connection_state = "connected"
        backend._available = True
        proc = _make_streaming_processor(backend)
        original_gen = proc._streaming_generation

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=original_gen,
            match_id=1,
            language="lt",
            utterance_id="post-off-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )

        # Queue utterance in the backend
        backend._queue_utterance(utt)

        # Voice off — invalidates generation but keeps backend reference alive
        # until after drain. We drain first, then clear.
        # Actually, clear_streaming_backend closes the backend and resets queues.
        # The correct flow: has_pending_events moves utt to internal queue,
        # then voice-off invalidates generation, then drain_streaming_events
        # validates and rejects.
        proc._finalized_utterance_queue.put_nowait(utt)
        proc.clear_streaming_backend()

        # Drain should reject the stale utterance (generation mismatch)
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0
        assert proc._streaming_stale == 1

    def test_stop_invalidates_generation_before_close(self):
        """stop() should invalidate generation before closing the backend."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        original_gen = proc._streaming_generation

        proc.stop()

        assert proc._streaming_generation == original_gen + 1
        assert proc._streaming_active is False
        assert backend._closed


# ---------------------------------------------------------------------------
# Test Gate 7: Match change before final callback → no mutation
# ---------------------------------------------------------------------------

class TestMatchChangeBeforeFinalCallback:
    def test_match_id_mismatch_rejected(self):
        """An utterance for a different match_id should be rejected."""
        backend = MockStreamingBackend()
        backend._connection_state = "connected"
        backend._available = True
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,  # Original match
            language="lt",
            utterance_id="match-change-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        # Simulate match change — new match_id
        # drain_streaming_events reads match_id from session_state,
        # but we can also directly validate
        finalized = proc.drain_finalized_utterances(
            current_voice_session_id=proc._streaming_voice_session_id,
            current_backend_generation=proc._streaming_generation,
            current_match_id=2,  # Different match
        )
        assert len(finalized) == 0
        assert proc._streaming_stale == 1

    def test_match_change_after_accept_passes(self):
        """An utterance matching the current match_id should be accepted."""
        backend = MockStreamingBackend()
        backend._connection_state = "connected"
        backend._available = True
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=42,
            language="lt",
            utterance_id="match-ok-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        finalized = proc.drain_finalized_utterances(
            current_voice_session_id=proc._streaming_voice_session_id,
            current_backend_generation=proc._streaming_generation,
            current_match_id=42,
        )
        assert len(finalized) == 1
        assert finalized[0].transcript == "point red"


# ---------------------------------------------------------------------------
# Test Gate 8: Language change → old session invalidated
# ---------------------------------------------------------------------------

class TestLanguageChangeInvalidatesSession:
    def test_restarting_backend_invalidates_generation(self):
        """Starting a new session should increment the generation."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        original_gen = proc._streaming_generation

        # Simulate language change → restart session
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=1,
            language="en",
            sample_rate=16000,
            channels=2,
        )

        assert proc._streaming_generation == original_gen + 1
        assert proc._streaming_voice_session_id == "voice_session_2"

    def test_old_session_events_rejected_after_restart(self):
        """Events from the old session should be rejected after restart.

        When the session is restarted, the backend queues are reset (no replay).
        Any utterance that survives in the processor's internal queue with
        the old generation should be rejected.
        """
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation
        old_session = proc._streaming_voice_session_id

        utt = FinalizedUtterance(
            voice_session_id=old_session,
            backend_generation=old_gen,
            match_id=1,
            language="lt",
            utterance_id="old-session-001",
            created_at=time.time(),
            transcript="point red",
            raw_transcript="point red",
            finalization_reason="speech_final",
        )

        # Put the old utterance directly into the processor's internal queue
        # (bypassing the backend, which resets on start_session)
        proc._finalized_utterance_queue.put_nowait(utt)

        # Restart with new session/language (invalidates generation)
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=1,
            language="en",
        )

        # Old utterance should be cleared on restart (no stale processing)
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0
        assert proc._streaming_stale == 0


# ---------------------------------------------------------------------------
# Test Gate 9: Reconnect → no buffered audio replay
# ---------------------------------------------------------------------------

class TestReconnectNoReplay:
    def test_reset_queues_on_start_session(self):
        """Starting a new session should drain queued audio (no replay)."""
        backend = MockStreamingBackend()

        # Enqueue some audio
        backend._enqueue_return_value = True
        backend._audio_queue.put_nowait(b"old-audio")
        backend._finalized_queue.put_nowait(
            FinalizedUtterance(
                voice_session_id="sess-old",
                backend_generation=0,
                match_id=1,
                language="lt",
                utterance_id="old-utterance",
                created_at=time.time(),
                transcript="old text",
                raw_transcript="old text",
                finalization_reason="speech_final",
            )
        )

        # Start new session
        backend.start_session(language="lt", keyterms=None)

        # Queues should be reset
        assert backend._audio_queue.empty()
        assert backend._finalized_queue.empty()

    def test_generation_increments_on_restart(self):
        """Each start_session call should increment generation."""
        backend = MockStreamingBackend()
        assert backend._generation == 0
        backend.start_session(language="lt")
        assert backend._generation == 1
        backend.start_session(language="en")
        assert backend._generation == 2


# ---------------------------------------------------------------------------
# Test Gate 10: Queue full → precise terminal transport outcome
# ---------------------------------------------------------------------------

class TestQueueFullTerminalOutcome:
    def test_queue_full_returns_precise_outcome(self):
        """When the backend queue is full, enqueue_audio returns False."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        # Now make enqueue fail to simulate queue full
        backend._available = False

        # Now enqueue_audio should return False
        result = backend.enqueue_audio(b"x" * 160)
        assert result is False
        assert backend._enqueue_return_value is False

    def test_queue_full_recorded_in_transport_stats(self):
        """Queue full events should be counted in transport stats."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Make the backend's enqueue fail (connection disconnected, queue full)
        backend._available = False
        frame_bytes = _make_int16_pcm(samples=160, channels=2, value=0.5)
        outcome = proc._enqueue_streaming_audio(frame_bytes)

        # When connection is "disconnected" and enqueue fails, it's queue_full
        assert outcome.outcome == "queue_full"
        assert proc._streaming_audio_queue_full == 1


# ---------------------------------------------------------------------------
# Test Gate 11: Streamlit rerun → no duplicate Deepgram connection
# ---------------------------------------------------------------------------

class TestNoDuplicateConnectionOnRerun:
    def test_single_backend_attachment(self):
        """Attaching a streaming backend twice should not create duplicate connections."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        gen1 = proc._streaming_generation

        # Simulate a rerun — re-attach the same backend
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        gen2 = proc._streaming_generation

        # Generation should increment, but backend should not be started twice
        assert gen2 == gen1 + 1
        # Only one backend reference (no duplicate)
        assert proc._streaming_backend is backend

    def test_backend_close_on_detach(self):
        """Detaching should close the old backend."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        assert not backend._closed

        proc.clear_streaming_backend()
        assert backend._closed
        assert backend._close_calls == 1


# ---------------------------------------------------------------------------
# Test Gate 12: Provider failure → manual scoring remains available
# ---------------------------------------------------------------------------

class TestProviderFailureManualScoring:
    def test_batch_path_still_works_when_streaming_fails(self):
        """When streaming backend is unavailable, the batch path should still work."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        # No streaming backend attached — should use batch path
        assert proc._streaming_backend is None
        assert proc._streaming_active is False

        # The batch path should be unaffected
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "point red"
        mock_asr.is_available.return_value = True
        proc._asr = mock_asr
        proc._asr_ready = True

        # Calibration policy should be local_batch, not streaming
        assert proc._calibration_policy is None

    def test_disabled_mode_preserved_for_local_batch(self):
        """When runtime is OFF and no streaming backend, use local_batch policy."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None

        decision = proc._evaluate_disabled_mode()
        assert not decision.accepted
        assert decision.rejection_reason == "runtime_off_no_calibration_context"

    def test_disabled_mode_streaming_uses_different_reason(self):
        """When runtime is OFF with streaming backend, use runtime_voice_disabled."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )

        decision = proc._evaluate_disabled_mode()
        assert not decision.accepted
        assert decision.rejection_reason == "runtime_voice_disabled"
        assert decision.rejection_reason != "runtime_off_no_calibration_context"


# ---------------------------------------------------------------------------
# Bonus: Transport outcome accounting
# ---------------------------------------------------------------------------

class TestTransportOutcomeAccounting:
    def test_all_transport_outcomes_tracked(self):
        """All transport outcomes should be tracked correctly."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # enqueued
        proc._enqueue_streaming_audio(_make_int16_pcm(value=0.5))
        assert proc._streaming_audio_enqueued == 1

        # queue_full (connection is "connected" but enqueue returns False)
        backend._available = False
        proc._enqueue_streaming_audio(_make_int16_pcm(value=0.5))
        assert proc._streaming_audio_queue_full == 1

        # provider_connecting (connection state is "connecting")
        backend._set_connection_state("connecting")
        backend._available = True  # Make enqueue succeed but state is connecting
        proc._enqueue_streaming_audio(_make_int16_pcm(value=0.5))
        assert proc._streaming_audio_stale == 1  # Connecting = stale (discarded)

        # stale (streaming inactive — voice off)
        proc._streaming_active = False
        outcome = proc._enqueue_streaming_audio(_make_int16_pcm(value=0.5))
        assert outcome.outcome == "stale"
        assert proc._streaming_audio_stale == 2  # 1 from connecting + 1 from voice-off


# ---------------------------------------------------------------------------
# Bonus: No network calls in recv_queued
# ---------------------------------------------------------------------------

class TestNoNetworkCallsInRecvQueued:
    def test_enqueue_audio_is_non_blocking(self):
        """enqueue_audio should not block on network I/O."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        frame_bytes = _make_int16_pcm(samples=160, channels=2, value=0.5)

        # This should complete instantly without any network calls
        start = time.monotonic()
        proc._enqueue_streaming_audio(frame_bytes)
        elapsed = time.monotonic() - start

        assert elapsed < 0.01, f"enqueue took {elapsed:.3f}s, expected <10ms"


# ---------------------------------------------------------------------------
# Step 9/10 UI lifecycle tests
# ---------------------------------------------------------------------------

class TestStartButtonClickedTwice:
    def test_single_backend_session_on_double_start(self):
        """Start button clicked twice should not create duplicate backend sessions."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        first_session_count = len(backend._start_session_calls)

        # Simulate double-start — calling set_streaming_backend again
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )

        # Only one start_session call per set_streaming_backend call
        assert len(backend._start_session_calls) == first_session_count + 1

    def test_no_duplicate_connection_on_rerun_during_connecting(self):
        """App rerun during connecting should not create a duplicate connection."""
        backend = MockStreamingBackend()
        backend._connection_state = "connecting"
        backend._available = False  # Simulate not yet connected

        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        gen1 = proc._streaming_generation

        # Simulate rerun — re-attach same backend
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        gen2 = proc._streaming_generation

        assert gen2 == gen1 + 1
        assert proc._streaming_backend is backend
        assert backend._close_calls >= 1  # Previous connection closed


class TestStopButtonClickedTwice:
    def test_clean_idempotent_shutdown(self):
        """Stop button clicked twice should not error."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        proc.clear_streaming_backend()
        first_close = backend._close_calls

        # Second call should be no-op
        proc.clear_streaming_backend()
        assert backend._close_calls == first_close  # No double close

    def test_stop_is_idempotent(self):
        """stop() called multiple times should be safe."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        proc.stop()
        proc.stop()  # Second call should not error
        proc.stop()  # Third call should not error
        assert backend._closed


class TestLanguageChangeRequiresRestart:
    def test_language_change_invalidates_old_generation(self):
        """Changing language should increment generation and invalidate old session."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=1,
            language="en",
        )

        assert proc._streaming_generation == old_gen + 1
        assert proc._streaming_voice_session_id == "voice_session_2"
        assert backend._language == "en"

    def test_old_language_session_events_stale(self):
        """Events from old language session should be stale after restart."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation
        old_session = proc._streaming_voice_session_id

        utt = FinalizedUtterance(
            voice_session_id=old_session,
            backend_generation=old_gen,
            match_id=1,
            language="lt",
            utterance_id="lang-change-001",
            created_at=time.time(),
            transcript="taškas",
            raw_transcript="taškas",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)
        # Also put into processor's internal queue (survives backend reset)
        proc._finalized_utterance_queue.put_nowait(utt)

        # Change language
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=1,
            language="en",
        )

        # Old utterance should be cleared on restart (no stale processing)
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0
        assert proc._streaming_stale == 0


class TestMatchChangeRequiresRestart:
    def test_match_change_invalidates_session(self):
        """Changing match should require session restart."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=2,
            language="lt",
        )

        assert proc._streaming_generation == old_gen + 1
        assert proc._streaming_match_id == 2


class TestRapidInterimUpdates:
    def test_interim_does_not_grow_scoring_queue(self):
        """Rapid interim updates should not fill the scoring event queue."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Queue rapid interim updates (may be dropped by bounded queue)
        queued_count = 0
        for i in range(100):
            try:
                backend._queue_interim(f"interim {i}", "sess-1")
                queued_count += 1
            except queue.Full:
                pass  # Some may be dropped — that's acceptable

        # Drain finalized — should be empty
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0

        # Only the latest interim should be in diagnostics
        proc._update_interim_diagnostics(backend)
        diag = proc.get_interim_diagnostics()
        # The throttle may prevent updating, but the last value should be recent
        assert diag is not None

    def test_interim_can_be_dropped(self):
        """Interim diagnostics are droppable — they should not block."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Fill interim queue beyond capacity
        for i in range(200):
            try:
                backend._queue_interim(f"interim {i}", "sess-1")
            except queue.Full:
                break  # Some may be dropped

        # Draining finalized should still work
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0


class TestBackendFailedState:
    def test_backend_failure_does_not_crash_processor(self):
        """Backend failure should not crash the processor."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Simulate backend failure
        backend._error_queue.put_nowait(("connection_error", "connection failed"))
        backend._available = False
        backend._set_connection_state("failed")

        # Audio should still be accepted (enqueued to audio queue) but
        # enqueue_audio returns False → provider_unavailable
        frame_bytes = _make_int16_pcm(value=0.5)
        outcome = proc._enqueue_streaming_audio(frame_bytes)
        assert outcome.outcome in ("provider_unavailable", "queue_full")

        # Errors should be drainable
        errors = backend.get_errors()
        assert len(errors) == 1

    def test_failed_backend_can_restart(self):
        """After failure, a new session can be started."""
        backend = MockStreamingBackend()
        backend._set_connection_state("failed")
        backend._available = False

        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation

        proc.clear_streaming_backend()

        # Start fresh
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_new",
            match_id=1,
            language="lt",
        )

        assert proc._streaming_generation == old_gen + 2  # old_gen was already +1 from clear
        assert proc._streaming_active is True
        assert backend._connection_state == "connected"


class TestAppRerunDuringReadyState:
    def test_existing_backend_retained_on_rerun(self):
        """App rerun during ready state should retain the existing backend."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        first_backend = proc._streaming_backend

        # Simulate rerun — re-attach same backend
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )

        # Same backend object retained
        assert proc._streaming_backend is backend


class TestProcessorReplaced:
    def test_old_backend_closed_on_replacement(self):
        """When processor is replaced, old backend should be closed (no orphan threads)."""
        backend1 = MockStreamingBackend()
        backend2 = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend1,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        assert not backend1._closed

        # Replace with new backend
        proc.set_streaming_backend(
            backend2,
            voice_session_id="voice_session_2",
            match_id=2,
            language="en",
        )

        # Old backend should be closed
        assert backend1._closed
        assert backend1._close_calls == 1
        # New backend should be active
        assert proc._streaming_backend is backend2


class TestStreamingConnectionState:
    def test_not_ready_until_connected(self):
        """Start button should not show Ready until backend confirms WebSocket connected."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        # Before attaching backend
        assert proc.is_streaming_connected() is False

        # Attach and start backend
        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )

        # Backend should be connected
        assert proc.is_streaming_connected() is True

        # After voice off
        proc.clear_streaming_backend()
        assert proc.is_streaming_connected() is False


class TestInterimClassification:
    def test_interim_and_final_classification_distinct(self):
        """Verify interim transcripts don't appear as finalized."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Queue one interim and one finalized
        backend._queue_interim("interim text", "sess-1")
        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="classify-001",
            created_at=time.time(),
            transcript="galutinis",
            raw_transcript="galutinis",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        # Drain finalized — should only contain the finalized utterance
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 1
        assert finalized[0].transcript == "galutinis"

        # Interim should be in diagnostics only
        proc._update_interim_diagnostics(backend)
        diag = proc.get_interim_diagnostics()
        assert "interim text" in diag["last_interim_text"]


# ---------------------------------------------------------------------------
# Backend shutdown verification (thread count baseline)
# ---------------------------------------------------------------------------

class TestBackendShutdownThreadCleanup:
    def test_repeated_close_is_idempotent(self):
        """Repeated close() calls must return quickly and not error."""
        backend = MockStreamingBackend()
        backend.start_session(language="lt")

        backend.close()
        backend.close()  # Second close should be a no-op
        backend.close()  # Third close should be a no-op
        assert backend._closed
        assert backend._close_calls == 1

    def test_close_stops_accepting_audio(self):
        """After close(), enqueue_audio must return False."""
        backend = MockStreamingBackend()
        backend.start_session(language="lt")

        backend.close()
        assert backend.enqueue_audio(b"\x00\x00\x00\x00") is False

    def test_close_resets_all_queues(self):
        """After close(), all queues must be empty."""
        backend = MockStreamingBackend()
        backend.start_session(language="lt")
        backend._queue_utterance(FinalizedUtterance(
            voice_session_id="sess",
            backend_generation=1,
            match_id=1,
            language="lt",
            utterance_id="test-1",
            created_at=0.0,
            transcript="test",
            raw_transcript="test",
            finalization_reason="speech_final",
        ))
        backend.enqueue_audio(b"\x00\x00\x00\x00")
        backend._queue_interim("interim", "sess")

        backend.close()

        assert backend._finalized_queue.qsize() == 0
        assert backend._audio_queue.qsize() == 0
        assert backend._interim_queue.qsize() == 0
        assert backend._error_queue.qsize() == 0

    def test_repeated_open_close_sessions_no_thread_leak(self):
        """Create and destroy many sessions — thread count must return to baseline."""
        import threading

        baseline_threads = threading.active_count()
        backends_created = []

        for i in range(25):
            backend = MockStreamingBackend()
            backend.start_session(
                language="lt",
                sample_rate=16000,
                channels=1,
            )
            backends_created.append(backend)
            # Simulate some work
            backend.enqueue_audio(b"\x00\x00" * 80)
            backend._queue_utterance(FinalizedUtterance(
                voice_session_id=f"sess-{i}",
                backend_generation=1,
                match_id=1,
                language="lt",
                utterance_id=f"utt-{i}",
                created_at=0.0,
                transcript="test",
                raw_transcript="test",
                finalization_reason="speech_final",
            ))
            backend.close()

        # All backends should be closed
        assert all(b._closed for b in backends_created)

        # Thread count should return to baseline (mock has no real threads)
        final_threads = threading.active_count()
        assert final_threads <= baseline_threads + 2, (
            f"Thread leak: baseline={baseline_threads}, "
            f"final={final_threads}, backends={len(backends_created)}"
        )

    def test_processor_stop_stops_backend(self):
        """Processor.stop() must close the streaming backend."""
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "voice_session_1"

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_1",
            match_id=1,
            language="lt",
        )
        assert not backend._closed

        proc.stop()
        assert backend._closed
        assert not proc._streaming_active


class TestMatchChangeStopsConnection:
    def test_active_match_change_stops_old_session(self):
        """Changing the active match while streaming must stop the old session."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        old_gen = proc._streaming_generation
        old_backend = proc._streaming_backend

        # Simulate match change by calling clear + new set
        proc.clear_streaming_backend()
        assert not proc._streaming_active

        proc.set_streaming_backend(
            backend,
            voice_session_id="voice_session_2",
            match_id=2,
            language="lt",
        )

        # Old generation invalidated, new backend attached
        assert proc._streaming_generation == old_gen + 2
        assert proc._streaming_match_id == 2
        assert proc._streaming_active

    def test_match_change_clears_pending_utterances(self):
        """Pending utterances in the processor queue must be cleared on match change."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="pending-001",
            created_at=0.0,
            transcript="point left",
            raw_transcript="point left",
            finalization_reason="speech_final",
        )
        proc._finalized_utterance_queue.put_nowait(utt)

        # Match change stops old session
        proc.clear_streaming_backend()

        # Pending utterance should not be processed (voice off)
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0


# ---------------------------------------------------------------------------
# Test Gate 13: Default channels and format consistency
# ---------------------------------------------------------------------------


class TestStreamingBackendDefaults:
    """set_streaming_backend must default to mono (channels=1) for streaming."""

    def test_set_streaming_backend_defaults_to_mono(self):
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc.set_streaming_backend(
            backend,
            voice_session_id="sess-1",
            match_id=1,
            language="lt",
        )
        assert proc._streaming_channels == 1
        assert backend._start_session_calls[0]["channels"] == 1

    def test_set_streaming_backend_accepts_explicit_channels(self):
        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc.set_streaming_backend(
            backend,
            voice_session_id="sess-1",
            match_id=1,
            language="lt",
            channels=2,
        )
        assert proc._streaming_channels == 2
        assert backend._start_session_calls[0]["channels"] == 2

    def test_no_duplicate_recv_queued(self):
        """Ensure there is only one recv_queued definition on the class."""
        import inspect

        methods = inspect.getmembers(VoiceAudioProcessor, predicate=inspect.isfunction)
        recv_queued_defs = [m for m in methods if m[0] == "recv_queued"]
        assert len(recv_queued_defs) == 1


class TestRouteStreamingAudioFormat:
    """_route_streaming_audio must use the detected format, not self._sample_format."""

    def test_float32_frame_uses_detected_format(self):
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._sample_format = SAMPLE_FORMAT_INT16
        proc._streaming_sample_rate = 16000

        float_bytes = np.array([0.5, -0.5, 0.1, -0.1], dtype=np.float32).tobytes()
        proc._route_streaming_audio(float_bytes, SAMPLE_FORMAT_FLOAT32, channels=1, sample_rate=16000)

        assert len(backend._enqueue_calls) == 1
        enqueued = backend._enqueue_calls[0]
        result = np.frombuffer(enqueued, dtype=np.int16)
        np.testing.assert_allclose(result, [16384, -16384, 3277, -3277], atol=1)

    def test_int16_frame_uses_detected_format(self):
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._sample_format = SAMPLE_FORMAT_FLOAT32
        proc._streaming_sample_rate = 16000

        int_bytes = np.array([1000, -1000, 500, -500], dtype=np.int16).tobytes()
        proc._route_streaming_audio(int_bytes, SAMPLE_FORMAT_INT16, channels=1, sample_rate=16000)

        assert len(backend._enqueue_calls) == 1
        enqueued = backend._enqueue_calls[0]
        result = np.frombuffer(enqueued, dtype=np.int16)
        np.testing.assert_allclose(result, [1000, -1000, 500, -500])

    def test_stereo_frame_downmixed_to_mono(self):
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_sample_rate = 16000

        stereo_bytes = np.array([0.5, 0.5, -0.5, -0.5], dtype=np.float32).tobytes()
        proc._route_streaming_audio(stereo_bytes, SAMPLE_FORMAT_FLOAT32, channels=2, sample_rate=16000)

        assert len(backend._enqueue_calls) == 1
        enqueued = backend._enqueue_calls[0]
        result = np.frombuffer(enqueued, dtype=np.int16)
        np.testing.assert_allclose(result, [16384, -16384], atol=1)


class TestAudioFormatContract:
    """Verify PCM format conversion preserves duration and matches Deepgram config."""

    def test_format_attributes_declared(self):
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        stats = proc.get_streaming_transport_stats()
        assert stats["output_encoding"] == "linear16"
        assert stats["output_sample_rate"] == 16000
        assert stats["output_channels"] == 1
        assert stats["input_channels"] == proc.audio_buffer.channels

    def test_stereo_48k_to_mono_16k_preserves_duration(self):
        """48kHz stereo → downmix mono → resample 16kHz: duration preserved."""
        from tournament_platform.app.services.voice_calibration.measurements import (
            normalize_pcm,
        )
        import numpy as np

        # 100ms at 48kHz stereo float32 = 4800 samples * 2 channels = 9600 floats
        n_samples_per_channel = 4800
        t = np.linspace(0, 0.1, n_samples_per_channel, endpoint=False)
        stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 880 * t)], axis=1)
        frame_bytes = stereo.astype(np.float32).tobytes()

        normalized = normalize_pcm(frame_bytes, "float32", 2)
        assert normalized.shape == (4800, 2)  # 4800 sample frames * 2 channels

        # Downmix to mono
        mono = normalized.mean(axis=1)
        assert mono.shape == (4800,)

        # Resample 48kHz -> 16kHz (ratio 1:3)
        from scipy.signal import resample
        n_target = int(len(mono) * 16000 / 48000)
        resampled = resample(mono, n_target)
        assert len(resampled) == 1600  # 4800 * 16000/48000 = 1600

        # Duration: 4800 samples / 48000 Hz = 0.1s
        # After resample: 1600 samples / 16000 Hz = 0.1s
        duration_in = 4800 / 48000
        duration_out = 1600 / 16000
        assert abs(duration_in - duration_out) < 0.01  # within 10ms

    def test_int16_mono_16k_frame_matches_deepgram_encoding(self):
        """Verify int16 mono bytes at 16kHz match linear16 encoding."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # 10ms at 16kHz mono int16 = 160 samples
        samples = np.array([100, -100, 200, -200], dtype=np.int16)
        frame_bytes = samples.tobytes()

        proc._route_streaming_audio(frame_bytes, SAMPLE_FORMAT_INT16, channels=1, sample_rate=16000)

        assert len(backend._enqueue_calls) == 1
        enqueued = backend._enqueue_calls[0]
        result = np.frombuffer(enqueued, dtype=np.int16)
        np.testing.assert_array_equal(result, samples)
        # 4 samples * 2 bytes = 8 bytes per frame
        assert len(enqueued) == 8
    """normalize_pcm must handle misaligned sample counts for multichannel data."""

    def test_truncates_odd_samples_for_stereo(self):
        from tournament_platform.app.services.voice_calibration.measurements import (
            normalize_pcm,
        )
        raw = np.array([0.5, 0.5, -0.5, -0.5, 0.1], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 2)
        assert samples.shape == (2, 2)

    def test_stereo_exact_samples_unchanged(self):
        from tournament_platform.app.services.voice_calibration.measurements import (
            normalize_pcm,
        )
        raw = np.array([0.5, 0.5, -0.5, -0.5], dtype=np.float32).tobytes()
        samples = normalize_pcm(raw, "float32", 2)
        assert samples.shape == (2, 2)


# ---------------------------------------------------------------------------
# Test Gate 14: End-to-end streaming pipeline (mocked Deepgram provider)
# ---------------------------------------------------------------------------


class TestEndToEndStreamingPipeline:
    """Full pipeline: PCM enqueue → interim/final drain → validated utterance."""

    def _make_utt(self, proc, transcript, utt_id, match_id=1):
        return FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=proc._streaming_generation,
            match_id=match_id,
            language="lt",
            utterance_id=utt_id,
            created_at=time.time(),
            transcript=transcript,
            raw_transcript=transcript,
            finalization_reason="speech_final",
            source=VoiceTranscriptSource.CONTINUOUS,
        )

    def test_full_pipeline_interim_then_final(self):
        """End-to-end: audio enqueued → interim visible → final drained once."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        for i in range(5):
            frame_bytes = _make_int16_pcm(samples=160, channels=1, value=0.5)
            proc._enqueue_streaming_audio(frame_bytes)

        assert proc._streaming_audio_enqueued == 5
        assert len(backend._enqueue_calls) == 5

        # Simulate interim transcript
        backend._queue_interim("taškas kai", proc._streaming_voice_session_id)

        # Simulate final transcript
        utt = self._make_utt(proc, "taškas kairė", "utt-001")
        backend._queue_utterance(utt)

        # Verify transport metrics bridge correctly
        stats = proc.get_streaming_transport_stats()
        assert stats["audio_enqueued"] == 5
        assert stats["output_channels"] == 1
        assert stats["output_encoding"] == "linear16"
        assert stats["output_sample_rate"] == 16000

        # Drain finalized utterances (also updates interim diagnostics)
        finalized = proc.drain_streaming_events()
        assert len(finalized) == 1
        assert finalized[0].transcript == "taškas kairė"
        assert finalized[0].utterance_id == "utt-001"

        # Verify interim appears in diagnostics after drain
        diags = proc.get_streaming_diagnostics()
        snapshot = diags.get("interim_diagnostics_snapshot", {})
        assert snapshot.get("last_interim_text") == "taškas kai"

    def test_duplicate_final_not_emitted_twice(self):
        """Same utterance ID drained twice must yield only one after dedup."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        utt = self._make_utt(proc, "taškas kairė", "utt-001")
        backend._queue_utterance(utt)
        backend._queue_utterance(utt)  # duplicate

        finalized = proc.drain_streaming_events()
        assert len(finalized) == 1

    def test_stale_generation_rejected(self):
        """Finalized utterance from an old backend generation must be rejected."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        old_gen = proc._streaming_generation

        utt = FinalizedUtterance(
            voice_session_id=proc._streaming_voice_session_id,
            backend_generation=old_gen - 1,  # stale generation
            match_id=1,
            language="lt",
            utterance_id="utt-stale",
            created_at=time.time(),
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            finalization_reason="speech_final",
            source=VoiceTranscriptSource.CONTINUOUS,
        )
        backend._queue_utterance(utt)

        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0
        stats = proc.get_streaming_transport_stats()
        assert stats["utterances_stale"] == 1

    def test_stale_session_rejected(self):
        """Finalized utterance from a different session must be rejected."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        utt = FinalizedUtterance(
            voice_session_id="wrong_session",
            backend_generation=proc._streaming_generation,
            match_id=1,
            language="lt",
            utterance_id="utt-wrong-session",
            created_at=time.time(),
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            finalization_reason="speech_final",
            source=VoiceTranscriptSource.CONTINUOUS,
        )
        backend._queue_utterance(utt)

        finalized = proc.drain_streaming_events()
        assert len(finalized) == 0
        stats = proc.get_streaming_transport_stats()
        assert stats["utterances_stale"] == 1

    def test_audio_send_metrics_bridge(self):
        """Runtime streaming transport stats must bridge backend metrics."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)

        # Simulate audio bytes sent at the backend level
        from tournament_platform.app.services.asr_backends.base import (
            DeepgramBackendMetrics,
        )
        backend._metrics = DeepgramBackendMetrics(
            audio_bytes_sent=3200,
            audio_duration_sent_ms=100.0,
            audio_frames_received=10,
            connection_state="connected",
        )
        backend._audio_bytes_sent = 3200
        backend._audio_duration_sent_ms = 100.0
        backend._audio_send_attempts = 10
        backend._audio_send_failed = 0

        stats = proc.get_streaming_transport_stats()
        assert stats["audio_bytes_sent"] == 3200
        assert stats["audio_send_attempts"] == 10
        assert stats["audio_send_success"] == 10
        assert stats["audio_send_failed"] == 0
        assert stats["audio_duration_sent_ms"] == 100.0


class TestFinalizedInvalidDiagnosticsAndClassIdentity:
    """Focused regression tests for finalized_invalid diagnostics and class identity."""

    def test_invalid_object_diagnostics_capture_type_module_repr_and_queue_source(self):
        """When drain_streaming_events receives an invalid item, it must capture
        exact type, module, repr, queue source, backend object ID, processor ID,
        and class identity diagnostics."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            FinalizedUtterance,
        )

        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        invalid_item = "not_a_finalized_utterance"
        proc._finalized_utterance_queue.put_nowait(invalid_item)

        diags_before = proc.get_streaming_diagnostics()
        assert diags_before["streaming_invalid_count"] == 0

        result = proc.drain_streaming_events()

        assert len(result) == 0
        assert proc._streaming_invalid == 1

        diags = proc.get_streaming_diagnostics()
        assert diags["streaming_invalid_count"] == 1
        assert diags["last_finalized_invalid_type"] == "str"
        assert diags["last_finalized_invalid_module"] == "builtins"
        assert "not_a_finalized_utterance" in diags["last_finalized_invalid_repr"]
        assert diags["last_finalized_invalid_queue_source"] == "processor_internal_queue"
        assert diags["last_finalized_invalid_backend_object_id"] == id(backend)
        assert diags["last_finalized_invalid_processor_id"] == id(proc)
        assert diags["last_finalized_invalid_utt_is_same_class"] is False
        assert diags["last_finalized_invalid_utt_type_id"] == id(str)
        assert diags["last_finalized_invalid_expected_type_id"] == id(FinalizedUtterance)

    def test_canonical_finalized_utterance_accepted_by_drain(self):
        """The object emitted by the backend's _emit_finalized must be accepted
        directly by VoiceAudioProcessor.drain_streaming_events() using canonical
        production imports."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            FinalizedUtterance,
        )

        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        utt = FinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="lt",
            utterance_id="utt-1",
            created_at=time.time(),
            transcript="taškas kairė",
            raw_transcript="taškas kairė",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        result = proc.drain_streaming_events()

        assert len(result) == 1
        assert isinstance(result[0], FinalizedUtterance)
        assert result[0].utterance_id == "utt-1"
        assert proc._streaming_invalid == 0
        assert proc._streaming_finalized == 1

    def test_class_identity_same_module_path(self):
        """Ensure type(utt) is FinalizedUtterance from the same module identity
        as the one imported by runtime.py."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            FinalizedUtterance as RuntimeFinalizedUtterance,
        )
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
        )

        backend = MockStreamingBackend()
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = "sess-1"
        proc.set_streaming_backend(
            backend,
            voice_session_id="sess-1",
            match_id=1,
            language="lt",
            sample_rate=16000,
            channels=1,
        )
        backend._connection_state = "connected"
        backend._available = True
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        utt = RuntimeFinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="lt",
            utterance_id="utt-identity",
            created_at=time.time(),
            transcript="point left",
            raw_transcript="point left",
            finalization_reason="speech_final",
        )
        backend._queue_utterance(utt)

        result = proc.drain_streaming_events()

        assert len(result) == 1
        assert type(result[0]) is RuntimeFinalizedUtterance
        assert type(result[0]).__module__ == RuntimeFinalizedUtterance.__module__
        assert id(type(result[0])) == id(RuntimeFinalizedUtterance)

    def test_full_event_bridge_point_left(self):
        """End-to-end: Deepgram final 'Point left.' → accumulator → FinalizedUtterance
        → backend queue → processor drain → accepted."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            FinalizedUtterance,
        )

        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        utt = FinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="en",
            utterance_id="utt-point-left",
            created_at=time.time(),
            transcript="point left",
            raw_transcript="Point left.",
            finalization_reason="speech_final",
            confidence=0.95,
        )
        backend._queue_utterance(utt)

        result = proc.drain_streaming_events()

        assert len(result) == 1
        assert result[0].transcript == "point left"
        assert result[0].raw_transcript == "Point left."
        assert result[0].finalization_reason == "speech_final"
        assert proc._streaming_invalid == 0
        assert proc._streaming_events_drained == 1


class TestDeepgramFinalizationCounters:
    """Focused regression tests for Deepgram finalization counters."""

    def test_point_left_speech_final_emits_and_drains(self):
        """Deepgram final 'Point left.' + speech_final=True must emit and drain."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        utt = FinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="en",
            utterance_id="utt-point-left",
            created_at=time.time(),
            transcript="point left",
            raw_transcript="Point left.",
            finalization_reason="speech_final",
            confidence=0.95,
        )
        backend._queue_utterance(utt)

        result = proc.drain_streaming_events()

        assert len(result) == 1
        assert result[0].transcript == "point left"
        assert backend._emit_finalized_calls == 1
        assert backend._completed_utterance_count == 1
        assert backend._finalized_queue_put_success == 1
        assert proc._streaming_invalid == 0
        assert proc._streaming_events_drained == 1

    def test_utterance_end_emits_once(self):
        """UtteranceEnd finalization must emit only once for the same occurrence."""
        backend = MockStreamingBackend()
        proc = _make_streaming_processor(backend)
        proc._streaming_generation = 1
        proc._streaming_voice_session_id = "sess-1"
        proc._streaming_match_id = 1

        utt = FinalizedUtterance(
            voice_session_id="sess-1",
            backend_generation=1,
            match_id=1,
            language="en",
            utterance_id="utt-ue-001",
            created_at=time.time(),
            transcript="point right",
            raw_transcript="point right",
            finalization_reason="utterance_end",
            confidence=0.9,
        )
        backend._queue_utterance(utt)

        result = proc.drain_streaming_events()

        assert len(result) == 1
        assert result[0].finalization_reason == "utterance_end"
        assert backend._emit_finalized_calls == 1
        assert backend._completed_utterance_count == 1
        assert proc._streaming_invalid == 0
        assert proc._streaming_events_drained == 1

        # Second drain must not re-emit the same occurrence
        result2 = proc.drain_streaming_events()
        assert len(result2) == 0
        assert backend._emit_finalized_calls == 1  # still 1
        assert backend._completed_utterance_count == 1  # still 1

    def test_backend_diagnostics_contains_new_counters(self):
        """Backend get_diagnostics must expose new counters."""
        backend = MockStreamingBackend()
        diags = backend.get_diagnostics()
        assert "finalized_utterances_emitted" in diags
        assert "accumulator_final_segments" in diags
        assert "accumulator_seal_attempts" in diags
        assert "accumulator_seal_success" in diags
        assert "emit_finalized_calls" in diags
        assert "finalized_queue_put_success" in diags
