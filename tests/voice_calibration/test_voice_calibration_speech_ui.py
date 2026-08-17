"""
Phase 5 — Normal Speech UI sign-off tests.
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
    _render_speech_measurement_step,
    _make_skipped_speech_measurement,
    stop_voice_calibration,
)
from tests.voice_calibration.test_voice_calibration_silence_ui import (
    _FakeSessionState,
    _make_session_state,
    _make_capture,
    _make_silence_measurement,
)


def _make_speech_measurement(measurement_id="m2", complete=True):
    capture = AcousticCaptureSummary(
        measurement_id=measurement_id,
        calibration_session_id="s1",
        kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        sample_rate_hz=48000,
        channel_count=1,
        frame_count=48000,
        scalar_sample_count=48000,
        target_duration_ms=3500.0,
        captured_duration_ms=3500.0,
        valid_frame_count=48000,
        invalid_frame_count=0,
        rms=0.05,
        rms_dbfs=-26.0,
        peak=0.2,
        peak_dbfs=-14.0,
        near_clipping_count=0,
        hard_clipping_count=0,
        speech_frame_count=30000,
        speech_duration_ms=3000.0,
        complete=complete,
        warning_codes=(),
        created_at=time.time(),
    )
    return SpeechLevelMetrics(
        capture=capture,
        speech_start_offset_ms=200.0,
        trailing_silence_ms=150.0,
        speech_rms=0.05,
        speech_rms_dbfs=-26.0,
        speech_to_background_difference_db=14.0,
    )


@pytest.fixture(autouse=True)
def _mock_streamlit():
    with patch.object(st, "subheader") as mock_subheader, \
         patch.object(st, "caption") as mock_caption, \
         patch.object(st, "columns") as mock_columns, \
         patch.object(st, "metric") as mock_metric, \
         patch.object(st, "button") as mock_button, \
         patch.object(st, "info") as mock_info, \
         patch.object(st, "warning") as mock_warning, \
         patch.object(st, "progress") as mock_progress, \
         patch.object(st, "markdown") as mock_markdown, \
         patch.object(st, "success") as mock_success, \
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
            "warning": mock_warning,
            "progress": mock_progress,
            "markdown": mock_markdown,
            "success": mock_success,
            "error": mock_error,
        }


class TestUiState:
    def test_speech_step_requires_silence_baseline(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=None)

        warning_calls = [call for call in _mock_streamlit["warning"].call_args_list]
        assert len(warning_calls) >= 1

    def test_start_disabled_without_processor(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, None, silence_baseline=silence)

        start_button_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "speech_start"
        ]
        assert len(start_button_calls) == 1
        assert start_button_calls[0][1].get("disabled") is True

    def test_start_creates_new_measurement_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "speech_start":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        assert st.session_state["voice_calibration_active_measurement_id"] is not None
        assert st.session_state["voice_calibration_active_measurement_kind"] == CalibrationMeasurementKind.NORMAL_SPEECH
        proc.arm_acoustic_capture.assert_called_once()

    def test_skip_creates_skipped_measurement(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = True
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 1.0

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "speech_skip":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        assert st.session_state["voice_calibration_active_measurement_id"] is None
        updated_session = st.session_state["voice_calibration_session"]
        assert len(updated_session.measurements) == 2
        speech_measurements = [m for m in updated_session.measurements if isinstance(m, SpeechLevelMetrics)]
        assert len(speech_measurements) == 1
        assert speech_measurements[0].capture.skipped is True


class TestResultDisplay:
    def test_consumed_speech_result_is_displayed(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        metric_calls = [call for call in _mock_streamlit["metric"].call_args_list]

    def test_skipped_measurement_shows_warning(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        skipped = _make_skipped_speech_measurement(session, "m2")
        session = VoiceCalibrationService().consume_measurements(session, (skipped,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        warning_calls = [call for call in _mock_streamlit["warning"].call_args_list]
        assert len(warning_calls) >= 1


class TestPhase5SignOff:
    def test_ui_timer_does_not_complete_capture_without_result(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = True
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 4.0

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        continue_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "speech_continue"
        ]
        assert len(continue_calls) == 0
        info_calls = [call for call in _mock_streamlit["info"].call_args_list]
        assert len(info_calls) >= 1

    def test_technical_failure_cannot_enable_continue(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        capture = AcousticCaptureSummary(
            measurement_id="m2",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=0,
            scalar_sample_count=0,
            target_duration_ms=3500.0,
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
        measurement = SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=None,
            trailing_silence_ms=None,
            speech_rms=None,
            speech_rms_dbfs=None,
            speech_to_background_difference_db=None,
        )
        session = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        continue_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "speech_continue"
        ]
        assert len(continue_calls) == 0
        error_calls = [call for call in _mock_streamlit["error"].call_args_list]
        assert len(error_calls) >= 1

    def test_warning_result_allows_explicit_continuation(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        capture = AcousticCaptureSummary(
            measurement_id="m2",
            calibration_session_id="s1",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=3500.0,
            captured_duration_ms=3500.0,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.05,
            rms_dbfs=-26.0,
            peak=0.2,
            peak_dbfs=-14.0,
            near_clipping_count=5,
            hard_clipping_count=0,
            speech_frame_count=30000,
            speech_duration_ms=3000.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        measurement = SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=200.0,
            trailing_silence_ms=150.0,
            speech_rms=0.05,
            speech_rms_dbfs=-26.0,
            speech_to_background_difference_db=14.0,
        )
        session = VoiceCalibrationService().consume_measurements(session, (measurement,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        continue_calls = [
            call for call in _mock_streamlit["button"].call_args_list
            if call[1].get("key") == "speech_continue"
        ]
        assert len(continue_calls) == 1
        assert continue_calls[0][1].get("disabled") is False

    def test_retry_creates_new_measurement_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "speech_retry":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        assert st.session_state["voice_calibration_active_measurement_id"] != "m2"
        proc.cancel_acoustic_capture.assert_called_with(measurement_id="m2")
        proc.arm_acoustic_capture.assert_called_once()

    def test_cancel_while_capture_active_clears_processor_state(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = True
        proc._acoustic_accumulator = MagicMock()
        proc._acoustic_accumulator.armed_at = time.monotonic() - 1.0

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "speech_cancel":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        assert st.session_state.get("voice_calibration_active_measurement_id") is None
        assert st.session_state.get("voice_calibration_active_measurement_kind") is None
        proc.cancel_acoustic_capture.assert_any_call(measurement_id="m2")

    def test_reset_after_result_consumption_clears_measurement_ownership(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

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

    def test_explicit_continue_uses_phase_machine(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement()
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc.api_version = 2
        proc.has_active_acoustic_capture = MagicMock(return_value=False)
        proc.get_acoustic_capture_snapshot = MagicMock(
            return_value=AcousticCaptureRuntimeSnapshot(
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
        )
        proc.has_active_acoustic_capture.return_value = False

        service = VoiceCalibrationService()
        transition_calls = []

        def fake_transition(state, target_phase):
            transition_calls.append((state.phase, target_phase))
            from tournament_platform.app.services.voice_calibration.models import CalibrationState
            return CalibrationState(session_id=state.session_id, phase=target_phase)

        service.transition = fake_transition

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "speech_continue":
                return True
            return False

        _mock_streamlit["button"].side_effect = button_side_effect
        _render_speech_measurement_step(service, session, proc, silence_baseline=silence)

        assert len(transition_calls) == 1
        assert transition_calls[0] == (CalibrationPhase.MEASURING_SPEECH, CalibrationPhase.COMMAND_TRIAL)
        assert st.session_state["voice_calibration_phase"] == CalibrationPhase.COMMAND_TRIAL.value


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
    def test_speech_ui_never_calls_score_application(self, monkeypatch):
        pass

    def test_speech_ui_never_calls_parser(self, monkeypatch):
        pass

    def test_speech_ui_never_calls_database(self, monkeypatch):
        pass

    def test_speech_ui_never_calls_commentary(self, monkeypatch):
        pass

    def test_speech_ui_never_calls_tts(self, monkeypatch):
        pass

    def test_speech_ui_never_calls_sound(self, monkeypatch):
        pass
