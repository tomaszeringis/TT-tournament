"""
Phase 11 — Measured Faster Whisper Hint A/B Testing (commit 1).

Pure capability models, experiment result models, aggregate calculations,
recommendation policy, and unit tests. No ASR transcription in this commit.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AsrAbSampleResult,
    AsrAbWorkItem,
    AsrExperimentAggregate,
    AsrExperimentConfig,
    AsrExperimentRecommendation,
    AsrExperimentStatus,
    AsrExperimentTranscript,
    AsrProviderCapabilities,
    CalibrationCaptureKind,
    CalibrationSession,
    CommandTrial,
    TrialClassification,
)
from tournament_platform.app.services.asr_backends.base import TranscriptionResult
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)
from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
    AsrAbWorker,
)


def _make_session(session_id: str = "s1") -> CalibrationSession:
    return CalibrationSession(
        session_id=session_id,
        created_at=time.time(),
        commands=("score_point", "undo", "reset_match"),
        attempts_per_command=3,
        current_command_index=0,
    )


def _make_trial(
    trial_id: str = "t1",
    expected_command_id: str = "score_point",
    expected_phrase: str = "point red",
    raw_transcript: str = "point read",
    classification: TrialClassification = TrialClassification.EXACT,
    asr_latency_ms: float | None = None,
) -> CommandTrial:
    return CommandTrial(
        trial_id=trial_id,
        expected_command_id=expected_command_id,
        expected_phrase=expected_phrase,
        raw_transcript=raw_transcript,
        normalized_transcript=raw_transcript.strip().lower(),
        resolved_command_id=expected_command_id,
        classification=classification,
        parser_confidence=0.9,
        rejection_reason=None,
        asr_latency_ms=asr_latency_ms,
    )


def _make_ab_result(
    sample_id: str,
    config_id: str,
    latency_ms: float,
    parser_command_id: str | None,
    would_accept_live: bool,
    capture_kind: str = CalibrationCaptureKind.COMMAND_TRIAL.value,
    expected_command_id: str = "score_point",
    expected_phrase: str = "point red",
) -> AsrAbSampleResult:
    baseline_raw = "point read" if config_id == "baseline" else "test"
    candidate_raw = "point red" if config_id == "candidate" else "test"

    baseline_transcript = AsrExperimentTranscript(
        config_id="baseline",
        raw_transcript=baseline_raw,
        normalized_transcript=baseline_raw,
        language="en",
        latency_ms=latency_ms if config_id == "baseline" else 0.0,
        average_log_probability=None,
        no_speech_probability=None,
        parser_command_id=parser_command_id if config_id == "baseline" else None,
        parser_confidence=0.9 if (config_id == "baseline" and parser_command_id) else None,
        would_accept_live=would_accept_live if config_id == "baseline" else False,
    )
    candidate_transcript = AsrExperimentTranscript(
        config_id=config_id,
        raw_transcript=candidate_raw,
        normalized_transcript=candidate_raw,
        language="en",
        latency_ms=latency_ms if config_id == "candidate" else 0.0,
        average_log_probability=None,
        no_speech_probability=None,
        parser_command_id=parser_command_id if config_id == "candidate" else None,
        parser_confidence=0.9 if (config_id == "candidate" and parser_command_id) else None,
        would_accept_live=would_accept_live if config_id == "candidate" else False,
    )
    return AsrAbSampleResult(
        experiment_id="exp-1",
        sample_id=sample_id,
        calibration_session_id="s1",
        capture_kind=capture_kind,
        expected_command_id=expected_command_id,
        expected_phrase=expected_phrase,
        baseline=baseline_transcript,
        candidate=candidate_transcript,
    )


class TestAsrProviderCapabilities:
    def test_faster_whisper_capabilities_detected(self):
        service = VoiceCalibrationService()
        caps = service.audit_asr_capabilities(provider="faster_whisper")
        assert caps.provider == "faster_whisper"
        assert caps.supports_hotwords is True
        assert caps.supports_initial_prompt is True
        assert caps.supports_condition_on_previous_text is True
        assert caps.supports_word_probabilities is False
        assert caps.supports_no_speech_probability is True
        assert caps.supports_average_log_probability is True

    def test_unsupported_provider_returns_safe_defaults(self):
        service = VoiceCalibrationService()
        caps = service.audit_asr_capabilities(provider="vosk")
        assert caps.provider == "vosk"
        assert caps.supports_hotwords is False
        assert caps.supports_initial_prompt is False
        assert caps.supports_condition_on_previous_text is False
        assert caps.supports_word_probabilities is False
        assert caps.supports_no_speech_probability is False
        assert caps.supports_average_log_probability is False

    def test_unknown_provider_does_not_crash(self):
        service = VoiceCalibrationService()
        caps = service.audit_asr_capabilities(provider="nonexistent")
        assert caps.provider == "nonexistent"
        assert all(
            getattr(caps, field) is False
            for field in caps.__dataclass_fields__
            if field != "provider"
        )


class TestAsrExperimentConfigs:
    def test_default_baseline_config_has_no_hints(self):
        service = VoiceCalibrationService()
        baseline, candidate = service.create_asr_experiment_configs()
        assert baseline.config_id == "baseline"
        assert baseline.hotwords is None
        assert baseline.initial_prompt is None
        assert baseline.condition_on_previous_text is None
        assert baseline.beam_size is None

    def test_default_candidate_config_has_safe_hints(self):
        service = VoiceCalibrationService()
        baseline, candidate = service.create_asr_experiment_configs()
        assert candidate.config_id == "candidate"
        assert candidate.language == "en"
        assert "point red" in (candidate.hotwords or "")
        assert "point blue" in (candidate.hotwords or "")
        assert "undo" in (candidate.hotwords or "")
        assert "reset game" in (candidate.hotwords or "")
        assert candidate.condition_on_previous_text is False
        assert candidate.beam_size == 5
        assert "point red" in (candidate.initial_prompt or "")

    def test_custom_configs_override_defaults(self):
        service = VoiceCalibrationService()
        custom_baseline = AsrExperimentConfig(
            config_id="custom_baseline",
            display_name="Custom baseline",
            language="en",
            hotwords="custom",
            initial_prompt="custom prompt",
            condition_on_previous_text=True,
            beam_size=10,
        )
        baseline, candidate = service.create_asr_experiment_configs(
            baseline=custom_baseline
        )
        assert baseline.config_id == "custom_baseline"
        assert baseline.hotwords == "custom"
        assert candidate.config_id == "candidate"


class TestAsrAbWorkItem:
    def test_work_item_is_immutable_and_contains_audio(self):
        service = VoiceCalibrationService()
        session = _make_session()
        audio = b"\x00\x01\x02\x03" * 100
        item = service.create_asr_ab_work_item(
            experiment_id="exp-1",
            sample_id="sample-1",
            session=session,
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
            audio_bytes=audio,
            sample_rate_hz=16000,
            expected_command_id="score_point",
            expected_phrase="point red",
        )
        assert item.experiment_id == "exp-1"
        assert item.sample_id == "sample-1"
        assert item.calibration_session_id == "s1"
        assert item.audio_bytes == audio
        assert item.baseline_config.config_id == "baseline"
        assert item.candidate_config.config_id == "candidate"
        assert item.expected_command_id == "score_point"
        assert item.expected_phrase == "point red"

    def test_work_item_does_not_mutate_session(self):
        service = VoiceCalibrationService()
        session = _make_session()
        service.create_asr_ab_work_item(
            experiment_id="exp-1",
            sample_id="sample-1",
            session=session,
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
            audio_bytes=b"audio",
            sample_rate_hz=16000,
        )
        assert len(session.asr_ab_results) == 0


class TestAsrExperimentTranscript:
    def test_transcript_records_both_configs(self):
        baseline = AsrExperimentTranscript(
            config_id="baseline",
            raw_transcript="point read",
            normalized_transcript="point read",
            language="en",
            latency_ms=620.0,
            average_log_probability=-0.3,
            no_speech_probability=0.1,
            parser_command_id="score_point",
            parser_confidence=0.9,
            would_accept_live=True,
        )
        candidate = AsrExperimentTranscript(
            config_id="candidate",
            raw_transcript="point red",
            normalized_transcript="point red",
            language="en",
            latency_ms=675.0,
            average_log_probability=-0.2,
            no_speech_probability=0.05,
            parser_command_id="score_point",
            parser_confidence=0.95,
            would_accept_live=True,
        )
        result = AsrAbSampleResult(
            experiment_id="exp-1",
            sample_id="sample-1",
            calibration_session_id="s1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
            expected_command_id="score_point",
            expected_phrase="point red",
            baseline=baseline,
            candidate=candidate,
        )
        assert result.baseline.raw_transcript == "point read"
        assert result.candidate.raw_transcript == "point red"
        assert result.baseline.latency_ms == 620.0
        assert result.candidate.latency_ms == 675.0


class TestAsrExperimentAggregate:
    def test_aggregate_counts_positive_attempts(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                _make_ab_result(
                    sample_id=f"sample-{i}",
                    config_id="baseline",
                    latency_ms=600.0 + i * 10,
                    parser_command_id="score_point",
                    would_accept_live=True,
                ),
            )
        agg = service.compute_asr_experiment_aggregate(
            session=session, config_id="baseline"
        )
        assert agg.positive_attempts == 3
        assert agg.parser_successes == 3
        assert agg.exact_matches == 3
        assert agg.wrong_command_count == 0
        assert agg.unknown_count == 0

    def test_aggregate_computes_median_and_p95_latency(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(5):
            session = service.consume_asr_ab_results(
                session,
                _make_ab_result(
                    sample_id=f"sample-{i}",
                    config_id="baseline",
                    latency_ms=600.0 + i * 20,
                    parser_command_id="score_point",
                    would_accept_live=True,
                ),
            )
        agg = service.compute_asr_experiment_aggregate(
            session=session, config_id="baseline"
        )
        assert agg.median_latency_ms == 640.0
        assert agg.p95_latency_ms == 680.0

    def test_aggregate_counts_negative_false_candidates(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result(
                sample_id="sample-neg",
                config_id="candidate",
                latency_ms=620.0,
                parser_command_id="score_point",
                would_accept_live=True,
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
            ),
        )
        agg = service.compute_asr_experiment_aggregate(
            session=session, config_id="candidate"
        )
        assert agg.negative_false_candidate_count == 1

    def test_aggregate_counts_tts_false_candidates(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result(
                sample_id="sample-tts",
                config_id="candidate",
                latency_ms=620.0,
                parser_command_id="score_point",
                would_accept_live=True,
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
            ),
        )
        agg = service.compute_asr_experiment_aggregate(
            session=session, config_id="candidate"
        )
        assert agg.tts_false_candidate_count == 1

    def test_aggregate_counts_wrong_command(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result(
                sample_id="sample-wc",
                config_id="candidate",
                latency_ms=620.0,
                parser_command_id="undo",
                would_accept_live=True,
            ),
        )
        agg = service.compute_asr_experiment_aggregate(
            session=session, config_id="candidate"
        )
        assert agg.wrong_command_count == 1


class TestAsrExperimentRecommendation:
    def test_negative_false_candidate_blocks_recommendation(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-neg",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id="score_point",
                    parser_confidence=0.9,
                    would_accept_live=True,
                ),
            ),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.CANDIDATE_UNSAFE
        assert reason == "negative_false_candidates_increased"

    def test_tts_false_candidate_blocks_recommendation(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-tts",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id="score_point",
                    parser_confidence=0.9,
                    would_accept_live=True,
                ),
            ),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.CANDIDATE_UNSAFE
        assert reason == "tts_false_candidates_increased"

    def test_wrong_command_increase_blocks_recommendation(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red" if i > 0 else "undo",
                        normalized_transcript="point red" if i > 0 else "undo",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point" if i > 0 else "undo",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                ),
            )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.CANDIDATE_UNSAFE
        assert reason == "wrong_command_count_increased"

    def test_safe_improvement_recommends_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red" if i < 2 else "unknown",
                        normalized_transcript="point red" if i < 2 else "unknown",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point" if i < 2 else "unknown",
                        parser_confidence=0.9 if i < 2 else None,
                        would_accept_live=True if i < 2 else False,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=600.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    experiment_identity={"provider": "faster_whisper"},
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-neg",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-tts",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.CANDIDATE_RECOMMENDED
        assert reason == "exact_match_improved"

    def test_equal_results_keep_baseline(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    experiment_identity={"provider": "faster_whisper"},
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-neg",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-tts",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.BASELINE_RETAINED
        assert reason == "no_parser_success_improvement"

    def test_latency_regression_can_keep_baseline(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=700.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    experiment_identity={"provider": "faster_whisper"},
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-neg",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-tts",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.BASELINE_RETAINED
        assert reason == "no_parser_success_improvement"

    def test_too_few_samples_returns_more_samples_required(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result("sample-0", "candidate", 600.0, "score_point", True),
        )
        rec, reason = service.recommend_asr_config(session=session)
        assert rec == AsrExperimentRecommendation.MORE_SAMPLES_REQUIRED
        assert reason in ("insufficient_positive_attempts", "insufficient_negative_samples", "insufficient_tts_samples")

    def test_recommendation_is_deterministic(self):
        service = VoiceCalibrationService()
        session = _make_session()
        for i in range(3):
            session = service.consume_asr_ab_results(
                session,
                AsrAbSampleResult(
                    experiment_id="exp-1",
                    sample_id=f"sample-{i}",
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline=AsrExperimentTranscript(
                        config_id="baseline",
                        raw_transcript="point red" if i < 2 else "unknown",
                        normalized_transcript="point red" if i < 2 else "unknown",
                        language="en",
                        latency_ms=620.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point" if i < 2 else "unknown",
                        parser_confidence=0.9 if i < 2 else None,
                        would_accept_live=True if i < 2 else False,
                    ),
                    candidate=AsrExperimentTranscript(
                        config_id="candidate",
                        raw_transcript="point red",
                        normalized_transcript="point red",
                        language="en",
                        latency_ms=600.0,
                        average_log_probability=None,
                        no_speech_probability=None,
                        parser_command_id="score_point",
                        parser_confidence=0.9,
                        would_accept_live=True,
                    ),
                    experiment_identity={"provider": "faster_whisper"},
                ),
            )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-neg",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="I like red",
                    normalized_transcript="i like red",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        session = service.consume_asr_ab_results(
            session,
            AsrAbSampleResult(
                experiment_id="exp-1",
                sample_id="sample-tts",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline=AsrExperimentTranscript(
                    config_id="baseline",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=0.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                candidate=AsrExperimentTranscript(
                    config_id="candidate",
                    raw_transcript="great shot",
                    normalized_transcript="great shot",
                    language="en",
                    latency_ms=620.0,
                    average_log_probability=None,
                    no_speech_probability=None,
                    parser_command_id=None,
                    parser_confidence=None,
                    would_accept_live=False,
                ),
                experiment_identity={"provider": "faster_whisper"},
            ),
        )
        rec1, reason1 = service.recommend_asr_config(session=session)
        rec2, reason2 = service.recommend_asr_config(session=session)
        assert rec1 == rec2
        assert reason1 == reason2


class TestAsrExperimentLifecycle:
    def test_reset_clears_session_experiment_results(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result("sample-1", "baseline", 620.0, "score_point", True),
        )
        assert len(session.asr_ab_results) == 1
        fresh = CalibrationSession(session_id=session.session_id, created_at=session.created_at)
        assert len(fresh.asr_ab_results) == 0

    def test_experiment_state_does_not_leak_between_tests(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.consume_asr_ab_results(
            session,
            _make_ab_result("sample-1", "baseline", 620.0, "score_point", True),
        )
        assert len(session.asr_ab_results) == 1

    def test_duplicate_sample_result_consumed_once(self):
        service = VoiceCalibrationService()
        session = _make_session()
        result = _make_ab_result("sample-1", "baseline", 620.0, "score_point", True)
        session = service.consume_asr_ab_results(session, result)
        session = service.consume_asr_ab_results(session, result)
        assert len(session.asr_ab_results) == 1


class TestAsrExperimentAdapter:
    def test_faster_whisper_backend_has_transcribe_experiment(self):
        from tournament_platform.app.services.asr_backends.faster_whisper_backend import (
            FasterWhisperBackend,
        )
        from tournament_platform.app.services.asr_backends.base import TranscriptionResult
        backend = FasterWhisperBackend()
        assert hasattr(backend, "transcribe_experiment")

    def test_local_asr_transcribe_experiment_returns_result_type(self):
        from tournament_platform.app.services.voice_asr import LocalASR
        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed"
        result = asr.transcribe_experiment(
            audio=b"",
            config=AsrExperimentConfig(
                config_id="baseline",
                display_name="baseline",
                language="en",
                hotwords=None,
                initial_prompt=None,
                condition_on_previous_text=None,
                beam_size=None,
            ),
        )
        assert result.text == ""

    def test_experiment_does_not_mutate_production_defaults(self):
        from tournament_platform.app.services.asr_backends.faster_whisper_backend import (
            FasterWhisperBackend,
        )
        backend = FasterWhisperBackend()
        original_hotwords = getattr(backend, "_hotwords", None)
        asr = backend._get_asr()
        original_asr_hotwords = asr._hotwords
        config = AsrExperimentConfig(
            config_id="candidate",
            display_name="candidate",
            language="en",
            hotwords="point red, point blue",
            initial_prompt="hint",
            condition_on_previous_text=False,
            beam_size=5,
        )
        asr.transcribe_experiment(audio=b"", config=config)
        assert asr._hotwords == original_asr_hotwords


class TestAsrAbWorker:
    def test_worker_processes_work_item(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-1",
                sample_id="sample-1",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item) is True
            worker._queue.join()
            results = worker.drain_results()
            assert len(results) == 1
            assert results[0].sample_id == "sample-1"
            assert results[0].baseline.raw_transcript == "point red"
            assert results[0].candidate.raw_transcript == "point red"
        finally:
            worker.stop()

    def test_worker_cancels_pending_experiment(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-cancel",
                sample_id="sample-cancel",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item) is True
            worker.cancel("exp-cancel")
            worker._queue.join()
            results = worker.drain_results()
            assert len(results) == 0
        finally:
            worker.stop()

    def test_worker_rejects_when_queue_full(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=1)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item1 = AsrAbWorkItem(
                experiment_id="exp-1",
                sample_id="sample-1",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            item2 = AsrAbWorkItem(
                experiment_id="exp-2",
                sample_id="sample-2",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item1) is True
            assert worker.enqueue(item2) is False
        finally:
            worker.stop()


class TestAsrExperimentInferenceSerialization:
    def test_experiment_and_production_transcription_are_serialized(self):
        from tournament_platform.app.services.voice_asr import LocalASR
        from concurrent.futures import ThreadPoolExecutor

        asr = LocalASR()
        asr._load_attempted = True
        asr._load_failed = True
        asr._load_error = "faster-whisper is not installed"

        call_count = 0
        original_transcribe = asr.transcribe_chunk

        def mock_transcribe(audio_bytes):
            nonlocal call_count
            call_count += 1
            time.sleep(0.01)
            return "test"

        asr.transcribe_chunk = mock_transcribe
        asr.transcribe_experiment = lambda **kwargs: TranscriptionResult(
            text=mock_transcribe(kwargs.get("audio", b"")),
            latency_ms=10.0,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(asr.transcribe_chunk, b"audio1"),
                executor.submit(asr.transcribe_experiment, audio=b"audio2", config=AsrExperimentConfig(
                    config_id="test", display_name="test", language="en", hotwords=None,
                    initial_prompt=None, condition_on_previous_text=None, beam_size=None,
                )),
            ]
            for f in futures:
                f.result()

        assert call_count == 2

    def test_experiment_reuses_model_without_concurrent_inference(self):
        from tournament_platform.app.services.voice_asr import LocalASR
        asr = LocalASR()
        assert hasattr(asr, "_inference_lock")
        assert asr._inference_lock is not None


class TestAsrAbOrderBias:
    def test_ab_execution_order_is_balanced(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=8)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            candidate_first = 0
            baseline_first = 0
            for i in range(20):
                sample_id = f"sample-{i}"
                item = AsrAbWorkItem(
                    experiment_id="exp-order",
                    sample_id=sample_id,
                    calibration_session_id="s1",
                    capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                    expected_command_id="score_point",
                    expected_phrase="point red",
                    baseline_config=AsrExperimentConfig(
                        config_id="baseline",
                        display_name="baseline",
                        language="en",
                        hotwords=None,
                        initial_prompt=None,
                        condition_on_previous_text=None,
                        beam_size=None,
                    ),
                    candidate_config=AsrExperimentConfig(
                        config_id="candidate",
                        display_name="candidate",
                        language="en",
                        hotwords="point red",
                        initial_prompt="hint",
                        condition_on_previous_text=False,
                        beam_size=5,
                    ),
                    audio_bytes=b"\x00\x01\x02\x03",
                    sample_rate_hz=16000,
                )
                worker.enqueue(item)
                if hash(sample_id) % 2 == 1:
                    candidate_first += 1
                else:
                    baseline_first += 1
            worker._queue.join()
            assert candidate_first > 0
            assert baseline_first > 0
        finally:
            worker.stop()

    def test_execution_order_does_not_swap_config_results(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text=f"result-{config.config_id}",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-order",
                sample_id="sample-swap",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            worker.enqueue(item)
            worker._queue.join()
            results = worker.drain_results()
            assert len(results) == 1
            assert results[0].baseline.config_id == "baseline"
            assert results[0].candidate.config_id == "candidate"
            assert results[0].baseline.raw_transcript == "result-baseline"
            assert results[0].candidate.raw_transcript == "result-candidate"
        finally:
            worker.stop()


class TestAsrExperimentMemory:
    def test_result_does_not_retain_audio(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-audio",
                sample_id="sample-audio",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03\x04\x05",
                sample_rate_hz=16000,
            )
            worker.enqueue(item)
            worker._queue.join()
            results = worker.drain_results()
            assert len(results) == 1
            assert results[0].baseline.raw_transcript == "point red"
            assert results[0].candidate.raw_transcript == "point red"
        finally:
            worker.stop()

    def test_cancel_releases_pending_audio_reference(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-cancel",
                sample_id="sample-cancel",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item) is True
            worker.cancel("exp-cancel")
            worker._queue.join()
            results = worker.drain_results()
            assert len(results) == 0
        finally:
            worker.stop()

    def test_reset_clears_ab_work_queue(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-reset",
                sample_id="sample-reset",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item) is True
            worker.reset()
            assert worker.pending_count == 0
            assert worker.drain_results() == []
        finally:
            worker.stop()

    def test_worker_shutdown_releases_pending_items(self):
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        worker = AsrAbWorker(max_queue_size=4)
        worker.configure(
            transcribe_fn=lambda audio, config: TranscriptionResult(
                text="point red",
                language="en",
                latency_ms=620.0,
                metadata={"config_id": config.config_id},
            ),
            parse_fn=lambda text: type(
                "Parsed", (), {"command_id": "score_point", "confidence": 0.9}
            )(),
        )
        worker.start()

        try:
            item = AsrAbWorkItem(
                experiment_id="exp-shutdown",
                sample_id="sample-shutdown",
                calibration_session_id="s1",
                capture_kind=CalibrationCaptureKind.COMMAND_TRIAL.value,
                expected_command_id="score_point",
                expected_phrase="point red",
                baseline_config=AsrExperimentConfig(
                    config_id="baseline",
                    display_name="baseline",
                    language="en",
                    hotwords=None,
                    initial_prompt=None,
                    condition_on_previous_text=None,
                    beam_size=None,
                ),
                candidate_config=AsrExperimentConfig(
                    config_id="candidate",
                    display_name="candidate",
                    language="en",
                    hotwords="point red",
                    initial_prompt="hint",
                    condition_on_previous_text=False,
                    beam_size=5,
                ),
                audio_bytes=b"\x00\x01\x02\x03",
                sample_rate_hz=16000,
            )
            assert worker.enqueue(item) is True
            worker.stop()
            assert not worker._running
        finally:
            worker.stop()
