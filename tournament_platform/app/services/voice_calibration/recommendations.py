"""
Voice Calibration — Deterministic recommendation engine.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

import math
from typing import Tuple

from tournament_platform.app.services.voice_calibration.models import (
    AcousticRecommendation,
    AcousticRecommendationCode,
    AliasConfirmationCandidate,
    AsrExperimentConfig,
    CalibrationProfileIdentity,
    CommandPhraseCandidate,
    LiveVoiceProfileRecommendation,
    NegativeSpeechSnapshot,
    NoiseGateRecommendation,
    NoiseGateRecommendationPolicy,
    RecommendationEvidence,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
    TtsEchoSnapshot,
)


# --------------------------------------------------------------------------- #
# Silence Baseline Rules                                                     #
# --------------------------------------------------------------------------- #
def generate_silence_recommendations(
    metrics: SilenceBaselineMetrics,
) -> Tuple[AcousticRecommendation, ...]:
    capture = metrics.capture
    recommendations: list[AcousticRecommendation] = []

    if capture.frame_count == 0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.NO_AUDIO,
            "error",
            "No audio was received during the silence measurement.",
        ))
        return tuple(recommendations)

    if not capture.complete:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.INCOMPLETE_CAPTURE,
            "warning",
            f"Capture is incomplete ({capture.captured_duration_ms:.0f} ms of {capture.target_duration_ms:.0f} ms target).",
        ))

    if metrics.median_dbfs is not None and metrics.median_dbfs > -30.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.BACKGROUND_NOISE_HIGH,
            "warning",
            "Background noise floor is too high. Reduce nearby noise sources.",
            evidence=(_evidence("median_dbfs", metrics.median_dbfs, "dBFS"),),
        ))

    if metrics.median_dbfs is not None and metrics.median_dbfs < -60.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.TOO_QUIET,
            "info",
            "Environment is very quiet. Move closer to the microphone or increase gain.",
            evidence=(_evidence("median_dbfs", metrics.median_dbfs, "dBFS"),),
        ))

    if metrics.contaminated_by_speech:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.SPEECH_STARTED_TOO_EARLY,
            "error",
            "Speech was detected during the silence baseline. Please remain silent and retry.",
            evidence=(
                _evidence("speech_frame_count", metrics.speech_frame_count, "frames"),
                _evidence("speech_duration_ms", metrics.speech_duration_ms, "ms"),
            ),
        ))

    if capture.near_clipping_count > 0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.CLIPPING,
            "warning",
            "Near-clipping samples detected. Reduce microphone gain.",
            evidence=(_evidence("near_clipping_count", capture.near_clipping_count, "samples"),),
        ))

    if not recommendations:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.READY,
            "info",
            "Silence baseline captured successfully.",
        ))

    return tuple(recommendations)


# --------------------------------------------------------------------------- #
# Normal Speech Rules                                                         #
# --------------------------------------------------------------------------- #
def generate_speech_recommendations(
    metrics: SpeechLevelMetrics,
    silence_baseline: SilenceBaselineMetrics | None = None,
) -> Tuple[AcousticRecommendation, ...]:
    capture = metrics.capture
    recommendations: list[AcousticRecommendation] = []

    if capture.speech_frame_count == 0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.NO_SPEECH_DETECTED,
            "error",
            "No speech was detected during the measurement. Speak more clearly or check your microphone.",
        ))
        return tuple(recommendations)

    if metrics.speech_rms_dbfs is not None and metrics.speech_rms_dbfs < -40.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.SPEECH_TOO_QUIET,
            "warning",
            "Speech level is too quiet. Move closer to the microphone.",
            evidence=(_evidence("speech_rms_dbfs", metrics.speech_rms_dbfs, "dBFS"),),
        ))

    if metrics.speech_rms_dbfs is not None and metrics.speech_rms_dbfs > -3.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.SPEECH_TOO_LOUD,
            "warning",
            "Speech level is too loud. Reduce speaker or microphone gain.",
            evidence=(_evidence("speech_rms_dbfs", metrics.speech_rms_dbfs, "dBFS"),),
        ))

    if capture.near_clipping_count > 0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.CLIPPING,
            "warning",
            "Near-clipping samples detected. Reduce microphone gain.",
            evidence=(_evidence("near_clipping_count", capture.near_clipping_count, "samples"),),
        ))

    if metrics.speech_start_offset_ms is not None and metrics.speech_start_offset_ms < 50.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.SPEECH_STARTED_TOO_EARLY,
            "info",
            "Speech started before the measurement began. Begin speaking after the prompt appears.",
            evidence=(_evidence("speech_start_offset_ms", metrics.speech_start_offset_ms, "ms"),),
        ))

    if metrics.trailing_silence_ms is not None and metrics.trailing_silence_ms > 2000.0:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.TRAILING_SILENCE_HIGH,
            "info",
            "Long trailing silence detected. Keep the microphone position stable.",
            evidence=(_evidence("trailing_silence_ms", metrics.trailing_silence_ms, "ms"),),
        ))

    if (
        silence_baseline is not None
        and metrics.speech_to_background_difference_db is not None
        and metrics.speech_to_background_difference_db < 6.0
    ):
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.LOW_SPEECH_TO_BACKGROUND_DIFFERENCE,
            "warning",
            "Speech-to-background difference is low. Move closer to the microphone.",
            evidence=(
                _evidence("speech_to_background_difference_db", metrics.speech_to_background_difference_db, "dB"),
            ),
        ))

    if not recommendations:
        recommendations.append(_ready_or_error(
            AcousticRecommendationCode.READY,
            "info",
            "Speech level measurement captured successfully.",
        ))

    return tuple(recommendations)


# --------------------------------------------------------------------------- #
# Noise Gate Recommendation                                                 #
# --------------------------------------------------------------------------- #
def generate_noise_gate_recommendation(
    silence: SilenceBaselineMetrics | None,
    speech: SpeechLevelMetrics | None,
    policy: NoiseGateRecommendationPolicy | None = None,
) -> NoiseGateRecommendation:
    """Compute a noise-gate recommendation from silence and speech metrics.

    Uses the conservative formula from the plan:
    - background_dbfs = silence_p95_dbfs
    - minimum_gate_dbfs = background_dbfs + background_margin_db
    - maximum_gate_dbfs = speech_rms_dbfs - speech_headroom_db
    - Safe range exists when minimum_gate_dbfs <= maximum_gate_dbfs
      and speech-to-background separation >= minimum_safe_separation_db
    - recommended_threshold_dbfs = minimum_gate_dbfs (conservative)
    - recommended_threshold_rms = 10 ** (recommended_threshold_dbfs / 20)
    - Clamped to [0.0, 1.0]

    Returns UNAVAILABLE when the safe range is empty or inputs are invalid.
    """
    policy = policy or NoiseGateRecommendationPolicy()
    evidence: list[RecommendationEvidence] = []

    if silence is None or speech is None:
        return NoiseGateRecommendation(
            enabled=False,
            threshold_rms=None,
            threshold_dbfs=None,
            confidence=0.0,
            evidence=tuple(evidence),
        )

    if silence.median_dbfs is None or speech.speech_rms_dbfs is None:
        return NoiseGateRecommendation(
            enabled=False,
            threshold_rms=None,
            threshold_dbfs=None,
            confidence=0.0,
            evidence=tuple(evidence),
        )

    if math.isnan(silence.median_dbfs) or math.isnan(speech.speech_rms_dbfs):
        return NoiseGateRecommendation(
            enabled=False,
            threshold_rms=None,
            threshold_dbfs=None,
            confidence=0.0,
            evidence=tuple(evidence),
        )

    background_dbfs = silence.p95_dbfs if silence.p95_dbfs is not None else silence.median_dbfs
    evidence.append(_evidence("background_dbfs", round(background_dbfs, 2), "dBFS"))

    minimum_gate_dbfs = background_dbfs + policy.background_margin_db
    evidence.append(_evidence("minimum_gate_dbfs", round(minimum_gate_dbfs, 2), "dBFS"))

    maximum_gate_dbfs = speech.speech_rms_dbfs - policy.speech_headroom_db
    evidence.append(_evidence("maximum_gate_dbfs", round(maximum_gate_dbfs, 2), "dBFS"))

    separation_db = speech.speech_to_background_difference_db
    evidence.append(_evidence("speech_to_background_difference_db", round(separation_db, 2) if separation_db is not None else "unknown", "dB"))

    if separation_db is None or separation_db < policy.minimum_safe_separation_db:
        return NoiseGateRecommendation(
            enabled=False,
            threshold_rms=None,
            threshold_dbfs=None,
            confidence=0.0,
            evidence=tuple(evidence),
        )

    if minimum_gate_dbfs > maximum_gate_dbfs:
        return NoiseGateRecommendation(
            enabled=False,
            threshold_rms=None,
            threshold_dbfs=None,
            confidence=0.0,
            evidence=tuple(evidence),
        )

    recommended_threshold_dbfs = minimum_gate_dbfs
    recommended_threshold_rms = 10 ** (recommended_threshold_dbfs / 20)
    recommended_threshold_rms = max(0.0, min(1.0, recommended_threshold_rms))

    evidence.append(_evidence("recommended_threshold_dbfs", round(recommended_threshold_dbfs, 2), "dBFS"))
    evidence.append(_evidence("recommended_threshold_rms", round(recommended_threshold_rms, 6), "RMS"))

    return NoiseGateRecommendation(
        enabled=True,
        threshold_rms=recommended_threshold_rms,
        threshold_dbfs=recommended_threshold_dbfs,
        confidence=1.0,
        evidence=tuple(evidence),
    )


# --------------------------------------------------------------------------- #
# Strict Mode Recommendation                                                #
# --------------------------------------------------------------------------- #
def generate_strict_mode_recommendation(
    negative_speech: NegativeSpeechSnapshot,
    tts_echo: TtsEchoSnapshot,
) -> bool:
    """Determine whether strict mode should be enabled based on safety results.

    Strict mode is forced ON when:
    - Negative speech safety has not been tested (missing evidence), OR
    - Negative speech has false candidates, OR
    - TTS echo safety has not been tested (missing evidence), OR
    - TTS echo has false candidates.
    """
    if negative_speech.trials == 0:
        return True
    if negative_speech.false_live_acceptable_candidates > 0:
        return True
    if tts_echo.playback_tests == 0:
        return True
    if tts_echo.live_acceptable_command_candidates > 0:
        return True
    return False


# --------------------------------------------------------------------------- #
# Live Voice Profile Recommendation                                         #
# --------------------------------------------------------------------------- #
def generate_live_voice_profile_recommendation(
    calibration_session_id: str,
    calibration_profile_id: str | None,
    identity: "CalibrationProfileIdentity",
    silence: SilenceBaselineMetrics | None,
    speech: SpeechLevelMetrics | None,
    negative_speech: NegativeSpeechSnapshot,
    tts_echo: TtsEchoSnapshot,
    confirmed_aliases: Tuple[AliasConfirmationCandidate, ...],
    preferred_phrases: Tuple[CommandPhraseCandidate, ...],
    selected_asr_config: AsrExperimentConfig | None,
    policy: NoiseGateRecommendationPolicy | None = None,
) -> "LiveVoiceProfileRecommendation":
    """Compose a complete live voice profile recommendation from calibration data.

    The recommendation status is determined by the most restrictive section:
    - FAIL or INVALID_DATA → BLOCKED
    - NOT_TESTED or INCOMPLETE → UNAVAILABLE
    - WARNING → WARNING
    - PASS → AVAILABLE
    """
    from tournament_platform.app.services.voice_calibration.models import (
        LiveVoiceProfileRecommendation,
        RecommendationStatus,
    )

    policy = policy or NoiseGateRecommendationPolicy()
    noise_rec = generate_noise_gate_recommendation(silence, speech, policy)
    strict_mode = generate_strict_mode_recommendation(negative_speech, tts_echo)

    applied_sections: list[str] = []
    blocked_sections: list[str] = []
    reason_codes: list[str] = []
    evidence: list[RecommendationEvidence] = []

    if noise_rec.enabled:
        applied_sections.append("noise_gate")
        if noise_rec.threshold_rms is not None:
            evidence.append(_evidence("noise_threshold_rms", noise_rec.threshold_rms, "RMS"))
        if noise_rec.threshold_dbfs is not None:
            evidence.append(_evidence("noise_threshold_dbfs", noise_rec.threshold_dbfs, "dBFS"))
    else:
        blocked_sections.append("noise_gate")
        reason_codes.append("NO_SAFE_THRESHOLD_RANGE")

    if strict_mode:
        applied_sections.append("strict_mode")
        evidence.append(_evidence("strict_mode", "forced_on", "bool"))

    if confirmed_aliases:
        applied_sections.append("confirmed_aliases")
        evidence.append(_evidence("confirmed_aliases_count", len(confirmed_aliases), "count"))

    if preferred_phrases:
        applied_sections.append("preferred_phrases")
        evidence.append(_evidence("preferred_phrases_count", len(preferred_phrases), "count"))

    if selected_asr_config is not None:
        applied_sections.append("asr_config")
        evidence.append(_evidence("asr_config_id", selected_asr_config.config_id, "str"))

    # Determine overall recommendation status
    has_failures = (
        negative_speech.false_live_acceptable_candidates > 0
        or tts_echo.live_acceptable_command_candidates > 0
    )
    has_missing_evidence = (
        negative_speech.trials == 0
        or tts_echo.playback_tests == 0
    )
    has_warnings = not noise_rec.enabled and noise_rec.threshold_rms is None

    if has_failures:
        status = RecommendationStatus.UNAVAILABLE
    elif has_missing_evidence:
        status = RecommendationStatus.UNAVAILABLE
    elif has_warnings:
        status = RecommendationStatus.WARNING
    else:
        status = RecommendationStatus.AVAILABLE

    return LiveVoiceProfileRecommendation(
        calibration_session_id=calibration_session_id,
        calibration_profile_id=calibration_profile_id,
        identity=identity,
        status=status,
        noise_gate_enabled=noise_rec.enabled,
        noise_threshold_rms=noise_rec.threshold_rms,
        noise_threshold_dbfs=noise_rec.threshold_dbfs,
        strict_mode_enabled=strict_mode,
        selected_asr_config=selected_asr_config,
        preferred_phrases=preferred_phrases,
        confirmed_aliases=confirmed_aliases,
        confidence_policy="conservative",
        profile_version="1.0.0",
        applied_sections=tuple(applied_sections),
        blocked_sections=tuple(blocked_sections),
        reason_codes=tuple(reason_codes),
        evidence=tuple(evidence),
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _ready_or_error(
    code: AcousticRecommendationCode,
    severity: str,
    message: str,
    evidence: Tuple[RecommendationEvidence, ...] = (),
) -> AcousticRecommendation:
    return AcousticRecommendation(
        code=code.value,
        severity=severity,
        message=message,
        evidence=evidence,
    )


def _evidence(name: str, value: float | int | str, unit: str | None = None) -> RecommendationEvidence:
    return RecommendationEvidence(name=name, value=value, unit=unit)
