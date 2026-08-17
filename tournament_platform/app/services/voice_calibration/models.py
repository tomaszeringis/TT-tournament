"""
Voice Calibration — Pure domain models.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Tuple


def normalize_calibration_phrase(text: str) -> str:
    """Strict phrase normalizer for calibration comparison.

    - Unicode normalization (NFKC)
    - casefold
    - replace punctuation with spaces
    - collapse repeated whitespace
    - trim whitespace
    - preserve words and digits exactly as spoken

    Does NOT perform number-word conversion or homophone substitution.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = normalized.replace(",", " ").replace(".", " ").replace("!", " ").replace("?", " ").replace("—", " ").replace("-", " ")
    tokens = normalized.split()
    return " ".join(tokens)


class CalibrationPhase(StrEnum):
    IDLE = "idle"
    ENVIRONMENT_CHECK = "environment_check"
    MEASURING_SILENCE = "measuring_silence"
    MEASURING_SPEECH = "measuring_speech"
    COMMAND_TRIAL = "command_trial"
    NEGATIVE_TRIAL = "negative_trial"
    TTS_ECHO_TEST = "tts_echo_test"
    REVIEW = "review"
    SAVING = "saving"
    COMPLETED = "completed"


class CommandTrialUIStatus(StrEnum):
    UNARMED = "unarmed"
    ARMING = "arming"
    WAITING_FOR_MICROPHONE = "waiting_for_microphone"
    ARMED = "armed"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ARM_REJECTED = "arm_rejected"
    TIMED_OUT = "timed_out"


class TrialClassification(StrEnum):
    EXACT = "exact"
    VARIANT = "variant"
    WRONG_COMMAND = "wrong_command"
    UNKNOWN = "unknown"
    EMPTY = "empty"


@dataclass(frozen=True)
class CanonicalCommandIntent:
    action: str
    target: str | None = None


class AliasCandidateStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INELIGIBLE = "ineligible"


class CalibrationMeasurementKind(StrEnum):
    SILENCE_BASELINE = "silence_baseline"
    NORMAL_SPEECH = "normal_speech"


class CalibrationCaptureKind(StrEnum):
    COMMAND_TRIAL = "command_trial"
    NEGATIVE_TRIAL = "negative_trial"
    TTS_ECHO_TEST = "tts_echo_test"


class NegativeTrialClassification(StrEnum):
    CORRECTLY_REJECTED = "correctly_rejected"
    FALSE_POINT_CANDIDATE = "false_point_candidate"
    FALSE_UNDO_CANDIDATE = "false_undo_candidate"
    FALSE_RESET_CANDIDATE = "false_reset_candidate"
    WRONG_NON_SCORE_CANDIDATE = "wrong_non_score_candidate"
    NO_AUDIO = "no_audio"
    ASR_FAILED = "asr_failed"


@dataclass(frozen=True)
class AcousticCaptureSummary:
    measurement_id: str
    calibration_session_id: str
    kind: CalibrationMeasurementKind
    sample_rate_hz: int
    channel_count: int
    frame_count: int
    scalar_sample_count: int
    target_duration_ms: float
    captured_duration_ms: float
    valid_frame_count: int
    invalid_frame_count: int
    rms: float | None
    rms_dbfs: float | None
    peak: float | None
    peak_dbfs: float | None
    near_clipping_count: int
    hard_clipping_count: int
    speech_frame_count: int
    speech_duration_ms: float
    complete: bool
    warning_codes: tuple[str, ...]
    created_at: float
    skipped: bool = False


@dataclass(frozen=True)
class SilenceBaselineMetrics:
    capture: AcousticCaptureSummary
    median_rms: float | None
    median_dbfs: float | None
    p90_rms: float | None
    p90_dbfs: float | None
    p95_rms: float | None
    p95_dbfs: float | None
    mad_rms: float | None
    transient_count: int
    contaminated_by_speech: bool
    speech_frame_count: int
    speech_duration_ms: float


@dataclass(frozen=True)
class SpeechLevelMetrics:
    capture: AcousticCaptureSummary
    speech_start_offset_ms: float | None
    trailing_silence_ms: float | None
    speech_rms: float | None
    speech_rms_dbfs: float | None
    speech_to_background_difference_db: float | None


AcousticMeasurementResult = SilenceBaselineMetrics | SpeechLevelMetrics


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
class CalibrationArmAcknowledgement:
    accepted: bool
    processor_id: int
    calibration_session_id: str | None
    trial_id: str | None
    capture_kind: CalibrationCaptureKind | None
    armed_at: float | None
    rejection_reason: str | None


@dataclass(frozen=True)
class AudioFrameDecision:
    passes_noise_gate: bool
    is_speech: bool


@dataclass(frozen=True)
class AcousticCaptureContext:
    calibration_session_id: str
    measurement_id: str
    kind: CalibrationMeasurementKind
    target_duration_ms: int
    timeout_ms: int
    armed_at_monotonic: float


@dataclass(frozen=True)
class RecommendationEvidence:
    name: str
    value: float | int | str
    unit: str | None = None


@dataclass(frozen=True)
class AcousticRecommendation:
    code: str
    severity: str
    message: str
    evidence: tuple[RecommendationEvidence, ...]


class AcousticRecommendationCode(StrEnum):
    READY = "ready"
    NO_AUDIO = "no_audio"
    INCOMPLETE_CAPTURE = "incomplete_capture"
    TOO_QUIET = "too_quiet"
    BACKGROUND_NOISE_HIGH = "background_noise_high"
    CLIPPING = "clipping"
    SPEECH_STARTED_TOO_EARLY = "speech_started_too_early"
    TRAILING_SILENCE_HIGH = "trailing_silence_high"
    SAMPLE_RATE_CHANGED = "sample_rate_changed"
    SPEECH_TOO_QUIET = "speech_too_quiet"
    SPEECH_TOO_LOUD = "speech_too_loud"
    NO_SPEECH_DETECTED = "no_speech_detected"
    LOW_SPEECH_TO_BACKGROUND_DIFFERENCE = "low_speech_to_background_difference"


@dataclass(frozen=True)
class AsrMetadata:
    latency_ms: float | None
    no_speech_probability: float | None
    average_log_probability: float | None
    word_probabilities: Tuple[float, ...]


@dataclass(frozen=True)
class CalibrationAliasCandidate:
    transcript: str
    command_id: str
    classification: str
    confirmed: bool = False
    language: str = "en"


@dataclass(frozen=True)
class CommandTrial:
    trial_id: str
    expected_command_id: str
    expected_phrase: str
    raw_transcript: str
    normalized_transcript: str
    resolved_command_id: str | None
    classification: TrialClassification
    parser_confidence: float | None
    rejection_reason: str | None
    expected_phrase_id: str | None = None
    asr_latency_ms: float | None = None
    exact_phrase_match_parser_miss: bool = False


@dataclass(frozen=True)
class CalibrationState:
    session_id: str
    phase: CalibrationPhase
    revision: int = 0


@dataclass(frozen=True)
class CommandTrialUIState:
    status: CommandTrialUIStatus
    calibration_session_id: str
    trial_id: str | None = None
    expected_command_id: str | None = None
    expected_phrase: str | None = None
    processor_id: int | None = None
    armed_at: float | None = None
    rejection_reason: str | None = None
    attempt_index: int = 0


@dataclass(frozen=True)
class NegativeTrial:
    trial_id: str
    prompt_id: str
    raw_transcript: str
    normalized_transcript: str
    parser_command_id: str | None
    parser_confidence: float | None
    would_accept_live: bool
    classification: NegativeTrialClassification
    created_at: float


@dataclass(frozen=True)
class TtsEchoTestContext:
    playback_id: str
    text: str
    voice_provider: str
    playback_started_at: float
    playback_ended_at: float | None = None


@dataclass(frozen=True)
class TtsEchoTranscript:
    transcript_id: str
    tts_playback_id: str
    captured_during_playback: bool
    capture_offset_ms: float | None
    transcript: str
    normalized_transcript: str
    tts_source: str
    created_at: float


@dataclass(frozen=True)
class CalibrationSession:
    session_id: str
    created_at: float
    trials: tuple[CommandTrial, ...] = field(default_factory=tuple)
    alias_candidates: tuple[CalibrationAliasCandidate, ...] = field(default_factory=tuple)
    commands: tuple[str, ...] = field(default_factory=tuple)
    attempts_per_command: int = 3
    current_command_index: int = 0
    measurements: tuple[AcousticMeasurementResult, ...] = field(default_factory=tuple)
    negative_trials: tuple[NegativeTrial, ...] = field(default_factory=tuple)
    tts_echo_transcripts: tuple[TtsEchoTranscript, ...] = field(default_factory=tuple)
    tts_echo_test_contexts: tuple[TtsEchoTestContext, ...] = field(
        default_factory=tuple
    )
    phrase_candidates: tuple[CommandPhraseCandidate, ...] = field(default_factory=tuple)
    asr_ab_results: tuple[AsrAbSampleResult, ...] = field(default_factory=tuple)
    skipped_phases: tuple[CalibrationPhaseSkipRecord, ...] = field(default_factory=tuple)
    revision: int = 0


@dataclass(frozen=True)
class CommandCalibrationResult:
    command_id: str
    attempts: int
    exact_matches: int
    successful_resolutions: int
    wrong_command_count: int
    unknown_count: int


@dataclass(frozen=True)
class Collision:
    transcript: str
    conflicting_ids: tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None


@dataclass(frozen=True)
class CommandPhraseCandidate:
    phrase_id: str
    command_id: str
    display_phrase: str
    normalized_phrase: str
    language: str
    sort_order: int


@dataclass(frozen=True)
class PhraseComparisonResult:
    phrase_id: str
    command_id: str
    display_phrase: str
    attempts: int
    exact_matches: int
    parser_successes: int
    wrong_command_count: int
    unknown_count: int
    false_accept_count: int
    median_latency_ms: float | None
    p95_latency_ms: float | None


@dataclass(frozen=True)
class CalibrationConfusionEntry:
    test_type: str
    expected: str
    transcript: str
    normalized_transcript: str
    parser_candidate: str | None
    parser_confidence: float | None
    outcome: str


@dataclass(frozen=True)
class CalibrationSafetyOutcome:
    category: str
    outcome: str
    detail: str
    failure: bool


class CalibrationOverallStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_TESTED = "not_tested"
    INCOMPLETE = "incomplete"
    INVALID_DATA = "invalid_data"


@dataclass(frozen=True)
class CalibrationVerdictReason:
    code: str
    status: CalibrationOverallStatus
    section: str
    title: str
    explanation: str
    evidence: tuple[str, ...]
    remediation: str
    blocking: bool


@dataclass(frozen=True)
class CalibrationSectionOutcome:
    section: str
    status: CalibrationOverallStatus
    reasons: tuple[CalibrationVerdictReason, ...]
    evidence_count: int
    required_evidence_count: int


class RecommendationStatus(StrEnum):
    AVAILABLE = "available"
    WARNING = "warning"
    UNAVAILABLE = "unavailable"
    INVALID_DATA = "invalid_data"
    DEVICE_MISMATCH = "device_mismatch"


class VoiceProfileActivationStatus(StrEnum):
    NOT_APPLIED = "not_applied"
    APPLYING = "applying"
    ACTIVE_NEEDS_VERIFICATION = "active_needs_verification"
    ACTIVE_VERIFIED = "active_verified"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class CalibrationPhaseSkipRecord:
    phase: str
    skipped_at: float
    reason: str


@dataclass(frozen=True)
class NoiseGateRecommendation:
    enabled: bool
    threshold_rms: float | None
    threshold_dbfs: float | None
    confidence: float
    evidence: tuple[RecommendationEvidence, ...]


@dataclass(frozen=True)
class NoiseGateRecommendationPolicy:
    background_margin_db: float = 6.0
    speech_headroom_db: float = 6.0
    minimum_safe_separation_db: float = 12.0
    min_speech_to_background_db: float = 12.0


@dataclass(frozen=True)
class LiveVoiceProfileRecommendation:
    calibration_session_id: str
    calibration_profile_id: str | None
    identity: CalibrationProfileIdentity
    status: RecommendationStatus
    noise_gate_enabled: bool
    noise_threshold_rms: float | None
    noise_threshold_dbfs: float | None
    strict_mode_enabled: bool
    selected_asr_config: AsrExperimentConfig | None
    preferred_phrases: tuple[CommandPhraseCandidate, ...]
    confirmed_aliases: tuple[AliasConfirmationCandidate, ...]
    confidence_policy: str
    profile_version: str
    applied_sections: tuple[str, ...]
    blocked_sections: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence: tuple[RecommendationEvidence, ...]


@dataclass(frozen=True)
class LiveVoiceRuntimeConfig:
    revision: int
    noise_gate_enabled: bool
    noise_threshold_rms: float
    strict_mode_enabled: bool
    preferred_phrases: tuple[str, ...]
    confirmed_aliases: tuple[str, ...]
    asr_config: AsrExperimentConfig | None


@dataclass(frozen=True)
class LiveVoiceSettingsSnapshot:
    noise_gate_enabled: bool
    noise_threshold_rms: float
    strict_mode_enabled: bool
    asr_config_id: str | None
    aliases: tuple[AliasConfirmationCandidate, ...]
    preferred_phrases: tuple[CommandPhraseCandidate, ...]
    config_revision: int


@dataclass(frozen=True)
class AcousticSummarySnapshot:
    background_median_dbfs: float | None = None
    background_p90_dbfs: float | None = None
    background_p95_dbfs: float | None = None
    speech_level_dbfs: float | None = None
    speech_background_difference_db: float | None = None
    clipping_detected: bool = False
    measurement_count: int = 0
    total_measurements: int = 0
    complete_measurements: int = 0
    valid_complete_measurements: int = 0
    silence_measurement_count: int = 0
    speech_measurement_count: int = 0
    required_kinds_present: int = 0
    selected_silence_measurement_id: str | None = None
    selected_speech_measurement_id: str | None = None


@dataclass(frozen=True)
class CommandRecognitionEntry:
    command_id: str
    attempts: int = 0
    exact_matches: int = 0
    successful_resolutions: int = 0
    wrong_command_count: int = 0
    unknown_count: int = 0


@dataclass(frozen=True)
class ParserCandidateInfo:
    raw_transcript: str
    normalized_transcript: str
    parser_command_id: str | None
    parser_confidence: float | None
    would_accept_live: bool
    classification: str


@dataclass(frozen=True)
class NegativeSpeechSnapshot:
    trials: int = 0
    correctly_rejected: int = 0
    false_point_candidates: int = 0
    false_undo_reset_candidates: int = 0
    false_live_acceptable_candidates: int = 0
    parser_candidates: tuple[ParserCandidateInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TtsEchoTranscriptInfo:
    transcript: str
    normalized_transcript: str
    tts_source: str
    captured_during_playback: bool


@dataclass(frozen=True)
class TtsEchoSnapshot:
    playback_tests: int = 0
    transcripts_captured: int = 0
    live_acceptable_command_candidates: int = 0
    score_actions: int = 0
    transcripts: tuple[TtsEchoTranscriptInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VerificationMetadata:
    verified_at: float | None = None
    verification_notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CalibrationResults:
    session_id: str
    acoustic_summary: AcousticSummarySnapshot
    command_recognition: tuple[CommandRecognitionEntry, ...]
    negative_speech: NegativeSpeechSnapshot
    tts_echo: TtsEchoSnapshot
    confusion_table: tuple[CalibrationConfusionEntry, ...]
    safety_outcomes: tuple[CalibrationSafetyOutcome, ...]
    overall_pass: bool
    overall_status: CalibrationOverallStatus
    section_outcomes: tuple[CalibrationSectionOutcome, ...]
    blocking_reasons: tuple[CalibrationVerdictReason, ...]
    warning_reasons: tuple[CalibrationVerdictReason, ...]
    incomplete_reasons: tuple[CalibrationVerdictReason, ...]
    invalid_data_reasons: tuple[CalibrationVerdictReason, ...]
    created_at: float


@dataclass(frozen=True)
class AliasConfirmationCandidate:
    candidate_id: str
    calibration_session_id: str
    source_trial_id: str
    command_id: str
    language: str
    raw_transcript: str
    normalized_alias: str
    expected_phrase: str
    occurrence_count: int
    collision_command_ids: tuple[str, ...]
    eligible: bool
    rejection_reasons: tuple[str, ...]
    status: AliasCandidateStatus = AliasCandidateStatus.PENDING


class AsrExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    CANCELLED = "cancelled"


class AsrExperimentRecommendation(StrEnum):
    CANDIDATE_RECOMMENDED = "candidate_recommended"
    BASELINE_RETAINED = "baseline_retained"
    MORE_SAMPLES_REQUIRED = "more_samples_required"
    CANDIDATE_UNSAFE = "candidate_unsafe"
    PROVIDER_UNSUPPORTED = "provider_unsupported"


@dataclass(frozen=True)
class AsrProviderCapabilities:
    provider: str
    supports_hotwords: bool
    supports_initial_prompt: bool
    supports_condition_on_previous_text: bool
    supports_word_probabilities: bool
    supports_no_speech_probability: bool
    supports_average_log_probability: bool


@dataclass(frozen=True)
class AsrExperimentConfig:
    config_id: str
    display_name: str
    language: str | None
    hotwords: str | None
    initial_prompt: str | None
    condition_on_previous_text: bool | None
    beam_size: int | None


@dataclass(frozen=True)
class ExperimentIdentity:
    sample_id: str = ""
    calibration_session_id: str = ""
    experiment_id: str = ""


@dataclass(frozen=True)
class AsrAbWorkItem:
    experiment_id: str
    sample_id: str
    calibration_session_id: str
    capture_kind: str
    expected_command_id: str | None
    expected_phrase: str | None
    baseline_config: AsrExperimentConfig
    candidate_config: AsrExperimentConfig
    audio_bytes: bytes
    sample_rate_hz: int
    experiment_identity: ExperimentIdentity = field(default_factory=ExperimentIdentity)


@dataclass(frozen=True)
class AsrExperimentTranscript:
    config_id: str
    raw_transcript: str
    normalized_transcript: str
    language: str | None
    latency_ms: float
    average_log_probability: float | None
    no_speech_probability: float | None
    parser_command_id: str | None
    parser_confidence: float | None
    would_accept_live: bool


@dataclass(frozen=True)
class AsrAbSampleResult:
    experiment_id: str
    sample_id: str
    calibration_session_id: str
    capture_kind: str
    expected_command_id: str | None
    expected_phrase: str | None
    baseline: AsrExperimentTranscript
    candidate: AsrExperimentTranscript
    experiment_identity: ExperimentIdentity = field(default_factory=ExperimentIdentity)


@dataclass(frozen=True)
class AsrExperimentAggregate:
    config_id: str
    positive_attempts: int
    exact_matches: int
    parser_successes: int
    wrong_command_count: int
    unknown_count: int
    negative_false_candidate_count: int
    tts_false_candidate_count: int
    total_negative_samples: int
    total_tts_samples: int
    median_latency_ms: float | None
    p95_latency_ms: float | None


class CalibrationProfileStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    INVALID = "invalid"


@dataclass(frozen=True)
class CalibrationProfileIdentity:
    language: str
    asr_provider: str
    asr_model: str
    compute_type: str | None
    microphone_device_hash: str | None
    sample_rate_hz: int | None
    profile_schema_version: int = 1


@dataclass(frozen=True)
class VoiceCalibrationProfile:
    profile_id: str
    owner_id: str
    identity: CalibrationProfileIdentity
    status: CalibrationProfileStatus
    preferred_phrases: tuple[str, ...]
    confirmed_aliases: tuple[AliasConfirmationCandidate, ...]
    selected_asr_config: AsrExperimentConfig | None
    acoustic_summary: AcousticSummarySnapshot
    negative_speech_outcome: NegativeSpeechSnapshot
    tts_echo_outcome: TtsEchoSnapshot
    verification_metadata: VerificationMetadata
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class CompletedMeasurementRef:
    """Reference to a completed acoustic measurement result.
    
    This is the durable identity for a completed measurement after it is
    consumed into a CalibrationSession. It allows the renderer to locate
    the result in the measurements tuple without depending on active_measurement_id,
    which may be cleared prematurely.
    
    Scoped to calibration_session_id to prevent results from different
    sessions from being confused or displayed out of context.
    """
    calibration_session_id: str
    measurement_id: str
    kind: CalibrationMeasurementKind


@dataclass(frozen=True)
class AcousticReconciliationResult:
    """Result of reconciling drained acoustic measurements into a session.
    
    The page/controller owns session-state updates. This helper must not
    read or mutate Streamlit session state.
    """
    session: CalibrationSession
    completed_ref: CompletedMeasurementRef | None
    consumed_measurement_ids: tuple[str, ...]
    ignored_measurement_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...]


class CalibrationProfileStore:
    """Storage abstraction for calibration profiles.

    Implementations may persist to session state, browser local storage,
    or a database. This class defines the contract only.
    """

    def load(self, owner_id: str, identity: CalibrationProfileIdentity) -> VoiceCalibrationProfile | None:
        raise NotImplementedError

    def save(self, owner_id: str, profile: VoiceCalibrationProfile) -> None:
        raise NotImplementedError

    def delete(self, owner_id: str, profile_id: str) -> None:
        raise NotImplementedError
