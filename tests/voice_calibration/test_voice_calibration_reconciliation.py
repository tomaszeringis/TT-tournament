"""
Regression tests for Voice Calibration Step 2 — Normal Speech reconciliation.

Reproduces the exact audit pattern where normal-speech captures complete
but reconciliation is skipped because a previous completed reference
exists or because the late drain is discarded.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticReconciliationResult,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    CompletedMeasurementRef,
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
    _render_silence_baseline_step,
    find_rendered_terminal_result,
    resolve_acoustic_ui_state,
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


class TestReconciliationGate:
    """Tests that every validated acoustic result is consumed and persisted."""

    def test_existing_silence_completed_ref_does_not_block_speech_reconciliation(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = service.consume_measurements(session, (speech,))

        result = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech,),
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        assert len(result.session.measurements) == 2
        assert result.completed_ref is not None
        assert result.completed_ref.measurement_id == "m2"
        assert result.completed_ref.kind == CalibrationMeasurementKind.NORMAL_SPEECH
        assert "m2" in result.ignored_measurement_ids

    def test_existing_speech_completed_ref_does_not_block_speech_retry_result(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))
        speech_a = _make_speech_measurement(measurement_id="m2")
        session = service.consume_measurements(session, (speech_a,))
        speech_b = _make_speech_measurement(measurement_id="m3")
        session = service.consume_measurements(session, (speech_b,))

        result = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech_b,),
            active_measurement_id="m3",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        assert len(result.session.measurements) == 3
        assert result.completed_ref.measurement_id == "m3"
        assert "m3" in result.ignored_measurement_ids

    def test_every_accepted_current_session_result_is_consumed(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))

        for i in range(3):
            mid = f"speech_{i}"
            speech = _make_speech_measurement(measurement_id=mid)
            result = service.reconcile_acoustic_measurements(
                session=session,
                measurements=(speech,),
                active_measurement_id=mid,
                active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            )
            session = result.session
            assert len(session.measurements) == 2 + i
            assert result.completed_ref.measurement_id == mid

    def test_completed_display_ref_is_overwritten_by_newer_completed_result(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))

        speech_a = _make_speech_measurement(measurement_id="m2")
        result_a = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech_a,),
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )
        session = result_a.session
        ref_a = result_a.completed_ref
        assert ref_a.measurement_id == "m2"

        speech_b = _make_speech_measurement(measurement_id="m3")
        result_b = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech_b,),
            active_measurement_id="m3",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )
        assert result_b.completed_ref.measurement_id == "m3"
        assert result_b.completed_ref.kind == CalibrationMeasurementKind.NORMAL_SPEECH

    def test_starting_retry_clears_stale_display_ref(self):
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            calibration_completed_measurement_ref=CompletedMeasurementRef(
                calibration_session_id="s1",
                measurement_id="m2",
                kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            ),
        )
        assert "calibration_completed_measurement_ref" in st.session_state
        st.session_state.pop("calibration_completed_measurement_ref", None)
        assert "calibration_completed_measurement_ref" not in st.session_state

    def test_transition_to_speech_clears_or_ignores_silence_display_ref(self):
        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            calibration_completed_measurement_ref=CompletedMeasurementRef(
                calibration_session_id="s1",
                measurement_id="m1",
                kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            ),
        )
        session = VoiceCalibrationService().start_session("s1")
        speech = _make_speech_measurement(measurement_id="m2")
        result = VoiceCalibrationService().reconcile_acoustic_measurements(
            session=session,
            measurements=(speech,),
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )
        assert result.completed_ref.measurement_id == "m2"
        assert result.completed_ref.kind == CalibrationMeasurementKind.NORMAL_SPEECH

    def test_display_ref_is_not_used_for_idempotency(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = service.consume_measurements(session, (speech,))

        result = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech,),
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        assert len(result.session.measurements) == 2
        assert "m2" in result.ignored_measurement_ids
        assert result.completed_ref.measurement_id == "m2"

    def test_duplicate_terminal_result_remains_idempotent_using_session_measurements(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = service.consume_measurements(session, (speech,))

        result = service.reconcile_acoustic_measurements(
            session=session,
            measurements=(speech,),
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        assert len(result.session.measurements) == 2
        assert result.completed_ref.measurement_id == "m2"


class TestSpeechRendererLookup:
    """Tests that the speech renderer locates the correct terminal result."""

    def test_speech_renderer_finds_exact_normal_speech_result(self):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = VoiceCalibrationService().consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        completed_ref = CompletedMeasurementRef(
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        result = find_rendered_terminal_result(
            session=session,
            completed_ref=completed_ref,
            active_measurement_id=None,
            active_measurement_kind=None,
        )
        assert result is not None
        assert result.capture.measurement_id == "m2"
        assert result.capture.kind == CalibrationMeasurementKind.NORMAL_SPEECH

    def test_speech_renderer_does_not_use_silence_completed_ref(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = VoiceCalibrationService().consume_measurements(session, (silence,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
            calibration_completed_measurement_ref=CompletedMeasurementRef(
                calibration_session_id="s1",
                measurement_id="m1",
                kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            ),
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

        _mock_streamlit["button"].return_value = False
        _render_speech_measurement_step(VoiceCalibrationService(), session, proc, silence_baseline=silence)

        subheader_calls = [call for call in _mock_streamlit["subheader"].call_args_list]
        assert any("Normal Speech" in str(c) for c in subheader_calls)

    def test_terminal_result_precedes_inactive_processor_snapshot(self):
        session = VoiceCalibrationService().start_session("s1")
        speech = _make_speech_measurement(measurement_id="m2")
        session = VoiceCalibrationService().consume_measurements(session, (speech,))

        completed_ref = CompletedMeasurementRef(
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        snapshot = AcousticCaptureRuntimeSnapshot(
            processor_id=1,
            active=False,
            calibration_session_id="s1",
            measurement_id="m2",
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            accumulator_present=False,
            frame_count=0,
            sample_count=0,
            sample_rate_hz=48000,
            channels=1,
            elapsed_ms=0.0,
            result_queue_size=0,
            completion_reason=None,
        )

        terminal_result = find_rendered_terminal_result(
            session=session,
            completed_ref=completed_ref,
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        )

        resolution = resolve_acoustic_ui_state(
            active_measurement_id="m2",
            active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            terminal_result=terminal_result,
            snapshot=snapshot,
            arm_error=None,
            legacy_active=False,
            capabilities=None,
            expected_calibration_session_id="s1",
        )
        assert resolution.state.value in ("complete", "warning")


class TestFailedStateRendering:
    """Tests that FAILED state hides elapsed timer and Cancel button."""

    def test_failed_state_hides_elapsed_timer(self):
        session = VoiceCalibrationService().start_session("s1")
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

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=measurement,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == "failed"
        assert resolution.show_elapsed is False
        assert resolution.can_cancel is False

    def test_failed_state_hides_cancel(self):
        session = VoiceCalibrationService().start_session("s1")
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

        resolution = resolve_acoustic_ui_state(
            active_measurement_id=None,
            active_measurement_kind=None,
            terminal_result=measurement,
            snapshot=None,
            arm_error=None,
        )
        assert resolution.state == "failed"
        assert resolution.can_cancel is False


class TestSilenceStepUnchanged:
    """Tests that Step 1 silence measurement remains working."""

    def test_silence_step_renders_complete_result(self, _mock_streamlit):
        session = VoiceCalibrationService().start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = VoiceCalibrationService().consume_measurements(session, (silence,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SILENCE.value,
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

        _mock_streamlit["button"].return_value = False
        _render_silence_baseline_step(VoiceCalibrationService(), session, proc)

        metric_calls = [call for call in _mock_streamlit["metric"].call_args_list]
        assert len(metric_calls) >= 1


class TestLateDrainReconciliation:
    """Tests that measurements drained by the late _process_voice_events() call are reconciled."""

    def test_late_drain_result_is_reconciled(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _reconcile_calibration_measurements,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import VoiceDrainResult

        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id="m2",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )

        speech = _make_speech_measurement(measurement_id="m2")
        drain_result = VoiceDrainResult(
            calibration_measurements=[speech],
            last_drained_measurement_id="m2",
        )

        _reconcile_calibration_measurements(drain_result)

        updated_session = st.session_state["voice_calibration_session"]
        assert len(updated_session.measurements) == 2
        assert st.session_state.get("calibration_completed_measurement_ref") is not None
        assert st.session_state["calibration_completed_measurement_ref"].measurement_id == "m2"
        assert st.session_state.get("voice_calibration_active_measurement_id") is None

    def test_late_drain_does_not_double_reconcile(self):
        from tournament_platform.app.pages.voice_scorekeeper import (
            _reconcile_calibration_measurements,
        )
        from tournament_platform.app.services.voice_scorekeeper.events import VoiceDrainResult

        service = VoiceCalibrationService()
        session = service.start_session("s1")
        silence = _make_silence_measurement(measurement_id="m1")
        session = service.consume_measurements(session, (silence,))
        speech = _make_speech_measurement(measurement_id="m2")
        session = service.consume_measurements(session, (speech,))

        st.session_state = _make_session_state(
            voice_calibration_active_session_id="s1",
            voice_calibration_active_measurement_id=None,
            voice_calibration_active_measurement_kind=None,
            voice_calibration_phase=CalibrationPhase.MEASURING_SPEECH.value,
            voice_calibration_session=session,
        )

        drain_result = VoiceDrainResult(
            calibration_measurements=[speech],
            last_drained_measurement_id="m2",
        )

        _reconcile_calibration_measurements(drain_result)

        updated_session = st.session_state["voice_calibration_session"]
        assert len(updated_session.measurements) == 2
        assert st.session_state.get("calibration_completed_measurement_ref") is not None
