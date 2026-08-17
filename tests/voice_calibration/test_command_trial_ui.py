"""
Command Trial UI state and button handler tests.

Tests the typed CommandTrialUIState transitions, Start Trial button behavior,
acknowledgement verification, and audit event emission.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationArmAcknowledgement,
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    CommandTrialUIState,
    CommandTrialUIStatus,
    TrialClassification,
)
from tournament_platform.app.services.voice_calibration.service import VoiceCalibrationService
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    VOICE_RUNTIME_IMPLEMENTATION_VERSION,
    AcousticCaptureRuntimeSnapshot,
    VoiceAudioProcessor,
    VoiceRuntimeMode,
)
from tournament_platform.app.components.voice_scorekeeper.voice_calibration import (
    _arm_command_trial,
    _build_trial_context,
    _clear_command_trial_ui_state,
    _emit_arm_state_verified,
    _emit_ui_ack_received,
    _emit_ui_arm_clicked,
    _get_command_trial_ui_state,
    _set_command_trial_ui_state,
    _verify_acknowledgement,
    render_voice_calibration,
)


def _make_mock_processor() -> MagicMock:
    proc = MagicMock(spec=VoiceAudioProcessor)
    proc._asr_ready = True
    proc.api_version = 2
    proc._implementation_version = VOICE_RUNTIME_IMPLEMENTATION_VERSION
    proc._processor_generation = 1
    proc._worker_thread = MagicMock()
    proc._worker_thread.is_alive.return_value = True
    proc.get_processor_diagnostics.return_value = {
        "audio_frames_received": 1,
        "last_frame_timestamp": time.monotonic() - 1.0,
    }
    proc.get_acoustic_capture_snapshot.return_value = AcousticCaptureRuntimeSnapshot(
        processor_id=id(proc),
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
    return proc


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
        "voice_runtime_mode": VoiceRuntimeMode.CALIBRATION.value,
        "voice_calibration_phase": CalibrationPhase.COMMAND_TRIAL.value,
        "voice_webrtc_ctx": None,
        "match_manager": MagicMock(),
        "voice_calibration_session": None,
        "voice_calibration_active_trial_id": None,
    }
    defaults.update(overrides)
    return _FakeSessionState(**defaults)


@pytest.fixture(autouse=True)
def _mock_streamlit():
    with patch.object(st, "subheader") as mock_subheader, \
         patch.object(st, "caption") as mock_caption, \
         patch.object(st, "columns") as mock_columns, \
         patch.object(st, "metric") as mock_metric, \
         patch.object(st, "button") as mock_button, \
         patch.object(st, "info") as mock_info, \
         patch.object(st, "error") as mock_error, \
         patch.object(st, "success") as mock_success, \
         patch.object(st, "warning") as mock_warning, \
         patch.object(st, "markdown") as mock_markdown, \
         patch.object(st, "divider") as mock_divider, \
         patch.object(st, "expander") as mock_expander, \
         patch.object(st, "rerun") as mock_rerun, \
         patch("tournament_platform.app.pages.voice_scorekeeper._get_webrtc_playing_state", return_value=True):
        def columns_side_effect(n):
            return [MagicMock() for _ in range(n)]
        mock_columns.side_effect = columns_side_effect
        mock_expander.return_value.__enter__ = MagicMock(return_value=None)
        mock_expander.return_value.__exit__ = MagicMock(return_value=False)
        yield {
            "subheader": mock_subheader,
            "caption": mock_caption,
            "columns": mock_columns,
            "metric": mock_metric,
            "button": mock_button,
            "info": mock_info,
            "error": mock_error,
            "success": mock_success,
            "warning": mock_warning,
            "markdown": mock_markdown,
            "divider": mock_divider,
            "expander": mock_expander,
            "rerun": mock_rerun,
        }


class TestCommandTrialUIState:
    def test_unarmed_state_is_initialized_on_entry(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        _mock_streamlit["button"].return_value = False
        render_voice_calibration(VoiceCalibrationService())

        ct_ui_state = _get_command_trial_ui_state()
        assert ct_ui_state is not None
        assert ct_ui_state.status == CommandTrialUIStatus.UNARMED
        assert ct_ui_state.calibration_session_id == session.session_id
        assert ct_ui_state.attempt_index == 0

    def test_start_trial_button_is_enabled_in_unarmed_state(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        _mock_streamlit["button"].return_value = False
        render_voice_calibration(VoiceCalibrationService())

        button_calls = [call for call in _mock_streamlit["button"].call_args_list if call[1].get("key") == "cal_start_trial"]
        assert len(button_calls) == 1
        assert button_calls[0][1].get("disabled") is not True
        assert button_calls[0][1].get("type") == "primary"

    def test_start_trial_generates_new_trial_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        trial_ids = []

        def arm_side_effect(context, *args, **kwargs):
            trial_ids.append(context.calibration_trial_id)
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect
        proc.get_calibration_trial_snapshot.return_value = {
            "processor_id": id(proc),
            "calibration_session_id": session.session_id,
            "trial_id": "dynamic",
            "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
            "expected_command_id": "point_red",
            "expected_phrase": "point red",
            "armed_at": time.time(),
            "claimed": False,
        }

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())

        assert len(trial_ids) == 1
        assert trial_ids[0] is not None

    def test_start_trial_uses_current_calibration_session(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        captured_context = None

        def arm_side_effect(context, *args, **kwargs):
            nonlocal captured_context
            captured_context = context
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect
        proc.get_calibration_trial_snapshot.return_value = {
            "processor_id": id(proc),
            "calibration_session_id": session.session_id,
            "trial_id": "dynamic",
            "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
            "expected_command_id": "point_red",
            "expected_phrase": "point red",
            "armed_at": time.time(),
            "claimed": False,
        }

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())

        assert captured_context is not None
        assert captured_context.calibration_session_id == session.session_id
        assert captured_context.capture_kind == CalibrationCaptureKind.COMMAND_TRIAL

    def test_start_trial_uses_currently_mounted_processor(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        proc.arm_calibration_trial.return_value = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        proc.get_calibration_trial_snapshot.return_value = {
            "processor_id": id(proc),
            "calibration_session_id": session.session_id,
            "trial_id": "trial-123",
            "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
            "expected_command_id": "point_red",
            "expected_phrase": "point red",
            "armed_at": time.time(),
            "claimed": False,
        }

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())

        proc.arm_calibration_trial.assert_called_once()

    def test_accepted_ack_changes_ui_state_to_armed(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        last_context = {}

        def arm_side_effect(context, *args, **kwargs):
            last_context["trial_id"] = context.calibration_trial_id
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect

        def snapshot_side_effect():
            return {
                "processor_id": id(proc),
                "calibration_session_id": session.session_id,
                "trial_id": last_context.get("trial_id", "dynamic"),
                "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
                "expected_command_id": "point_red",
                "expected_phrase": "point red",
                "armed_at": time.time(),
                "claimed": False,
            }
        proc.get_calibration_trial_snapshot.side_effect = snapshot_side_effect

        new_state = _arm_command_trial(session, proc, attempt_index=0)
        assert new_state.status == CommandTrialUIStatus.ARMED
        assert new_state.trial_id is not None
        assert new_state.processor_id == id(proc)

    def test_rejected_ack_changes_ui_state_to_arm_rejected(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        proc.arm_calibration_trial.return_value = CalibrationArmAcknowledgement(
            accepted=False,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=None,
            rejection_reason="active_capture_already_set",
        )

        new_state = _arm_command_trial(session, proc, attempt_index=0)
        assert new_state.status == CommandTrialUIStatus.ARM_REJECTED
        assert new_state.rejection_reason == "active_capture_already_set"

    def test_rejected_ack_leaves_start_trial_enabled(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        proc.arm_calibration_trial.return_value = CalibrationArmAcknowledgement(
            accepted=False,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=None,
            rejection_reason="active_capture_already_set",
        )

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            elif kwargs.get("key") == "cal_try_again":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())

        start_calls = [call for call in _mock_streamlit["button"].call_args_list if call[1].get("key") == "cal_start_trial"]
        assert len(start_calls) == 1
        assert start_calls[0][1].get("disabled") is not True

    def test_ui_never_displays_armed_when_ack_validation_fails(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()

        def arm_side_effect(context, *args, **kwargs):
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect
        proc.get_calibration_trial_snapshot.return_value = None

        new_state = _arm_command_trial(session, proc, attempt_index=0)
        assert new_state.status == CommandTrialUIStatus.ARM_REJECTED
        assert new_state.rejection_reason == "processor_context_verification_failed"


class TestRetrySemantics:
    def test_retry_after_failed_result_generates_new_trial_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        trial_ids = []

        def arm_side_effect(context, *args, **kwargs):
            trial_ids.append(context.calibration_trial_id)
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect
        proc.get_calibration_trial_snapshot.return_value = {
            "processor_id": id(proc),
            "calibration_session_id": session.session_id,
            "trial_id": "dynamic",
            "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
            "expected_command_id": "point_red",
            "expected_phrase": "point red",
            "armed_at": time.time(),
            "claimed": False,
        }

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            elif kwargs.get("key") == "cal_retry":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())
        first_id = trial_ids[-1]

        _set_command_trial_ui_state(CommandTrialUIState(
            status=CommandTrialUIStatus.COMPLETED,
            calibration_session_id=session.session_id,
            trial_id=first_id,
            attempt_index=0,
        ))

        render_voice_calibration(VoiceCalibrationService())
        second_id = trial_ids[-1]
        assert first_id != second_id

    def test_retry_after_timeout_generates_new_trial_id(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        trial_ids = []

        def arm_side_effect(context, *args, **kwargs):
            trial_ids.append(context.calibration_trial_id)
            return CalibrationArmAcknowledgement(
                accepted=True,
                processor_id=id(proc),
                calibration_session_id=session.session_id,
                trial_id=context.calibration_trial_id,
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
                armed_at=time.time(),
                rejection_reason=None,
            )
        proc.arm_calibration_trial.side_effect = arm_side_effect
        proc.get_calibration_trial_snapshot.return_value = {
            "processor_id": id(proc),
            "calibration_session_id": session.session_id,
            "trial_id": "dynamic",
            "capture_kind": CalibrationCaptureKind.COMMAND_TRIAL,
            "expected_command_id": "point_red",
            "expected_phrase": "point red",
            "armed_at": time.time(),
            "claimed": False,
        }

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            elif kwargs.get("key") == "cal_retry":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())
        first_id = trial_ids[-1]

        _set_command_trial_ui_state(CommandTrialUIState(
            status=CommandTrialUIStatus.TIMED_OUT,
            calibration_session_id=session.session_id,
            trial_id=first_id,
            attempt_index=0,
        ))

        render_voice_calibration(VoiceCalibrationService())
        second_id = trial_ids[-1]
        assert first_id != second_id

    def test_retry_after_arm_rejection_calls_processor_again(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        proc.arm_calibration_trial.return_value = CalibrationArmAcknowledgement(
            accepted=False,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="rejected-trial",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=None,
            rejection_reason="active_capture_already_set",
        )

        def button_side_effect(*args, **kwargs):
            if kwargs.get("key") == "cal_start_trial":
                return True
            elif kwargs.get("key") == "cal_try_again":
                return True
            return False
        _mock_streamlit["button"].side_effect = button_side_effect

        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        render_voice_calibration(VoiceCalibrationService())
        assert proc.arm_calibration_trial.call_count == 1

        render_voice_calibration(VoiceCalibrationService())
        assert proc.arm_calibration_trial.call_count == 2


class TestProcessorVerification:
    def test_processor_id_mismatch_fails_closed(self):
        session = VoiceCalibrationService().start_command_trial_session()
        proc_a = MagicMock(spec=VoiceAudioProcessor)
        proc_b = MagicMock(spec=VoiceAudioProcessor)
        ack = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc_a),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        verified, reason = _verify_acknowledgement(ack, proc_b, session, "trial-123", CalibrationCaptureKind.COMMAND_TRIAL)
        assert verified is False
        assert reason == "processor_id_mismatch"

    def test_trial_id_mismatch_fails_closed(self):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        ack = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        verified, reason = _verify_acknowledgement(ack, proc, session, "different-trial", CalibrationCaptureKind.COMMAND_TRIAL)
        assert verified is False
        assert reason == "trial_id_mismatch"

    def test_calibration_session_mismatch_fails_closed(self):
        session = VoiceCalibrationService().start_command_trial_session()
        other_session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        ack = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc),
            calibration_session_id=other_session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        verified, reason = _verify_acknowledgement(ack, proc, session, "trial-123", CalibrationCaptureKind.COMMAND_TRIAL)
        assert verified is False
        assert reason == "calibration_session_mismatch"

    def test_capture_kind_mismatch_fails_closed(self):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        ack = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        verified, reason = _verify_acknowledgement(ack, proc, session, "trial-123", CalibrationCaptureKind.NEGATIVE_TRIAL)
        assert verified is False
        assert reason == "capture_kind_mismatch"


class TestAuditEvents:
    def test_ui_arm_click_emitted(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        _emit_ui_arm_clicked(
            session=session,
            trial_id="trial-123",
            expected_command_id="point_red",
            expected_phrase="point red",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            proc=proc,
            phase=CalibrationPhase.COMMAND_TRIAL,
            attempt_index=0,
        )
        audit_events = st.session_state.get("voice_audit_events", [])
        ui_arm_clicks = [e for e in audit_events if e.get("stage") == "calibration_command_trial_ui_arm_clicked"]
        assert len(ui_arm_clicks) >= 1

    def test_ui_ack_received_emitted(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        ack = CalibrationArmAcknowledgement(
            accepted=True,
            processor_id=id(proc),
            calibration_session_id=session.session_id,
            trial_id="trial-123",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            armed_at=time.time(),
            rejection_reason=None,
        )
        _emit_ui_ack_received(ack, None)
        audit_events = st.session_state.get("voice_audit_events", [])
        ui_acks = [e for e in audit_events if e.get("stage") == "calibration_command_trial_ui_ack_received"]
        assert len(ui_acks) >= 1

    def test_arm_state_verified_emitted_on_success(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        _emit_arm_state_verified(proc, session, "trial-123", CalibrationCaptureKind.COMMAND_TRIAL, accepted=True)
        audit_events = st.session_state.get("voice_audit_events", [])
        verified = [e for e in audit_events if e.get("stage") == "calibration_command_trial_arm_state_verified"]
        assert len(verified) >= 1

    def test_arm_state_mismatch_emitted_on_failure(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = MagicMock(spec=VoiceAudioProcessor)
        proc._asr_ready = True
        _emit_arm_state_verified(proc, session, "trial-123", CalibrationCaptureKind.COMMAND_TRIAL, accepted=False)
        audit_events = st.session_state.get("voice_audit_events", [])
        mismatches = [e for e in audit_events if e.get("stage") == "calibration_command_trial_arm_state_mismatch"]
        assert len(mismatches) >= 1


class TestPhaseEntry:
    def test_phase_entry_initializes_unarmed_state(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        _mock_streamlit["button"].return_value = False
        render_voice_calibration(VoiceCalibrationService())

        ct_ui_state = _get_command_trial_ui_state()
        assert ct_ui_state is not None
        assert ct_ui_state.status == CommandTrialUIStatus.UNARMED
        assert ct_ui_state.calibration_session_id == session.session_id

    def test_phase_entry_does_not_auto_arm(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        _mock_streamlit["button"].return_value = False
        render_voice_calibration(VoiceCalibrationService())

        proc.arm_calibration_trial.assert_not_called()

    def test_phase_entry_clears_acoustic_keys_only(self, _mock_streamlit):
        session = VoiceCalibrationService().start_command_trial_session()
        proc = _make_mock_processor()
        st.session_state = _make_session_state(
            voice_calibration_session=session,
            voice_calibration_active_session_id=session.session_id,
            voice_calibration_active_trial_id=None,
            voice_calibration_active_measurement_id="old-measurement",
            voice_calibration_active_measurement_kind=CalibrationMeasurementKind.SILENCE_BASELINE.value,
            voice_calibration_phase=CalibrationPhase.COMMAND_TRIAL.value,
            voice_webrtc_ctx={"processor": proc},
        )
        _mock_streamlit["button"].return_value = False
        render_voice_calibration(VoiceCalibrationService())

        assert st.session_state.get("voice_calibration_active_session_id") == session.session_id
        assert st.session_state.get("voice_calibration_active_trial_id") is None
        assert st.session_state.get("voice_calibration_active_measurement_id") is None
        assert st.session_state.get("voice_calibration_active_measurement_kind") is None
