"""Unit tests for the provider-aware calibration policy.

Covers plan §3.6, §3.8, §6.14, and §9.6:
- Deepgram continuous mode accepts audio without calibration context.
- Deepgram continuous mode does not emit runtime_off_no_calibration_context.
- Local batch mode preserves existing rejection behavior.
- VAD calibration requirements are capability-driven.
- Microphone health checks use precise rejection reasons.
- Degraded mode permits Deepgram operation when configured.
"""
from __future__ import annotations

import pytest

from tournament_platform.app.services.asr_backends.calibration_policy import (
    ASRCapabilities,
    AudioDeliveryPolicy,
    AudioAdmissionDecision,
    AudioHealthStatus,
    AudioHealthState,
    CalibrationPolicy,
    deepgram_continuous_policy,
    deepgram_gated_policy,
    local_batch_policy,
)


class TestPresets:
    def test_local_batch_not_streaming(self):
        p = local_batch_policy()
        assert p.is_streaming is False
        assert p.requires_vad_calibration is True

    def test_deepgram_continuous_is_streaming(self):
        p = deepgram_continuous_policy()
        assert p.is_streaming is True
        assert p.requires_vad_calibration is False
        assert p.capabilities.requires_speaker_calibration is False

    def test_deepgram_gated_requires_vad(self):
        p = deepgram_gated_policy()
        assert p.is_streaming is True
        assert p.requires_vad_calibration is True
        assert p.capabilities.supports_local_vad is True


class TestContinuousModeAcceptsWithoutCalibration:
    """Deepgram continuous streaming must accept audio without calibration context."""

    def test_accepts_without_vad_calibration(self):
        p = deepgram_continuous_policy()
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
        )
        assert result.accepted is True
        assert result.rejection_reason is None

    def test_accepts_without_calibration_no_health(self):
        p = deepgram_continuous_policy()
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
            health=None,
        )
        assert result.accepted is True


class TestDisabledModeReasons:
    """Disabled-mode rejection reason must be provider-aware, not global."""

    def test_deepgram_disabled_uses_runtime_voice_disabled(self):
        p = deepgram_continuous_policy()
        result = p.evaluate_disabled_mode()
        assert result.accepted is False
        assert result.rejection_reason == "runtime_voice_disabled"
        assert result.rejection_reason != "runtime_off_no_calibration_context"

    def test_local_batch_disabled_preserves_legacy_reason(self):
        p = local_batch_policy()
        result = p.evaluate_disabled_mode()
        assert result.accepted is False
        assert result.rejection_reason == "runtime_off_no_calibration_context"


class TestVadCalibrationRequirement:
    """VAD calibration requirement is driven by capabilities, not provider name."""

    def test_local_batch_rejects_without_vad_calibration(self):
        p = local_batch_policy()
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
        )
        assert result.accepted is False
        assert result.rejection_reason == "vad_calibration_required"

    def test_local_batch_accepts_with_vad_calibration(self):
        p = local_batch_policy()
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=True,
        )
        assert result.accepted is True

    def test_gated_mode_rejects_without_vad_no_fallback(self):
        caps = ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=True,
            supports_optional_audio_health_check=True,
        )
        policy = CalibrationPolicy(
            capabilities=caps,
            delivery_policy=AudioDeliveryPolicy(
                mode="vad_gated",
                require_vad_calibration=True,
                allow_degraded_fallback=False,
            ),
        )
        result = policy.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
        )
        assert result.accepted is False
        assert result.rejection_reason == "vad_calibration_required"

    def test_gated_mode_allows_degraded_fallback(self):
        caps = ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=True,
            supports_optional_audio_health_check=True,
        )
        policy = CalibrationPolicy(
            capabilities=caps,
            delivery_policy=AudioDeliveryPolicy(
                mode="vad_gated",
                require_vad_calibration=True,
                allow_degraded_fallback=True,
            ),
        )
        result = policy.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
        )
        assert result.accepted is True


class TestMicrophoneHealthChecks:
    """Microphone health checks use precise rejection reasons."""

    def test_no_signal_rejected(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=False,
            valid_sample_rate=True,
            valid_channel_count=True,
        )
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
            health=health,
        )
        assert result.accepted is False
        assert result.rejection_reason == "microphone_no_signal"

    def test_invalid_format_rejected(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=False,
            valid_channel_count=True,
        )
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
            health=health,
        )
        assert result.accepted is False
        assert result.rejection_reason == "microphone_invalid_format"

    def test_clipping_degraded_with_fallback(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=True,
            valid_channel_count=True,
            microphone_clipping_detected=True,
        )
        result = p.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
            health=health,
        )
        assert result.accepted is True

    def test_clipping_rejected_without_fallback(self):
        caps = ASRCapabilities(
            supports_streaming=True,
            requires_speaker_calibration=False,
            supports_local_vad=False,
            supports_optional_audio_health_check=True,
        )
        policy = CalibrationPolicy(
            capabilities=caps,
            delivery_policy=AudioDeliveryPolicy(
                mode="continuous",
                require_vad_calibration=False,
                allow_degraded_fallback=False,
            ),
        )
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=True,
            valid_channel_count=True,
            microphone_clipping_detected=True,
        )
        result = policy.evaluate_live_audio_admission(
            session_id="sess-1",
            vad_calibration_available=False,
            health=health,
        )
        assert result.accepted is False
        assert result.rejection_reason == "audio_health_check_failed"


class TestMissingSession:
    def test_no_session_id_rejected(self):
        p = deepgram_continuous_policy()
        result = p.evaluate_live_audio_admission(
            session_id=None,
            vad_calibration_available=False,
        )
        assert result.accepted is False
        assert result.rejection_reason == "missing_continuous_session"


class TestHealthStatus:
    def test_not_required_when_check_disabled_and_not_supported(self):
        caps = ASRCapabilities(supports_optional_audio_health_check=False)
        policy = CalibrationPolicy(
            capabilities=caps,
            delivery_policy=AudioDeliveryPolicy(mode="continuous"),
        )
        status = policy.health_status(
            health_check_enabled=False,
            health_check_required=False,
            health=None,
        )
        assert status == AudioHealthStatus.NOT_REQUIRED

    def test_skipped_when_check_disabled_but_supported(self):
        p = deepgram_continuous_policy()
        status = p.health_status(
            health_check_enabled=False,
            health_check_required=False,
            health=None,
        )
        assert status == AudioHealthStatus.SKIPPED

    def test_ready_when_all_checks_pass(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=True,
            valid_channel_count=True,
        )
        status = p.health_status(
            health_check_enabled=True,
            health_check_required=False,
            health=health,
        )
        assert status == AudioHealthStatus.READY

    def test_failed_when_no_signal(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=False,
            valid_sample_rate=True,
            valid_channel_count=True,
        )
        status = p.health_status(
            health_check_enabled=True,
            health_check_required=True,
            health=health,
        )
        assert status == AudioHealthStatus.FAILED

    def test_degraded_when_clipping(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=True,
            valid_channel_count=True,
            microphone_clipping_detected=True,
        )
        status = p.health_status(
            health_check_enabled=True,
            health_check_required=False,
            health=health,
        )
        assert status == AudioHealthStatus.DEGRADED

    def test_failed_when_invalid_format(self):
        p = deepgram_continuous_policy()
        health = AudioHealthState(
            microphone_signal_detected=True,
            valid_sample_rate=False,
            valid_channel_count=True,
        )
        status = p.health_status(
            health_check_enabled=True,
            health_check_required=True,
            health=health,
        )
        assert status == AudioHealthStatus.FAILED
