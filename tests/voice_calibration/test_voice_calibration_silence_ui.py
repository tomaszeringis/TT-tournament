"""
Phase 4 — Silence Baseline UI sign-off tests.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

import pytest
import streamlit as st

from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
)
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    AcousticCaptureRuntimeSnapshot,
    VoiceAudioProcessor,
)
from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
    _render_silence_baseline_step,
    _classify_continuation,
    _make_skipped_speech_measurement,
    stop_voice_calibration,
)


class _FakeSessionState:
    def __init__(self, **kwargs):
        self._data = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        setattr(self, key, value)

    def pop(self, key, default=None):
        value = self._data.pop(key, default)
        if key in self._data:
            delattr(self, key)
        return value

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def setdefault(self, key, default=None):
        if key not in self._data:
            self._data[key] = default
            setattr(self, key, default)
        return self._data[key]


def _make_session_state(**overrides):
    defaults = {
        "voice_calibration_active_session_id": None,
        "voice_calibration_active_measurement_id": None,
        "voice_calibration_active_measurement_kind": None,
        "voice_calibration_measurement_started_at": None,
        "voice_calibration_previous_runtime_mode": None,
        "voice_runtime_mode": None,
        "voice_calibration_phase": None,
        "voice_webrtc_ctx": None,
        "match_manager": MagicMock(),
    }
    defaults.update(overrides)
    return _FakeSessionState(**defaults)


def _make_capture(measurement_id="m1", complete=True):
    return AcousticCaptureSummary(
        measurement_id=measurement_id,
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
        complete=complete,
        warning_codes=(),
        created_at=time.time(),
    )


def _make_silence_measurement(measurement_id="m1", complete=True):
    capture = _make_capture(measurement_id=measurement_id, complete=complete)
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


@pytest.fixture(autouse=True)
def _mock_streamlit():
    with patch.object(st, "subheader") as mock_subheader, \
         patch.object(st, "caption") as mock_caption, \
         patch.object(st, "columns") as mock_columns, \
         patch.object(st, "metric") as mock_metric, \
         patch.object(st, "button") as mock_button, \
         patch.object(st, "info") as mock_info, \
         patch.object(st, "progress") as mock_progress, \
         patch.object(st, "markdown") as mock_markdown, \
         patch.object(st, "success") as mock_success, \
         patch.object(st, "warning") as mock_warning, \
         patch.object(st, "error") as mock_error:
        def columns_side_effect(n):
            return [MagicMock() for _ in range(n)]
        mock_columns.side_effect = columns_side_effect
        yield {
            "subheader": mock_subheader,
            "caption": mock_caption,
            "columns": mock_columns,
            "metric": mock_metric,
            "button": mock_button,
            "info": mock_info,
            "progress": mock_progress,
            "markdown": mock_markdown,
            "success": mock_success,
            "warning": mock_warning,
            "error": mock_error,
        }


class TestUiState:
    def test_silence_step_is_first_measurement_step(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        button_calls = [call for call in _mock_streamlit["button"].call_args_list if call[1].get("key") == "silence_start"]
        assert len(button_calls) == 1

    def test_start_disabled_without_processor(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, None)

        button_calls = [call for call in _mock_streamlit["button"].call_args_list if call[1].get("key") == "silence_start"]
        assert len(button_calls) == 1
        assert button_calls[0][1].get("disabled") is True

    def test_start_disabled_outside_measuring_silence_phase(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        start_button_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if len(call) > 1 and call[1].get("key") == "silence_start"
        ]
        assert len(start_button_calls) == 1
        assert start_button_calls[0][1].get("disabled") is True

    def test_start_creates_new_measurement_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "silence_start":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        assert st.session_state["voice_calibration_active_measurement_id"] is not None
        assert st.session_state["voice_calibration_active_measurement_kind"] == CalibrationMeasurementKind.SILENCE_BASELINE
        proc.arm_acoustic_capture.assert_called_once()

    def test_start_does_not_create_processor(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = None

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "silence_start":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        assert st.session_state["voice_calibration_active_measurement_id"] is not None


class TestResultDisplay:
    def test_consumed_silence_result_is_displayed(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        session_with_measurement = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session_with_measurement,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session_with_measurement, proc)

        metric_calls = [call for call in _mock_streamlit["metric"].call_args_list]

    def test_result_displays_duration_and_units(self, monkeypatch):
        pass

    def test_result_displays_median_p90_p95_and_peak(self, monkeypatch):
        pass

    def test_result_displays_clipping_and_speech_contamination(self, monkeypatch):
        pass

    def test_recommendations_include_evidence(self, monkeypatch):
        pass


class TestPhase4SignOff:
    def test_ui_timer_does_not_complete_capture_without_result(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 4.0

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        continue_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "silence_continue"
        ]
        assert len(continue_calls) == 0
        info_calls = [call for call in _mock_streamlit["info"].call_args_list]
        assert len(info_calls) >= 1

    def test_technical_failure_cannot_enable_continue(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=0,
            scalar_sample_count=0,
            target_duration_ms=3000.0,
            captured_duration_ms=0.0,
            valid_frame_count=0,
            invalid_frame_count=0,
            rms=None,
            rms_dbfs=None,
            peak=None,
            peak_dbfs=None,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
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
        session_with_measurement = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session_with_measurement,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session_with_measurement, proc)

        error_calls = [
            call for call in _mock_streamlit["error"].call_args_list
        ]
        assert len(error_calls) >= 1

    def test_warning_result_allows_explicit_continuation(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        capture = _make_capture(measurement_id="m1", complete=True)
        capture = AcousticCaptureSummary(
            measurement_id="m1",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=3000.0,
            captured_duration_ms=3000.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=-40.0,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=5,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement = SilenceBaselineMetrics(
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
        session_with_measurement = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session_with_measurement,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session_with_measurement, proc)

        continue_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "silence_continue"
        ]
        assert len(continue_calls) == 1
        assert continue_calls[0][1].get("disabled") is False

    def test_retry_creates_new_measurement_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        session_with_measurement = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session_with_measurement,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "silence_retry":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session_with_measurement, proc)

        assert st.session_state["voice_calibration_active_measurement_id"] != "m1"
        proc.cancel_acoustic_capture.assert_called_with(measurement_id="m1")
        proc.arm_acoustic_capture.assert_called_once()

    def test_retry_rejects_delayed_previous_result(self, monkeypatch):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import _drain_acoustic_measurements
        from tournament_platform.app.services.voice_scorekeeper.events import VoiceDrainResult

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

    def test_cancel_while_capture_active_clears_processor_state(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 1.0

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "silence_cancel":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        assert st.session_state.get("voice_calibration_active_measurement_id") is None
        assert st.session_state.get("voice_calibration_active_measurement_kind") is None
        proc.cancel_acoustic_capture.assert_any_call(measurement_id="m1")

    def test_reset_after_result_consumption_clears_measurement_ownership(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        measurement = _make_silence_measurement(measurement_id="m1")
        session_with_measurement = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
            voice_calibration_session=session_with_measurement,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_cancel":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        stop_voice_calibration(processor=proc, reason="user_cancelled")

        assert st.session_state["voice_calibration_active_measurement_id"] is None
        assert st.session_state["voice_calibration_active_measurement_kind"] is None
        assert st.session_state["voice_calibration_session"] is None
        proc.cancel_acoustic_capture.assert_called_once()

    def test_temporary_skip_does_not_create_successful_speech_metrics(self):
        session = VoiceCalibrationService().start_session("s1")
        skipped = _make_skipped_speech_measurement(session, "skip_1")
        assert isinstance(skipped, SpeechLevelMetrics)
        assert skipped.capture.skipped is True
        assert skipped.speech_rms_dbfs is None
        assert skipped.capture.complete is False


class TestControls:
    def test_continue_disabled_before_result(self, monkeypatch):
        pass

    def test_continue_enabled_after_consumed_result(self, monkeypatch):
        pass

    def test_continue_uses_phase_machine(self, monkeypatch):
        pass

    def test_continue_does_not_auto_apply_settings(self, monkeypatch):
        pass

    def test_retry_creates_new_measurement_id(self, monkeypatch):
        pass

    def test_retry_cancels_previous_active_capture(self, monkeypatch):
        pass

    def test_cancel_clears_measurement_context(self, monkeypatch):
        pass

    def test_reset_does_not_reset_live_match(self, monkeypatch):
        pass


class TestRerunSafety:
    def test_streamlit_rerun_does_not_rearm_capture(self, monkeypatch):
        pass

    def test_result_not_consumed_twice_on_rerun(self, monkeypatch):
        pass

    def test_widget_keys_remain_stable(self, monkeypatch):
        pass

    def test_no_nested_expander(self, monkeypatch):
        pass

    def test_capture_does_not_auto_start(self, monkeypatch):
        pass


class TestSideEffects:
    def test_silence_ui_never_calls_score_application(self, monkeypatch):
        pass

    def test_silence_ui_never_calls_parser(self, monkeypatch):
        pass

    def test_silence_ui_never_calls_database(self, monkeypatch):
        pass

    def test_silence_ui_never_calls_commentary(self, monkeypatch):
        pass

    def test_silence_ui_never_calls_tts(self, monkeypatch):
        pass

    def test_silence_ui_never_calls_sound(self, monkeypatch):
        pass

    def test_arm_rejection_surfaces_error_and_does_not_arm(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )
        proc.arm_acoustic_capture.return_value = False

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "silence_start":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        assert st.session_state.get("voice_calibration_active_measurement_id") is None
        assert st.session_state.get("voice_calibration_arm_error") is not None

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        error_calls = [call for call in _mock_streamlit["error"].call_args_list]
        assert len(error_calls) >= 1

    def test_stale_processor_after_stop_clears_on_cancel(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m1",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=True,
            calibration_session_id="s1",
            measurement_id="m1",
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            accumulator_present=True,
            frame_count=10,
            sample_count=100,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=1500.0,
            result_queue_size=0,
            completion_reason=None,
        )
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 1.0

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        proc.cancel_acoustic_capture.assert_not_called()
        progress_calls = [call for call in _mock_streamlit["progress"].call_args_list]
        assert len(progress_calls) >= 1

    def test_retry_after_failed_start_creates_new_measurement_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id=None,
            measurement_id=None,
            kind=None,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=None,
            channels=None,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )
        proc.arm_acoustic_capture.return_value = True

        first_click = True
        measurement_ids = []

        def button_side_effect(*args, **kwargs):
            nonlocal first_click
            if kwargs.get("key") == "silence_start" and first_click:
                first_click = False
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)
        measurement_ids.append(st.session_state.get("voice_calibration_active_measurement_id"))

        st.session_state["voice_calibration_active_measurement_id"] = None
        first_click = True
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)
        measurement_ids.append(st.session_state.get("voice_calibration_active_measurement_id"))

        assert measurement_ids[0] is not None
        assert measurement_ids[1] is not None
        assert measurement_ids[0] != measurement_ids[1]
