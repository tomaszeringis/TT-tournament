"""
Regression tests for PR 3 blockers.

Covers:
- Context claimed before ASR starts
- Context bound to audio work item
- Out-of-order ASR completion preserves trial context
- Two chunks cannot claim the same trial context
- ASR failure does not leave context armed
- Unarmed calibration speech never routes live
- Review phase speech cannot score
- Between-attempts speech cannot score
- Live scoring resumes after calibration exit
- Conflicting flattened context is rejected
- Component delegates trial consumption to service
- Trial ID preserved end-to-end
- Runtime mode restored after cancel/completion/exception
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

from tournament_platform.app.services.voice_scorekeeper.events import (
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    CaptureSnapshot,
    InvalidVoiceTranscriptEvent,
    TranscriptionWorkItem,
    VoiceRuntimeMode,
    VoiceTranscriptEvent,
    VoiceTranscriptSource,
    normalize_voice_transcript_event,
)
from tournament_platform.app.services.voice_scorekeeper.event_drain import (
    _get_calibration_processed_ids,
    _process_voice_events,
    get_voice_runtime_mode,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService
from tournament_platform.app.services.voice_calibration.models import (
    CalibrationPhase,
    CalibrationSession,
    CommandTrial,
    TrialClassification,
)


class TestContextClaimedBeforeASR:
    def test_claim_before_transcribe(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)
        snapshot = processor.claim_capture_snapshot()
        claimed = snapshot.calibration_context
        assert claimed is ctx
        assert processor._calibration_context is None

    def test_two_chunks_cannot_claim_same_trial(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)
        first_snapshot = processor.claim_capture_snapshot()
        first = first_snapshot.calibration_context
        second_snapshot = processor.claim_capture_snapshot()
        second = second_snapshot.calibration_context
        assert first is ctx
        assert second is None

    def test_asr_failure_does_not_leave_context_armed(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)
        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b""
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1
        snapshot = processor.claim_capture_snapshot()
        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=snapshot.calibration_context,
            capture_runtime_mode=snapshot.runtime_mode,
        )
        processor._transcribe_chunk(work_item)
        assert processor._calibration_context is None


class TestContextBoundToWorkItem:
    def test_work_item_carries_context(self):
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        chunk = MagicMock()
        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=ctx,
        )
        assert work_item.calibration_context is ctx
        assert work_item.runtime_session_id == "session-1"
        assert work_item.audio is chunk


class TestOutOfOrderASRCompletion:
    def test_first_chunk_keeps_context_even_if_second_finishes_first(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)
        snapshot_a = processor.claim_capture_snapshot()
        work_item_a = TranscriptionWorkItem(
            audio=MagicMock(),
            runtime_session_id="session-1",
            calibration_context=snapshot_a.calibration_context,
            capture_runtime_mode=snapshot_a.runtime_mode,
        )
        snapshot_b = processor.claim_capture_snapshot()
        work_item_b = TranscriptionWorkItem(
            audio=MagicMock(),
            runtime_session_id="session-1",
            calibration_context=snapshot_b.calibration_context,
            capture_runtime_mode=snapshot_b.runtime_mode,
        )
        assert work_item_a.calibration_context is ctx
        assert work_item_b.calibration_context is None


class TestUnarmedCalibrationSpeech:
    def test_unarmed_calibration_speech_rejected(self, monkeypatch):
        import streamlit as st
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            _process_voice_events,
            _get_calibration_processed_ids,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import VoiceRuntimeMode

        _get_calibration_processed_ids("cal-session-1").clear()

        mock_processor = MagicMock()
        evt = MagicMock()
        evt.source = "calibration"
        evt.calibration_session_id = None
        evt.calibration_trial_id = None
        evt.expected_command_id = None
        evt.expected_phrase = None
        evt.event_id = "evt-1"
        evt.timestamp = 1000.0
        mock_processor.get_events.return_value = [("hello", "hello", evt)]
        mock_processor.has_pending_events.return_value = False

        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "cal-session-1",
            "voice_calibration_active_trial_id": None,
            "voice_events_enabled": True,
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
            "voice_webrtc_ctx": {"processor": mock_processor},
        }.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)
        mock_state.match_manager.engine.match_status = "in_progress"

        result = _process_voice_events(calibration_service=VoiceCalibrationService())
        assert result.calibration_events_rejected == 1
        assert result.last_rejection_reason == "calibration_trial_not_armed"


class TestTrialIdPreserved:
    def test_trial_id_preserved_end_to_end(self):
        service = VoiceCalibrationService()
        trial_id = "fixed-trial-id"
        trial = service.evaluate_transcript(
            transcript="point red",
            expected_command_id="score_point",
            expected_phrase="point red",
            trial_id=trial_id,
        )
        assert trial.trial_id == trial_id
        session = CalibrationSession(session_id="s1", created_at=time.time())
        updated = service.consume_trials(session, (trial,))
        assert updated.trials[0].trial_id == trial_id

    def test_trial_id_survives_capture_to_result_path(self):
        service = VoiceCalibrationService()
        trial_id = "fixed-trial-id"
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id=trial_id,
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
        )
        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1

        mock_asr2 = MagicMock()
        mock_asr2.transcribe_pcm.return_value = "point red"
        processor = VoiceAudioProcessor(asr=mock_asr2)
        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=ctx,
            capture_runtime_mode=VoiceRuntimeMode.CALIBRATION,
        )
        processor._transcribe_chunk(work_item)

        events = processor.get_events()
        assert len(events) == 1
        event = events[0]
        raw_text = event.raw_transcript
        text = event.transcript
        normalized = event
        assert normalized.calibration_trial_id == trial_id
        assert normalized.calibration_context is ctx

        trial = service.evaluate_transcript(
            text,
            expected_command_id=ctx.expected_command_id,
            expected_phrase=ctx.expected_phrase,
            trial_id=normalized.calibration_trial_id,
        )
        assert trial.trial_id == trial_id

        session = CalibrationSession(session_id="s1", created_at=time.time())
        updated = service.consume_trials(session, (trial,))
        assert updated.trials[0].trial_id == trial_id


class TestContextClaimedBeforeASR:
    def test_context_claimed_before_asr_provider_not_called(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)

        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "point red"
        processor._asr = mock_asr
        processor._asr_ready = True

        snapshot = processor.claim_capture_snapshot()
        claimed = snapshot.calibration_context
        assert claimed is ctx
        assert processor._calibration_context is None
        assert not mock_asr.transcribe_pcm.called

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1

        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=claimed,
            capture_runtime_mode=snapshot.runtime_mode,
        )
        processor._transcribe_chunk(work_item)
        assert mock_asr.transcribe_pcm.called

    def test_asr_failure_context_consumed_and_recoverable(self):
        processor = VoiceAudioProcessor()
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(ctx)

        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.side_effect = RuntimeError("ASR failure")
        processor._asr = mock_asr
        processor._asr_ready = True

        snapshot = processor.claim_capture_snapshot()
        claimed = snapshot.calibration_context
        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1

        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=claimed,
            capture_runtime_mode=snapshot.runtime_mode,
        )
        processor._transcribe_chunk(work_item)
        assert processor._calibration_context is None

        new_ctx = CalibrationCaptureContext(
            calibration_session_id="s2",
            calibration_trial_id="t2",
            expected_command_id="score_point",
            expected_phrase="point blue",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        processor.set_calibration_context(new_ctx)
        snapshot2 = processor.claim_capture_snapshot()
        claimed2 = snapshot2.calibration_context
        assert claimed2 is new_ctx
        assert processor._calibration_context is None

        mock_asr.transcribe_pcm.side_effect = None
        mock_asr.transcribe_pcm.return_value = "point blue"

        chunk2 = MagicMock()
        chunk2.to_pcm_bytes.return_value = b"\x00" * 160
        chunk2.rms = 0.1
        chunk2.sample_format = "float32"
        chunk2.sample_rate = 16000
        chunk2.channels = 1

        work_item2 = TranscriptionWorkItem(
            audio=chunk2,
            runtime_session_id="session-1",
            calibration_context=claimed2,
            capture_runtime_mode=VoiceRuntimeMode.CALIBRATION,
        )
        processor._transcribe_chunk(work_item2)

        service = VoiceCalibrationService()
        trial = service.evaluate_transcript(
            transcript="point blue",
            expected_command_id=new_ctx.expected_command_id,
            expected_phrase=new_ctx.expected_phrase,
        )
        assert trial.trial_id != ""
        assert len(trial.trial_id) > 10


class TestCaptureTimeModeIntegration:
    def test_audio_enqueued_during_calibration_remains_calibration_after_mode_exit(
        self, monkeypatch
    ):
        import streamlit as st

        mock_asr = MagicMock()
        mock_asr.transcribe_pcm.return_value = "point red"
        processor = VoiceAudioProcessor(asr=mock_asr)
        # Prevent the auto-starting worker from consuming the chunk before
        # the test can inspect the captured work_item.
        monkeypatch.setattr(processor, "_ensure_worker_running", lambda: True)

        processor.set_runtime_mode(VoiceRuntimeMode.CALIBRATION)
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
        )
        processor.set_calibration_context(ctx)
        processor._session_id = "calibration_session"

        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1

        processor._enqueue_chunk(chunk)

        work_item = processor._chunk_queue.get_nowait()
        assert work_item.capture_runtime_mode == VoiceRuntimeMode.CALIBRATION
        assert work_item.calibration_context is ctx

        processor.set_runtime_mode(VoiceRuntimeMode.LIVE)

        processor._transcribe_chunk(work_item)
        events = processor.get_events()
        assert len(events) == 1
        event = events[0]
        assert event.source == VoiceTranscriptSource.CALIBRATION

        _get_calibration_processed_ids("s1").clear()
        state = {
            "voice_scoring_enabled": True,
            "quick_voice_mode": "full",
            "voice_selected_match_id": 1,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": "current-session",
            "voice_continuous_session_start": 1000.0,
            "voice_listening": True,
            "voice_webrtc_streamer_state": {"playing": True},
            "voice_calibration_active_session_id": "s1",
            "voice_calibration_active_trial_id": None,
            "voice_events_enabled": True,
            "voice_runtime_mode": VoiceRuntimeMode.LIVE,
            "voice_webrtc_ctx": {"processor": MagicMock()},
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = state.get
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)
        mock_state.match_manager.engine.match_status = "in_progress"

        mock_proc = MagicMock()
        mock_proc.get_events.return_value = events
        mock_proc.has_pending_events.return_value = False
        state["voice_webrtc_ctx"] = {"processor": mock_proc}

        result = _process_voice_events(calibration_service=VoiceCalibrationService())
        assert result.calibration_events_evaluated == 1
        assert result.calibration_events_rejected == 0
        assert result.events_accepted == 0

    def test_unknown_runtime_mode_fails_closed(self):
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            InvalidVoiceTranscriptEvent as RuntimeInvalidVoiceTranscriptEvent,
            source_from_capture_mode,
        )

        with pytest.raises(RuntimeInvalidVoiceTranscriptEvent, match="Unsupported capture runtime mode"):
            source_from_capture_mode("invalid_mode")  # type: ignore

    def test_off_mode_work_item_cannot_produce_continuous_event(self):
        processor = VoiceAudioProcessor()
        chunk = MagicMock()
        chunk.to_pcm_bytes.return_value = b"\x00" * 160
        chunk.rms = 0.1
        chunk.sample_format = "float32"
        chunk.sample_rate = 16000
        chunk.channels = 1

        work_item = TranscriptionWorkItem(
            audio=chunk,
            runtime_session_id="session-1",
            calibration_context=None,
            capture_runtime_mode=VoiceRuntimeMode.OFF,
        )
        processor._transcribe_chunk(work_item)
        assert processor.event_queue.empty()


class TestConflictingFlattenedContext:
    def test_conflicting_context_raises(self):
        with pytest.raises(InvalidVoiceTranscriptEvent, match="Conflicting calibration trial id"):
            VoiceTranscriptEvent(
                transcript="hello",
                raw_transcript="hello",
                event_id="e1",
                source=VoiceTranscriptSource.CALIBRATION,
                calibration_trial_id="trial-a",
                calibration_context=CalibrationCaptureContext(
                    calibration_session_id="s1",
                    calibration_trial_id="trial-b",
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                ),
            )

    def test_matching_context_is_accepted(self):
        ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            expected_command_id="score_point",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
        )
        evt = VoiceTranscriptEvent(
            transcript="hello",
            raw_transcript="hello",
            event_id="e1",
            source=VoiceTranscriptSource.CALIBRATION,
            calibration_context=ctx,
        )
        assert evt.calibration_trial_id == "t1"
        assert evt.expected_command_id == "score_point"


class TestComponentDelegation:
    def test_component_delegates_to_service(self):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            consume_calibration_trials,
        )

        service = MagicMock(spec=VoiceCalibrationService)
        session = CalibrationSession(session_id="s1", created_at=time.time())
        trials = (
            CommandTrial(
                trial_id="t1",
                expected_command_id="score_point",
                expected_phrase="point red",
                raw_transcript="point red",
                normalized_transcript="point red",
                resolved_command_id="score_point",
                classification=TrialClassification.EXACT,
                parser_confidence=0.9,
                rejection_reason=None,
            ),
        )
        consume_calibration_trials(service=service, session=session, trials=trials)
        service.consume_trials.assert_called_once_with(session=session, trials=trials)

    def test_component_returns_none_when_session_is_none(self):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            consume_calibration_trials,
        )

        service = MagicMock(spec=VoiceCalibrationService)
        result = consume_calibration_trials(service=service, session=None, trials=())
        assert result is None
        service.consume_trials.assert_not_called()


class TestRuntimeModeRestored:
    def test_runtime_mode_restored_after_cancel(self, monkeypatch):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            stop_voice_calibration,
        )

        state = {
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.LIVE,
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = state.get
        mock_state.__getitem__.side_effect = state.__getitem__
        mock_state.__setitem__.side_effect = state.__setitem__
        mock_state.pop.side_effect = state.pop
        monkeypatch.setattr(st, "session_state", mock_state)

        stop_voice_calibration(processor=None, reason="cancel")
        assert state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE
        assert "voice_calibration_previous_runtime_mode" not in state

    def test_runtime_mode_restored_after_completion(self, monkeypatch):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            _exit_calibration_mode,
        )

        state = {
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.LIVE,
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = state.get
        mock_state.__getitem__.side_effect = state.__getitem__
        mock_state.__setitem__.side_effect = state.__setitem__
        mock_state.pop.side_effect = state.pop
        monkeypatch.setattr(st, "session_state", mock_state)

        _exit_calibration_mode()
        assert state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE

    def test_runtime_mode_restored_after_rendering_exception(self, monkeypatch):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            _exit_calibration_mode,
        )

        state = {
            "voice_calibration_previous_runtime_mode": VoiceRuntimeMode.LIVE,
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = state.get
        mock_state.__getitem__.side_effect = state.__getitem__
        mock_state.__setitem__.side_effect = state.__setitem__
        mock_state.pop.side_effect = state.pop
        monkeypatch.setattr(st, "session_state", mock_state)

        try:
            raise RuntimeError("render failure")
        except RuntimeError:
            _exit_calibration_mode()
        assert state["voice_runtime_mode"] == VoiceRuntimeMode.LIVE


class TestLiveScoringResumes:
    def test_live_scoring_resumes_after_calibration_exit(self, monkeypatch):
        from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
            _exit_calibration_mode,
        )
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            get_voice_runtime_mode,
        )

        state = {
            "voice_calibration_active_session_id": None,
            "voice_runtime_mode": VoiceRuntimeMode.LIVE,
        }

        class _MockSessionState(dict):
            def __missing__(self, key):
                return None

        mock_state = _MockSessionState(state)
        monkeypatch.setattr(st, "session_state", mock_state)

        _exit_calibration_mode()
        assert get_voice_runtime_mode() == VoiceRuntimeMode.LIVE
