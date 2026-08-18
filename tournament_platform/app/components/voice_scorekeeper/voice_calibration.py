import inspect
import logging
import time
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Optional, Tuple

import streamlit as st

from tournament_platform.app.services.voice_scorekeeper.events import (
    CalibrationCaptureContext,
    RuntimeTransitionAcknowledgement,
    VoiceDrainResult,
    VoiceRuntimeMode,
)
from tournament_platform.app.services.voice_scorekeeper.runtime import (
    AcousticCaptureRuntimeSnapshot,
    VOICE_AUDIO_PROCESSOR_API_VERSION,  # noqa: F401 — re-exported for tests
    VoiceAudioProcessor,
)
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureContext,
    AcousticMeasurementResult,
    AcousticRecommendation,
    AliasCandidateStatus,
    AsrExperimentRecommendation,
    CalibrationArmAcknowledgement,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationOverallStatus,
    CalibrationPhase,
    CalibrationSession,
    CalibrationState,
    CalibrationResults,
    CanonicalCommandIntent,
    CommandTrial,
    CommandTrialUIState,
    CommandTrialUIStatus,
    LiveVoiceProfileRecommendation,
    LiveVoiceRuntimeConfig,
    LiveVoiceSettingsSnapshot,
    RecommendationStatus,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
    TrialClassification,
    VoiceProfileActivationStatus,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)
from tournament_platform.app.services.voice_calibration.recommendations import (
    generate_silence_recommendations,
    generate_speech_recommendations,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationProcessorReadiness:
    """Authoritative readiness snapshot for calibration processor."""

    ready: bool
    status: str
    processor_id: int | None
    processor_generation: int | None
    webrtc_playing: bool
    processor_present: bool
    worker_alive: bool
    recent_frame_received: bool
    restart_required: bool
    reason: str | None


READINESS_FRAME_MAX_AGE_SECONDS = 5.0
READINESS_RESTART_TIMEOUT_SECONDS = 15.0


def resolve_calibration_processor_readiness(
    *,
    webrtc_playing: bool,
    processor: VoiceAudioProcessor | None,
    expected_api_version: int,
    expected_implementation_version: str,
    current_time: float | None = None,
) -> CalibrationProcessorReadiness:
    """Resolve calibration processor readiness from current state.

    Uses the current processor and WebRTC state directly. Does not depend
    on stale Streamlit flags when the current processor can prove readiness.
    """
    if current_time is None:
        current_time = time.monotonic()

    if not webrtc_playing:
        return CalibrationProcessorReadiness(
            ready=False,
            status="MICROPHONE_STOPPED",
            processor_id=id(processor) if processor is not None else None,
            processor_generation=getattr(processor, "_processor_generation", None) if processor is not None else None,
            webrtc_playing=False,
            processor_present=processor is not None,
            worker_alive=False,
            recent_frame_received=False,
            restart_required=False,
            reason="microphone_not_playing",
        )

    if processor is None:
        return CalibrationProcessorReadiness(
            ready=False,
            status="WAITING_FOR_PROCESSOR",
            processor_id=None,
            processor_generation=None,
            webrtc_playing=webrtc_playing,
            processor_present=False,
            worker_alive=False,
            recent_frame_received=False,
            restart_required=False,
            reason="no_processor",
        )

    processor_id = id(processor)
    processor_generation = getattr(processor, "_processor_generation", None)
    api_version = getattr(processor, "api_version", None)
    impl_version = getattr(processor, "_implementation_version", None)
    worker_alive = getattr(processor, "_worker_thread", None) is not None and getattr(processor, "_worker_thread").is_alive()
    diag = getattr(processor, "get_processor_diagnostics", lambda: {})()
    audio_frames_received = diag.get("audio_frames_received", 0)
    last_frame_timestamp = diag.get("last_frame_timestamp")
    restart_required = False
    restart_reason = None

    if api_version is not None and api_version != expected_api_version:
        restart_required = True
        restart_reason = f"api_version_mismatch_{api_version}_expected_{expected_api_version}"

    if impl_version is not None and impl_version != expected_implementation_version:
        restart_required = True
        restart_reason = f"implementation_version_mismatch_{impl_version}"

    # Point 6: ASR readiness is NOT required for calibration.
    # Calibration measures raw audio levels and VAD effectiveness, not ASR.
    # We remove the mandatory asr_not_ready check here.

    recent_frame = False
    if last_frame_timestamp is not None:
        frame_age = current_time - last_frame_timestamp
        recent_frame = frame_age <= READINESS_FRAME_MAX_AGE_SECONDS
    elif audio_frames_received > 0:
        recent_frame = True

    if audio_frames_received == 0 and not recent_frame:
        if not restart_required:
            restart_required = True
            restart_reason = "no_frames_received"

    if restart_required:
        return CalibrationProcessorReadiness(
            ready=False,
            status="RESTART_REQUIRED",
            processor_id=processor_id,
            processor_generation=processor_generation,
            webrtc_playing=webrtc_playing,
            processor_present=True,
            worker_alive=worker_alive,
            recent_frame_received=recent_frame,
            restart_required=True,
            reason=restart_reason,
        )

    if audio_frames_received == 0:
        return CalibrationProcessorReadiness(
            ready=False,
            status="WAITING_FOR_FIRST_FRAME",
            processor_id=processor_id,
            processor_generation=processor_generation,
            webrtc_playing=webrtc_playing,
            processor_present=True,
            worker_alive=worker_alive,
            recent_frame_received=False,
            restart_required=False,
            reason="awaiting_first_frame",
        )

    return CalibrationProcessorReadiness(
        ready=True,
        status="READY",
        processor_id=processor_id,
        processor_generation=processor_generation,
        webrtc_playing=webrtc_playing,
        processor_present=True,
        worker_alive=worker_alive,
        recent_frame_received=True,
        restart_required=False,
        reason=None,
    )

def _get_acoustic_capture_snapshot(
    proc: object | None,
) -> AcousticCaptureRuntimeSnapshot | None:
    if proc is None:
        return None

    snapshot_getter = getattr(proc, "get_acoustic_capture_snapshot", None)
    if callable(snapshot_getter):
        try:
            return snapshot_getter()
        except Exception:
            return None

    legacy_getter = getattr(proc, "get_acoustic_capture_runtime_snapshot", None)
    if callable(legacy_getter):
        try:
            return legacy_getter()
        except Exception:
            return None

    return None


def _get_processor_api_version(proc: object | None) -> int:
    if proc is None:
        return 0
    version = getattr(proc, "api_version", 1)
    try:
        return int(version)
    except (TypeError, ValueError):
        return 1


def _has_legacy_active_capture(proc: object | None) -> bool:
    if proc is None:
        return False
    legacy_method = getattr(proc, "has_active_acoustic_capture", None)
    if callable(legacy_method):
        try:
            return bool(legacy_method())
        except Exception:
            return False
    return False


_CT_UI_STATE_KEY = "voice_calibration_command_trial_ui_state"


def _get_command_trial_ui_state() -> CommandTrialUIState | None:
    raw = st.session_state.get(_CT_UI_STATE_KEY)
    if raw is None:
        return None
    if isinstance(raw, CommandTrialUIState):
        return raw
    if isinstance(raw, dict):
        try:
            status = CommandTrialUIStatus(raw.get("status", "unarmed"))
            return CommandTrialUIState(
                status=status,
                calibration_session_id=raw.get("calibration_session_id", ""),
                trial_id=raw.get("trial_id"),
                expected_command_id=raw.get("expected_command_id"),
                expected_phrase=raw.get("expected_phrase"),
                processor_id=raw.get("processor_id"),
                armed_at=raw.get("armed_at"),
                rejection_reason=raw.get("rejection_reason"),
                attempt_index=raw.get("attempt_index", 0),
            )
        except (TypeError, ValueError):
            return None
    return None


def _set_command_trial_ui_state(state: CommandTrialUIState) -> None:
    st.session_state[_CT_UI_STATE_KEY] = state


def _clear_command_trial_ui_state() -> None:
    st.session_state.pop(_CT_UI_STATE_KEY, None)


def _build_trial_context(
    session: CalibrationSession,
    proc: VoiceAudioProcessor,
    capture_kind: CalibrationCaptureKind = CalibrationCaptureKind.COMMAND_TRIAL,
) -> CalibrationCaptureContext:
    current_command = _derive_current_command(session)
    expected_phrase = current_command.replace("_", " ") if current_command else ""
    return CalibrationCaptureContext(
        calibration_session_id=session.session_id,
        calibration_trial_id=str(uuid.uuid4()),
        capture_kind=capture_kind,
        expected_command_id=current_command or "",
        expected_phrase=expected_phrase,
    )


def _verify_acknowledgement(
    ack: CalibrationArmAcknowledgement,
    proc: VoiceAudioProcessor,
    session: CalibrationSession,
    trial_id: str,
    capture_kind: CalibrationCaptureKind,
) -> tuple[bool, str | None]:
    if not ack.accepted:
        return False, ack.rejection_reason
    if ack.processor_id != id(proc):
        return False, "processor_id_mismatch"
    if ack.calibration_session_id != session.session_id:
        return False, "calibration_session_mismatch"
    if ack.trial_id != trial_id:
        return False, "trial_id_mismatch"
    if ack.capture_kind != capture_kind:
        return False, "capture_kind_mismatch"
    snapshot = proc.get_calibration_trial_snapshot()
    if snapshot is None:
        return False, "processor_context_verification_failed"
    if snapshot.get("processor_id") != ack.processor_id:
        return False, "processor_context_verification_failed"
    if snapshot.get("calibration_session_id") != ack.calibration_session_id:
        return False, "processor_context_verification_failed"
    if snapshot.get("trial_id") != ack.trial_id:
        return False, "processor_context_verification_failed"
    if snapshot.get("capture_kind") != ack.capture_kind:
        return False, "processor_context_verification_failed"
    if snapshot.get("claimed"):
        return False, "processor_context_verification_failed"
    return True, None


def _emit_ui_arm_clicked(
    session: CalibrationSession,
    trial_id: str,
    expected_command_id: str | None,
    expected_phrase: str | None,
    capture_kind: CalibrationCaptureKind,
    proc: VoiceAudioProcessor,
    phase: CalibrationPhase,
    attempt_index: int,
) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace
    _append_continuous_trace(
        "calibration_command_trial_ui_arm_clicked",
        f"calibration_session_id={session.session_id} "
        f"trial_id={trial_id} "
        f"expected_command_id={expected_command_id} "
        f"expected_phrase={expected_phrase} "
        f"capture_kind={capture_kind.value} "
        f"UI_processor_id={id(proc)} "
        f"phase={phase.value} "
        f"attempt_index={attempt_index}",
    )


def _emit_ui_ack_received(
    ack: CalibrationArmAcknowledgement,
    rejection_reason: str | None,
) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace
    _append_continuous_trace(
        "calibration_command_trial_ui_ack_received",
        f"accepted={ack.accepted} "
        f"ack_processor_id={ack.processor_id} "
        f"ack_session_id={ack.calibration_session_id} "
        f"ack_trial_id={ack.trial_id} "
        f"ack_capture_kind={ack.capture_kind.value if ack.capture_kind else 'N/A'} "
        f"rejection_reason={rejection_reason or 'N/A'}",
    )


def _emit_arm_state_verified(
    proc: VoiceAudioProcessor,
    session: CalibrationSession,
    trial_id: str,
    capture_kind: CalibrationCaptureKind,
    accepted: bool,
) -> None:
    from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace
    if accepted:
        _append_continuous_trace(
            "calibration_command_trial_arm_state_verified",
            f"processor_id={id(proc)} "
            f"session={session.session_id} "
            f"trial_id={trial_id} "
            f"capture_kind={capture_kind.value}",
        )
    else:
        _append_continuous_trace(
            "calibration_command_trial_arm_state_mismatch",
            f"processor_id={id(proc)} "
            f"session={session.session_id} "
            f"trial_id={trial_id} "
            f"capture_kind={capture_kind.value}",
        )


def _arm_command_trial(
    session: CalibrationSession,
    proc: VoiceAudioProcessor,
    capture_kind: CalibrationCaptureKind = CalibrationCaptureKind.COMMAND_TRIAL,
    attempt_index: int = 0,
) -> CommandTrialUIState:
    if not _is_processor_ready(proc):
        return CommandTrialUIState(
            status=CommandTrialUIStatus.WAITING_FOR_MICROPHONE,
            calibration_session_id=session.session_id,
            trial_id=None,
            expected_command_id=None,
            expected_phrase=None,
            processor_id=id(proc),
            armed_at=None,
            rejection_reason="processor_not_ready",
            attempt_index=attempt_index,
        )

    ctx = _build_trial_context(session, proc, capture_kind)
    _emit_ui_arm_clicked(
        session=session,
        trial_id=ctx.calibration_trial_id,
        expected_command_id=ctx.expected_command_id,
        expected_phrase=ctx.expected_phrase,
        capture_kind=capture_kind,
        proc=proc,
        phase=CalibrationPhase.COMMAND_TRIAL,
        attempt_index=attempt_index,
    )
    ack = _arm_trial(proc, ctx)
    _emit_ui_ack_received(ack, ack.rejection_reason)
    verified, reason = _verify_acknowledgement(ack, proc, session, ctx.calibration_trial_id, capture_kind)
    _emit_arm_state_verified(proc, session, ctx.calibration_trial_id, capture_kind, verified)
    if verified:
        st.session_state["voice_calibration_active_trial_id"] = ctx.calibration_trial_id
        return CommandTrialUIState(
            status=CommandTrialUIStatus.ARMED,
            calibration_session_id=session.session_id,
            trial_id=ctx.calibration_trial_id,
            expected_command_id=ctx.expected_command_id,
            expected_phrase=ctx.expected_phrase,
            processor_id=id(proc),
            armed_at=ack.armed_at,
            attempt_index=attempt_index,
        )
    st.session_state.pop("voice_calibration_active_trial_id", None)
    proc.clear_calibration_context()
    return CommandTrialUIState(
        status=CommandTrialUIStatus.ARM_REJECTED,
        calibration_session_id=session.session_id,
        trial_id=ctx.calibration_trial_id,
        expected_command_id=ctx.expected_command_id,
        expected_phrase=ctx.expected_phrase,
        processor_id=id(proc),
        rejection_reason=reason or ack.rejection_reason,
        attempt_index=attempt_index,
    )


@dataclass(frozen=True)
class VoiceProcessorCapabilities:
    api_version: int | None
    snapshot_available: bool
    legacy_snapshot_available: bool
    active_capture_check_available: bool
    acoustic_arm_available: bool
    acoustic_cancel_available: bool
    acoustic_drain_available: bool
    restart_required: bool
    restart_reason: str | None


def inspect_voice_processor_capabilities(
    proc: object | None,
) -> VoiceProcessorCapabilities:
    if proc is None:
        return VoiceProcessorCapabilities(
            api_version=None,
            snapshot_available=False,
            legacy_snapshot_available=False,
            active_capture_check_available=False,
            acoustic_arm_available=False,
            acoustic_cancel_available=False,
            acoustic_drain_available=False,
            restart_required=True,
            restart_reason="no_processor",
        )

    snapshot_getter = getattr(proc, "get_acoustic_capture_snapshot", None)
    legacy_snapshot_getter = getattr(proc, "get_acoustic_capture_runtime_snapshot", None)
    active_getter = getattr(proc, "has_active_acoustic_capture", None)
    arm_method = getattr(proc, "arm_acoustic_capture", None)
    cancel_method = getattr(proc, "cancel_acoustic_capture", None)
    drain_method = getattr(proc, "drain_acoustic_measurement_results", None)

    supports_snapshot = callable(snapshot_getter)
    supports_legacy_snapshot = callable(legacy_snapshot_getter)
    supports_active_check = callable(active_getter)
    supports_arm = callable(arm_method)
    supports_cancel = callable(cancel_method)
    supports_drain = callable(drain_method)

    api_version = _get_processor_api_version(proc)

    restart_required = not (supports_snapshot or supports_legacy_snapshot or supports_active_check)
    restart_reason = None
    if restart_required:
        restart_reason = "no_acoustic_capabilities"

    return VoiceProcessorCapabilities(
        api_version=api_version if api_version > 1 else None,
        snapshot_available=supports_snapshot,
        legacy_snapshot_available=supports_legacy_snapshot,
        active_capture_check_available=supports_active_check,
        acoustic_arm_available=supports_arm,
        acoustic_cancel_available=supports_cancel,
        acoustic_drain_available=supports_drain,
        restart_required=restart_required,
        restart_reason=restart_reason,
    )


class AcousticUiState(StrEnum):
    NOT_STARTED = "not_started"
    MEASURING = "measuring"
    RESULT_PENDING_COMMIT = "result_pending_commit"
    COMPLETE = "complete"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class AcousticUiResolution:
    state: AcousticUiState
    reason: str | None
    active_measurement_id: str | None
    processor_measurement_id: str | None
    can_start: bool
    can_cancel: bool
    show_elapsed: bool


def resolve_acoustic_ui_state(
    *,
    active_measurement_id: str | None,
    active_measurement_kind: CalibrationMeasurementKind | None,
    terminal_result: AcousticMeasurementResult | None,
    snapshot: AcousticCaptureRuntimeSnapshot | None,
    arm_error: str | None,
    legacy_active: bool = False,
    capabilities: VoiceProcessorCapabilities | None = None,
    expected_calibration_session_id: str | None = None,
    last_drained_measurement_id: str | None = None,
    reconciliation_error: str | None = None,
) -> AcousticUiResolution:
    processor_measurement_id = snapshot.measurement_id if snapshot is not None else None

    if terminal_result is not None:
        if terminal_result.capture.frame_count <= 0 and not terminal_result.capture.skipped:
            state = AcousticUiState.FAILED
        elif terminal_result.capture.warning_codes:
            state = AcousticUiState.WARNING
        else:
            state = AcousticUiState.COMPLETE

        return AcousticUiResolution(
            state=state,
            reason=None,
            active_measurement_id=None,
            processor_measurement_id=None,
            can_start=False,
            can_cancel=False,
            show_elapsed=False,
        )

    if active_measurement_id is not None:
        if (
            snapshot is not None
            and snapshot.active
            and snapshot.measurement_id == active_measurement_id
        ):
            if expected_calibration_session_id is not None:
                if snapshot.calibration_session_id != expected_calibration_session_id:
                    return AcousticUiResolution(
                        state=AcousticUiState.FAILED,
                        reason="calibration_session_id_mismatch",
                        active_measurement_id=active_measurement_id,
                        processor_measurement_id=processor_measurement_id,
                        can_start=False,
                        can_cancel=True,
                        show_elapsed=False,
                    )
            return AcousticUiResolution(
                state=AcousticUiState.MEASURING,
                reason=None,
                active_measurement_id=active_measurement_id,
                processor_measurement_id=processor_measurement_id,
                can_start=False,
                can_cancel=True,
                show_elapsed=True,
            )

        # Processor may have completed and queued the result between snapshots.
        if snapshot is not None and snapshot.result_queue_size > 0:
            return AcousticUiResolution(
                state=AcousticUiState.MEASURING,
                reason="result_pending_drain",
                active_measurement_id=active_measurement_id,
                processor_measurement_id=processor_measurement_id,
                can_start=False,
                can_cancel=False,
                show_elapsed=True,
            )

        # One-rerun grace: processor is inactive but we just drained a matching
        # result that has not yet been committed to the session.
        if (
            last_drained_measurement_id is not None
            and last_drained_measurement_id == active_measurement_id
            and (snapshot is None or not snapshot.active)
        ):
            return AcousticUiResolution(
                state=AcousticUiState.RESULT_PENDING_COMMIT,
                reason=None,
                active_measurement_id=active_measurement_id,
                processor_measurement_id=processor_measurement_id,
                can_start=False,
                can_cancel=False,
                show_elapsed=False,
            )

        # Snapshot is active but measurement_id does not match the UI's active
        # measurement. This is a capture synchronization error: do not adopt,
        # cancel, or accept results from the processor's active capture.
        if snapshot is not None and snapshot.active:
            return AcousticUiResolution(
                state=AcousticUiState.FAILED,
                reason="capture_synchronization_error",
                active_measurement_id=active_measurement_id,
                processor_measurement_id=processor_measurement_id,
                can_start=False,
                can_cancel=False,
                show_elapsed=False,
            )

        # Legacy processor without snapshot API but with active capture.
        if legacy_active:
            return AcousticUiResolution(
                state=AcousticUiState.MEASURING,
                reason="legacy_processor_active",
                active_measurement_id=active_measurement_id,
                processor_measurement_id=None,
                can_start=False,
                can_cancel=True,
                show_elapsed=True,
            )

        # Capability-first: only require restart when the processor lacks
        # every acoustic capability needed to safely manage calibration.
        if capabilities is not None and capabilities.restart_required:
            return AcousticUiResolution(
                state=AcousticUiState.FAILED,
                reason="processor_outdated_restart_required",
                active_measurement_id=active_measurement_id,
                processor_measurement_id=None,
                can_start=False,
                can_cancel=True,
                show_elapsed=False,
            )

        if reconciliation_error:
            return AcousticUiResolution(
                state=AcousticUiState.FAILED,
                reason=reconciliation_error,
                active_measurement_id=active_measurement_id,
                processor_measurement_id=None,
                can_start=False,
                can_cancel=False,
                show_elapsed=False,
            )

        return AcousticUiResolution(
            state=AcousticUiState.FAILED,
            reason="active_measurement_missing_from_processor",
            active_measurement_id=active_measurement_id,
            processor_measurement_id=None,
            can_start=False,
            can_cancel=False,
            show_elapsed=False,
        )

    if snapshot is not None and snapshot.active:
        return AcousticUiResolution(
            state=AcousticUiState.FAILED,
            reason="orphaned_processor_capture",
            active_measurement_id=snapshot.measurement_id,
            processor_measurement_id=processor_measurement_id,
            can_start=False,
            can_cancel=True,
            show_elapsed=False,
        )

    if legacy_active:
        return AcousticUiResolution(
            state=AcousticUiState.MEASURING,
            reason="legacy_processor_active_no_ui_id",
            active_measurement_id=None,
            processor_measurement_id=None,
            can_start=False,
            can_cancel=True,
            show_elapsed=True,
        )

    if arm_error:
        return AcousticUiResolution(
            state=AcousticUiState.FAILED,
            reason=arm_error,
            active_measurement_id=None,
            processor_measurement_id=None,
            can_start=True,
            can_cancel=False,
            show_elapsed=False,
        )

    return AcousticUiResolution(
        state=AcousticUiState.NOT_STARTED,
        reason=None,
        active_measurement_id=None,
        processor_measurement_id=None,
        can_start=True,
        can_cancel=False,
        show_elapsed=False,
    )


def _get_active_processor() -> Optional[VoiceAudioProcessor]:
    ctx = st.session_state.get("voice_webrtc_ctx")
    if ctx is None:
        return None
    if isinstance(ctx, dict):
        return ctx.get("processor")
    for attr_name in ("processor", "audio_processor", "voice_processor"):
        proc = getattr(ctx, attr_name, None)
        if proc is not None:
            return proc
    return None


def _get_current_processor() -> VoiceAudioProcessor | None:
    """Get the current processor from the active WebRTC context.

    Always reads from the live WebRTC context, never from stale session state.
    """
    from tournament_platform.app.pages.voice_scorekeeper import _get_voice_webrtc_processor

    ctx = st.session_state.get("voice_webrtc_ctx")
    return _get_voice_webrtc_processor(ctx)


def _is_processor_ready(proc: Optional[VoiceAudioProcessor]) -> bool:
    from tournament_platform.app.pages.voice_scorekeeper import _get_webrtc_playing_state
    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        VOICE_RUNTIME_IMPLEMENTATION_VERSION,
        VOICE_AUDIO_PROCESSOR_API_VERSION,
    )

    resolution = resolve_calibration_processor_readiness(
        webrtc_playing=_get_webrtc_playing_state(),
        processor=proc,
        expected_api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
        expected_implementation_version=VOICE_RUNTIME_IMPLEMENTATION_VERSION,
    )
    return resolution.ready


def _arm_trial(proc: VoiceAudioProcessor, context: CalibrationCaptureContext) -> CalibrationArmAcknowledgement:
    """Arm a calibration trial and return processor acknowledgement."""
    return proc.arm_calibration_trial(context)


def _disarm_trial(proc: Optional[VoiceAudioProcessor]) -> None:
    if proc is not None:
        proc.clear_calibration_context()


def _compute_post_calibration_runtime_mode() -> VoiceRuntimeMode:
    """Determine the correct runtime mode after calibration exits.

    Uses the actual user-facing state instead of a stale stored value.
    Falls back to the current ``voice_runtime_mode`` if it is already set
    to a valid non-CALIBRATION mode.
    """
    current = st.session_state.get("voice_runtime_mode")
    if current is not None and current != VoiceRuntimeMode.CALIBRATION:
        try:
            return VoiceRuntimeMode(current)
        except (TypeError, ValueError):
            pass

    listening = bool(st.session_state.get("voice_listening"))
    webrtc_playing = bool(
        st.session_state.get("voice_webrtc_streamer_state", {}).get("playing", False)
    )
    events_enabled = bool(st.session_state.get("voice_events_enabled", False))
    if listening and webrtc_playing:
        return VoiceRuntimeMode.LIVE
    if events_enabled and webrtc_playing:
        return VoiceRuntimeMode.LIVE
    return VoiceRuntimeMode.OFF


def _enter_calibration_mode(previous_mode: Optional[str]) -> None:
    if previous_mode is None:
        previous_mode = _compute_post_calibration_runtime_mode().value
    st.session_state["voice_calibration_previous_runtime_mode"] = previous_mode
    from tournament_platform.app.pages.voice_scorekeeper import _set_voice_runtime_mode
    _set_voice_runtime_mode(
        VoiceRuntimeMode.CALIBRATION,
        reason="calibration_started",
        caller="_enter_calibration_mode",
    )


def _exit_calibration_mode() -> None:
    """Restore the correct runtime mode after calibration exits.

    Falls back to computing the mode from actual user state when the
    stored previous mode is missing or stale.
    Never restores CALIBRATION — that would suppress live scoring.
    """
    previous = st.session_state.get("voice_calibration_previous_runtime_mode")
    st.session_state.pop("voice_calibration_previous_runtime_mode", None)

    if previous is not None:
        try:
            target_mode = VoiceRuntimeMode(previous)
        except (TypeError, ValueError):
            target_mode = _compute_post_calibration_runtime_mode()
    else:
        target_mode = _compute_post_calibration_runtime_mode()

    if target_mode == VoiceRuntimeMode.CALIBRATION:
        target_mode = _compute_post_calibration_runtime_mode()

    from tournament_platform.app.pages.voice_scorekeeper import _set_voice_runtime_mode
    _set_voice_runtime_mode(
        target_mode,
        reason="calibration_exit",
        caller="_exit_calibration_mode",
    )


def _derive_current_command(session: Optional[CalibrationSession]) -> Optional[str]:
    if session is None or not session.commands:
        return None
    idx = session.current_command_index
    if idx < len(session.commands):
        return session.commands[idx]
    return None


def _derive_attempt_count(session: Optional[CalibrationSession]) -> int:
    if session is None:
        return 0
    current_cmd = _derive_current_command(session)
    if current_cmd is None:
        return 0
    return sum(
        1
        for t in session.trials
        if t.expected_command_id == current_cmd
        and t.classification in {
            TrialClassification.EXACT,
            TrialClassification.VARIANT,
            TrialClassification.WRONG_COMMAND,
            TrialClassification.UNKNOWN,
            TrialClassification.EMPTY,
        }
    )


def _is_session_complete(session: Optional[CalibrationSession]) -> bool:
    if session is None or not session.commands:
        return False
    for cmd in session.commands:
        count = sum(
            1
            for t in session.trials
            if t.expected_command_id == cmd
            and t.classification in {
                TrialClassification.EXACT,
                TrialClassification.VARIANT,
                TrialClassification.WRONG_COMMAND,
                TrialClassification.UNKNOWN,
                TrialClassification.EMPTY,
            }
        )
        if count < session.attempts_per_command:
            return False
    return True


def find_rendered_terminal_result(
    session: Optional[CalibrationSession],
    completed_ref: Optional[Any],
    active_measurement_id: Optional[str] = None,
    active_measurement_kind: Optional[CalibrationMeasurementKind] = None,
) -> Optional[AcousticMeasurementResult]:
    """Find terminal measurement result with precedence.
    
    Lookup order:
    1. CompletedMeasurementRef (durable identity from reconciliation)
    2. Active measurement ID (still measuring or result pending)
    3. None
    
    IMPORTANT: This function is pure. It does NOT mutate session state.
    All state cleanup happens in the controller layer (voice_scorekeeper.py).
    
    Args:
        session: CalibrationSession to search
        completed_ref: CompletedMeasurementRef from reconciliation
        active_measurement_id: Active measurement ID (fallback lookup)
        active_measurement_kind: Active measurement kind (fallback lookup)
    
    Returns:
        Terminal AcousticMeasurementResult if found; None otherwise.
    """
    if session is None:
        return None
    
    # Priority 1: Completed reference (from reconciliation transaction)
    if completed_ref is not None:
        # Validate scope: measurement must belong to this session
        if hasattr(completed_ref, 'calibration_session_id'):
            if completed_ref.calibration_session_id != session.session_id:
                return None
        
        result = find_measurement_result(
            session,
            measurement_id=completed_ref.measurement_id,
            kind=completed_ref.kind,
        )
        if result is not None:
            return result
    
    # Priority 2: Active measurement (still being captured)
    if active_measurement_id is not None and active_measurement_kind is not None:
        return find_measurement_result(
            session,
            measurement_id=active_measurement_id,
            kind=active_measurement_kind,
        )
    
    return None


def find_measurement_result(
    session: Optional[CalibrationSession],
    *,
    measurement_id: str,
    kind: CalibrationMeasurementKind,
) -> Optional[AcousticMeasurementResult]:
    """Find a terminal measurement result by exact measurement ID and kind."""
    if session is None or measurement_id is None:
        return None
    for measurement in session.measurements:
        if measurement.capture.measurement_id == measurement_id and measurement.capture.kind == kind:
            return measurement
    return None


def _get_latest_measurement(
    session: Optional[CalibrationSession],
    active_measurement_id: Optional[str],
) -> Optional[AcousticMeasurementResult]:
    if session is None or active_measurement_id is None:
        return None
    matching = [m for m in session.measurements if m.capture.measurement_id == active_measurement_id]
    if not matching:
        return None
    return matching[-1]


def _classify_continuation(
    recommendations: Tuple[AcousticRecommendation, ...],
    capture,
) -> bool:
    if capture.frame_count == 0:
        return False
    if not capture.complete and capture.captured_duration_ms < 500:
        return False
    if "sample_rate_changed" in capture.warning_codes:
        return False
    for rec in recommendations:
        if rec.severity == "error":
            return False
    return True


def _arm_acoustic_capture(
    proc: Optional[VoiceAudioProcessor],
    session: CalibrationSession,
    kind: CalibrationMeasurementKind,
    target_duration_ms: int = 3000,
    timeout_ms: int = 5000,
    measurement_id: Optional[str] = None,
) -> str:
    if measurement_id is None:
        measurement_id = str(uuid.uuid4())
    context = AcousticCaptureContext(
        calibration_session_id=session.session_id,
        measurement_id=measurement_id,
        kind=kind,
        target_duration_ms=target_duration_ms,
        timeout_ms=timeout_ms,
        armed_at_monotonic=time.monotonic(),
    )
    if proc is not None:
        armed = proc.arm_acoustic_capture(context)
        if not armed:
            st.session_state["voice_calibration_arm_error"] = "Processor rejected acoustic capture."
            return measurement_id
    st.session_state["voice_calibration_active_measurement_id"] = measurement_id
    st.session_state["voice_calibration_active_measurement_kind"] = kind.value
    st.session_state["voice_calibration_measurement_started_at"] = time.time()
    return measurement_id


def _cancel_acoustic_capture(
    proc: Optional[VoiceAudioProcessor],
    measurement_id: Optional[str] = None,
) -> None:
    if proc is not None:
        if measurement_id is not None:
            proc.cancel_acoustic_capture(measurement_id=measurement_id)
        if proc.has_active_acoustic_capture():
            proc.cancel_acoustic_capture(measurement_id=None)
    st.session_state.pop("voice_calibration_active_measurement_id", None)
    st.session_state.pop("voice_calibration_active_measurement_kind", None)
    st.session_state.pop("voice_calibration_measurement_started_at", None)
    st.session_state.pop("voice_calibration_arm_error", None)


def _make_skipped_speech_measurement(
    session: CalibrationSession,
    measurement_id: str,
) -> SpeechLevelMetrics:
    from tournament_platform.app.services.voice_calibration.models import AcousticCaptureSummary
    capture = AcousticCaptureSummary(
        measurement_id=measurement_id,
        calibration_session_id=session.session_id,
        kind=CalibrationMeasurementKind.NORMAL_SPEECH,
        sample_rate_hz=0,
        channel_count=0,
        frame_count=0,
        scalar_sample_count=0,
        target_duration_ms=0.0,
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
        complete=False,
        warning_codes=(),
        skipped=True,
        created_at=time.time(),
    )
    return SpeechLevelMetrics(
        capture=capture,
        speech_start_offset_ms=None,
        trailing_silence_ms=None,
        speech_rms=None,
        speech_rms_dbfs=None,
        speech_to_background_difference_db=None,
    )


def _render_silence_baseline_step(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
    proc: Optional[VoiceAudioProcessor],
    drain_result: Optional[VoiceDrainResult] = None,
) -> None:
    """Render the Step 1 — Background Noise silence baseline measurement."""
    active_measurement_id = st.session_state.get("voice_calibration_active_measurement_id")
    phase = st.session_state.get("voice_calibration_phase")

    if active_measurement_id is None and st.session_state.get("voice_calibration_measurement_started_at") is not None:
        st.session_state.pop("voice_calibration_measurement_started_at", None)

    st.subheader("Step 1 — Background Noise")
    st.caption("Remain silent for three seconds.")

    snapshot = _get_acoustic_capture_snapshot(proc)
    legacy_active = _has_legacy_active_capture(proc)
    capabilities = inspect_voice_processor_capabilities(proc)
    active_kind = st.session_state.get("voice_calibration_active_measurement_kind")
    
    # Get completed measurement reference from reconciliation transaction
    completed_ref = st.session_state.get("calibration_completed_measurement_ref")
    
    # Use pure lookup helper (no state mutations)
    terminal_result = find_rendered_terminal_result(
        session=session,
        completed_ref=completed_ref,
        active_measurement_id=active_measurement_id,
        active_measurement_kind=CalibrationMeasurementKind(active_kind) if active_kind else None,
    )
    
    arm_error = st.session_state.get("voice_calibration_arm_error")
    reconciliation_error = st.session_state.get("voice_calibration_reconciliation_error")

    resolution = resolve_acoustic_ui_state(
        active_measurement_id=active_measurement_id,
        active_measurement_kind=st.session_state.get("voice_calibration_active_measurement_kind"),
        terminal_result=terminal_result,
        snapshot=snapshot,
        arm_error=arm_error,
        legacy_active=legacy_active,
        capabilities=capabilities,
        expected_calibration_session_id=session.session_id if session is not None else None,
        last_drained_measurement_id=drain_result.last_drained_measurement_id if drain_result else None,
        reconciliation_error=reconciliation_error,
    )

    col_ready1, col_ready2, col_ready3 = st.columns(3)
    with col_ready1:
        st.metric("Microphone", "Ready" if proc is not None else "Not available")
    with col_ready2:
        st.metric("WebRTC", "Playing" if proc is not None else "Not available")
    with col_ready3:
        st.metric("Capture", resolution.state.value.replace("_", " ").title())

    if arm_error:
        st.error(arm_error)

    if resolution.state == AcousticUiState.NOT_STARTED:
        can_start = (
            proc is not None
            and st.session_state.get("voice_runtime_mode") == VoiceRuntimeMode.CALIBRATION
            and phase == CalibrationPhase.MEASURING_SILENCE.value
        )
        if st.button("Start background measurement", key="silence_start", type="primary", disabled=not can_start):
            measurement_id = calibration_service.start_measurement(
                session, CalibrationMeasurementKind.SILENCE_BASELINE.value
            )
            _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.SILENCE_BASELINE, measurement_id=measurement_id)
            st.rerun()
        return

    if resolution.state == AcousticUiState.MEASURING:
        elapsed_ms = snapshot.elapsed_ms if snapshot is not None else 0.0
        target_ms = 3000.0
        progress = min(elapsed_ms / target_ms, 1.0)

        st.info(f"Capturing background noise... Target: {target_ms / 1000.0:.1f} seconds")
        st.progress(progress)
        if resolution.show_elapsed:
            st.caption(f"Elapsed audio: {elapsed_ms / 1000.0:.1f} seconds")

        if resolution.can_cancel and st.button("Cancel", key="silence_cancel"):
            _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
            st.rerun()
        return

    if resolution.state == AcousticUiState.RESULT_PENDING_COMMIT:
        st.info("Finalizing measurement...")
        if st.button("Refresh", key="silence_refresh_pending"):
            st.rerun()
        return

    if resolution.state in (AcousticUiState.COMPLETE, AcousticUiState.WARNING):
        if terminal_result is None:
            return

        st.subheader("Background Noise Result")
        capture = terminal_result.capture
        col_dur, col_rate, col_ch = st.columns(3)
        with col_dur:
            st.metric("Captured duration", f"{capture.captured_duration_ms:.2f} s")
        with col_rate:
            st.metric("Sample rate", f"{capture.sample_rate_hz:,} Hz")
        with col_ch:
            st.metric("Channels", str(capture.channel_count))

        if isinstance(terminal_result, SilenceBaselineMetrics):
            col_med, col_p90, col_p95, col_peak = st.columns(4)
            with col_med:
                st.metric("Median level", f"{terminal_result.median_dbfs:.1f} dBFS" if terminal_result.median_dbfs is not None else "—")
            with col_p90:
                st.metric("P90", f"{terminal_result.p90_dbfs:.1f} dBFS" if terminal_result.p90_dbfs is not None else "—")
            with col_p95:
                st.metric("P95", f"{terminal_result.p95_dbfs:.1f} dBFS" if terminal_result.p95_dbfs is not None else "—")
            with col_peak:
                st.metric("Peak", f"{capture.peak_dbfs:.1f} dBFS" if capture.peak_dbfs is not None else "—")

            col_nc, col_hc, col_sp = st.columns(3)
            with col_nc:
                st.metric("Near clipping", str(capture.near_clipping_count))
            with col_hc:
                st.metric("Hard clipping", str(capture.hard_clipping_count))
            with col_sp:
                st.metric("Speech detected", "Yes" if terminal_result.contaminated_by_speech else "No")

            recommendations = generate_silence_recommendations(terminal_result)
            if recommendations:
                st.markdown("**Recommendations**")
                for rec in recommendations:
                    severity_icon = {
                        "info": "ℹ️",
                        "warning": "⚠️",
                        "error": "❌",
                    }.get(rec.severity, "ℹ️")
                    st.markdown(f"{severity_icon} **{rec.message}**")
                    if rec.evidence:
                        evidence_str = ", ".join(
                            f"{e.name}={e.value}{' ' + e.unit if e.unit else ''}"
                            for e in rec.evidence
                        )
                        st.caption(f"Evidence: {evidence_str}")

        status = "Ready" if capture.complete else "Incomplete"
        if capture.skipped:
            status = "Skipped"
        st.markdown(f"**Status:** {status}")

        col_retry, col_continue = st.columns(2)
        with col_retry:
            if st.button("Retry", key="silence_retry"):
                if proc is not None:
                    proc.cancel_acoustic_capture(measurement_id=active_measurement_id)
                # Clear stale completed reference before starting new attempt
                st.session_state.pop("calibration_completed_measurement_ref", None)
                _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.SILENCE_BASELINE)
                st.rerun()
        with col_continue:
            can_continue = terminal_result is not None and capture.complete and not capture.skipped
            if isinstance(terminal_result, SilenceBaselineMetrics):
                can_continue = can_continue and _classify_continuation(recommendations, capture)
            continue_disabled = not can_continue
            if st.button("Continue", key="silence_continue", disabled=continue_disabled):
                if calibration_service is not None and session is not None:
                    state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.MEASURING_SILENCE)
                    try:
                        new_state = calibration_service.transition(state, CalibrationPhase.MEASURING_SPEECH)
                        st.session_state["voice_calibration_phase"] = new_state.phase.value
                    except Exception:
                        pass
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.session_state.pop("calibration_completed_measurement_ref", None)
                st.rerun()
        return

    if resolution.state == AcousticUiState.FAILED:
        if resolution.reason == "processor_outdated_restart_required":
            st.warning(
                "Microphone restart required. "
                "The audio processor was replaced or reloaded. "
                "Please restart the microphone to use calibration."
            )
            if st.button("Restart microphone", key="silence_restart_mic"):
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.session_state.pop("voice_calibration_arm_error", None)
                st.session_state.pop("voice_calibration_measurement_started_at", None)
                st.rerun()
        elif resolution.reason == "capture_synchronization_error":
            st.error("Capture synchronization error")
            ui_id = resolution.active_measurement_id[:8] if resolution.active_measurement_id else "none"
            proc_id = resolution.processor_measurement_id[:8] if resolution.processor_measurement_id else "none"
            st.caption(f"UI attempt: {ui_id}")
            st.caption(f"Processor attempt: {proc_id}")
            st.info("Wait for the active capture to finish, or restart the microphone.")
            if st.button("Restart microphone", key="silence_restart_sync"):
                if proc is not None:
                    proc.stop()
                st.session_state.pop("voice_calibration_active_measurement_id", None)
                st.session_state.pop("voice_calibration_active_measurement_kind", None)
                st.session_state.pop("voice_calibration_measurement_started_at", None)
                st.rerun()
        else:
            st.error(f"Capture failed: {resolution.reason or 'unknown error'}")
            col_retry, col_dismiss = st.columns(2)
            with col_retry:
                if st.button("Retry", key="silence_retry_failed"):
                    if proc is not None and active_measurement_id:
                        proc.cancel_acoustic_capture(measurement_id=active_measurement_id)
                    st.session_state.pop("voice_calibration_arm_error", None)
                    _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.SILENCE_BASELINE)
                    st.rerun()
            with col_dismiss:
                if st.button("Dismiss", key="silence_dismiss_failed"):
                    _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                    st.rerun()
        return


def _render_speech_measurement_step(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
    proc: Optional[VoiceAudioProcessor],
    silence_baseline: Optional[SilenceBaselineMetrics],
) -> None:
    """Render the Step 2 — Normal Speech measurement."""
    active_measurement_id = st.session_state.get("voice_calibration_active_measurement_id")
    phase = st.session_state.get("voice_calibration_phase")

    if active_measurement_id is None and st.session_state.get("voice_calibration_measurement_started_at") is not None:
        st.session_state.pop("voice_calibration_measurement_started_at", None)

    st.subheader("Step 2 — Normal Speech")
    st.caption("Speak normally after the prompt appears.")

    snapshot = _get_acoustic_capture_snapshot(proc)
    legacy_active = _has_legacy_active_capture(proc)
    capabilities = inspect_voice_processor_capabilities(proc)
    completed_ref = st.session_state.get("calibration_completed_measurement_ref")
    active_kind = st.session_state.get("voice_calibration_active_measurement_kind")
    terminal_result = find_rendered_terminal_result(
        session=session,
        completed_ref=completed_ref,
        active_measurement_id=active_measurement_id,
        active_measurement_kind=CalibrationMeasurementKind(active_kind) if active_kind else None,
    )
    if (
        terminal_result is not None
        and terminal_result.capture.kind != CalibrationMeasurementKind.NORMAL_SPEECH
    ):
        terminal_result = None
    arm_error = st.session_state.get("voice_calibration_arm_error")
    reconciliation_error = st.session_state.get("voice_calibration_reconciliation_error")

    resolution = resolve_acoustic_ui_state(
        active_measurement_id=active_measurement_id,
        active_measurement_kind=active_kind,
        terminal_result=terminal_result,
        snapshot=snapshot,
        arm_error=arm_error,
        legacy_active=legacy_active,
        capabilities=capabilities,
        expected_calibration_session_id=session.session_id if session is not None else None,
        last_drained_measurement_id=None,
        reconciliation_error=reconciliation_error,
    )

    if resolution.state == AcousticUiState.NOT_STARTED:
        can_start = (
            proc is not None
            and st.session_state.get("voice_runtime_mode") == VoiceRuntimeMode.CALIBRATION
            and phase == CalibrationPhase.MEASURING_SPEECH.value
            and silence_baseline is not None
        )
        if not can_start:
            st.warning("A valid silence baseline is required before speech measurement.")
        if arm_error:
            st.error(arm_error)
        if st.button("Start speech measurement", key="speech_start", type="primary", disabled=not can_start):
            measurement_id = calibration_service.start_measurement(
                session, CalibrationMeasurementKind.NORMAL_SPEECH.value
            )
            # Clear stale completed reference from silence or prior speech attempt before starting new
            st.session_state.pop("calibration_completed_measurement_ref", None)
            _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.NORMAL_SPEECH, target_duration_ms=3500, timeout_ms=6000, measurement_id=measurement_id)
            st.rerun()
        return

    if resolution.state == AcousticUiState.MEASURING:
        elapsed_ms = snapshot.elapsed_ms if snapshot is not None else 0.0
        target_ms = 3500.0
        progress = min(elapsed_ms / target_ms, 1.0)

        st.info(f"Capturing speech... Target: {target_ms / 1000.0:.1f} seconds")
        st.progress(progress)
        if resolution.show_elapsed:
            st.caption(f"Elapsed audio: {elapsed_ms / 1000.0:.1f} seconds")

        col_cancel, col_skip = st.columns(2)
        with col_cancel:
            if resolution.can_cancel and st.button("Cancel", key="speech_cancel"):
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.rerun()
        with col_skip:
            if st.button("Skip (dev only)", key="speech_skip", help="Temporary development-only skip. Does not imply valid speech calibration."):
                skipped_measurement = _make_skipped_speech_measurement(session, active_measurement_id or str(uuid.uuid4()))
                updated_session = calibration_service.consume_measurements(session, (skipped_measurement,))
                st.session_state["voice_calibration_session"] = updated_session
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.session_state.pop("calibration_completed_measurement_ref", None)
                st.session_state["voice_calibration_active_measurement_id"] = None
                st.session_state["voice_calibration_active_measurement_kind"] = None
                st.session_state["voice_calibration_measurement_started_at"] = None
                st.rerun()
        return

    if resolution.state in (AcousticUiState.COMPLETE, AcousticUiState.WARNING):
        if terminal_result is None:
            return

        st.subheader("Normal Speech Result")
        capture = terminal_result.capture
        col_dur, col_rate, col_ch = st.columns(3)
        with col_dur:
            st.metric("Captured duration", f"{capture.captured_duration_ms:.2f} s")
        with col_rate:
            st.metric("Sample rate", f"{capture.sample_rate_hz:,} Hz")
        with col_ch:
            st.metric("Channels", str(capture.channel_count))

        if capture.skipped:
            st.warning("Speech measurement was skipped. This does not imply valid speech calibration.")
            st.markdown("**Status:** Skipped")
            if st.button("Retry", key="speech_retry"):
                measurement_id = calibration_service.start_measurement(
                    session, CalibrationMeasurementKind.NORMAL_SPEECH.value
                )
                # Clear stale completed reference before starting new retry attempt
                st.session_state.pop("calibration_completed_measurement_ref", None)
                _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.NORMAL_SPEECH, target_duration_ms=3500, timeout_ms=6000, measurement_id=measurement_id)
                st.rerun()
            return

        if isinstance(terminal_result, SpeechLevelMetrics):
            col_speech, col_peak, col_nc, col_hc = st.columns(4)
            with col_speech:
                st.metric("Speech detected", "Yes" if capture.speech_frame_count > 0 else "No")
            with col_peak:
                st.metric("Peak", f"{capture.peak_dbfs:.1f} dBFS" if capture.peak_dbfs is not None else "—")
            with col_nc:
                st.metric("Near clipping", str(capture.near_clipping_count))
            with col_hc:
                st.metric("Hard clipping", str(capture.hard_clipping_count))

            if terminal_result.speech_rms_dbfs is not None:
                st.metric("Speech level", f"{terminal_result.speech_rms_dbfs:.1f} dBFS")
            if terminal_result.speech_start_offset_ms is not None:
                st.metric("Speech started", f"{terminal_result.speech_start_offset_ms:.0f} ms after capture began")
            if terminal_result.trailing_silence_ms is not None:
                st.metric("Trailing silence", f"{terminal_result.trailing_silence_ms:.0f} ms")
            if terminal_result.speech_to_background_difference_db is not None:
                st.metric("Speech/background difference", f"{terminal_result.speech_to_background_difference_db:+.1f} dB")

            recommendations = generate_speech_recommendations(terminal_result, silence_baseline=silence_baseline)
            if recommendations:
                st.markdown("**Recommendations**")
                for rec in recommendations:
                    severity_icon = {
                        "info": "ℹ️",
                        "warning": "⚠️",
                        "error": "❌",
                    }.get(rec.severity, "ℹ️")
                    st.markdown(f"{severity_icon} **{rec.message}**")
                    if rec.evidence:
                        evidence_str = ", ".join(
                            f"{e.name}={e.value}{' ' + e.unit if e.unit else ''}"
                            for e in rec.evidence
                        )
                        st.caption(f"Evidence: {evidence_str}")

        status = "Ready" if capture.complete else "Incomplete"
        if capture.skipped:
            status = "Skipped"
        st.markdown(f"**Status:** {status}")

        col_retry, col_continue = st.columns(2)
        with col_retry:
            if st.button("Retry", key="speech_retry"):
                if proc is not None:
                    proc.cancel_acoustic_capture(measurement_id=active_measurement_id)
                # Clear stale completed reference before starting new retry attempt
                st.session_state.pop("calibration_completed_measurement_ref", None)
                _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.NORMAL_SPEECH, target_duration_ms=3500, timeout_ms=6000)
                st.rerun()
        with col_continue:
            can_continue = False
            if terminal_result is not None and capture.complete and not capture.skipped:
                if isinstance(terminal_result, SpeechLevelMetrics):
                    recommendations = generate_speech_recommendations(terminal_result, silence_baseline=silence_baseline)
                    can_continue = _classify_continuation(recommendations, capture)
            continue_disabled = not can_continue
            if st.button("Continue", key="speech_continue", disabled=continue_disabled):
                if calibration_service is not None and session is not None:
                    state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.MEASURING_SPEECH)
                    try:
                        new_state = calibration_service.transition(state, CalibrationPhase.COMMAND_TRIAL)
                        st.session_state["voice_calibration_phase"] = new_state.phase.value
                    except Exception:
                        pass
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.rerun()
        return

    if resolution.state == AcousticUiState.FAILED:
        if resolution.reason == "processor_outdated_restart_required":
            st.warning(
                "Microphone restart required. "
                "The audio processor was replaced or reloaded. "
                "Please restart the microphone to use calibration."
            )
            if st.button("Restart microphone", key="speech_restart_mic"):
                _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                st.session_state.pop("voice_calibration_arm_error", None)
                st.session_state.pop("voice_calibration_measurement_started_at", None)
                st.rerun()
        elif resolution.reason == "capture_synchronization_error":
            st.error("Capture synchronization error")
            ui_id = resolution.active_measurement_id[:8] if resolution.active_measurement_id else "none"
            proc_id = resolution.processor_measurement_id[:8] if resolution.processor_measurement_id else "none"
            st.caption(f"UI attempt: {ui_id}")
            st.caption(f"Processor attempt: {proc_id}")
            st.info("Wait for the active capture to finish, or restart the microphone.")
            if st.button("Restart microphone", key="speech_restart_sync"):
                if proc is not None:
                    proc.stop()
                st.session_state.pop("voice_calibration_active_measurement_id", None)
                st.session_state.pop("voice_calibration_active_measurement_kind", None)
                st.session_state.pop("voice_calibration_measurement_started_at", None)
                st.rerun()
        else:
            st.error(f"Capture failed: {resolution.reason or 'unknown error'}")
            col_retry, col_dismiss = st.columns(2)
            with col_retry:
                if st.button("Retry", key="speech_retry_failed"):
                    if proc is not None and active_measurement_id:
                        proc.cancel_acoustic_capture(measurement_id=active_measurement_id)
                    st.session_state.pop("voice_calibration_arm_error", None)
                    st.session_state.pop("calibration_completed_measurement_ref", None)
                    _arm_acoustic_capture(proc, session, CalibrationMeasurementKind.NORMAL_SPEECH, target_duration_ms=3500, timeout_ms=6000)
                    st.rerun()
            with col_dismiss:
                if st.button("Dismiss", key="speech_dismiss_failed"):
                    _cancel_acoustic_capture(proc, measurement_id=active_measurement_id)
                    st.rerun()
        return


def _render_negative_trial_step(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
    proc: Optional[VoiceAudioProcessor],
) -> None:
    """Render the Step 3 — Negative Speech trial."""
    active_trial_id = st.session_state.get("voice_calibration_active_trial_id")

    st.subheader("Step 3 — Negative Speech")
    st.caption("Speak normal, unrelated phrases. No score command should be accepted.")

    if not active_trial_id:
        st.session_state["voice_calibration_active_trial_id"] = str(uuid.uuid4())
        ctx = CalibrationCaptureContext(
            calibration_session_id=session.session_id,
            calibration_trial_id=st.session_state["voice_calibration_active_trial_id"],
            capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL,
            expected_command_id="CALIBRATION_NEGATIVE",
            expected_phrase="",
        )
        ack = _arm_trial(proc, ctx)
        if not ack.accepted:
            st.error(f"Failed to arm negative trial: {ack.rejection_reason}")
            st.session_state.pop("voice_calibration_active_trial_id", None)
        st.rerun()

    completed = [t for t in session.negative_trials]
    correctly_rejected = sum(1 for t in completed if t.classification == "correctly_rejected")
    false_points = sum(1 for t in completed if t.classification == "false_point_candidate")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Negative trials", str(len(completed)))
    with col2:
        st.metric("Correctly rejected", str(correctly_rejected))
    with col3:
        st.metric("False point candidates", str(false_points))

    if completed:
        st.markdown("**Recent trials**")
        for trial in completed[-5:]:
            icon = "✅" if trial.classification == "correctly_rejected" else "❌"
            st.markdown(
                f"{icon} `{trial.trial_id[:8]}` — **{trial.classification}** "
                f"| raw: `{trial.transcript}` "
                f"| resolved: `{trial.resolved_command_id or 'none'}`"
            )

    col_next, col_skip = st.columns(2)
    with col_next:
        if st.button("Next", key="negative_next", disabled=len(completed) == 0):
            state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.NEGATIVE_TRIAL)
            try:
                new_state = calibration_service.transition(state, CalibrationPhase.TTS_ECHO_TEST)
                st.session_state["voice_calibration_phase"] = new_state.phase.value
            except Exception:
                pass
            st.session_state["voice_calibration_active_trial_id"] = None
            _disarm_trial(proc)
            st.rerun()
    with col_skip:
        if st.button("Skip", key="negative_skip"):
            state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.NEGATIVE_TRIAL)
            try:
                new_state = calibration_service.transition(state, CalibrationPhase.TTS_ECHO_TEST)
                st.session_state["voice_calibration_phase"] = new_state.phase.value
            except Exception:
                pass
            st.session_state["voice_calibration_active_trial_id"] = None
            _disarm_trial(proc)
            st.rerun()


def _render_tts_echo_test_step(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
    proc: Optional[VoiceAudioProcessor],
) -> None:
    """Render the Step 4 — TTS Echo safety test."""
    active_trial_id = st.session_state.get("voice_calibration_active_trial_id")

    st.subheader("Step 4 — TTS Echo Safety")
    st.caption("The system will play confirmations and commentary. Verify no score commands are triggered.")

    if not active_trial_id:
        st.session_state["voice_calibration_active_trial_id"] = str(uuid.uuid4())
        ctx = CalibrationCaptureContext(
            calibration_session_id=session.session_id,
            calibration_trial_id=st.session_state["voice_calibration_active_trial_id"],
            capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST,
            expected_command_id="CALIBRATION_TTS_ECHO",
            expected_phrase="",
        )
        ack = _arm_trial(proc, ctx)
        if not ack.accepted:
            st.error(f"Failed to arm TTS echo test: {ack.rejection_reason}")
            st.session_state.pop("voice_calibration_active_trial_id", None)
        st.rerun()

    completed = [t for t in session.tts_echo_transcripts]
    st.metric("Echo transcripts captured", str(len(completed)))

    if completed:
        st.markdown("**Captured transcripts**")
        for transcript in completed[-5:]:
            st.markdown(f"`{transcript.transcript}` *(source: {transcript.tts_source})*")

    col_next, col_skip = st.columns(2)
    with col_next:
        if st.button("Next", key="echo_next", disabled=len(completed) == 0):
            state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.TTS_ECHO_TEST)
            try:
                new_state = calibration_service.transition(state, CalibrationPhase.REVIEW)
                st.session_state["voice_calibration_phase"] = new_state.phase.value
            except Exception:
                pass
            st.session_state["voice_calibration_active_trial_id"] = None
            _disarm_trial(proc)
            st.rerun()
    with col_skip:
        if st.button("Skip", key="echo_skip"):
            state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.TTS_ECHO_TEST)
            try:
                new_state = calibration_service.transition(state, CalibrationPhase.REVIEW)
                st.session_state["voice_calibration_phase"] = new_state.phase.value
            except Exception:
                pass
            st.session_state["voice_calibration_active_trial_id"] = None
            _disarm_trial(proc)
            st.rerun()


def render_calibration_results(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
) -> None:
    """Render Phase 8 — Calibration Results and Safety Report."""
    results = calibration_service.compute_results(session)

    st.subheader("Calibration Results & Safety Report")

    col_overall, col_id = st.columns(2)
    with col_overall:
        status_text = results.overall_status.value.upper()
        if results.overall_status == CalibrationOverallStatus.PASS:
            st.success(f"Overall: {status_text}")
        elif results.overall_status == CalibrationOverallStatus.WARNING:
            st.warning(f"Overall: {status_text}")
        elif results.overall_status == CalibrationOverallStatus.FAIL:
            st.error(f"Overall: {status_text}")
        elif results.overall_status == CalibrationOverallStatus.INCOMPLETE:
            st.warning(f"Overall: {status_text}")
        elif results.overall_status == CalibrationOverallStatus.NOT_TESTED:
            st.info(f"Overall: {status_text}")
        elif results.overall_status == CalibrationOverallStatus.INVALID_DATA:
            st.error(f"Overall: {status_text}")
        else:
            st.info(f"Overall: {status_text}")
    with col_id:
        st.caption(f"Session: `{results.session_id[:8]}`")

    _render_calibration_verdict_reasons(results)

    st.divider()
    st.subheader("Acoustic Summary")
    acoustic = results.acoustic_summary
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        st.metric("Background median", f"{acoustic.background_median_dbfs:.1f} dBFS" if acoustic.background_median_dbfs is not None else "—")
    with col_a2:
        st.metric("Background P95", f"{acoustic.background_p95_dbfs:.1f} dBFS" if acoustic.background_p95_dbfs is not None else "—")
    with col_a3:
        st.metric("Speech level", f"{acoustic.speech_level_dbfs:.1f} dBFS" if acoustic.speech_level_dbfs is not None else "—")
    with col_a4:
        if acoustic.speech_background_difference_db is not None:
            st.metric("Speech/background difference", f"{acoustic.speech_background_difference_db:+.1f} dB")
        else:
            st.metric("Speech/background difference", "—")
    st.caption(f"Clipping detected: {'Yes' if acoustic.clipping_detected else 'No'}")

    st.divider()
    st.subheader("Command Recognition")
    for stats in results.command_recognition:
        with st.expander(f"Command: {stats.command_id}"):
            col_c1, col_c2, col_c3, col_c4, col_c5 = st.columns(5)
            with col_c1:
                st.metric("Attempts", str(stats.attempts))
            with col_c2:
                st.metric("Exact", str(stats.exact_matches))
            with col_c3:
                st.metric("Resolved", str(stats.successful_resolutions))
            with col_c4:
                st.metric("Wrong", str(stats.wrong_command_count))
            with col_c5:
                st.metric("Unknown", str(stats.unknown_count))

    st.divider()
    st.subheader("Negative Speech")
    neg = results.negative_speech
    col_n1, col_n2, col_n3, col_n4 = st.columns(4)
    with col_n1:
        st.metric("Trials", str(neg.trials))
    with col_n2:
        st.metric("Correctly rejected", str(neg.correctly_rejected))
    with col_n3:
        st.metric("False point candidates", str(neg.false_point_candidates))
    with col_n4:
        st.metric("False undo/reset candidates", str(neg.false_undo_reset_candidates))

    if neg.parser_candidates:
        st.markdown("**Negative trial parser dry-run results**")
        for candidate in neg.parser_candidates:
            st.caption(
                f"`{candidate.raw_transcript}` -> parser: `{candidate.parser_command_id}` "
                f"(confidence: {candidate.parser_confidence}) -> {candidate.classification}"
            )

    st.divider()
    st.subheader("TTS Echo Safety")
    echo = results.tts_echo
    col_e1, col_e2, col_e3, col_e4 = st.columns(4)
    with col_e1:
        st.metric("Playback tests", str(echo.playback_tests))
    with col_e2:
        st.metric("Transcripts captured", str(echo.transcripts_captured))
    with col_e3:
        st.metric("Live-acceptable candidates", str(echo.live_acceptable_command_candidates))
    with col_e4:
        st.metric("Score actions", str(echo.score_actions))

    if echo.transcripts:
        st.markdown("**Captured transcripts**")
        for transcript in echo.transcripts:
            st.caption(f"`{transcript.transcript}` (source: {transcript.tts_source})")

    st.divider()
    st.subheader("Confusion Table")
    if results.confusion_table:
        table_data = []
        for entry in results.confusion_table:
            table_data.append({
                "Test type": entry.test_type,
                "Expected": entry.expected,
                "Transcript": entry.transcript,
                "Normalized": entry.normalized_transcript,
                "Parser candidate": entry.parser_candidate,
                "Confidence": entry.parser_confidence,
                "Outcome": entry.outcome,
            })
        st.dataframe(table_data, use_container_width=True)
    else:
        st.caption("No confusion data available.")

    st.divider()
    st.subheader("Safety Outcomes")
    for outcome in results.safety_outcomes:
        icon = "✅" if not outcome.failure else "❌"
        st.markdown(f"{icon} **{outcome.category}**: {outcome.outcome} — {outcome.detail}")

    render_phrase_comparison(calibration_service, session)

    _render_alias_confirmation(calibration_service, session)

    _render_asr_experiment_results(calibration_service, session)

    st.divider()
    st.subheader("Live Voice Profile")

    auto_apply = st.session_state.get("voice_calibration_auto_apply", False)
    st.session_state["voice_calibration_auto_apply"] = st.checkbox(
        "Apply safe recommendations after successful calibration",
        value=auto_apply,
        help="When enabled, a passing calibration will automatically activate the calibrated voice profile.",
    )

    if st.session_state.get("voice_live_profile_recommendation") is None or True:
        recommendation = calibration_service.compute_live_voice_profile_recommendation(
            session=session,
            calibration_profile_id=st.session_state.get("voice_live_profile_calibration_profile_id"),
        )
        st.session_state["voice_live_profile_recommendation"] = recommendation
    else:
        recommendation = st.session_state["voice_live_profile_recommendation"]

    _render_live_profile_recommendation(recommendation)

    activation_status = st.session_state.get("voice_live_profile_activation_status")
    activation_enabled = recommendation is not None and recommendation.status in {
        RecommendationStatus.AVAILABLE,
        RecommendationStatus.WARNING,
    }
    if activation_status is None and activation_enabled and (auto_apply or st.button("Activate calibrated voice profile", key="activate_profile_btn", type="primary")):
        current = LiveVoiceSettingsSnapshot(
            noise_gate_enabled=st.session_state.get("voice_noise_filtering", False),
            noise_threshold_rms=st.session_state.get("voice_noise_threshold", 0.0),
            strict_mode_enabled=st.session_state.get("voice_strict_mode", False),
            asr_config_id=None,
            aliases=(),
            preferred_phrases=(),
            config_revision=st.session_state.get("voice_live_profile_config_revision", 0),
        )
        previous = _activate_calibrated_voice_profile(recommendation, current)
        if previous is not None:
            st.rerun()
        elif recommendation.status == RecommendationStatus.UNAVAILABLE:
            st.error("Profile cannot be activated: recommendation status is UNAVAILABLE.")
        elif recommendation.status == RecommendationStatus.INVALID_DATA:
            st.error("Profile cannot be activated: calibration data is invalid.")
        elif recommendation.status == RecommendationStatus.DEVICE_MISMATCH:
            st.error("Profile cannot be activated: device mismatch. Re-calibrate.")

    if activation_status is not None:
        if st.button("Undo calibrated settings", key="undo_profile_btn", type="secondary"):
            _undo_calibrated_settings()
            st.rerun()

    _render_post_activation_verification()
    _render_effective_configuration()

    st.divider()
    if st.button("Finish Calibration", key="results_finish", type="primary"):
        stop_voice_calibration(processor=_get_active_processor(), reason="results_reviewed")
        st.rerun()


def _render_asr_experiment_results(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
) -> None:
    """Render Phase 11 — ASR Hint Experiment results."""
    if not session.asr_ab_results:
        return

    st.divider()
    st.subheader("ASR Hint Experiment")
    st.caption("Recommendation only — production ASR unchanged.")

    baseline = calibration_service.compute_asr_experiment_aggregate(
        session=session, config_id="baseline"
    )
    candidate = calibration_service.compute_asr_experiment_aggregate(
        session=session, config_id="candidate"
    )
    recommendation, reason = calibration_service.recommend_asr_config(session=session)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Baseline**")
        st.metric("Parser success", f"{baseline.parser_successes}/{baseline.positive_attempts}")
        st.metric("Exact recognition", f"{baseline.exact_matches}/{baseline.positive_attempts}")
        st.metric("Negative false candidates", baseline.negative_false_candidate_count)
        st.metric("TTS false candidates", baseline.tts_false_candidate_count)
        if baseline.median_latency_ms is not None:
            st.metric("Median latency", f"{baseline.median_latency_ms:.0f} ms")
    with col2:
        st.markdown("**Command hints**")
        st.metric("Parser success", f"{candidate.parser_successes}/{candidate.positive_attempts}")
        st.metric("Exact recognition", f"{candidate.exact_matches}/{candidate.positive_attempts}")
        st.metric("Negative false candidates", candidate.negative_false_candidate_count)
        st.metric("TTS false candidates", candidate.tts_false_candidate_count)
        if candidate.median_latency_ms is not None:
            st.metric("Median latency", f"{candidate.median_latency_ms:.0f} ms")

    st.markdown("**Recommendation**")
    if recommendation == AsrExperimentRecommendation.CANDIDATE_RECOMMENDED:
        st.success(
            "Command hints improved parser success without increasing false candidates."
        )
    elif recommendation == AsrExperimentRecommendation.CANDIDATE_UNSAFE:
        st.error(f"Candidate is unsafe: {reason}")
    elif recommendation == AsrExperimentRecommendation.MORE_SAMPLES_REQUIRED:
        st.warning(f"More samples required: {reason}")
    else:
        st.info(f"Baseline retained: {reason}")

    with st.expander("Sample results"):
        rows = []
        for result in session.asr_ab_results:
            rows.append({
                "Sample": result.sample_id,
                "Capture": result.capture_kind,
                "Baseline transcript": result.baseline.raw_transcript,
                "Baseline parser": result.baseline.parser_command_id or "—",
                "Candidate transcript": result.candidate.raw_transcript,
                "Candidate parser": result.candidate.parser_command_id or "—",
            })
        st.dataframe(rows, use_container_width=True)


def _render_alias_confirmation(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
) -> None:
    """Render Phase 10 — Alias Confirmation."""
    st.divider()
    st.subheader("Alias Confirmation")
    st.caption("Session-only — not saved after reset or browser session end.")

    candidates = calibration_service.compute_alias_candidates(session=session)
    if not candidates:
        st.caption("No alias candidates observed during calibration.")
        return

    pending = [c for c in candidates if c.status == AliasCandidateStatus.PENDING]
    confirmed = [c for c in candidates if c.status == AliasCandidateStatus.CONFIRMED]
    rejected = [c for c in candidates if c.status == AliasCandidateStatus.REJECTED]
    ineligible = [c for c in candidates if c.status == AliasCandidateStatus.INELIGIBLE]

    if confirmed:
        st.markdown("**Confirmed aliases (session-only)**")
        for candidate in confirmed:
            st.success(
                f"`{candidate.normalized_alias}` → `{candidate.expected_phrase}` "
                f"(command: {candidate.command_id})"
            )

    if pending:
        st.markdown("**Pending alias candidates**")
        for candidate in pending:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"`{candidate.raw_transcript}`")
                    st.caption(
                        f"Expected: {candidate.expected_phrase} | "
                        f"Observed: {candidate.occurrence_count} time(s) | "
                        f"Collision: {', '.join(candidate.collision_command_ids) if candidate.collision_command_ids else 'None'}"
                    )
                with col2:
                    if st.button("Confirm", key=f"alias_confirm_{candidate.candidate_id}"):
                        updated = calibration_service.confirm_alias(
                            session=session,
                            candidate_id=candidate.candidate_id,
                        )
                        st.session_state["voice_calibration_session"] = updated
                        st.rerun()
                    if st.button("Reject", key=f"alias_reject_{candidate.candidate_id}"):
                        updated = calibration_service.reject_alias(
                            session=session,
                            candidate_id=candidate.candidate_id,
                        )
                        st.session_state["voice_calibration_session"] = updated
                        st.rerun()

    if rejected:
        st.markdown("**Rejected aliases**")
        for candidate in rejected:
            st.markdown(f"`{candidate.normalized_alias}` — rejected")

    if ineligible:
        st.markdown("**Ineligible candidates**")
        for candidate in ineligible:
            st.caption(
                f"`{candidate.raw_transcript}` cannot be confirmed: "
                + ", ".join(candidate.rejection_reasons)
            )


def render_phrase_comparison(
    calibration_service: VoiceCalibrationService,
    session: CalibrationSession,
) -> None:
    """Render Phase 9 — Phrase Comparison and Recommendation."""
    if not session.commands:
        st.caption("No commands registered for phrase comparison.")
        return

    st.divider()
    st.subheader("Phrase Comparison & Recommendation")

    if session.phrase_candidates:
        st.markdown("**Registered phrase candidates**")
        table_data = []
        for candidate in session.phrase_candidates:
            table_data.append({
                "Phrase ID": candidate.phrase_id,
                "Command": candidate.command_id,
                "Display phrase": candidate.display_phrase,
                "Language": candidate.language,
                "Sort order": candidate.sort_order,
            })
        st.dataframe(table_data, use_container_width=True)
    else:
        st.caption("No phrase candidates registered yet.")

    command_id = st.session_state.get("voice_calibration_phrase_command_id")
    if not command_id:
        command_id = session.commands[0] if session.commands else None
        st.session_state["voice_calibration_phrase_command_id"] = command_id

    col_cmd, _, _ = st.columns(3)
    with col_cmd:
        command_id = st.selectbox(
            "Command",
            options=session.commands,
            index=session.commands.index(command_id) if command_id in session.commands else 0,
            key="voice_calibration_phrase_command_id",
        )

    comparison_results = calibration_service.compute_phrase_comparison(session)
    command_results = [r for r in comparison_results if r.command_id == command_id]

    if command_results:
        st.markdown(f"**Comparison results for `{command_id}`**")
        results_table = []
        for result in command_results:
            results_table.append({
                "Phrase ID": result.phrase_id,
                "Display phrase": result.display_phrase,
                "Attempts": result.attempts,
                "Exact": result.exact_matches,
                "Parser success": result.parser_successes,
                "Wrong command": result.wrong_command_count,
                "Unknown": result.unknown_count,
                "False accepts": result.false_accept_count,
                "Median latency (ms)": result.median_latency_ms,
                "P95 latency (ms)": result.p95_latency_ms,
            })
        st.dataframe(results_table, use_container_width=True)

    recommendation = calibration_service.recommend_phrase(
        session,
        command_id,
        canonical_phrase_id=session.phrase_candidates[0].phrase_id
        if session.phrase_candidates
        else None,
    )

    st.markdown("**Recommendation**")
    if recommendation:
        st.success(
            f"Recommended phrase: **{recommendation.display_phrase}** "
            f"(`{recommendation.phrase_id}`)\n\n"
            f"Parser successes: {recommendation.parser_successes}/{recommendation.attempts}\n\n"
            f"P95 latency: {recommendation.p95_latency_ms:.1f} ms"
            if recommendation.p95_latency_ms is not None
            else "P95 latency: n/a"
        )
    else:
        st.warning(
            "No reliable phrase recommendation available. "
            "All candidates have wrong_command or false_accept hits."
        )


def exit_calibration_and_restore_live_runtime(
    *,
    processor: Optional[VoiceAudioProcessor],
    reason: str,
) -> Optional[RuntimeTransitionAcknowledgement]:
    """Authoritative atomic exit from calibration that restores live runtime.

    Executed from every terminal / exit path:
        successful completion, cancel, reset, dismiss, wizard close,
        exception cleanup, page navigation, microphone restart.

    Steps:
        1. Cancel any active acoustic capture.
        2. Clear acoustic accumulators and pending measurement results.
        3. Clear CalibrationCaptureContext.
        4. Clear pending/armed command trial state.
        5. Clear negative-trial and TTS-echo capture context.
        6. Remove calibration-only event references (trial UI state).
        7. Reset VAD speech segment and rolling audio buffer.
        8. Clear partial calibration chunks and stale calibration work items.
        9. Set runtime mode based on current user state.
        10. Create a fresh continuous session ID when entering LIVE.
        11. Apply validated live runtime configuration.
        12. Verify the processor accepted the transition.
        13. Emit a typed audit event.
    """
    from tournament_platform.app.pages.voice_scorekeeper import (
        _append_continuous_trace,
        _set_voice_runtime_mode,
    )

    st.session_state["voice_calibration_active_session_id"] = None
    st.session_state["voice_calibration_session"] = None
    st.session_state["voice_calibration_active_trial_id"] = None
    st.session_state["voice_calibration_active_measurement_id"] = None
    st.session_state["voice_calibration_active_measurement_kind"] = None
    st.session_state["voice_calibration_measurement_started_at"] = None
    st.session_state["voice_calibration_phase"] = None
    st.session_state.pop("voice_calibration_pending_wizard_state", None)
    _clear_command_trial_ui_state()

    if processor is not None:
        processor.cancel_acoustic_capture()

    previous = st.session_state.get("voice_calibration_previous_runtime_mode")
    st.session_state.pop("voice_calibration_previous_runtime_mode", None)

    if previous is not None:
        try:
            target_mode = VoiceRuntimeMode(previous)
        except (TypeError, ValueError):
            target_mode = _compute_post_calibration_runtime_mode()
    else:
        target_mode = _compute_post_calibration_runtime_mode()

    new_session_id: Optional[str] = None
    if target_mode == VoiceRuntimeMode.LIVE:
        import uuid as _uuid
        new_session_id = str(_uuid.uuid4())
        st.session_state["voice_continuous_session_id"] = new_session_id
        st.session_state["voice_continuous_session_start"] = time.time()
        st.session_state["voice_listening"] = True
        st.session_state["voice_events_enabled"] = True

    st.session_state["voice_runtime_mode"] = target_mode

    ack: Optional[RuntimeTransitionAcknowledgement] = None
    if processor is not None:
        if hasattr(processor, "audio_buffer") and processor.audio_buffer is not None:
            processor.audio_buffer.reset()

        ack = processor.transition_runtime(
            target_mode=target_mode,
            continuous_session_id=new_session_id,
            clear_calibration_state=True,
        )

        _append_continuous_trace(
            "calibration_exit_and_restore",
            f"processor_id={id(processor)} "
            f"reason={reason} "
            f"target_mode={target_mode.value} "
            f"ack_accepted={ack.accepted} "
            f"ack_new_mode={ack.new_mode.value} "
            f"calibration_cleared={ack.calibration_context_cleared} "
            f"acoustic_cleared={ack.acoustic_capture_cleared} "
            f"work_cleared={ack.pending_calibration_work_cleared} "
            f"new_session={ack.new_continuous_session_id[:8] if ack.new_continuous_session_id else 'none'}",
        )
        st.session_state["voice_last_calibration_exit_ack"] = {
            "processor_id": ack.processor_id,
            "accepted": ack.accepted,
            "new_mode": ack.new_mode.value,
            "calibration_context_cleared": ack.calibration_context_cleared,
            "acoustic_capture_cleared": ack.acoustic_capture_cleared,
            "new_continuous_session_id": ack.new_continuous_session_id,
        }
    else:
        _append_continuous_trace(
            "calibration_exit_and_restore",
            f"reason={reason} "
            f"target_mode={target_mode.value} "
            f"processor=None",
        )

    return ack


def stop_voice_calibration(
    *,
    processor: Optional[VoiceAudioProcessor],
    reason: str,
) -> None:
    """Stop calibration and restore the appropriate runtime mode.

    Delegates to :func:`exit_calibration_and_restore_live_runtime` which
    performs the atomic processor-state transition and audit tracing.
    """
    _disarm_trial(processor)
    exit_calibration_and_restore_live_runtime(processor=processor, reason=reason)


def render_voice_calibration(
    calibration_service: VoiceCalibrationService,
    snapshot: Optional["WebRtcRenderSnapshot"] = None,
) -> None:
    from tournament_platform.app.services.voice_scorekeeper.runtime import WebRtcRenderSnapshot
    if snapshot is None:
        snapshot = WebRtcRenderSnapshot.unavailable()

    session: Optional[CalibrationSession] = st.session_state.get("voice_calibration_session")
    active_trial_id: Optional[str] = st.session_state.get("voice_calibration_active_trial_id")
    
    # Authoritative current processor comes from the snapshot
    proc = snapshot.processor

    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        VOICE_RUNTIME_IMPLEMENTATION_VERSION,
        VOICE_AUDIO_PROCESSOR_API_VERSION,
    )

    resolution = resolve_calibration_processor_readiness(
        webrtc_playing=snapshot.playing,
        processor=proc,
        expected_api_version=VOICE_AUDIO_PROCESSOR_API_VERSION,
        expected_implementation_version=VOICE_RUNTIME_IMPLEMENTATION_VERSION,
    )

    current_phase = st.session_state.get("voice_calibration_phase")
    expanded = False
    if current_phase is not None:
        try:
            phase_enum = CalibrationPhase(current_phase)
            expanded = phase_enum not in {
                CalibrationPhase.IDLE,
                CalibrationPhase.REVIEW,
                CalibrationPhase.COMPLETED,
            }
        except ValueError:
            pass

    with st.expander("🎯 Calibration Trial Wizard", expanded=expanded):
        if session is None:
            if proc is None:
                st.caption("Start the microphone to begin calibration.")
            elif resolution.status == "RESTART_REQUIRED":
                st.caption(f"Processor restart required: {resolution.reason}")
                if st.button("Restart voice processor", key="cal_restart_processor"):
                    st.session_state._voice_processor_cache_cleared = False
                    st.session_state._voice_processor_version = None
                    st.rerun()
            elif resolution.status == "WAITING_FOR_PROCESSOR":
                st.caption("Waiting for voice processor...")
            elif resolution.status == "WAITING_FOR_FIRST_FRAME":
                st.caption("Waiting for first audio frame...")
            elif resolution.status == "MICROPHONE_STOPPED":
                st.caption("Start the microphone to begin calibration.")
            elif not resolution.ready:
                st.caption(f"Processor not ready: {resolution.reason}")
            else:
                st.caption("No active calibration session.")

            start_disabled = not resolution.ready
            if st.button("Start Calibration", key="cal_start", type="primary", disabled=start_disabled):
                if proc is None or not resolution.ready:
                    st.warning("Processor is not ready. Ensure the microphone is mounted and ASR is loaded.")
                else:
                    new_session = calibration_service.start_command_trial_session()
                    st.session_state["voice_calibration_session"] = new_session
                    st.session_state["voice_calibration_active_session_id"] = new_session.session_id
                    st.session_state["voice_calibration_phase"] = CalibrationPhase.MEASURING_SILENCE.value
                    _enter_calibration_mode(st.session_state.get("voice_runtime_mode"))
                    st.rerun()
            return

        current_phase = st.session_state.get("voice_calibration_phase")
        if current_phase == CalibrationPhase.MEASURING_SILENCE.value:
            _render_silence_baseline_step(calibration_service, session, proc)
            return

        if current_phase == CalibrationPhase.MEASURING_SPEECH.value:
            silence_baseline = None
            for m in session.measurements:
                if isinstance(m, SilenceBaselineMetrics) and m.capture.complete and not m.capture.skipped:
                    silence_baseline = m
                    break
            _render_speech_measurement_step(calibration_service, session, proc, silence_baseline)
            return

        if current_phase == CalibrationPhase.NEGATIVE_TRIAL.value:
            _render_negative_trial_step(calibration_service, session, proc)
            return

        if current_phase == CalibrationPhase.TTS_ECHO_TEST.value:
            _render_tts_echo_test_step(calibration_service, session, proc)
            return

        if current_phase == CalibrationPhase.REVIEW.value:
            render_calibration_results(calibration_service, session)
            return

        if current_phase == CalibrationPhase.COMMAND_TRIAL.value:
            st.session_state.pop("voice_calibration_active_measurement_id", None)
            st.session_state.pop("voice_calibration_active_measurement_kind", None)
            st.session_state.pop("voice_calibration_measurement_started_at", None)
            st.session_state.pop("calibration_completed_measurement_ref", None)

        current_command = _derive_current_command(session)
        attempt_count = _derive_attempt_count(session)
        phase = CalibrationPhase.COMMAND_TRIAL
        complete = _is_session_complete(session)

        ct_ui_state = _get_command_trial_ui_state()
        if ct_ui_state is None:
            ct_ui_state = CommandTrialUIState(
                status=CommandTrialUIStatus.UNARMED,
                calibration_session_id=session.session_id,
                attempt_index=attempt_count,
            )
            _set_command_trial_ui_state(ct_ui_state)

        if ct_ui_state.status == CommandTrialUIStatus.ARMED and not active_trial_id:
            ct_ui_state = CommandTrialUIState(
                status=CommandTrialUIStatus.COMPLETED,
                calibration_session_id=ct_ui_state.calibration_session_id,
                trial_id=ct_ui_state.trial_id,
                expected_command_id=ct_ui_state.expected_command_id,
                expected_phrase=ct_ui_state.expected_phrase,
                processor_id=ct_ui_state.processor_id,
                attempt_index=ct_ui_state.attempt_index,
            )
            _set_command_trial_ui_state(ct_ui_state)

        col_status, col_cmd, col_attempt = st.columns(3)
        with col_status:
            st.metric("Phase", phase.value)
        with col_cmd:
            st.metric("Current Command", current_command.replace("_", " ") if current_command else "—")
        with col_attempt:
            st.metric("Attempt", f"{attempt_count} / {session.attempts_per_command}")

        if ct_ui_state.status == CommandTrialUIStatus.ARMED:
            st.caption(f"Armed trial: `{ct_ui_state.trial_id[:8]}...`")
            if ct_ui_state.expected_phrase:
                st.info(f"Listening for \"{ct_ui_state.expected_phrase}\"...")
            else:
                st.info("Listening...")
        elif ct_ui_state.status == CommandTrialUIStatus.ARM_REJECTED:
            st.caption("No trial armed.")
            if ct_ui_state.rejection_reason:
                st.error(f"Arm rejected: {ct_ui_state.rejection_reason}")
        elif ct_ui_state.status == CommandTrialUIStatus.COMPLETED:
            st.caption("Trial completed.")
        elif ct_ui_state.status == CommandTrialUIStatus.TIMED_OUT:
            st.caption("Trial timed out.")
        else:
            st.caption("No trial armed.")

        last_trial = None
        if session.trials:
            last_trial = session.trials[-1]

        if last_trial is not None:
            classification = getattr(last_trial, "classification", None)
            classification_value = classification.value if hasattr(classification, "value") else str(classification)
            raw_transcript = getattr(last_trial, "raw_transcript", "")
            normalized_transcript = getattr(last_trial, "normalized_transcript", "")
            resolved_command_id = getattr(last_trial, "resolved_command_id", None)
            parser_confidence = getattr(last_trial, "parser_confidence", None)
            exact_phrase_match_parser_miss = getattr(last_trial, "exact_phrase_match_parser_miss", False)

            expected_canonical = None
            parsed_canonical = None
            if current_command:
                expected_canonical = CanonicalCommandIntent(
                    action=current_command,
                    target=None,
                )
                _COMMAND_TO_ACTION = {
                    "point_red": "score_point",
                    "point_blue": "score_point",
                    "point_green": "score_point",
                    "point_teal": "score_point",
                    "point_orange": "score_point",
                    "undo": "undo",
                }
                expected_canonical = CanonicalCommandIntent(
                    action=_COMMAND_TO_ACTION.get(current_command, current_command),
                    target=current_command.replace("point_", "") if current_command.startswith("point_") else None,
                )
            if resolved_command_id:
                parsed_target = None
                if resolved_command_id == "score_point":
                    parsed_target = "blue" if exact_phrase_match_parser_miss else None
                parsed_canonical = CanonicalCommandIntent(
                    action=resolved_command_id,
                    target=parsed_target,
                )

            if classification_value == "exact":
                st.success("Result: Correct")
            elif classification_value == "variant":
                st.success("Result: Variant match")
            elif classification_value == "wrong_command":
                st.error("Result: Wrong command")
            elif classification_value == "unknown":
                st.warning("Result: Unrecognized")
            elif classification_value == "empty":
                st.warning("Result: Blank transcript")
            else:
                st.info(f"Result: {classification_value}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Expected:** {current_command.replace('_', ' ') if current_command else '—'}")
                st.markdown(f"**Heard:** {raw_transcript or '—'}")
                st.markdown(f"**Normalized:** {normalized_transcript or '—'}")
            with col_b:
                if expected_canonical is not None:
                    st.markdown(f"**Expected action:** {expected_canonical.action}")
                    st.markdown(f"**Expected target:** {expected_canonical.target or '—'}")
                else:
                    st.markdown("**Expected action:** —")
                    st.markdown("**Expected target:** —")
                if parsed_canonical is not None:
                    st.markdown(f"**Parsed action:** {parsed_canonical.action}")
                    st.markdown(f"**Parsed target:** {parsed_canonical.target or '—'}")
                else:
                    st.markdown("**Parsed action:** none")
                    st.markdown("**Parsed target:** none")
                if parser_confidence is not None:
                    st.markdown(f"**Confidence:** {parser_confidence:.2f}")
                else:
                    st.markdown("**Confidence:** N/A")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if ct_ui_state.status == CommandTrialUIStatus.UNARMED:
                if st.button("Start Trial", key="cal_start_trial", type="primary"):
                    if proc is None or not _is_processor_ready(proc):
                        st.error("Microphone processor not ready")
                        from tournament_platform.app.pages.voice_scorekeeper import _append_continuous_trace
                        _append_continuous_trace(
                            "calibration_command_trial_ui_arm_rejected",
                            "processor_unavailable",
                        )
                    else:
                        new_state = _arm_command_trial(session, proc, attempt_index=attempt_count)
                        _set_command_trial_ui_state(new_state)
                        st.rerun()
            elif ct_ui_state.status == CommandTrialUIStatus.ARMED:
                if not complete and st.button("Next", key="cal_next"):
                    if current_command and attempt_count >= session.attempts_per_command:
                        cmd_idx = session.current_command_index + 1
                        if cmd_idx >= len(session.commands):
                            complete = True
                        else:
                            new_session = replace(
                                session,
                                current_command_index=cmd_idx,
                                revision=session.revision + 1,
                            )
                            st.session_state["voice_calibration_session"] = new_session
                            next_cmd = _derive_current_command(new_session)
                            if next_cmd:
                                new_state = _arm_command_trial(new_session, proc, attempt_index=0)
                                _set_command_trial_ui_state(new_state)
                            else:
                                st.session_state["voice_calibration_active_trial_id"] = None
                                _disarm_trial(proc)
                                _clear_command_trial_ui_state()
                    else:
                        if current_command:
                            new_state = _arm_command_trial(session, proc, attempt_index=attempt_count)
                            _set_command_trial_ui_state(new_state)
                    st.rerun()
        with col2:
            if ct_ui_state.status in {CommandTrialUIStatus.COMPLETED, CommandTrialUIStatus.TIMED_OUT}:
                if st.button("Retry", key="cal_retry"):
                    if proc is None or not _is_processor_ready(proc):
                        st.error("Microphone processor not ready")
                    else:
                        new_state = _arm_command_trial(session, proc, attempt_index=ct_ui_state.attempt_index)
                        _set_command_trial_ui_state(new_state)
                        st.rerun()
            elif ct_ui_state.status == CommandTrialUIStatus.ARM_REJECTED:
                if st.button("Try Again", key="cal_try_again"):
                    if proc is None or not _is_processor_ready(proc):
                        st.error("Microphone processor not ready")
                    else:
                        new_state = _arm_command_trial(session, proc, attempt_index=ct_ui_state.attempt_index)
                        _set_command_trial_ui_state(new_state)
                        st.rerun()
        with col3:
            if ct_ui_state.status == CommandTrialUIStatus.ARMED:
                if st.button("Cancel Trial", key="cal_cancel_trial"):
                    _disarm_trial(proc)
                    st.session_state["voice_calibration_active_trial_id"] = None
                    ct_ui_state = CommandTrialUIState(
                        status=CommandTrialUIStatus.UNARMED,
                        calibration_session_id=session.session_id,
                        attempt_index=ct_ui_state.attempt_index,
                    )
                    _set_command_trial_ui_state(ct_ui_state)
                    st.rerun()
            else:
                if st.button("Cancel", key="cal_cancel"):
                    stop_voice_calibration(processor=proc, reason="user_cancelled")
                    st.rerun()
        with col4:
            if st.button("Reset", key="cal_reset"):
                stop_voice_calibration(processor=proc, reason="user_reset")
                st.rerun()

        if complete:
            state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.COMMAND_TRIAL)
            col_fin, col_neg, col_echo = st.columns(3)
            with col_fin:
                if st.button("Finish", key="cal_finish", type="primary"):
                    try:
                        new_state = calibration_service.transition(state, CalibrationPhase.REVIEW)
                        st.session_state["voice_calibration_phase"] = new_state.phase.value
                    except Exception:
                        pass
                    st.rerun()
            with col_neg:
                if st.button("Negative Speech", key="cal_negative"):
                    try:
                        new_state = calibration_service.transition(state, CalibrationPhase.NEGATIVE_TRIAL)
                        st.session_state["voice_calibration_phase"] = new_state.phase.value
                    except Exception:
                        pass
                    st.rerun()
            with col_echo:
                if st.button("TTS Echo Test", key="cal_echo"):
                    try:
                        new_state = calibration_service.transition(state, CalibrationPhase.TTS_ECHO_TEST)
                        st.session_state["voice_calibration_phase"] = new_state.phase.value
                    except Exception:
                        pass
                    st.rerun()

        if session.trials:
            if st.button("🔄 Re-evaluate calibration trials", key="cal_reevaluate"):
                updated_session, counts = calibration_service.re_evaluate_trials(session)
                st.session_state["voice_calibration_session"] = updated_session
                st.toast(f"Re-evaluated {len(counts['before'])} trials.", icon="🔄")
                st.rerun()

        st.divider()
        st.markdown("**Results**")
        if session.trials:
            for trial in session.trials[-10:]:
                icon = "✅" if trial.classification == TrialClassification.EXACT else "⚠️"
                st.markdown(
                    f"{icon} `{trial.trial_id[:8]}` — **{trial.classification.value}** "
                    f"| raw: `{trial.raw_transcript}`"
                )
        else:
            st.caption("No trials yet.")

    _render_acoustic_diagnostics(proc)


def _get_acoustic_diagnostics(
    proc: Optional[VoiceAudioProcessor],
) -> dict[str, Any]:
    """Collect acoustic diagnostics for the developer expander."""
    from tournament_platform.app.services.voice_scorekeeper.runtime import (
        _acoustic_audit_last_enqueue_count,
    )

    capabilities = inspect_voice_processor_capabilities(proc)
    snapshot = _get_acoustic_capture_snapshot(proc)

    return {
        "processor_id": id(proc) if proc is not None else None,
        "capture_active": snapshot.active if snapshot is not None else False,
        "session_id": snapshot.calibration_session_id if snapshot is not None else None,
        "measurement_id": snapshot.measurement_id if snapshot is not None else None,
        "kind": snapshot.kind.value if snapshot is not None and snapshot.kind else None,
        "scalar_sample_count": snapshot.sample_count if snapshot is not None else 0,
        "sample_frame_count": snapshot.frame_count if snapshot is not None else 0,
        "sample_rate_hz": snapshot.sample_rate_hz if snapshot is not None else None,
        "channels": snapshot.channels if snapshot is not None else None,
        "measured_duration_ms": snapshot.elapsed_ms if snapshot is not None else 0.0,
        "result_queue_size": snapshot.result_queue_size if snapshot is not None else 0,
        "last_completion_reason": snapshot.completion_reason if snapshot is not None else None,
        "acoustic_drain_invocations": _acoustic_audit_last_enqueue_count,
        "last_accepted_measurement_id": snapshot.measurement_id if snapshot is not None and snapshot.active else None,
        "last_rejected_measurement_id": None,
        "api_version": capabilities.api_version,
        "snapshot_api_available": capabilities.snapshot_available,
        "legacy_api_available": capabilities.legacy_snapshot_available,
        "active_capture_check_available": capabilities.active_capture_check_available,
        "arm_api_available": capabilities.acoustic_arm_available,
        "cancel_api_available": capabilities.acoustic_cancel_available,
        "drain_api_available": capabilities.acoustic_drain_available,
        "restart_required": capabilities.restart_required,
        "restart_reason": capabilities.restart_reason,
        "processor_module": type(proc).__module__ if proc is not None else None,
        "processor_source_file": inspect.getfile(type(proc)) if proc is not None else None,
    }


def _render_acoustic_diagnostics(
    proc: Optional[VoiceAudioProcessor],
) -> None:
    """Render a collapsed developer expander with acoustic diagnostics."""
    diag = _get_acoustic_diagnostics(proc)
    with st.expander("🔧 Acoustic Diagnostics", expanded=False):
        st.caption("Developer-only acoustic capture diagnostics.")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Processor ID", str(diag["processor_id"]) if diag["processor_id"] is not None else "—")
            st.metric("Capture active", str(diag["capture_active"]))
            st.metric("Session ID", diag["session_id"] or "—")
            st.metric("Measurement ID", diag["measurement_id"] or "—")
            st.metric("Kind", diag["kind"] or "—")
            st.metric("Scalar sample count", str(diag["scalar_sample_count"]))
        with col2:
            st.metric("Sample-frame count", str(diag["sample_frame_count"]))
            st.metric("Sample rate", f"{diag['sample_rate_hz']:,} Hz" if diag["sample_rate_hz"] else "—")
            st.metric("Channels", str(diag["channels"]) if diag["channels"] is not None else "—")
            st.metric("Measured duration", f"{diag['measured_duration_ms']:.1f} ms")
            st.metric("Result queue size", str(diag["result_queue_size"]))
            st.metric("Last completion reason", diag["last_completion_reason"] or "—")
            st.metric("Acoustic drain invocations", str(diag["acoustic_drain_invocations"]))
            st.metric("Last accepted measurement ID", diag["last_accepted_measurement_id"] or "—")
            st.metric("Last rejected measurement ID", diag["last_rejected_measurement_id"] or "—")
            st.metric("Processor API version", str(diag["api_version"]) if diag["api_version"] else "—")
            st.metric("Snapshot API available", str(diag["snapshot_api_available"]))
            st.metric("Legacy snapshot available", str(diag["legacy_api_available"]))
            st.metric("Active capture check available", str(diag["active_capture_check_available"]))
            st.metric("Arm API available", str(diag["arm_api_available"]))
            st.metric("Cancel API available", str(diag["cancel_api_available"]))
            st.metric("Drain API available", str(diag["drain_api_available"]))
            st.metric("Restart required", str(diag["restart_required"]))
            st.metric("Restart reason", diag["restart_reason"] or "—")
            st.metric("Processor module", diag["processor_module"] or "—")
            st.metric("Processor source file", diag["processor_source_file"] or "—")


def _render_calibration_verdict_reasons(
    results: CalibrationResults,
) -> None:
    """Render typed verdict reasons for each section."""
    if not results.section_outcomes:
        return

    st.markdown("**Section Breakdown**")
    for section in results.section_outcomes:
        status_icon = {
            CalibrationOverallStatus.PASS: "✅",
            CalibrationOverallStatus.WARNING: "⚠️",
            CalibrationOverallStatus.FAIL: "❌",
            CalibrationOverallStatus.NOT_TESTED: "🔍",
            CalibrationOverallStatus.INCOMPLETE: "⏳",
            CalibrationOverallStatus.INVALID_DATA: "🚫",
        }.get(section.status, "❓")

        st.markdown(f"{status_icon} **{section.section}** — {section.status.value}")
        if section.reasons:
            for reason in section.reasons:
                if reason.blocking:
                    icon = "🔴"
                elif reason.status == CalibrationOverallStatus.WARNING:
                    icon = "🟡"
                else:
                    icon = "🔵"
                st.caption(f"{icon} {reason.title}: {reason.explanation}")
                if reason.evidence:
                    st.caption(f"Evidence: {', '.join(reason.evidence)}")
                if reason.remediation:
                    st.caption(f"Remediation: {reason.remediation}")


def _render_live_profile_recommendation(
    recommendation: LiveVoiceProfileRecommendation | None,
) -> None:
    """Display the full LiveVoiceProfileRecommendation."""
    if recommendation is None:
        st.caption("No calibration recommendation available yet.")
        return

    status_icon = {
        RecommendationStatus.AVAILABLE: "✅",
        RecommendationStatus.WARNING: "⚠️",
        RecommendationStatus.UNAVAILABLE: "🔒",
        RecommendationStatus.INVALID_DATA: "🚫",
        RecommendationStatus.DEVICE_MISMATCH: "⚠️",
    }.get(recommendation.status, "❓")

    st.markdown(f"{status_icon} **Recommendation Status:** {recommendation.status.value}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Noise Gate:** {'On' if recommendation.noise_gate_enabled else 'Off'}")
        if recommendation.noise_threshold_rms is not None:
            st.markdown(f"**Threshold (RMS):** {recommendation.noise_threshold_rms:.6f}")
        if recommendation.noise_threshold_dbfs is not None:
            st.markdown(f"**Threshold (dBFS):** {recommendation.noise_threshold_dbfs:.2f}")
        st.markdown(f"**Strict Mode:** {'On' if recommendation.strict_mode_enabled else 'Off'}")

    with col2:
        st.markdown(f"**Profile Version:** {recommendation.profile_version}")
        st.markdown(f"**Confidence Policy:** {recommendation.confidence_policy}")
        st.markdown(f"**Applied Sections:** {', '.join(recommendation.applied_sections) or 'None'}")
        if recommendation.blocked_sections:
            st.markdown(f"**Blocked Sections:** {', '.join(recommendation.blocked_sections)}")

    if recommendation.reason_codes:
        st.markdown("**Reason Codes:**")
        for code in recommendation.reason_codes:
            st.caption(f"  - `{code}`")

    if recommendation.evidence:
        st.markdown("**Evidence:**")
        for ev in recommendation.evidence:
            unit = f" {ev.unit}" if ev.unit else ""
            st.caption(f"  - {ev.name}: {ev.value}{unit}")


def _activate_calibrated_voice_profile(
    recommendation: LiveVoiceProfileRecommendation | None,
    current_settings: LiveVoiceSettingsSnapshot | None,
) -> LiveVoiceSettingsSnapshot | None:
    """Activate a calibrated voice profile atomically.

    Returns the previous settings snapshot for rollback, or None if activation was blocked.
    """
    if recommendation is None:
        return None
    if recommendation.status in {
        RecommendationStatus.UNAVAILABLE,
        RecommendationStatus.INVALID_DATA,
        RecommendationStatus.DEVICE_MISMATCH,
    }:
        return None

    previous = current_settings or LiveVoiceSettingsSnapshot(
        noise_gate_enabled=st.session_state.get("voice_noise_filtering", False),
        noise_threshold_rms=st.session_state.get("voice_noise_threshold", 0.0),
        strict_mode_enabled=st.session_state.get("voice_strict_mode", False),
        asr_config_id=None,
        aliases=(),
        preferred_phrases=(),
        config_revision=0,
    )

    try:
        proc = _get_active_processor()
        if proc is not None:
            config = LiveVoiceRuntimeConfig(
                revision=(previous.config_revision + 1) if previous else 1,
                noise_gate_enabled=recommendation.noise_gate_enabled,
                noise_threshold_rms=recommendation.noise_threshold_rms or 0.0,
                strict_mode_enabled=recommendation.strict_mode_enabled,
                preferred_phrases=tuple(p.display_phrase for p in recommendation.preferred_phrases),
                confirmed_aliases=tuple(a.normalized_alias for a in recommendation.confirmed_aliases),
                asr_config=recommendation.selected_asr_config,
            )
            proc.apply_runtime_config(config)

        st.session_state["voice_live_profile_activation_status"] = (
            VoiceProfileActivationStatus.ACTIVE_NEEDS_VERIFICATION.value
        )
        st.session_state["voice_live_profile_settings_snapshot"] = previous
        st.session_state["voice_live_profile_config_revision"] = config.revision
        return previous
    except Exception as exc:
        logger.error("Failed to activate calibrated profile: %s", exc)
        return None


def _undo_calibrated_settings() -> None:
    """Undo calibrated settings by restoring the previous snapshot."""
    previous = st.session_state.get("voice_live_profile_settings_snapshot")
    if previous is None:
        return

    try:
        proc = _get_active_processor()
        if proc is not None:
            config = LiveVoiceRuntimeConfig(
                revision=previous.config_revision + 1,
                noise_gate_enabled=previous.noise_gate_enabled,
                noise_threshold_rms=previous.noise_threshold_rms,
                strict_mode_enabled=previous.strict_mode_enabled,
                preferred_phrases=(),
                confirmed_aliases=(),
                asr_config=None,
            )
            proc.apply_runtime_config(config)

        st.session_state["voice_noise_filtering"] = previous.noise_gate_enabled
        st.session_state["voice_noise_threshold"] = previous.noise_threshold_rms
        st.session_state["voice_strict_mode"] = previous.strict_mode_enabled
        st.session_state["voice_live_profile_activation_status"] = (
            VoiceProfileActivationStatus.ROLLED_BACK.value
        )
        st.session_state.pop("voice_live_profile_settings_snapshot", None)
    except Exception as exc:
        logger.error("Failed to undo calibrated settings: %s", exc)


def _render_post_activation_verification() -> None:
    """Render post-activation verification status."""
    status = st.session_state.get("voice_live_profile_activation_status")
    if not status:
        return

    status_enum = VoiceProfileActivationStatus(status)
    st.markdown("**Post-Activation Verification**")

    if status_enum == VoiceProfileActivationStatus.ACTIVE_NEEDS_VERIFICATION:
        st.info(
            "Profile activated. Please verify by saying 'point red', 'point blue', "
            "and an unrelated sentence. The system should recognize the commands "
            "and reject unrelated speech."
        )
    elif status_enum == VoiceProfileActivationStatus.ACTIVE_VERIFIED:
        st.success("Profile verified — all verification commands passed.")
    elif status_enum == VoiceProfileActivationStatus.ROLLED_BACK:
        st.warning("Calibrated settings were rolled back to the previous snapshot.")
    elif status_enum == VoiceProfileActivationStatus.BLOCKED:
        st.error("Profile activation was blocked. Check the calibration results for details.")


def _render_effective_configuration() -> None:
    """Render the authoritative effective configuration view."""
    st.markdown("**Effective Configuration**")

    proc = _get_active_processor()
    if proc is None:
        st.caption("No active processor.")
        return

    config = proc.get_current_runtime_config() if hasattr(proc, "get_current_runtime_config") else None
    if config is None:
        st.caption("Runtime configuration not available.")
        return

    st.markdown(f"**Configuration Revision:** {config.revision}")
    st.markdown(f"**Noise Gate:** {'On' if config.noise_gate_enabled else 'Off'}")
    st.markdown(f"**Threshold (RMS):** {config.noise_threshold_rms:.6f}")
    st.markdown(f"**Strict Mode:** {'On' if config.strict_mode_enabled else 'Off'}")
    st.markdown(f"**Preferred Phrases:** {len(config.preferred_phrases)}")
    st.markdown(f"**Confirmed Aliases:** {len(config.confirmed_aliases)}")
    st.markdown(f"**ASR Config:** {config.asr_config.config_id if config.asr_config else 'Baseline'}")


def consume_calibration_trials(
    *,
    service: VoiceCalibrationService,
    session: CalibrationSession | None,
    trials: tuple[CommandTrial, ...],
) -> CalibrationSession | None:
    if session is None or not trials:
        return session
    return service.consume_trials(
        session=session,
        trials=trials,
    )
