"""Streamlit context guard tests.

Verify that the audio processor never touches Streamlit APIs from
audio/worker threads, which would trigger missing ScriptRunContext
warnings.
"""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
)
from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32


def _make_frame() -> MagicMock:
    frame = MagicMock()
    frame.pts = time.monotonic()
    frame.format = MagicMock()
    frame.format.name = "flt"
    frame.sample_rate = 48000
    frame.channels = 2
    return frame


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


# ---------------------------------------------------------------------------
# 11. Streamlit API fails from audio thread do NOT happen
# ---------------------------------------------------------------------------


def test_streamlit_api_fails_from_audio_thread():
    """Monkeypatch st.session_state to raise from async_media_processor_2,
    run recv_queued, and assert no exception is raised (no Streamlit access)."""
    import streamlit as st

    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr_ready = True

    errors: list[Exception] = []

    def _fail_streamlit(*args, **kwargs):
        err = RuntimeError("st.session_state accessed from audio thread")
        errors.append(err)
        raise err

    frames = [_make_frame(), _make_frame()]
    for frame in frames:
        frame.pts = time.monotonic()

    with patch.object(
        st,
        "session_state",
        MagicMock(setdefault=MagicMock(side_effect=_fail_streamlit)),
    ):
        import asyncio

        old_name = threading.current_thread().name
        try:
            threading.current_thread().name = "async_media_processor_2"
            asyncio.run(proc.recv_queued(frames))
        finally:
            threading.current_thread().name = old_name

    assert len(errors) == 0, (
        "st.session_state was accessed from audio thread. "
        "This indicates a missing thread-safety guard."
    )
    proc.stop()


# ---------------------------------------------------------------------------
# 12. No ScriptRunContext warnings in logs during background processing
# ---------------------------------------------------------------------------


def test_no_script_run_ctx_warning_in_logs(caplog: pytest.LogCaptureFixture):
    """Run recv_queued on a named background thread, capture logs,
    and assert no 'missing ScriptRunContext' or 'NoSessionContext' warnings."""
    proc = VoiceAudioProcessor()
    proc._asr = MagicMock()
    proc._asr_ready = True

    frames = [_make_frame()]
    for frame in frames:
        frame.pts = time.monotonic()

    old_thread_name = threading.current_thread().name
    try:
        threading.current_thread().name = "async_media_processor_2"
        with caplog.at_level(logging.WARNING, logger="streamlit"):
            import asyncio

            asyncio.run(proc.recv_queued(frames))
    finally:
        threading.current_thread().name = old_thread_name

    proc.stop()

    combined_logs = "\n".join(
        record.getMessage() for record in caplog.records
    )
    assert "missing ScriptRunContext" not in combined_logs, (
        "Streamlit 'missing ScriptRunContext' warning detected in logs. "
        "This indicates Streamlit was accessed from a non-main thread."
    )
    assert "NoSessionContext" not in combined_logs, (
        "Streamlit 'NoSessionContext' warning detected in logs. "
        "This indicates Streamlit session_state was accessed from a non-main thread."
    )
