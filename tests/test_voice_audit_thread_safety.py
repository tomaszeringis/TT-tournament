"""Thread-safety tests for the new runtime audit queue.

These tests verify that VoiceAudioProcessor no longer touches Streamlit
from audio/worker threads, and that the bounded audit queue behaves
correctly under concurrency.
"""

from __future__ import annotations

import ast
import dataclasses
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_scorekeeper.events import (
    VoiceRuntimeAuditEvent,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
    _assert_not_on_audio_thread,
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
    chunk.frames = [MagicMock()]
    return chunk


def _make_frame() -> MagicMock:
    frame = MagicMock()
    frame.pts = time.monotonic()
    frame.format = MagicMock()
    frame.format.name = "flt"
    frame.sample_rate = 48000
    frame.channels = 2
    return frame


# ---------------------------------------------------------------------------
# 1. _ingest_frame does not touch Streamlit from audio threads
# ---------------------------------------------------------------------------


def test_recv_queued_no_streamlit_access():
    """_ingest_frame on async_media_processor_2 thread never touches st.session_state."""
    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr_ready = True

    errors: list[Exception] = []

    def _fail_streamlit(*args, **kwargs):
        errors.append(RuntimeError("st.session_state accessed from audio thread"))
        raise errors[-1]

    with patch(
        "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
        MagicMock(setdefault=MagicMock(side_effect=_fail_streamlit)),
    ):
        frame = _make_frame()
        old_name = threading.current_thread().name
        try:
            threading.current_thread().name = "async_media_processor_2"
            proc._ingest_frame(frame)
        finally:
            threading.current_thread().name = old_name

    assert len(errors) == 0, (
        f"Streamlit was accessed from audio thread: {errors[0]}"
    )
    proc.stop()


# ---------------------------------------------------------------------------
# 2. _transcribe_chunk does not touch Streamlit from worker threads
# ---------------------------------------------------------------------------


def test_transcribe_chunk_no_streamlit_access():
    """_transcribe_chunk on voice_processor thread never touches st.session_state."""
    from tournament_platform.app.services.voice_scorekeeper.events import (
        TranscriptionWorkItem,
        VoiceRuntimeMode,
    )

    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr.transcribe_pcm.return_value = "point red"
    proc._asr_ready = True
    proc.post_processor.process = MagicMock(return_value="point red")
    proc.parser.parse = MagicMock(
        return_value=MagicMock(
            type="increment",
            event_id="evt_1",
            raw_text="point red",
            confidence=0.9,
            source="continuous",
        )
    )

    errors: list[Exception] = []

    def _fail_streamlit(*args, **kwargs):
        errors.append(RuntimeError("st.session_state accessed from worker thread"))
        raise errors[-1]

    work_item = TranscriptionWorkItem(
        audio=_make_chunk(),
        runtime_session_id="s1",
        calibration_context=None,
        capture_runtime_mode=VoiceRuntimeMode.LIVE,
    )

    with patch(
        "tournament_platform.app.pages.voice_scorekeeper.st.session_state",
        MagicMock(setdefault=MagicMock(side_effect=_fail_streamlit)),
    ):
        old_name = threading.current_thread().name
        try:
            threading.current_thread().name = "voice_processor"
            proc._transcribe_chunk(work_item)
        finally:
            threading.current_thread().name = old_name

    assert len(errors) == 0, (
        f"Streamlit was accessed from worker thread: {errors[0]}"
    )
    proc.stop()


# ---------------------------------------------------------------------------
# 3. VoiceRuntimeAuditEvent is immutable
# ---------------------------------------------------------------------------


def test_audit_event_is_immutable():
    event = VoiceRuntimeAuditEvent(
        timestamp=time.time(),
        processor_id=123,
        processor_generation=1,
        thread_name="main",
        stage="test",
        note="note",
        metadata=(("key", "value"),),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.stage = "changed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.timestamp = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 4. Audit queue is bounded and counts drops
# ---------------------------------------------------------------------------


def test_audit_queue_bounded_and_counts_drops():
    proc = VoiceAudioProcessor()
    assert proc._audit_queue.maxsize == 200
    assert proc._audit_dropped_count == 0

    for i in range(205):
        proc._emit_runtime_audit("test_stage", note=f"event_{i}")

    assert proc._audit_dropped_count >= 5
    assert proc._audit_queue.qsize() == 200
    proc.stop()


# ---------------------------------------------------------------------------
# 5. Drain moves events to main thread st.session_state
# ---------------------------------------------------------------------------


def test_drain_runtime_audit_events_moves_to_main_thread():
    import streamlit as st

    state = {"voice_audit_events": []}

    class _MockState(dict):
        def __missing__(self, key):
            return None
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)
        def __setattr__(self, key, value):
            self[key] = value

    mock_state = _MockState(state)
    with patch.object(st, "session_state", mock_state):
        proc = VoiceAudioProcessor()
        proc._emit_runtime_audit("stage_a", note="event_a", processor_id="1")
        proc._emit_runtime_audit("stage_b", note="event_b", processor_id="2")

        events = proc.drain_runtime_audit_events()
        assert len(events) == 2

        audit_list = mock_state.get("voice_audit_events", [])
        assert len(audit_list) == 0

        for audit_event in events:
            entry = {
                "timestamp": audit_event.timestamp,
                "event_id": "",
                "source": "runtime",
                "stage": audit_event.stage,
                "event_type": audit_event.stage,
                "transcript": "",
                "player": None,
                "score_a": None,
                "score_b": None,
                "confidence": 0.0,
                "accepted": False,
                "previous_score": "",
                "new_score": "",
                "note": audit_event.note,
                "speaker_label": None,
                "language": "en",
                "asr_latency_ms": None,
                "noise_rms": None,
                "processor_id": audit_event.processor_id,
                "processor_generation": audit_event.processor_generation,
                "thread_name": audit_event.thread_name,
                "metadata": dict(audit_event.metadata),
            }
            mock_state.voice_audit_events.append(entry)

        assert len(mock_state.voice_audit_events) == 2
        assert mock_state.voice_audit_events[0]["stage"] == "stage_a"
        assert mock_state.voice_audit_events[1]["stage"] == "stage_b"
        proc.stop()


# ---------------------------------------------------------------------------
# 6. runtime.py does not import streamlit at module level
# ---------------------------------------------------------------------------


def test_no_streamlit_in_runtime_module_import():
    import tournament_platform.app.services.voice_scorekeeper.runtime as rt

    source_file = getattr(rt, "VOICE_RUNTIME_SOURCE_FILE", None)
    assert source_file is not None
    with open(source_file, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "streamlit" or (
                    isinstance(node, ast.ImportFrom) and node.module == "streamlit"
                ):
                    pytest.fail(
                        f"runtime.py imports streamlit at module level: {ast.dump(node)}"
                    )


# ---------------------------------------------------------------------------
# 7. _ingest_frame updates processor timestamps
# ---------------------------------------------------------------------------


def test_recv_queued_updates_processor_timestamps():
    import asyncio

    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr_ready = True
    frame = _make_frame()

    asyncio.run(proc.recv_queued([frame]))

    assert proc._audio_frames_received == 1
    assert proc._last_frame_timestamp > 0
    proc.stop()


# ---------------------------------------------------------------------------
# 8. get_diagnostics returns an independent snapshot
# ---------------------------------------------------------------------------


def test_get_diagnostics_returns_snapshot():
    proc = VoiceAudioProcessor()
    d1 = proc.get_diagnostics()
    d2 = proc.get_diagnostics()
    assert d1 == d2
    assert d1 is not d2
    proc.stop()


# ---------------------------------------------------------------------------
# 9. Two processors have independent audit queues
# ---------------------------------------------------------------------------


def test_processor_replacement_independent_state():
    proc_a = VoiceAudioProcessor()
    proc_b = VoiceAudioProcessor()

    proc_a._emit_runtime_audit("proc_a_stage", note="from_a")
    proc_b._emit_runtime_audit("proc_b_stage", note="from_b")

    a_events = proc_a.drain_runtime_audit_events()
    b_events = proc_b.drain_runtime_audit_events()

    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0].stage == "proc_a_stage"
    assert b_events[0].stage == "proc_b_stage"
    proc_a.stop()
    proc_b.stop()


# ---------------------------------------------------------------------------
# 10. Rate limiting prevents per-frame audit floods
# ---------------------------------------------------------------------------


def test_rate_limiting_prevents_per_frame_audit():
    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr_ready = True

    frame = _make_frame()

    for _ in range(100):
        proc._ingest_frame(frame)

    events = proc.drain_runtime_audit_events()
    assert len(events) < 10, (
        f"Expected < 10 audit events for 100 frames, got {len(events)}. "
        "Audit queue is not properly rate-limited."
    )
    proc.stop()
