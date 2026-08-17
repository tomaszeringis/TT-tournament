"""
Calibration Policy — Provider-aware audio admission control.

Replaces the global "no calibration context -> reject every audio chunk" rule
with a capability-driven decision based on ``ASRCapabilities`` and
``AudioDeliveryPolicy``.  See plan §3.6 and §3.8.

This module is deliberately free of Streamlit and SDK imports so it can be
unit-tested in complete isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


class AudioHealthStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_REQUIRED = "not_required"


class UtteranceOutcome(StrEnum):
    FINALIZED = "finalized"
    EMPTY = "empty"
    DUPLICATE = "duplicate"
    STALE = "stale"
    PARSER_REJECTED = "parser_rejected"
    ENGINE_REJECTED = "engine_rejected"
    APPLIED = "applied"
    PROVIDER_FAILED = "provider_failed"


class AudioTransportOutcome(StrEnum):
    ENQUEUED = "enqueued"
    SENT = "sent"
    REJECTED = "rejected"
    STALE = "stale"
    QUEUE_FULL = "queue_full"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True)
class ASRCapabilities:
    supports_streaming: bool = False
    requires_speaker_calibration: bool = False
    supports_local_vad: bool = False
    supports_optional_audio_health_check: bool = False


@dataclass(frozen=True)
class AudioDeliveryPolicy:
    mode: str = "continuous"  # "continuous" | "vad_gated" | "disabled"
    require_vad_calibration: bool = False
    allow_degraded_fallback: bool = False


@dataclass(frozen=True)
class AudioAdmissionDecision:
    accepted: bool
    rejection_reason: Optional[str] = None
    terminal_outcome: str = ""

    @classmethod
    def accept(cls, outcome: str = "enqueued") -> "AudioAdmissionDecision":
        return cls(accepted=True, rejection_reason=None, terminal_outcome=outcome)

    @classmethod
    def reject(cls, reason: str, outcome: str = "rejected") -> "AudioAdmissionDecision":
        return cls(accepted=False, rejection_reason=reason, terminal_outcome=outcome)


@dataclass(frozen=True)
class AudioHealthState:
    microphone_signal_detected: bool = False
    microphone_clipping_detected: bool = False
    microphone_low_level_detected: bool = False
    noise_floor_dbfs: Optional[float] = None
    valid_sample_rate: bool = True
    valid_channel_count: bool = True


# ---------------------------------------------------------------------------
# Preset policies
# ---------------------------------------------------------------------------

_LOCAL_BATCH_CAPABILITIES = ASRCapabilities(
    supports_streaming=False,
    requires_speaker_calibration=False,
    supports_local_vad=True,
    supports_optional_audio_health_check=True,
)

_LOCAL_BATCH_DELIVERY_CONTINUOUS = AudioDeliveryPolicy(
    mode="continuous",
    require_vad_calibration=True,
    allow_degraded_fallback=False,
)

_DEEPGRAM_CAPABILITIES = ASRCapabilities(
    supports_streaming=True,
    requires_speaker_calibration=False,
    supports_local_vad=False,
    supports_optional_audio_health_check=True,
)

_DEEPGRAM_DELIVERY_CONTINUOUS = AudioDeliveryPolicy(
    mode="continuous",
    require_vad_calibration=False,
    allow_degraded_fallback=True,
)


def local_batch_policy() -> "CalibrationPolicy":
    """Policy for local batch providers (faster-whisper, vosk).

    Preserves the existing terminal-outcome behavior so existing tests that
    expect ``runtime_off_no_calibration_context`` continue to pass.
    """
    return CalibrationPolicy(
        capabilities=_LOCAL_BATCH_CAPABILITIES,
        delivery_policy=AudioDeliveryPolicy(
            mode="vad_gated",
            require_vad_calibration=True,
            allow_degraded_fallback=False,
        ),
    )


def deepgram_continuous_policy() -> "CalibrationPolicy":
    """Policy for Deepgram continuous streaming — no calibration required."""
    return CalibrationPolicy(
        capabilities=_DEEPGRAM_CAPABILITIES,
        delivery_policy=_DEEPGRAM_DELIVERY_CONTINUOUS,
    )


def deepgram_gated_policy() -> "CalibrationPolicy":
    """Policy for Deepgram with local VAD gating — VAD calibration may be required."""
    return CalibrationPolicy(
        capabilities=ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=True,
            supports_optional_audio_health_check=True,
        ),
        delivery_policy=AudioDeliveryPolicy(
            mode="vad_gated",
            require_vad_calibration=True,
            allow_degraded_fallback=True,
        ),
    )


class CalibrationPolicy:
    """Centralizes the decision of whether audio should be accepted.

    The policy evaluates three signals in priority order:

    1. Runtime mode — if voice scoring is OFF, the rejection reason depends on
       whether the provider requires calibration (``runtime_off_no_calibration_context``
       for legacy local providers, ``runtime_voice_disabled`` for streaming
       providers).
    2. VAD calibration — if the delivery policy requires VAD calibration and it
       is not available, reject with ``vad_calibration_required`` (unless a
       degraded fallback is configured).
    3. Microphone health — check signal presence and format validity.
    """

    def __init__(
        self,
        capabilities: ASRCapabilities,
        delivery_policy: AudioDeliveryPolicy,
    ) -> None:
        self._capabilities = capabilities
        self._delivery_policy = delivery_policy

    @property
    def capabilities(self) -> ASRCapabilities:
        return self._capabilities

    @property
    def delivery_policy(self) -> AudioDeliveryPolicy:
        return self._delivery_policy

    @property
    def is_streaming(self) -> bool:
        return self._capabilities.supports_streaming

    @property
    def requires_vad_calibration(self) -> bool:
        return self._delivery_policy.require_vad_calibration

    def evaluate_disabled_mode(self) -> AudioAdmissionDecision:
        """Decide the rejection reason when voice scoring is off.

        Streaming providers (Deepgram) use ``runtime_voice_disabled``.
        Legacy local batch providers preserve ``runtime_off_no_calibration_context``
        so existing regression tests remain green (plan §3.8, §9.8).
        """
        if self._capabilities.supports_streaming:
            return AudioAdmissionDecision.reject(
                reason="runtime_voice_disabled",
                outcome="rejected",
            )
        return AudioAdmissionDecision.reject(
            reason="runtime_off_no_calibration_context",
            outcome="rejected",
        )

    def evaluate_live_audio_admission(
        self,
        *,
        session_id: Optional[str],
        vad_calibration_available: bool,
        health: Optional[AudioHealthState] = None,
    ) -> AudioAdmissionDecision:
        """Determine whether live audio should be accepted for provider submission.

        Parameters
        ----------
        session_id:
            Current continuous-listening session ID.  If ``None`` the chunk is
            rejected because there is no active session.
        vad_calibration_available:
            Whether a valid VAD calibration is present (noise floor + gate).
        health:
            Optional microphone health state from the bounded health window.
        """
        if session_id is None:
            return AudioAdmissionDecision.reject(
                reason="missing_continuous_session",
                outcome="rejected",
            )

        # --- VAD calibration check ---
        if self._delivery_policy.require_vad_calibration and not vad_calibration_available:
            if self._delivery_policy.allow_degraded_fallback:
                # Allow audio through, but mark as degraded.  The caller
                # should surface a warning.
                pass
            else:
                return AudioAdmissionDecision.reject(
                    reason="vad_calibration_required",
                    outcome="rejected",
                )

        # --- Microphone health check ---
        if health is not None:
            if not health.microphone_signal_detected:
                return AudioAdmissionDecision.reject(
                    reason="microphone_no_signal",
                    outcome="rejected",
                )
            if not health.valid_sample_rate or not health.valid_channel_count:
                return AudioAdmissionDecision.reject(
                    reason="microphone_invalid_format",
                    outcome="rejected",
                )
            if (
                health.microphone_clipping_detected
                or health.microphone_low_level_detected
            ):
                # Degraded — warn but do not block (unless health check is required
                # and the operator has not accepted degraded fallback).
                if self._delivery_policy.allow_degraded_fallback:
                    pass
                else:
                    return AudioAdmissionDecision.reject(
                        reason="audio_health_check_failed",
                        outcome="rejected",
                    )

        return AudioAdmissionDecision.accept(outcome="enqueued")

    def evaluate_calibration_audio_admission(
        self,
        *,
        calibration_context_available: bool,
        health: Optional[AudioHealthState] = None,
    ) -> AudioAdmissionDecision:
        """Determine whether calibration audio should be accepted."""
        if not calibration_context_available:
            return AudioAdmissionDecision.reject(
                reason="stale_calibration_context",
                outcome="rejected",
            )

        if health is not None:
            if not health.microphone_signal_detected:
                return AudioAdmissionDecision.reject(
                    reason="microphone_no_signal",
                    outcome="rejected",
                )
            if not health.valid_sample_rate or not health.valid_channel_count:
                return AudioAdmissionDecision.reject(
                    reason="microphone_invalid_format",
                    outcome="rejected",
                )

        return AudioAdmissionDecision.accept(outcome="enqueued")

    def health_status(
        self,
        *,
        health_check_enabled: bool,
        health_check_required: bool,
        health: Optional[AudioHealthState] = None,
    ) -> AudioHealthStatus:
        """Return a provider-independent audio health status string."""
        if not health_check_enabled:
            if self._capabilities.supports_optional_audio_health_check:
                return AudioHealthStatus.SKIPPED
            return AudioHealthStatus.NOT_REQUIRED

        if health is None:
            return AudioHealthStatus.SKIPPED

        if not health.microphone_signal_detected:
            return AudioHealthStatus.FAILED

        if not health.valid_sample_rate or not health.valid_channel_count:
            return AudioHealthStatus.FAILED

        if (
            health.microphone_clipping_detected
            or health.microphone_low_level_detected
            or (health.noise_floor_dbfs is not None and health.noise_floor_dbfs > -20.0)
        ):
            return AudioHealthStatus.DEGRADED

        return AudioHealthStatus.READY
