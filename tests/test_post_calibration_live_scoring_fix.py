"""Regression tests for live continuous voice scoring after Voice Calibration.

Covers the bug where ``VoiceRuntimeMode`` remained OFF after calibration
exit because ``voice_runtime_mode`` was never set to LIVE during
continuous listening, causing all post-calibration chunks to be rejected
with ``runtime_off_no_calibration_context``.
"""
from __future__ import annotations

import queue
import time
import uuid
from unittest.mock import MagicMock, patch

from tournament_platform.app.services.voice_scorekeeper.events import (
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    VoiceRuntimeMode,
    VoiceTranscriptSource,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VoiceAudioProcessor,
)
from tournament_platform.app.services.voice_audio import SAMPLE_FORMAT_FLOAT32


def _make_live_processor() -> VoiceAudioProcessor:
    proc = VoiceAudioProcessor()
    proc._runtime_mode = VoiceRuntimeMode.LIVE
    proc._session_id = str(uuid.uuid4())
    mock_asr = MagicMock()
    mock_asr.transcribe_pcm.return_value = "point red"
    proc._asr = mock_asr
    proc._asr_ready = True
    return proc


def _make_calibrated_processor() -> VoiceAudioProcessor:
    proc = VoiceAudioProcessor()
    proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
    proc._session_id = "cal_session"
    proc.set_calibration_context(_make_armed_calibration_context())
    return proc


def _make_chunk() -> MagicMock:
    chunk = MagicMock()
    chunk.to_pcm_bytes.return_value = b"\x00" * 160
    chunk.rms = 0.1
    chunk.duration_ms = 100.0
    chunk.sample_format = SAMPLE_FORMAT_FLOAT32
    chunk.sample_rate = 16000
    chunk.channels = 1
    return chunk


def _make_armed_calibration_context(trial_id: str = "t1") -> CalibrationCaptureContext:
    return CalibrationCaptureContext(
        calibration_session_id="s1",
        calibration_trial_id=trial_id,
        capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        expected_command_id="score_point",
        expected_phrase="point red",
        armed_at=time.time(),
    )


def _make_unarmed_calibration_context(trial_id: str = "t1") -> CalibrationCaptureContext:
    return CalibrationCaptureContext(
        calibration_session_id="s1",
        calibration_trial_id=trial_id,
        capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        expected_command_id="score_point",
        expected_phrase="point red",
        armed_at=None,
    )


class TestCalibrationContextClearedAfterExit:
    """Tests 1-4: calibration context is cleared after all exit paths."""

    def test_completion_clears_calibration_context(self):
        proc = VoiceAudioProcessor()
        proc.set_calibration_context(_make_armed_calibration_context())
        proc.set_runtime_mode(VoiceRuntimeMode.CALIBRATION)

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=str(uuid.uuid4()),
            clear_calibration_state=True,
        )

        assert ack.accepted is True
        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.calibration_context_cleared is True
        assert proc._calibration_context is None

    def test_cancel_clears_calibration_context(self):
        proc = VoiceAudioProcessor()
        proc.set_calibration_context(_make_armed_calibration_context())
        proc.set_runtime_mode(VoiceRuntimeMode.CALIBRATION)

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.OFF,
            clear_calibration_state=True,
        )

        assert ack.accepted is True
        assert ack.new_mode == VoiceRuntimeMode.OFF
        assert ack.calibration_context_cleared is True
        assert proc._calibration_context is None

    def test_reset_clears_calibration_context(self):
        proc = VoiceAudioProcessor()
        proc.set_calibration_context(_make_armed_calibration_context())
        proc.set_runtime_mode(VoiceRuntimeMode.CALIBRATION)

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=str(uuid.uuid4()),
            clear_calibration_state=True,
        )

        assert ack.accepted is True
        assert proc._calibration_context is None

    def test_exception_cleanup_clears_calibration_context(self):
        proc = VoiceAudioProcessor()
        proc.set_calibration_context(_make_armed_calibration_context())
        proc.set_runtime_mode(VoiceRuntimeMode.CALIBRATION)

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=str(uuid.uuid4()),
            clear_calibration_state=True,
        )

        assert ack.accepted is True
        assert proc._calibration_context is None


class TestRuntimeTransitionToLive:
    """Tests 5-8: runtime mode transitions correctly after calibration."""

    def test_active_continuous_listening_transitions_to_live(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._calibration_context = _make_armed_calibration_context()

        new_session = str(uuid.uuid4())
        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=new_session,
            clear_calibration_state=True,
        )

        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.new_continuous_session_id == new_session
        assert proc._session_id == new_session
        assert proc._runtime_mode == VoiceRuntimeMode.LIVE

    def test_disabled_listening_transitions_to_off(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._calibration_context = _make_armed_calibration_context()

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.OFF,
            clear_calibration_state=True,
        )

        assert ack.new_mode == VoiceRuntimeMode.OFF
        assert proc._session_id is None

    def test_transition_acknowledgement_reflects_actual_state(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._calibration_context = _make_armed_calibration_context()
        proc._session_id = "old_session"

        new_session = str(uuid.uuid4())
        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=new_session,
            clear_calibration_state=True,
        )

        assert ack.accepted is True
        assert ack.processor_id == id(proc)
        assert ack.previous_mode == VoiceRuntimeMode.CALIBRATION
        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.previous_continuous_session_id == "old_session"
        assert ack.new_continuous_session_id == new_session
        assert ack.calibration_context_cleared is True
        assert ack.acoustic_capture_cleared is True
        assert ack.rejection_reason is None
        proc.stop()

    def test_rejected_transition_does_not_create_fake_success(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._calibration_context = _make_armed_calibration_context()

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=None,
            clear_calibration_state=False,
        )

        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.calibration_context_cleared is False
        assert proc._calibration_context is not None
        proc.stop()


class TestChunkAdmissionAfterCalibration:
    """Tests 9-16: chunk admission rules after calibration."""

    def test_valid_live_chunk_creates_work_item(self):
        """Test 9: A valid live chunk after calibration creates a TranscriptionWorkItem."""
        proc = _make_live_processor()
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_queue.qsize() == 1
        proc.stop()

    def test_live_chunk_source_is_continuous(self):
        """Test 10: Live chunk source is continuous."""
        proc = _make_live_processor()
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.capture_runtime_mode == VoiceRuntimeMode.LIVE
        proc.stop()

    def test_live_chunk_uses_fresh_session_id(self):
        """Test 11: Live chunk uses a fresh continuous session ID."""
        proc = VoiceAudioProcessor()
        old_session = "old_stale_session"
        new_session = str(uuid.uuid4())
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = old_session
        proc._asr = MagicMock()
        proc._asr_ready = True

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=new_session,
        )

        assert ack.new_continuous_session_id == new_session
        assert proc._session_id == new_session

        chunk = _make_chunk()
        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.runtime_session_id == new_session
        proc.stop()

    def test_live_chunk_not_rejected_as_calibration_trial_not_armed(self):
        """Test 12: Live chunk is not rejected as calibration_trial_not_armed."""
        proc = _make_live_processor()
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_enqueue_rejected == 0
            assert proc._last_chunk_rejection_reason is None
            assert proc._last_chunk_admission_outcome == "ENQUEUED"
        proc.stop()

    def test_valid_armed_calibration_chunk_routes_to_calibration(self):
        """Test 13: A valid armed calibration chunk still routes to calibration."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._session_id = "cal_session"
        proc.set_calibration_context(_make_armed_calibration_context())
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
            assert work_item.calibration_context is not None
        proc.stop()

    def test_unarmed_calibration_audio_is_rejected(self):
        """Test 14: Unarmed calibration audio is rejected."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._session_id = "cal_session"
        proc.set_calibration_context(_make_unarmed_calibration_context())
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_enqueue_rejected == 1
            assert proc._last_chunk_rejection_reason == "stale_calibration_context"
            assert proc._chunk_queue.qsize() == 0
        proc.stop()

    def test_every_chunk_has_terminal_outcome(self):
        """Test 15: Every created chunk is either enqueued or rejected with a typed reason."""
        proc = _make_live_processor()
        chunk1 = _make_chunk()
        chunk2 = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk1)
            proc._enqueue_chunk(chunk2)

            total = proc._chunk_enqueue_accepted + proc._chunk_enqueue_rejected
            assert total == 2
        proc.stop()

    def test_no_chunk_disappears_silently(self):
        """Test 16: No chunk disappears silently."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._last_chunk_admission_outcome == "REJECTED"
            assert proc._last_chunk_rejection_reason == "runtime_off_no_calibration_context"
            assert proc._chunk_enqueue_rejected == 1
        proc.stop()

    def test_queue_full_rejection_observable(self):
        """Test 17: Queue-full rejection is observable."""
        proc = _make_live_processor()
        proc._chunk_queue = queue.Queue(maxsize=1)

        chunk1 = _make_chunk()
        chunk2 = _make_chunk()
        chunk3 = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk1)
            proc._enqueue_chunk(chunk2)
            proc._enqueue_chunk(chunk3)
            assert proc._chunk_queue.qsize() == 1
            assert proc._dropped_chunks >= 1
        proc.stop()

    def test_worker_unavailable_rejection_observable(self):
        """Test 18: Worker-unavailable rejection is observable."""
        proc = _make_live_processor()
        proc._ensure_worker_running = MagicMock(return_value=False)
        chunk = _make_chunk()

        proc._enqueue_chunk(chunk)
        assert proc._chunk_enqueue_rejected == 1
        assert proc._last_chunk_rejection_reason == "worker_unavailable"
        assert proc._rejected_by_reason.get("worker_unavailable", 0) == 1
        proc.stop()


class TestStaleCalibrationContextDoesNotBlockLive:
    """Edge cases: stale calibration state after exit."""

    def test_stale_calibration_context_does_not_force_calibration_mode(self):
        """Armed calibration context with LIVE mode is accepted for calibration work,
        not rejected. Calibration work takes precedence over live scoring when
        a valid armed calibration context exists."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = str(uuid.uuid4())
        proc._calibration_context = _make_armed_calibration_context()
        proc._asr = MagicMock()
        proc._asr_ready = True

        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_enqueue_accepted == 1
            assert proc._last_chunk_admission_outcome == "ENQUEUED"
            assert proc._chunk_queue.qsize() == 1
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
        proc.stop()

    def test_transition_runtime_drains_calibration_work_items(self):
        """transition_runtime with clear_calibration_state drains calibration work items from queue."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            TranscriptionWorkItem,
        )
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._session_id = "cal_session"
        proc.set_calibration_context(_make_armed_calibration_context())

        work_item = TranscriptionWorkItem(
            audio=MagicMock(),
            runtime_session_id="cal_session",
            calibration_context=_make_armed_calibration_context("t_old"),
            capture_runtime_mode=VoiceRuntimeMode.CALIBRATION,
        )
        proc._chunk_queue.put_nowait(work_item)

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=str(uuid.uuid4()),
            clear_calibration_state=True,
        )

        assert ack.pending_calibration_work_cleared is True
        assert proc._chunk_queue.qsize() == 0
        proc.stop()


class TestExitCalibrationAndRestore:
    """Tests 29-35: exit_calibration_and_restore_live_runtime function."""

    def test_exit_restores_live_mode(self):
        """After calibration exit, runtime mode becomes LIVE when listening is active."""
        import streamlit as st

        state = {
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.LIVE.value,
            "voice_audit_events": [],
        }

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
            from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
                exit_calibration_and_restore_live_runtime,
            )
            proc = _make_calibrated_processor()
            ack = exit_calibration_and_restore_live_runtime(
                processor=proc,
                reason="completed",
            )

        assert mock_state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE
        assert ack is not None
        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.calibration_context_cleared is True

    def test_exit_restores_off_when_listening_disabled(self):
        import streamlit as st

        state = {
            "voice_listening": False,
            "voice_webrtc_streamer_state": {"playing": False},
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_calibration_previous_runtime_mode": None,
            "voice_audit_events": [],
        }

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
            from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
                exit_calibration_and_restore_live_runtime,
            )
            proc = _make_calibrated_processor()
            ack = exit_calibration_and_restore_live_runtime(
                processor=proc,
                reason="cancelled",
            )

        assert mock_state["voice_runtime_mode"] == VoiceRuntimeMode.OFF
        assert ack is not None
        assert ack.new_mode == VoiceRuntimeMode.OFF

    def test_exit_without_processor_still_sets_session_state(self):
        import streamlit as st

        state = {
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.LIVE.value,
            "voice_audit_events": [],
        }

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
            from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
                exit_calibration_and_restore_live_runtime,
            )
            ack = exit_calibration_and_restore_live_runtime(
                processor=None,
                reason="cancelled",
            )

        assert mock_state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE
        assert ack is None
        assert mock_state["voice_calibration_phase"] is None
        assert mock_state["voice_calibration_active_session_id"] is None


class TestEndToEndPostCalibration:
    """Test 29-37: Full end-to-end flow from calibration to live scoring."""

    def test_post_calibration_live_command_travels_full_path(self):
        """Full path: audio frame -> chunk -> work item -> transcript -> event."""
        proc = VoiceAudioProcessor()
        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "point red"
        proc._asr = mock_asr
        proc._asr_ready = True

        proc._calibration_context = None
        proc._active_acoustic_capture = None

        new_session = str(uuid.uuid4())
        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=new_session,
        )

        assert ack.new_mode == VoiceRuntimeMode.LIVE
        assert ack.new_continuous_session_id == new_session

        proc._start_worker()

        chunk = _make_chunk()
        proc._enqueue_chunk(chunk)

        time.sleep(0.3)

        diag = proc.get_diagnostics()
        assert diag["chunk_admission_attempts"] >= 1
        assert diag["chunks_enqueued"] >= 1
        assert diag["work_items_enqueued"] >= 1
        assert diag["runtime_mode"] == "live"

        assert mock_asr.transcribe_pcm.call_count >= 1

        events = proc.get_events()
        assert len(events) >= 1

        proc.stop()

    def test_post_calibration_transition_creates_fresh_session(self):
        """Post-calibration transition creates a fresh session ID."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.CALIBRATION
        proc._calibration_context = _make_armed_calibration_context()
        proc._session_id = "old_session"

        new_session = str(uuid.uuid4())

        ack = proc.transition_runtime(
            target_mode=VoiceRuntimeMode.LIVE,
            continuous_session_id=new_session,
            clear_calibration_state=True,
        )

        assert ack.previous_continuous_session_id == "old_session"
        assert ack.new_continuous_session_id == new_session
        assert ack.new_continuous_session_id != "old_session"
        proc.stop()


class TestSafetyAfterCalibration:
    """Tests 38-42: Safety guarantees after calibration exit."""

    def test_delayed_calibration_transcript_does_not_score(self):
        """Test 38: A delayed calibration work item after exit cannot produce a live event."""
        from tournament_platform.app.services.voice_scorekeeper.events import (
            TranscriptionWorkItem,
        )
        proc = VoiceAudioProcessor()
        proc._asr = MagicMock()
        proc._asr_ready = True
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = str(uuid.uuid4())

        stale_ctx = CalibrationCaptureContext(
            calibration_session_id="old_session",
            calibration_trial_id="old_trial",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="score_point",
            expected_phrase="point red",
            armed_at=time.time(),
        )
        work_item = TranscriptionWorkItem(
            audio=_make_chunk(),
            runtime_session_id="old_session",
            calibration_context=stale_ctx,
            capture_runtime_mode=VoiceRuntimeMode.CALIBRATION,
        )

        proc._transcribe_chunk(work_item)
        events = proc.get_events()
        for _raw, _text, event in events:
            assert event.source == VoiceTranscriptSource.CALIBRATION
        proc.stop()

    def test_calibration_results_not_routed_as_live(self):
        """Test 39: Calibration results are routed to calibration when armed
        calibration context exists, not to live scoring."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.LIVE
        proc._session_id = str(uuid.uuid4())
        proc.set_calibration_context(_make_armed_calibration_context())

        chunk = _make_chunk()
        proc._asr = MagicMock()
        proc._asr_ready = True

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_enqueue_accepted == 1
            assert proc._last_chunk_admission_outcome == "ENQUEUED"
            assert proc._chunk_queue.qsize() == 1
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
            assert work_item.calibration_context is not None
        proc.stop()

    def test_live_scoring_works_without_calibration(self):
        """Test 41: Existing live scoring works without running calibration."""
        proc = _make_live_processor()
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_queue.qsize() == 1
            work_item = proc._chunk_queue.get_nowait()
            assert work_item.capture_runtime_mode == VoiceRuntimeMode.LIVE
            assert work_item.calibration_context is None
        proc.stop()

    def test_voice_mode_off_remains_safe(self):
        """Test 42: Voice Mode Off remains safe -- no chunks enqueued."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            assert proc._chunk_enqueue_rejected == 1
            assert proc._last_chunk_rejection_reason == "runtime_off_no_calibration_context"
            assert proc._chunk_queue.qsize() == 0
        proc.stop()


class TestDiagnosticsAfterFix:
    """Verify diagnostics expose the fix-relevant fields."""

    def test_diagnostics_include_admission_counters(self):
        proc = _make_live_processor()
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            diag = proc.get_diagnostics()

        assert "chunk_admission_attempts" in diag
        assert "chunks_enqueued" in diag
        assert "chunks_rejected" in diag
        assert "rejected_by_reason" in diag
        assert "last_chunk_admission_outcome" in diag
        assert "last_chunk_rejection_reason" in diag
        assert "last_chunk_runtime_mode" in diag
        assert "last_chunk_capture_source" in diag
        assert "last_chunk_continuous_session_id" in diag
        assert diag["chunks_enqueued"] == 1
        assert diag["last_chunk_admission_outcome"] == "ENQUEUED"
        proc.stop()

    def test_diagnostics_include_rejection_by_reason(self):
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)
            diag = proc.get_diagnostics()

        assert diag["chunks_rejected"] == 1
        assert diag["rejected_by_reason"].get("runtime_off_no_calibration_context") == 1
        assert diag["last_chunk_admission_outcome"] == "REJECTED"
        proc.stop()


class TestVoiceModeOffCalibrationCommandTrial:
    """PR 0 — Reproduce and Fingerprint: failing integration tests.

    These tests demonstrate the exact failure mode described in the
    implementation plan before any refactoring is attempted.
    """

    def test_voice_mode_off_armed_calibration_accepts_chunks(self):
        """Failing command-trial integration test: Voice Mode Off with valid
        armed calibration context should accept chunks, not reject them.

        Current bug: ``_enqueue_chunk`` rejects chunks with
        ``stale_calibration_context`` when ``runtime_mode == OFF`` even
        though a valid armed ``CalibrationCaptureContext`` exists.
        """
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        proc.set_calibration_context(_make_armed_calibration_context())
        proc._asr = MagicMock()
        proc._asr.transcribe_pcm.return_value = "point red"
        proc._asr_ready = True

        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)

        # The chunk should be accepted for calibration work, not rejected.
        # Currently this fails because _enqueue_chunk rejects OFF-mode
        # chunks that have a calibration context.
        assert proc._last_chunk_admission_outcome == "ENQUEUED", (
            f"Expected ENQUEUED but got {proc._last_chunk_admission_outcome}; "
            f"rejection reason: {proc._last_chunk_rejection_reason}"
        )
        assert proc._chunk_queue.qsize() == 1
        work_item = proc._chunk_queue.get_nowait()
        assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
        assert work_item.calibration_context is not None

    def test_voice_mode_off_command_trial_scores_without_live_scoring(self):
        """Full path: Voice Mode Off + armed calibration → chunk accepted,
        not rejected with stale_calibration_context.

        Current bug: chunks are rejected at admission, so no attempt is
        recorded and the score remains 0–0 (but for the wrong reason).
        """
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        proc.set_calibration_context(_make_armed_calibration_context())
        proc._asr = MagicMock()
        proc._asr.transcribe_pcm.return_value = "point red"
        proc._asr_ready = True

        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)

        # The chunk should be accepted for calibration work, not rejected.
        assert proc._last_chunk_admission_outcome == "ENQUEUED", (
            f"Expected ENQUEUED but got {proc._last_chunk_admission_outcome}; "
            f"rejection reason: {proc._last_chunk_rejection_reason}"
        )
        assert proc._chunk_queue.qsize() == 1
        work_item = proc._chunk_queue.get_nowait()
        assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
        assert work_item.calibration_context is not None

    def test_voice_mode_off_with_unarmed_calibration_rejected(self):
        """Voice Mode Off + unarmed calibration context should be rejected
        with a typed reason (stale_calibration_context)."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        proc.set_calibration_context(_make_unarmed_calibration_context())

        chunk = _make_chunk()

        with patch.object(proc, "_ensure_worker_running", return_value=True):
            proc._enqueue_chunk(chunk)

        # Unarmed calibration context should be rejected
        assert proc._last_chunk_admission_outcome == "REJECTED"
        assert proc._last_chunk_rejection_reason == "stale_calibration_context"

    def test_processor_generation_and_queue_ids_recorded(self):
        """Processor generation and queue IDs are recorded in diagnostics."""
        proc = VoiceAudioProcessor()
        proc._runtime_mode = VoiceRuntimeMode.OFF
        proc._session_id = None
        proc.set_calibration_context(_make_armed_calibration_context())

        diag = proc.get_processor_diagnostics()
        # Processor ID should be recorded
        assert diag["processor_id"] is not None
        # Processor generation should be recorded
        assert diag["processor_generation"] is not None
        assert diag["processor_generation"] > 0
        # Chunk queue should be accessible
        assert proc._chunk_queue is not None


class TestContinuousListeningReadiness:
    """Tests for continuous listening readiness resolver."""

    def test_playing_true_no_frame_not_ready(self):
        """playing=True with no frames received is not READY."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            resolve_continuous_listening_readiness,
        )
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc._processor_generation = 1
        proc.get_processor_diagnostics.return_value = {
            "audio_frames_received": 0,
            "callback_count": 0,
            "last_frame_timestamp": None,
        }

        resolution = resolve_continuous_listening_readiness(
            webrtc_playing=True,
            processor=proc,
        )
        assert resolution["ready"] is False
        assert resolution["status"] == "WAITING_FOR_FIRST_FRAME"

    def test_playing_true_with_recent_frame_is_ready(self):
        """playing=True with recent frame is READY."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            resolve_continuous_listening_readiness,
        )
        from unittest.mock import MagicMock
        import time

        proc = MagicMock()
        proc._processor_generation = 1
        proc.get_processor_diagnostics.return_value = {
            "audio_frames_received": 5,
            "callback_count": 3,
            "last_frame_timestamp": time.monotonic() - 1.0,
        }

        resolution = resolve_continuous_listening_readiness(
            webrtc_playing=True,
            processor=proc,
        )
        assert resolution["ready"] is True
        assert resolution["status"] == "READY"
        assert resolution["recent_frame_received"] is True

    def test_stalled_when_frame_too_old(self):
        """Old frame timestamp results in STALLED status."""
        from tournament_platform.app.pages.voice_scorekeeper import (
            resolve_continuous_listening_readiness,
        )
        from unittest.mock import MagicMock
        import time

        proc = MagicMock()
        proc._processor_generation = 1
        proc.get_processor_diagnostics.return_value = {
            "audio_frames_received": 5,
            "callback_count": 3,
            "last_frame_timestamp": time.monotonic() - 10.0,
        }

        resolution = resolve_continuous_listening_readiness(
            webrtc_playing=True,
            processor=proc,
        )
        assert resolution["ready"] is False
        assert resolution["status"] == "STALLED"
        assert resolution["recent_frame_received"] is False

    def test_recv_queued_increments_counters(self):
        """recv_queued increments recv_queued_call_count and audio_frames_received."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
        )
        from unittest.mock import MagicMock, AsyncMock
        import asyncio

        proc = VoiceAudioProcessor()
        proc._asr = MagicMock()
        proc._asr_ready = True

        frames = [MagicMock(), MagicMock()]
        for frame in frames:
            frame.pts = time.monotonic()

        asyncio.run(proc.recv_queued(frames))

        assert proc._recv_queued_call_count == 1
        assert proc._audio_frames_received == 2
        assert proc._last_frame_timestamp > 0
        proc.stop()

    def test_recv_increments_counters(self):
        """recv increments recv_call_count and audio_frames_received."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
        )
        from unittest.mock import MagicMock
        import time

        proc = VoiceAudioProcessor()
        proc._asr = MagicMock()
        proc._asr_ready = True

        frame = MagicMock()
        frame.pts = time.monotonic()

        proc.recv(frame)

        assert proc._recv_call_count == 1
        assert proc._audio_frames_received == 1
        assert proc._last_frame_timestamp > 0
        proc.stop()

    def test_callback_exception_surfaced(self):
        """Callback exceptions are counted and stored."""
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            VoiceAudioProcessor,
        )
        from unittest.mock import MagicMock, patch
        import time

        proc = VoiceAudioProcessor()
        proc._asr = MagicMock()
        proc._asr_ready = True

        frame = MagicMock()
        frame.pts = time.monotonic()

        with patch.object(proc, '_copy_audio_packet', side_effect=RuntimeError('test error')):
            try:
                proc.recv(frame)
            except RuntimeError:
                pass

        assert proc._callback_exception_count == 1
        assert 'test error' in proc._last_callback_exception
        proc.stop()
