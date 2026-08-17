"""
Phase 3 — Typed Measurement Result Routing and Domain Consumption tests.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticMeasurementResult,
    CalibrationMeasurementKind,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
)
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService
from tournament_platform.app.services.voice_scorekeeper.events import (
    VoiceDrainResult,
    VoiceRuntimeMode,
)
from tournament_platform.app.services.voice_scorekeeper.event_drain import (
    _drain_acoustic_measurements,
    _process_voice_events,
    _validate_acoustic_measurement,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import VoiceAudioProcessor


def _make_session_state(**overrides):
    mock_state = MagicMock()
    defaults = {
        "voice_calibration_active_session_id": None,
        "voice_calibration_active_measurement_id": None,
        "voice_calibration_active_measurement_kind": None,
        "voice_calibration_phase": None,
        "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        "voice_continuous_session_id": None,
        "voice_continuous_session_start": 0.0,
        "voice_listening": True,
        "voice_events_enabled": True,
        "voice_scoring_enabled": False,
        "quick_voice_mode": "off",
        "voice_selected_match_id": None,
        "match_complete": False,
        "match_manager": MagicMock(),
        "voice_webrtc_ctx": None,
        "last_applied_voice_event_ids": [],
        "voice_calibration_session": None,
        "voice_calibration_active_trial_id": None,
        "voice_calibration_previous_runtime_mode": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(mock_state, key, value)
    mock_state.get.side_effect = lambda key, default=None: defaults.get(key, default)
    mock_state.pop.return_value = None
    return mock_state


def _make_capture(measurement_id="m1", complete=True, kind=CalibrationMeasurementKind.SILENCE_BASELINE):
    return AcousticCaptureSummary(
        measurement_id=measurement_id,
        calibration_session_id="s1",
        kind=kind,
        sample_rate_hz=48000,
        channel_count=1,
        frame_count=48000,
        scalar_sample_count=48000,
        target_duration_ms=1000.0,
        captured_duration_ms=1000.0,
        valid_frame_count=48000,
        invalid_frame_count=0,
        rms=0.01,
        rms_dbfs=-40.0,
        peak=0.05,
        peak_dbfs=-26.0,
        near_clipping_count=0,
        hard_clipping_count=0,
        speech_frame_count=0,
        speech_duration_ms=0.0,
        complete=complete,
        warning_codes=(),
        created_at=time.time(),
    )


def _make_silence_measurement(measurement_id="m1", complete=True):
    capture = _make_capture(measurement_id=measurement_id, complete=complete, kind=CalibrationMeasurementKind.SILENCE_BASELINE)
    return SilenceBaselineMetrics(
        capture=capture,
        median_rms=0.01,
        median_dbfs=-40.0,
        p90_rms=0.012,
        p90_dbfs=-38.0,
        p95_rms=0.013,
        p95_dbfs=-37.0,
        mad_rms=0.001,
        transient_count=0,
        contaminated_by_speech=False,
        speech_frame_count=0,
        speech_duration_ms=0.0,
    )


def _make_speech_measurement(measurement_id="m1", complete=True):
    capture = _make_capture(measurement_id=measurement_id, complete=complete, kind=CalibrationMeasurementKind.NORMAL_SPEECH)
    return SpeechLevelMetrics(
        capture=capture,
        speech_start_offset_ms=100.0,
        trailing_silence_ms=200.0,
        speech_rms=0.05,
        speech_rms_dbfs=-26.0,
        speech_to_background_difference_db=14.0,
    )


class TestSuccessfulRouting:
    def test_silence_measurement_reaches_voice_drain_result(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        result = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result)
        assert len(result.calibration_measurements) == 1
        assert result.calibration_measurements_evaluated == 1
        assert result.calibration_measurements_rejected == 0

    def test_speech_measurement_reaches_voice_drain_result(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase="measuring_speech",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_speech_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        result = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result)
        assert len(result.calibration_measurements) == 1
        assert result.calibration_measurements_evaluated == 1

    def test_measurement_is_consumed_into_calibration_session(self, monkeypatch):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        updated = service.consume_measurements(session, (measurement,))
        assert len(updated.measurements) == 1
        assert updated.measurements[0].capture.measurement_id == "m1"

    def test_consumption_preserves_existing_command_trials(self, monkeypatch):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        trial = service.evaluate_transcript("point red", "score_point", "point red")
        session_with_trial = service.consume_trials(session, (trial,))
        measurement = _make_silence_measurement(measurement_id="m1")
        updated = service.consume_measurements(session_with_trial, (measurement,))
        assert len(updated.trials) == 1
        assert len(updated.measurements) == 1

    def test_successful_consumption_clears_active_measurement(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
            voice_calibration_session=VoiceCalibrationService().start_session("s1"),
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        result = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result)

        assert len(result.calibration_measurements) == 1
        session = mock_state.voice_calibration_session
        previous_count = len(session.measurements)
        updated = VoiceCalibrationService().consume_measurements(
            session=session,
            measurements=tuple(result.calibration_measurements),
        )
        assert len(updated.measurements) > previous_count
        mock_state.voice_calibration_active_measurement_id = None
        mock_state.voice_calibration_active_measurement_kind = None
        assert mock_state.voice_calibration_active_measurement_id is None


class TestSessionAndIdValidation:
    def test_foreign_session_measurement_rejected(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        foreign_capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="foreign-session",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=1000.0,
            captured_duration_ms=1000.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement = SilenceBaselineMetrics(
            capture=foreign_capture,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert len(result.calibration_measurements) == 0

    def test_missing_active_measurement_rejected(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1

    def test_stale_measurement_id_rejected(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "stale_or_replaced_measurement"

    def test_retried_measurement_rejects_old_result(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "stale_or_replaced_measurement"

    def test_measurement_kind_mismatch_rejected(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_speech_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "measurement_kind_mismatch"


class TestPhaseValidation:
    def test_silence_result_requires_measuring_silence(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="command_trial",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "measurement_phase_mismatch"

    def test_speech_result_requires_measuring_speech(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase="command_trial",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_speech_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "measurement_phase_mismatch"

    def test_measurement_rejected_in_command_trial_phase(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="command_trial",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1

    def test_measurement_rejected_after_calibration_cancel(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id=None,
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=None,
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "missing_active_calibration_session"


class TestIncompleteOutcomes:
    def test_timeout_result_is_routed_as_measurement_outcome(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        capture = _make_capture(measurement_id="m1", complete=False)
        measurement = SilenceBaselineMetrics(
            capture=capture,
            median_rms=None,
            median_dbfs=None,
            p90_rms=None,
            p90_dbfs=None,
            p95_rms=None,
            p95_dbfs=None,
            mad_rms=None,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert len(result.calibration_measurements) == 1
        assert result.calibration_measurements[0].capture.complete is False

    def test_incomplete_result_is_not_runtime_rejection(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        capture = _make_capture(measurement_id="m1", complete=False)
        measurement = SilenceBaselineMetrics(
            capture=capture,
            median_rms=None,
            median_dbfs=None,
            p90_rms=None,
            p90_dbfs=None,
            p95_rms=None,
            p95_dbfs=None,
            mad_rms=None,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 0
        assert len(result.calibration_measurements) == 1

    def test_incomplete_result_does_not_advance_phase(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        capture = _make_capture(measurement_id="m1", complete=False)
        measurement = SilenceBaselineMetrics(
            capture=capture,
            median_rms=None,
            median_dbfs=None,
            p90_rms=None,
            p90_dbfs=None,
            p95_rms=None,
            p95_dbfs=None,
            mad_rms=None,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert mock_state.voice_calibration_phase == "measuring_silence"


class TestIdempotency:
    def test_duplicate_measurement_id_consumed_once(self, monkeypatch):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        updated1 = service.consume_measurements(session, (measurement,))
        assert len(updated1.measurements) == 1
        updated2 = service.consume_measurements(updated1, (measurement,))
        assert len(updated2.measurements) == 1

    def test_result_queue_drained_twice_does_not_duplicate(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.side_effect = [[measurement], []]

        result1 = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result1)
        assert len(result1.calibration_measurements) == 1

        result2 = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result2)
        assert len(result2.calibration_measurements) == 0

    def test_streamlit_rerun_does_not_duplicate_measurement(self, monkeypatch):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")

        session_after_1st = service.consume_measurements(session, (measurement,))
        assert len(session_after_1st.measurements) == 1

        session_after_2nd = service.consume_measurements(session_after_1st, (measurement,))
        assert len(session_after_2nd.measurements) == 1


class TestSideEffects:
    def test_measurement_routing_never_calls_voice_parser(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        with patch("tournament_platform.app.services.voice_parser.VoiceParser") as MockParser:
            result = VoiceDrainResult()
            _drain_acoustic_measurements(processor=processor, result=result)
            MockParser.assert_not_called()

    def test_measurement_routing_never_calls_score_application(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        with patch("tournament_platform.app.services.voice_scorekeeper.event_drain._process_voice_transcript") as mock_transcript:
            result = VoiceDrainResult()
            _drain_acoustic_measurements(processor=processor, result=result)
            mock_transcript.assert_not_called()

    def test_measurement_routing_never_calls_match_manager(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
            match_manager=MagicMock(),
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        result = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result)
        mock_state.match_manager.apply_score_event_and_refresh_ui.assert_not_called()

    def test_measurement_routing_never_calls_persistence(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        measurement = _make_silence_measurement(measurement_id="m1")
        processor.drain_acoustic_measurement_results.return_value = [measurement]

        with patch("tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace") as mock_trace:
            result = VoiceDrainResult()
            _drain_acoustic_measurements(processor=processor, result=result)
            assert mock_trace.called


class TestCleanup:
    def test_cancelled_session_late_result_is_rejected(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id=None,
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=None,
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert result.last_rejection_reason == "missing_active_calibration_session"

    def test_reset_session_late_result_is_rejected(self, monkeypatch):
        defaults = {
            "voice_calibration_active_session_id": "s1",
            "voice_calibration_active_measurement_id": "m1",
            "voice_calibration_active_measurement_kind": CalibrationMeasurementKind.SILENCE_BASELINE,
            "voice_calibration_phase": "measuring_silence",
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: defaults.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert len(result.calibration_measurements) == 1

        defaults["voice_calibration_active_session_id"] = None
        defaults["voice_calibration_active_measurement_id"] = None
        defaults["voice_calibration_active_measurement_kind"] = None

        measurement2 = _make_silence_measurement(measurement_id="m1")
        result2 = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement2])),
            result=result2,
        )
        assert result2.calibration_measurements_rejected == 1

    def test_processor_unavailable_is_safe(self):
        result = VoiceDrainResult()
        _drain_acoustic_measurements(processor=None, result=result)
        assert result.calibration_measurements_evaluated == 0
        assert result.calibration_measurements_rejected == 0

    def test_measurement_drain_exception_does_not_break_transcript_drain(self, monkeypatch):
        defaults = {
            "voice_calibration_active_session_id": "s1",
            "voice_calibration_active_measurement_id": "m1",
            "voice_calibration_active_measurement_kind": CalibrationMeasurementKind.SILENCE_BASELINE,
            "voice_calibration_phase": "measuring_silence",
            "voice_webrtc_ctx": {"processor": MagicMock()},
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: defaults.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        processor.drain_acoustic_measurement_results.side_effect = RuntimeError("drain failed")
        processor.get_events.return_value = []
        defaults["voice_webrtc_ctx"] = {"processor": processor}

        with patch("tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"):
            result = _process_voice_events(calibration_service=VoiceCalibrationService())
        assert result.last_exception == "measurement_drain_exception"


class TestDrainFailureIsolation:
    def test_acoustic_drain_failure_does_not_interrupt_transcript_processing(self, monkeypatch):
        defaults = {
            "voice_calibration_active_session_id": "s1",
            "voice_calibration_active_measurement_id": "m1",
            "voice_calibration_active_measurement_kind": CalibrationMeasurementKind.SILENCE_BASELINE,
            "voice_calibration_phase": "measuring_silence",
            "voice_webrtc_ctx": {"processor": MagicMock()},
            "voice_listening": True,
            "voice_events_enabled": True,
            "voice_scoring_enabled": False,
            "quick_voice_mode": "off",
            "voice_selected_match_id": None,
            "match_complete": False,
            "match_manager": MagicMock(),
            "voice_continuous_session_id": None,
            "voice_continuous_session_start": 0.0,
            "last_applied_voice_event_ids": [],
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: defaults.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        processor = MagicMock(spec=VoiceAudioProcessor)
        processor.drain_acoustic_measurement_results.side_effect = RuntimeError("drain failed")
        processor.get_events.return_value = []
        defaults["voice_webrtc_ctx"] = {"processor": processor}

        with patch("tournament_platform.app.pages.voice_scorekeeper._append_continuous_trace"):
            result = _process_voice_events(calibration_service=VoiceCalibrationService())
        assert result.last_exception == "measurement_drain_exception"


class TestStaleResultConsumption:
    def test_stale_result_removed_from_processor_queue(self, monkeypatch):
        defaults = {
            "voice_calibration_active_session_id": "s1",
            "voice_calibration_active_measurement_id": "m1",
            "voice_calibration_active_measurement_kind": CalibrationMeasurementKind.SILENCE_BASELINE,
            "voice_calibration_phase": "measuring_silence",
            "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION,
        }
        mock_state = MagicMock()
        mock_state.get.side_effect = lambda key, default=None: defaults.get(key, default)
        mock_state.pop.return_value = None
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        processor = MagicMock(spec=VoiceAudioProcessor)
        processor.drain_acoustic_measurement_results.side_effect = [[measurement], [measurement], []]

        result1 = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result1)
        assert result1.calibration_measurements_rejected == 0
        assert len(result1.calibration_measurements) == 1

        defaults["voice_calibration_active_session_id"] = None
        defaults["voice_calibration_active_measurement_id"] = None
        defaults["voice_calibration_active_measurement_kind"] = None

        result2 = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result2)
        assert result2.calibration_measurements_rejected == 1
        assert len(result2.calibration_measurements) == 0

        result3 = VoiceDrainResult()
        _drain_acoustic_measurements(processor=processor, result=result3)
        assert result3.calibration_measurements_rejected == 0
        assert len(result3.calibration_measurements) == 0


class TestDuplicatePayloadRejection:
    def test_duplicate_id_with_different_payload_rejected(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")

        capture1 = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=1000.0,
            captured_duration_ms=1000.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement1 = SilenceBaselineMetrics(
            capture=capture1,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )

        updated = service.consume_measurements(session, (measurement1,))
        assert len(updated.measurements) == 1

        capture2 = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=1000.0,
            captured_duration_ms=1000.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.02,
            rms_dbfs=-34.0,
            peak=0.06,
            peak_dbfs=-24.0,
            near_clipping_count=5,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement2 = SilenceBaselineMetrics(
            capture=capture2,
            median_rms=0.02,
            median_dbfs=-34.0,
            p90_rms=0.022,
            p90_dbfs=-32.0,
            p95_rms=0.023,
            p95_dbfs=-31.0,
            mad_rms=0.002,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )

        with pytest.raises(ValueError, match="Conflicting duplicate measurement"):
            service.consume_measurements(updated, (measurement2,))

    def test_exact_duplicate_is_idempotent(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")

        updated1 = service.consume_measurements(session, (measurement,))
        assert len(updated1.measurements) == 1

        updated2 = service.consume_measurements(updated1, (measurement,))
        assert len(updated2.measurements) == 1


class TestActiveStateClearing:
    def test_active_state_clears_after_successful_consumption(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
            voice_calibration_session=VoiceCalibrationService().start_session("s1"),
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        measurement = _make_silence_measurement(measurement_id="m1")
        session = mock_state.voice_calibration_session
        previous_count = len(session.measurements)
        updated = VoiceCalibrationService().consume_measurements(
            session=session,
            measurements=(measurement,),
        )
        if len(updated.measurements) > previous_count:
            mock_state.voice_calibration_active_measurement_id = None
            mock_state.voice_calibration_active_measurement_kind = None
            mock_state.voice_calibration_measurement_started_at = None

        assert mock_state.voice_calibration_active_measurement_id is None
        assert mock_state.voice_calibration_active_measurement_kind is None
        assert mock_state.voice_calibration_measurement_started_at is None

    def test_active_state_clears_after_exact_duplicate(self, monkeypatch):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        updated = service.consume_measurements(session, (measurement,))
        assert len(updated.measurements) == 1

        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
            voice_calibration_session=updated,
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        previous_count = len(updated.measurements)
        updated2 = VoiceCalibrationService().consume_measurements(
            session=updated,
            measurements=(measurement,),
        )
        if len(updated2.measurements) == previous_count:
            mock_state.voice_calibration_active_measurement_id = None
            mock_state.voice_calibration_active_measurement_kind = None
            mock_state.voice_calibration_measurement_started_at = None

        assert mock_state.voice_calibration_active_measurement_id is None
        assert mock_state.voice_calibration_active_measurement_kind is None
        assert mock_state.voice_calibration_measurement_started_at is None

    def test_active_state_not_cleared_after_foreign_session_result(self, monkeypatch):
        mock_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase="measuring_silence",
        )
        monkeypatch.setattr(st, "session_state", mock_state)

        foreign_capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="foreign-session",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=1000.0,
            captured_duration_ms=1000.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement = SilenceBaselineMetrics(
            capture=foreign_capture,
            median_rms=0.01,
            median_dbfs=-40.0,
            p90_rms=0.012,
            p90_dbfs=-38.0,
            p95_rms=0.013,
            p95_dbfs=-37.0,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )
        result = VoiceDrainResult()
        _drain_acoustic_measurements(
            processor=MagicMock(drain_acoustic_measurement_results=MagicMock(return_value=[measurement])),
            result=result,
        )
        assert result.calibration_measurements_rejected == 1
        assert mock_state.voice_calibration_active_measurement_id == "m1"
        assert mock_state.voice_calibration_active_measurement_kind == CalibrationMeasurementKind.SILENCE_BASELINE
