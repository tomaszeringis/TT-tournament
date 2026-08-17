from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, List, Optional

from tournament_platform.app.services.voice_calibration.models import (
    AcousticMeasurementResult,
    CalibrationCaptureKind,
    CommandTrial,
    NegativeTrial,
    TtsEchoTranscript,
)

logger = logging.getLogger(__name__)


class VoiceTranscriptSource(StrEnum):
    CONTINUOUS = "continuous"
    PUSH_TO_TALK = "push_to_talk"
    TYPED = "typed"
    CALIBRATION = "calibration"


class VoiceRuntimeMode(StrEnum):
    LIVE = "live"
    CALIBRATION = "calibration"
    OFF = "off"


class RuntimePermission(StrEnum):
    OFF = "off"
    LIVE = "live"
    CALIBRATION = "calibration"


class CalibrationExitReason(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESET = "reset"
    DISMISSED = "dismissed"
    WIZARD_CLOSED = "wizard_closed"
    EXCEPTION = "exception"
    PAGE_NAVIGATION = "page_navigation"
    MICROPHONE_RESTART = "microphone_restart"


@dataclass(frozen=True)
class VoiceRuntimeAuditEvent:
    timestamp: float
    processor_id: int
    processor_generation: int
    thread_name: str
    stage: str
    note: str
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RuntimeTransitionAcknowledgement:
    accepted: bool
    processor_id: int
    previous_mode: VoiceRuntimeMode
    new_mode: VoiceRuntimeMode
    previous_continuous_session_id: Optional[str]
    new_continuous_session_id: Optional[str]
    calibration_context_cleared: bool
    acoustic_capture_cleared: bool
    pending_calibration_work_cleared: bool
    config_revision: int
    rejection_reason: Optional[str]
    transitioned_at: float


@dataclass(frozen=True)
class CaptureSnapshot:
    runtime_mode: VoiceRuntimeMode
    calibration_context: Optional[CalibrationCaptureContext]
    runtime_session_id: Optional[str]


@dataclass(frozen=True)
class CalibrationCaptureContext:
    calibration_session_id: str
    calibration_trial_id: str
    capture_kind: CalibrationCaptureKind
    expected_command_id: str | None = None
    expected_phrase_id: str | None = None
    expected_phrase: str | None = None
    negative_prompt_id: str | None = None
    tts_playback_id: str | None = None
    armed_at: float | None = None
    revision: int = 0


@dataclass(frozen=True)
class TranscriptionWorkItem:
    audio: Any
    runtime_session_id: Optional[str]
    calibration_context: Optional[CalibrationCaptureContext]
    capture_runtime_mode: VoiceRuntimeMode = VoiceRuntimeMode.OFF


@dataclass(frozen=True)
class VoiceTranscriptEvent:
    transcript: str
    raw_transcript: str
    event_id: str
    source: VoiceTranscriptSource = VoiceTranscriptSource.CONTINUOUS
    runtime_session_id: Optional[str] = None
    match_id: Optional[Any] = None
    calibration_session_id: Optional[str] = None
    calibration_trial_id: Optional[str] = None
    expected_command_id: Optional[str] = None
    expected_phrase: Optional[str] = None
    created_at: Optional[float] = None
    calibration_context: Optional[CalibrationCaptureContext] = None
    capture_kind: Optional[CalibrationCaptureKind] = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.source, str):
            object.__setattr__(self, "source", normalize_event_source(self.source))
        if isinstance(self.calibration_context, CalibrationCaptureContext):
            if self.calibration_session_id not in {None, self.calibration_context.calibration_session_id}:
                raise InvalidVoiceTranscriptEvent("Conflicting calibration session id")
            if self.calibration_trial_id not in {None, self.calibration_context.calibration_trial_id}:
                raise InvalidVoiceTranscriptEvent("Conflicting calibration trial id")
            if self.expected_command_id not in {None, self.calibration_context.expected_command_id}:
                raise InvalidVoiceTranscriptEvent("Conflicting expected command id")
            if self.expected_phrase not in {None, self.calibration_context.expected_phrase}:
                raise InvalidVoiceTranscriptEvent("Conflicting expected phrase")
            object.__setattr__(self, "calibration_session_id", self.calibration_context.calibration_session_id)
            object.__setattr__(self, "calibration_trial_id", self.calibration_context.calibration_trial_id)
            object.__setattr__(self, "expected_command_id", self.calibration_context.expected_command_id)
            object.__setattr__(self, "expected_phrase", self.calibration_context.expected_phrase)
        elif self.calibration_session_id or self.calibration_trial_id or self.expected_command_id or self.expected_phrase:
            capture_kind = self.capture_kind or CalibrationCaptureKind.COMMAND_TRIAL
            object.__setattr__(
                self,
                "calibration_context",
                CalibrationCaptureContext(
                    calibration_session_id=self.calibration_session_id or "",
                    calibration_trial_id=self.calibration_trial_id or "",
                    capture_kind=capture_kind,
                    expected_command_id=self.expected_command_id or "",
                    expected_phrase=self.expected_phrase or "",
                ),
            )


class InvalidVoiceTranscriptEvent(Exception):
    """Raised when an event cannot be normalized to VoiceTranscriptEvent."""


def normalize_event_source(raw: object) -> VoiceTranscriptSource:
    if raw is None or raw == "":
        return VoiceTranscriptSource.CONTINUOUS
    try:
        return VoiceTranscriptSource(str(raw))
    except ValueError as exc:
        raise InvalidVoiceTranscriptEvent(
            f"Unsupported transcript source: {raw!r}"
        ) from exc


def normalize_voice_transcript_event(raw: object) -> VoiceTranscriptEvent:
    if isinstance(raw, VoiceTranscriptEvent):
        return raw

    if isinstance(raw, dict):
        ctx = raw.get("calibration_context")
        return VoiceTranscriptEvent(
            transcript=str(raw.get("transcript", "")),
            raw_transcript=str(
                raw.get("raw_transcript") or raw.get("transcript") or ""
            ),
            event_id=str(raw.get("event_id", "")),
            source=normalize_event_source(raw.get("source")),
            runtime_session_id=raw.get("runtime_session_id"),
            match_id=raw.get("match_id"),
            calibration_session_id=raw.get("calibration_session_id"),
            calibration_trial_id=raw.get("calibration_trial_id"),
            expected_command_id=raw.get("expected_command_id"),
            expected_phrase=raw.get("expected_phrase"),
            created_at=raw.get("created_at"),
            calibration_context=ctx,
            capture_kind=getattr(ctx, "capture_kind", None) if isinstance(ctx, CalibrationCaptureContext) else raw.get("capture_kind"),
            confidence=float(raw.get("confidence", 1.0)),
        )

    if isinstance(raw, tuple) and len(raw) == 3:
        transcript = raw[0]
        raw_transcript = raw[1]
        event_obj = raw[2]
        if hasattr(event_obj, "event_id"):
            event_id = str(getattr(event_obj, "event_id", ""))
        else:
            event_id = str(event_obj)
        calibration_context = getattr(event_obj, "calibration_context", None)
        if not isinstance(calibration_context, CalibrationCaptureContext):
            cal_session_id = getattr(event_obj, "calibration_session_id", None)
            cal_trial_id = getattr(event_obj, "calibration_trial_id", None)
            exp_cmd_id = getattr(event_obj, "expected_command_id", None)
            exp_phrase = getattr(event_obj, "expected_phrase", None)
            if cal_session_id or cal_trial_id or exp_cmd_id or exp_phrase:
                calibration_context = CalibrationCaptureContext(
                    calibration_session_id=cal_session_id or "",
                    calibration_trial_id=cal_trial_id or "",
                    capture_kind=getattr(event_obj, "capture_kind", None)
                    or CalibrationCaptureKind.COMMAND_TRIAL,
                    expected_command_id=exp_cmd_id or "",
                    expected_phrase=exp_phrase or "",
                )
            else:
                calibration_context = None
        return VoiceTranscriptEvent(
            transcript=str(transcript),
            raw_transcript=str(raw_transcript),
            event_id=event_id,
            calibration_context=calibration_context,
            capture_kind=getattr(calibration_context, "capture_kind", None) if calibration_context else None,
        )

    raise InvalidVoiceTranscriptEvent(
        f"Unsupported event schema: {type(raw).__name__}: {raw!r}"
    )


@dataclass(frozen=True)
class FinalizedUtterance:
    """A finalized utterance emitted by a streaming ASR backend (e.g. Deepgram).

    Carries the metadata needed to validate the event against the active
    voice session, match, and backend generation before scoring.
    See plan §3.6 and §8B.
    """
    voice_session_id: str
    backend_generation: int
    match_id: Optional[Any]
    language: str
    utterance_id: str
    created_at: float
    transcript: str
    raw_transcript: str
    finalization_reason: str  # "speech_final" | "endpoint" | "finalize_timeout" | "utterance_end"
    source: VoiceTranscriptSource = VoiceTranscriptSource.CONTINUOUS
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AudioTransportOutcome:
    """Terminal outcome for a single audio frame sent to a streaming backend."""
    outcome: str  # "enqueued" | "sent" | "queue_full" | "stale" | "provider_unavailable"
    rejection_reason: Optional[str] = None
    frame_id: str = ""
    timestamp: float = 0.0


@dataclass
class VoiceDrainResult:
    events_drained: int = 0
    events_accepted: int = 0
    events_rejected: int = 0
    events_stale: int = 0
    events_duplicate: int = 0
    calibration_events_evaluated: int = 0
    calibration_events_rejected: int = 0
    calibration_trials: List[Any] = field(default_factory=list)
    calibration_trial_results: List[CommandTrial] = field(default_factory=list)
    calibration_session_update: Optional[Any] = None
    calibration_measurements: List[AcousticMeasurementResult] = field(default_factory=list)
    calibration_measurements_evaluated: int = 0
    calibration_measurements_rejected: int = 0
    last_drained_measurement_id: str = ""
    calibration_negative_trials: List[NegativeTrial] = field(default_factory=list)
    calibration_tts_echo_transcripts: List[TtsEchoTranscript] = field(default_factory=list)
    last_transcript: str = ""
    last_command_source: str = ""
    last_rejection_reason: str = ""
    last_exception: Optional[str] = None
    # Streaming (Deepgram) event accounting (plan §8A)
    finalized_utterances_emitted: int = 0
    streaming_events_queued: int = 0
    streaming_events_drained: int = 0
    streaming_events_accepted: int = 0
    streaming_events_stale: int = 0
    streaming_events_duplicate: int = 0
    streaming_events_parser_rejected: int = 0
    streaming_events_failed: int = 0
    last_streaming_transcript: str = ""
    last_streaming_utterance_id: str = ""
