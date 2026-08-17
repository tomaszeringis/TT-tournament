"""
Voice Calibration — Core service orchestrator.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

import dataclasses
import re
import time
import uuid
from dataclasses import replace
from typing import Dict

from tournament_platform.app.services.voice.commands import VoiceCommandGrammar
from tournament_platform.app.services.voice_calibration.alias_policy import (
    CalibrationAliasPolicy,
)
from tournament_platform.app.services.voice_calibration.models import (
    AcousticCaptureSummary,
    AcousticMeasurementResult,
    AcousticReconciliationResult,
    AcousticSummarySnapshot,
    AliasCandidateStatus,
    AliasConfirmationCandidate,
    AsrAbSampleResult,
    AsrAbWorkItem,
    AsrExperimentAggregate,
    AsrExperimentConfig,
    AsrExperimentRecommendation,
    AsrProviderCapabilities,
    CalibrationAliasCandidate,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationOverallStatus,
    CalibrationPhase,
    CalibrationProfileIdentity,
    CalibrationProfileStatus,
    CalibrationProfileStore,
    CalibrationResults,
    CalibrationSafetyOutcome,
    CalibrationSectionOutcome,
    CalibrationVerdictReason,
    CalibrationSession,
    CalibrationState,
    CalibrationConfusionEntry,
    CanonicalCommandIntent,
    CommandCalibrationResult,
    CommandPhraseCandidate,
    CommandRecognitionEntry,
    CommandTrial,
    CompletedMeasurementRef,
    LiveVoiceProfileRecommendation,
    NegativeSpeechSnapshot,
    NegativeTrial,
    NegativeTrialClassification,
    NoiseGateRecommendation,
    NoiseGateRecommendationPolicy,
    ParserCandidateInfo,
    PhraseComparisonResult,
    RecommendationStatus,
    SilenceBaselineMetrics,
    SpeechLevelMetrics,
    TtsEchoSnapshot,
    TtsEchoTestContext,
    TtsEchoTranscript,
    TtsEchoTranscriptInfo,
    TrialClassification,
    VerificationMetadata,
    VoiceCalibrationProfile,
    VoiceProfileActivationStatus,
    normalize_calibration_phrase,
)
from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
    AsrAbWorker,
)
from tournament_platform.app.services.asr_backends.base import TranscriptionResult
from tournament_platform.app.services.voice_calibration.state_machine import (
    CalibrationPhaseMachine,
)


class VoiceCalibrationService:
    """Orchestrates voice command calibration without mutating scores.

    Dependencies:
    - Public voice-command grammar interface (VoiceCommandGrammar)
    - CalibrationPhaseMachine
    - CalibrationAliasPolicy

    Forbidden dependencies:
    - Streamlit, WebRTC, ASR provider, session state, MatchManager,
      ScoreEngine, Database, TTS, Commentary
    """

    def __init__(
        self,
        grammar: VoiceCommandGrammar | None = None,
        phase_machine: CalibrationPhaseMachine | None = None,
        alias_policy: CalibrationAliasPolicy | None = None,
    ) -> None:
        self._grammar = grammar or VoiceCommandGrammar()
        self._phase_machine = phase_machine or CalibrationPhaseMachine()
        self._alias_policy = alias_policy or CalibrationAliasPolicy(self._grammar)

    def start_session(self, session_id: str) -> CalibrationSession:
        """Create a new calibration session in IDLE phase."""
        return CalibrationSession(
            session_id=session_id,
            created_at=time.time(),
        )

    def end_session(self, session: CalibrationSession) -> CalibrationSession:
        """Transition a completed session's phase to COMPLETED for closure."""
        state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.COMMAND_TRIAL)
        new_state = self._phase_machine.transition(state, CalibrationPhase.SAVING)
        new_state = self._phase_machine.transition(new_state, CalibrationPhase.COMPLETED)
        return session

    def transition(
        self,
        state: CalibrationState,
        target: CalibrationPhase,
    ) -> CalibrationState:
        """Advance the calibration phase machine."""
        return self._phase_machine.transition(state, target)

    def start_command_trial_session(
        self,
        commands: tuple[str, ...] = ("point_red", "point_blue"),
        attempts_per_command: int = 3,
    ) -> CalibrationSession:
        """Create a new command-trial calibration session."""
        session_id = str(uuid.uuid4())
        return CalibrationSession(
            session_id=session_id,
            created_at=time.time(),
            commands=commands,
            attempts_per_command=attempts_per_command,
            current_command_index=0,
        )

    def start_measurement(
        self,
        session: CalibrationSession,
        kind: str,
    ) -> str:
        """Create a pending measurement ID.

        Does not mutate the input session. The caller must arm the processor
        and persist the returned measurement ID in session state.
        """
        return str(uuid.uuid4())

    def create_silence_measurement(
        self,
        session: CalibrationSession,
        measurement_id: str,
        *,
        median_dbfs: float = -40.0,
        p90_dbfs: float = -38.0,
        p95_dbfs: float = -37.0,
        captured_duration_ms: float = 3000.0,
    ) -> SilenceBaselineMetrics:
        """Create a synthetic silence baseline measurement for testing."""
        capture = AcousticCaptureSummary(
            measurement_id=measurement_id,
            calibration_session_id=session.session_id,
            kind=CalibrationMeasurementKind.SILENCE_BASELINE,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=3000.0,
            captured_duration_ms=captured_duration_ms,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=median_dbfs,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=0,
            speech_duration_ms=0.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        return SilenceBaselineMetrics(
            capture=capture,
            median_rms=0.01,
            median_dbfs=median_dbfs,
            p90_rms=0.012,
            p90_dbfs=p90_dbfs,
            p95_rms=0.013,
            p95_dbfs=p95_dbfs,
            mad_rms=0.001,
            transient_count=0,
            contaminated_by_speech=False,
            speech_frame_count=0,
            speech_duration_ms=0.0,
        )

    def create_speech_measurement(
        self,
        session: CalibrationSession,
        measurement_id: str,
        *,
        speech_rms_dbfs: float = -20.0,
        speech_to_background_difference_db: float = 20.0,
        captured_duration_ms: float = 3500.0,
    ) -> SpeechLevelMetrics:
        """Create a synthetic speech level measurement for testing."""
        capture = AcousticCaptureSummary(
            measurement_id=measurement_id,
            calibration_session_id=session.session_id,
            kind=CalibrationMeasurementKind.NORMAL_SPEECH,
            sample_rate_hz=48000,
            channel_count=1,
            frame_count=48000,
            scalar_sample_count=48000,
            target_duration_ms=3500.0,
            captured_duration_ms=captured_duration_ms,
            valid_frame_count=48000,
            invalid_frame_count=0,
            rms=0.01,
            rms_dbfs=speech_rms_dbfs,
            peak=0.05,
            peak_dbfs=-26.0,
            near_clipping_count=0,
            hard_clipping_count=0,
            speech_frame_count=1000,
            speech_duration_ms=2000.0,
            complete=True,
            warning_codes=(),
            created_at=time.time(),
        )
        return SpeechLevelMetrics(
            capture=capture,
            speech_start_offset_ms=500.0,
            trailing_silence_ms=300.0,
            speech_rms=0.01,
            speech_rms_dbfs=speech_rms_dbfs,
            speech_to_background_difference_db=speech_to_background_difference_db,
        )

    def consume_measurements(
        self,
        session: CalibrationSession,
        measurements: tuple[AcousticMeasurementResult, ...],
    ) -> CalibrationSession:
        """Append acoustic measurements to a session, idempotent by measurement_id.

        Ignores measurements that belong to a different calibration session.
        If a measurement ID already exists but the payload differs, raises
        ValueError to signal a conflicting duplicate.
        """
        existing_by_id: dict[str, AcousticMeasurementResult] = {
            m.capture.measurement_id: m for m in session.measurements
        }
        new_measurements = list(session.measurements)
        for measurement in measurements:
            if measurement.capture.calibration_session_id != session.session_id:
                continue
            existing = existing_by_id.get(measurement.capture.measurement_id)
            if existing is not None:
                if existing != measurement:
                    raise ValueError(
                        f"Conflicting duplicate measurement: {measurement.capture.measurement_id}"
                    )
                continue
            new_measurements.append(measurement)
            existing_by_id[measurement.capture.measurement_id] = measurement

        return replace(session, measurements=tuple(new_measurements), revision=session.revision + 1)

    def reconcile_acoustic_measurements(
        self,
        *,
        session: CalibrationSession,
        measurements: tuple[AcousticMeasurementResult, ...],
        active_measurement_id: str | None = None,
        active_measurement_kind: CalibrationMeasurementKind | None = None,
    ) -> AcousticReconciliationResult:
        """Reconcile acoustic measurements atomically into session.
        
        This is the page-level transaction for completed measurements:
        1. Classify each drained measurement as consumed or ignored
        2. Consume new measurements into immutable session via consume_measurements
        3. Find first completed terminal result in updated session
        4. Return pure typed result
        
        The caller must then:
        1. Persist result.session to session state
        2. Store result.completed_ref for renderer if present
        3. Clear active measurement keys (now safe)
        
        Idempotency is based on measurement IDs already stored in the session,
        not on any completed-display-ref key.
        """
        existing_ids = {m.capture.measurement_id for m in session.measurements}
        consumed_ids: list[str] = []
        ignored_ids: list[str] = []
        rejection_reasons: list[str] = []
        
        for measurement in measurements:
            mid = measurement.capture.measurement_id
            if measurement.capture.calibration_session_id != session.session_id:
                rejection_reasons.append(f"session_mismatch:{mid[:8]}")
                ignored_ids.append(mid)
                continue
            if mid in existing_ids:
                ignored_ids.append(mid)
                continue
            consumed_ids.append(mid)
        
        if not consumed_ids:
            completed_ref = None
            for measurement in measurements:
                if measurement.capture.complete and completed_ref is None:
                    completed_ref = CompletedMeasurementRef(
                        calibration_session_id=session.session_id,
                        measurement_id=measurement.capture.measurement_id,
                        kind=measurement.capture.kind,
                    )
                    break
            return AcousticReconciliationResult(
                session=session,
                completed_ref=completed_ref,
                consumed_measurement_ids=(),
                ignored_measurement_ids=tuple(ignored_ids),
                rejection_reasons=tuple(rejection_reasons),
            )
        
        try:
            updated_session = self.consume_measurements(session, measurements)
        except ValueError as e:
            rejection_reasons.append(str(e))
            return AcousticReconciliationResult(
                session=session,
                completed_ref=None,
                consumed_measurement_ids=(),
                ignored_measurement_ids=tuple(ignored_ids),
                rejection_reasons=tuple(rejection_reasons),
            )
        
        completed_ref = None
        for measurement in measurements:
            if measurement.capture.complete and completed_ref is None:
                completed_ref = CompletedMeasurementRef(
                    calibration_session_id=session.session_id,
                    measurement_id=measurement.capture.measurement_id,
                    kind=measurement.capture.kind,
                )
                break
        
        return AcousticReconciliationResult(
            session=updated_session,
            completed_ref=completed_ref,
            consumed_measurement_ids=tuple(consumed_ids),
            ignored_measurement_ids=tuple(ignored_ids),
            rejection_reasons=tuple(rejection_reasons),
        )

    def retry_measurement(
        self,
        session: CalibrationSession,
        measurement_id: str,
    ) -> CalibrationSession:
        """Remove a measurement by ID so it can be retried."""
        new_measurements = tuple(
            m for m in session.measurements if m.capture.measurement_id != measurement_id
        )
        return replace(session, measurements=new_measurements, revision=session.revision + 1)

    def complete_session_without_persistence(
        self,
        session: CalibrationSession,
    ) -> CalibrationSession:
        """Transition a session from REVIEW to COMPLETED without persistence."""
        state = CalibrationState(
            session_id=session.session_id,
            phase=CalibrationPhase.REVIEW,
            revision=0,
        )
        self._phase_machine.transition(state, CalibrationPhase.COMPLETED)
        return replace(session, revision=session.revision + 1)

    def consume_trials(
        self,
        session: CalibrationSession,
        trials: tuple[CommandTrial, ...],
    ) -> CalibrationSession:
        """Append evaluated trials to a session, idempotent by trial_id."""
        existing_ids = {t.trial_id for t in session.trials}
        new_trials = list(session.trials)
        for trial in trials:
            if trial.trial_id not in existing_ids:
                new_trials.append(trial)
                existing_ids.add(trial.trial_id)

        completed_session = replace(session, trials=tuple(new_trials), revision=session.revision + 1)
        return completed_session

    def evaluate_transcript(
        self,
        transcript: str,
        expected_command_id: str,
        expected_phrase: str,
        trial_id: str | None = None,
        phrase_id: str | None = None,
        asr_latency_ms: float | None = None,
    ) -> CommandTrial:
        """Evaluate a transcript against the expected command.

        Parses through the public grammar interface and classifies the outcome
        as EXACT, VARIANT, WRONG_COMMAND, UNKNOWN, or EMPTY.
        """
        _trial_id = trial_id or str(uuid.uuid4())
        if not transcript or not transcript.strip():
            return CommandTrial(
                trial_id=_trial_id,
                expected_command_id=expected_command_id,
                expected_phrase_id=phrase_id,
                expected_phrase=expected_phrase,
                raw_transcript=transcript or "",
                normalized_transcript=transcript.strip() if transcript else "",
                resolved_command_id=None,
                classification=TrialClassification.EMPTY,
                parser_confidence=None,
                rejection_reason="empty transcript",
                asr_latency_ms=asr_latency_ms,
            )

        parse_result = self._grammar.parse(transcript)
        resolved_command_id = self._resolve_command_id(parse_result)

        expected_canonical = self._expected_command_to_canonical(expected_command_id, expected_phrase)
        parsed_canonical = self._parse_result_to_canonical(parse_result)

        normalized_transcript = normalize_calibration_phrase(transcript)
        normalized_expected = normalize_calibration_phrase(expected_phrase)

        exact_phrase_match = normalized_transcript == normalized_expected

        if resolved_command_id == "unknown" or parsed_canonical is None:
            if exact_phrase_match:
                return CommandTrial(
                    trial_id=_trial_id,
                    expected_command_id=expected_command_id,
                    expected_phrase_id=phrase_id,
                    expected_phrase=expected_phrase,
                    raw_transcript=transcript,
                    normalized_transcript=normalized_transcript,
                    resolved_command_id=expected_command_id,
                    classification=TrialClassification.EXACT,
                    parser_confidence=parse_result.confidence,
                    rejection_reason=None,
                    asr_latency_ms=asr_latency_ms,
                    exact_phrase_match_parser_miss=True,
                )
            return CommandTrial(
                trial_id=_trial_id,
                expected_command_id=expected_command_id,
                expected_phrase_id=phrase_id,
                expected_phrase=expected_phrase,
                raw_transcript=transcript,
                normalized_transcript=normalized_transcript,
                resolved_command_id="unknown",
                classification=TrialClassification.UNKNOWN,
                parser_confidence=parse_result.confidence,
                rejection_reason="unknown command",
                asr_latency_ms=asr_latency_ms,
            )

        if parsed_canonical.action != expected_canonical.action:
            return CommandTrial(
                trial_id=_trial_id,
                expected_command_id=expected_command_id,
                expected_phrase_id=phrase_id,
                expected_phrase=expected_phrase,
                raw_transcript=transcript,
                normalized_transcript=normalized_transcript,
                resolved_command_id=resolved_command_id,
                classification=TrialClassification.WRONG_COMMAND,
                parser_confidence=parse_result.confidence,
                rejection_reason=f"resolved to {resolved_command_id}",
                asr_latency_ms=asr_latency_ms,
            )

        if parsed_canonical.target != expected_canonical.target:
            return CommandTrial(
                trial_id=_trial_id,
                expected_command_id=expected_command_id,
                expected_phrase_id=phrase_id,
                expected_phrase=expected_phrase,
                raw_transcript=transcript,
                normalized_transcript=normalized_transcript,
                resolved_command_id=resolved_command_id,
                classification=TrialClassification.WRONG_COMMAND,
                parser_confidence=parse_result.confidence,
                rejection_reason=f"expected target {expected_canonical.target}, got {parsed_canonical.target}",
                asr_latency_ms=asr_latency_ms,
            )

        classification = (
            TrialClassification.EXACT
            if exact_phrase_match
            else TrialClassification.VARIANT
        )

        return CommandTrial(
            trial_id=_trial_id,
            expected_command_id=expected_command_id,
            expected_phrase_id=phrase_id,
            expected_phrase=expected_phrase,
            raw_transcript=transcript,
            normalized_transcript=normalized_transcript,
            resolved_command_id=resolved_command_id,
            classification=classification,
            parser_confidence=parse_result.confidence,
            rejection_reason=None,
            asr_latency_ms=asr_latency_ms,
        )

    def _expected_command_to_canonical(self, command_id: str, expected_phrase: str) -> CanonicalCommandIntent:
        _MAPPING = {
            "point_red": CanonicalCommandIntent(action="score_point", target="red"),
            "point_blue": CanonicalCommandIntent(action="score_point", target="blue"),
            "point_green": CanonicalCommandIntent(action="score_point", target="green"),
            "point_teal": CanonicalCommandIntent(action="score_point", target="teal"),
            "point_orange": CanonicalCommandIntent(action="score_point", target="orange"),
            "undo": CanonicalCommandIntent(action="undo", target=None),
        }
        if command_id in _MAPPING:
            return _MAPPING[command_id]
        if command_id == "score_point":
            target = self._extract_target_from_phrase(expected_phrase)
            return CanonicalCommandIntent(action="score_point", target=target)
        return CanonicalCommandIntent(action=command_id, target=None)

    def _extract_target_from_phrase(self, phrase: str) -> str | None:
        lower = phrase.lower()
        _COLOR_MAP = {
            "red": "red",
            "blue": "blue",
            "green": "green",
            "teal": "teal",
            "orange": "orange",
            "read": "red",
        }
        for color, target in _COLOR_MAP.items():
            if re.search(r"\b" + re.escape(color) + r"\b", lower):
                return target
        return None

    def _parse_result_to_canonical(self, parse_result) -> CanonicalCommandIntent | None:
        intent = parse_result.intent
        if hasattr(intent, "value"):
            intent_value = intent.value
        else:
            intent_value = str(intent)

        if intent_value == "score_point":
            target = getattr(parse_result, "slots", {}).get("target")
            if target is None:
                player = getattr(parse_result, "slots", {}).get("player")
                _PLAYER_TO_TARGET = {"A": "blue", "B": "red"}
                target = _PLAYER_TO_TARGET.get(player)
            return CanonicalCommandIntent(action="score_point", target=target)
        if intent_value == "undo":
            return CanonicalCommandIntent(action="undo", target=None)
        return CanonicalCommandIntent(action=intent_value, target=None)

    def re_evaluate_trials(
        self,
        session: CalibrationSession,
    ) -> tuple[CalibrationSession, dict[str, int]]:
        """Re-evaluate stored trials with the current deterministic evaluator.

        Preserves original trial IDs and raw transcripts.
        Updates derived normalized text, canonical intent, and classification.
        Does NOT rerun ASR. Does NOT mutate score.
        """
        new_trials = []
        counts = {"before": {}, "after": {}}

        for trial in session.trials:
            counts["before"][trial.trial_id] = trial.classification.value
            updated = self.evaluate_transcript(
                transcript=trial.raw_transcript,
                expected_command_id=trial.expected_command_id,
                expected_phrase=trial.expected_phrase,
                trial_id=trial.trial_id,
                phrase_id=trial.expected_phrase_id,
                asr_latency_ms=trial.asr_latency_ms,
            )
            new_trials.append(updated)
            counts["after"][trial.trial_id] = updated.classification.value

        new_session = replace(
            session,
            trials=tuple(new_trials),
            revision=session.revision + 1,
        )
        return new_session, counts

    def add_alias_candidate(
        self,
        session: CalibrationSession,
        transcript: str,
        command_id: str,
        classification: str,
        confirmed: bool = False,
        language: str = "en",
    ) -> CalibrationSession:
        """Append an alias candidate to a session and return a new session."""
        candidate = CalibrationAliasCandidate(
            transcript=transcript,
            command_id=command_id,
            classification=classification,
            confirmed=confirmed,
            language=language,
        )
        return replace(session, alias_candidates=session.alias_candidates + (candidate,), revision=session.revision + 1)

    def aggregate_results(
        self,
        session: CalibrationSession,
    ) -> Dict[str, CommandCalibrationResult]:
        """Calculate per-command calibration metrics from session trials."""
        seen_ids: set[str] = set()
        counts: Dict[str, Dict[str, int]] = {}

        for trial in session.trials:
            if trial.trial_id in seen_ids:
                continue
            seen_ids.add(trial.trial_id)

            cmd_id = trial.expected_command_id
            if cmd_id not in counts:
                counts[cmd_id] = {
                    "attempts": 0,
                    "exact_matches": 0,
                    "successful_resolutions": 0,
                    "wrong_command_count": 0,
                    "unknown_count": 0,
                }

            c = counts[cmd_id]
            c["attempts"] += 1

            if trial.classification == TrialClassification.EXACT:
                c["exact_matches"] += 1
                c["successful_resolutions"] += 1
            elif trial.classification == TrialClassification.VARIANT:
                c["successful_resolutions"] += 1
            elif trial.classification == TrialClassification.WRONG_COMMAND:
                c["wrong_command_count"] += 1
            else:
                c["unknown_count"] += 1

        return {
            cmd_id: CommandCalibrationResult(command_id=cmd_id, **vals)
            for cmd_id, vals in counts.items()
        }

    @staticmethod
    def _resolve_command_id(parse_result) -> str:
        intent = parse_result.intent
        if hasattr(intent, "value"):
            return intent.value
        return str(intent)

    @staticmethod
    def _normalize_expected(phrase: str) -> str:
        from tournament_platform.app.services.voice_parser import _normalize_number_words

        return _normalize_number_words(phrase.strip().lower())

    def evaluate_negative_trial(
        self,
        transcript: str,
        *,
        prompt_id: str | None = None,
        trial_id: str | None = None,
    ) -> NegativeTrial:
        """Parse a negative-trial transcript in dry-run mode and classify.

        Returns a ``NegativeTrial`` with parser dry-run results and a
        calibration classification.
        """
        _trial_id = trial_id or str(uuid.uuid4())
        raw_transcript = transcript if transcript else ""
        normalized_transcript = transcript.strip() if transcript else ""

        parser_command_id: str | None = None
        parser_confidence: float | None = None
        would_accept_live = False
        classification = NegativeTrialClassification.NO_AUDIO

        if normalized_transcript:
            try:
                parse_result = self._grammar.parse(normalized_transcript)
                parser_command_id = self._resolve_command_id(parse_result)
                parser_confidence = parse_result.confidence
            except Exception:
                parser_command_id = None
                parser_confidence = None
                classification = NegativeTrialClassification.ASR_FAILED

            if parser_command_id == "score_point":
                would_accept_live = True
                classification = NegativeTrialClassification.FALSE_POINT_CANDIDATE
            elif parser_command_id == "undo":
                would_accept_live = True
                classification = NegativeTrialClassification.FALSE_UNDO_CANDIDATE
            elif parser_command_id == "reset_match":
                would_accept_live = True
                classification = NegativeTrialClassification.FALSE_RESET_CANDIDATE
            elif parser_command_id and parser_command_id != "unknown":
                would_accept_live = True
                classification = NegativeTrialClassification.WRONG_NON_SCORE_CANDIDATE
            else:
                would_accept_live = False
                classification = NegativeTrialClassification.CORRECTLY_REJECTED

        return NegativeTrial(
            trial_id=_trial_id,
            prompt_id=prompt_id or "",
            raw_transcript=raw_transcript,
            normalized_transcript=normalized_transcript,
            parser_command_id=parser_command_id,
            parser_confidence=parser_confidence,
            would_accept_live=would_accept_live,
            classification=classification,
            created_at=time.time(),
        )

    def consume_negative_trials(
        self,
        session: CalibrationSession,
        trials: tuple[NegativeTrial, ...],
    ) -> CalibrationSession:
        """Append negative trials idempotently by trial_id."""
        existing_ids = {t.trial_id for t in session.negative_trials}
        new_trials = list(session.negative_trials)
        for trial in trials:
            if trial.trial_id not in existing_ids:
                new_trials.append(trial)
                existing_ids.add(trial.trial_id)

        return replace(session, negative_trials=tuple(new_trials), revision=session.revision + 1)

    def start_tts_echo_test(
        self,
        session: CalibrationSession,
        *,
        playback_id: str | None = None,
        text: str = "",
        voice_provider: str = "browser",
    ) -> tuple[CalibrationSession, TtsEchoTestContext]:
        """Start a new TTS echo playback context."""
        _playback_id = playback_id or str(uuid.uuid4())
        context = TtsEchoTestContext(
            playback_id=_playback_id,
            text=text,
            voice_provider=voice_provider,
            playback_started_at=time.time(),
        )
        updated = replace(
            session,
            tts_echo_test_contexts=session.tts_echo_test_contexts + (context,),
            revision=session.revision + 1,
        )
        return updated, context

    def complete_tts_echo_test(
        self,
        session: CalibrationSession,
        playback_id: str,
    ) -> CalibrationSession:
        """Mark a TTS echo playback context as ended."""
        updated_contexts = []
        for ctx in session.tts_echo_test_contexts:
            if ctx.playback_id == playback_id and ctx.playback_ended_at is None:
                updated_contexts.append(
                    TtsEchoTestContext(
                        playback_id=ctx.playback_id,
                        text=ctx.text,
                        voice_provider=ctx.voice_provider,
                        playback_started_at=ctx.playback_started_at,
                        playback_ended_at=time.time(),
                    )
                )
            else:
                updated_contexts.append(ctx)

        return replace(session, tts_echo_test_contexts=tuple(updated_contexts), revision=session.revision + 1)

    def create_tts_echo_transcript(
        self,
        transcript: str,
        *,
        tts_playback_id: str | None = None,
        captured_during_playback: bool = True,
        capture_offset_ms: float | None = None,
        tts_source: str = "score_confirmation",
    ) -> TtsEchoTranscript:
        """Create a correlated TTS echo transcript record."""
        return TtsEchoTranscript(
            transcript_id=str(uuid.uuid4()),
            tts_playback_id=tts_playback_id or "",
            captured_during_playback=captured_during_playback,
            capture_offset_ms=capture_offset_ms,
            transcript=transcript.strip() if transcript else "",
            normalized_transcript=transcript.strip() if transcript else "",
            tts_source=tts_source,
            created_at=time.time(),
        )

    def consume_tts_echo_transcripts(
        self,
        session: CalibrationSession,
        transcripts: tuple[TtsEchoTranscript, ...],
    ) -> CalibrationSession:
        """Append TTS echo transcripts idempotently by transcript_id."""
        existing_ids = {t.transcript_id for t in session.tts_echo_transcripts}
        new_transcripts = list(session.tts_echo_transcripts)
        for transcript in transcripts:
            if transcript.transcript_id not in existing_ids:
                new_transcripts.append(transcript)
                existing_ids.add(transcript.transcript_id)

        return replace(session, tts_echo_transcripts=tuple(new_transcripts), revision=session.revision + 1)

    def compute_acoustic_summary(self, session: CalibrationSession) -> AcousticSummarySnapshot:
        """Compute acoustic measurement summary from immutable session data.

        Selects the latest valid completed measurement per kind, deduplicates by
        measurement ID, and excludes incomplete/skipped/rejected measurements.
        Never depends on the active processor or WebRTC state.
        """
        seen_ids: set[str] = set()
        silence_candidates: list[SilenceBaselineMetrics] = []
        speech_candidates: list[SpeechLevelMetrics] = []
        total = len(session.measurements)
        complete = 0
        valid_complete = 0

        for measurement in session.measurements:
            mid = measurement.capture.measurement_id
            if mid in seen_ids:
                continue
            seen_ids.add(mid)

            is_complete = measurement.capture.complete
            is_skipped = measurement.capture.skipped

            if is_complete:
                complete += 1
                if not is_skipped:
                    valid_complete += 1

            if not is_complete or is_skipped:
                continue

            if isinstance(measurement, SilenceBaselineMetrics):
                silence_candidates.append(measurement)
            elif isinstance(measurement, SpeechLevelMetrics):
                speech_candidates.append(measurement)

        silence_metrics = silence_candidates[-1] if silence_candidates else None
        speech_metrics = speech_candidates[-1] if speech_candidates else None

        clipping_detected = False
        if speech_metrics is not None:
            if speech_metrics.capture.near_clipping_count > 0:
                clipping_detected = True
            if speech_metrics.capture.hard_clipping_count > 0:
                clipping_detected = True

        required_kinds = 0
        if silence_metrics is not None:
            required_kinds += 1
        if speech_metrics is not None:
            required_kinds += 1

        return AcousticSummarySnapshot(
            background_median_dbfs=silence_metrics.median_dbfs if silence_metrics else None,
            background_p90_dbfs=silence_metrics.p90_dbfs if silence_metrics else None,
            background_p95_dbfs=silence_metrics.p95_dbfs if silence_metrics else None,
            speech_level_dbfs=speech_metrics.speech_rms_dbfs if speech_metrics else None,
            speech_background_difference_db=speech_metrics.speech_to_background_difference_db if speech_metrics else None,
            clipping_detected=clipping_detected,
            measurement_count=total,
            total_measurements=total,
            complete_measurements=complete,
            valid_complete_measurements=valid_complete,
            silence_measurement_count=len(silence_candidates),
            speech_measurement_count=len(speech_candidates),
            required_kinds_present=required_kinds,
            selected_silence_measurement_id=silence_metrics.capture.measurement_id if silence_metrics else None,
            selected_speech_measurement_id=speech_metrics.capture.measurement_id if speech_metrics else None,
        )

    def compute_command_trial_coverage(
        self,
        session: CalibrationSession,
        command_id: str,
        attempts_required: int | None = None,
    ) -> CommandRecognitionEntry:
        """Compute trial coverage for a single command with dedup and arm-only exclusion.

        Deduplicates by trial_id, excludes arm-only attempts (trials with
        no meaningful transcript or explicit arm rejection), and counts
        exact, variant, wrong_command, and unknown classifications.

        Args:
            session: Immutable calibration session.
            command_id: The expected command ID to filter trials for.
            attempts_required: Optional expected attempt count for
                inconsistency detection.

        Returns:
            CommandRecognitionEntry with coverage statistics.
        """
        attempts_required = attempts_required or session.attempts_per_command

        seen_ids: set[str] = set()
        exact = 0
        variants = 0
        wrong = 0
        unknown = 0
        attempts = 0

        for trial in session.trials:
            if trial.trial_id in seen_ids:
                continue
            if trial.expected_command_id != command_id:
                continue
            seen_ids.add(trial.trial_id)

            if trial.classification == TrialClassification.EXACT:
                exact += 1
            elif trial.classification == TrialClassification.VARIANT:
                variants += 1
            elif trial.classification == TrialClassification.WRONG_COMMAND:
                wrong += 1
            elif trial.classification == TrialClassification.UNKNOWN:
                unknown += 1
            else:
                continue

            attempts += 1

        return CommandRecognitionEntry(
            command_id=command_id,
            attempts=attempts,
            exact_matches=exact,
            successful_resolutions=exact + variants,
            wrong_command_count=wrong,
            unknown_count=unknown,
        )

    def compute_command_recognition(self, session: CalibrationSession) -> tuple[CommandRecognitionEntry, ...]:
        """Compute per-command recognition stats from immutable trial data.

        Uses ``compute_command_trial_coverage()`` for consistent dedup and
        arm-only exclusion across all UI components.
        """
        entries: list[CommandRecognitionEntry] = []
        for command in session.commands:
            entry = self.compute_command_trial_coverage(session, command)
            entries.append(entry)

        return tuple(entries)

    def compute_negative_speech_safety(self, session: CalibrationSession) -> NegativeSpeechSnapshot:
        """Compute negative speech safety metrics from immutable trial data."""
        total_trials = len(session.negative_trials)
        correctly_rejected = sum(
            1 for t in session.negative_trials
            if t.classification == NegativeTrialClassification.CORRECTLY_REJECTED
        )
        false_points = sum(
            1 for t in session.negative_trials
            if t.classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE
        )
        false_undos = sum(
            1 for t in session.negative_trials
            if t.classification in {
                NegativeTrialClassification.FALSE_UNDO_CANDIDATE,
                NegativeTrialClassification.FALSE_RESET_CANDIDATE,
            }
        )
        false_accepts = false_points + false_undos

        parser_candidates = tuple(
            ParserCandidateInfo(
                raw_transcript=t.raw_transcript,
                normalized_transcript=t.normalized_transcript,
                parser_command_id=t.parser_command_id,
                parser_confidence=t.parser_confidence,
                would_accept_live=t.would_accept_live,
                classification=t.classification.value,
            )
            for t in session.negative_trials
        )

        return NegativeSpeechSnapshot(
            trials=total_trials,
            correctly_rejected=correctly_rejected,
            false_point_candidates=false_points,
            false_undo_reset_candidates=false_undos,
            false_live_acceptable_candidates=false_accepts,
            parser_candidates=parser_candidates,
        )

    def compute_tts_echo_safety(self, session: CalibrationSession) -> TtsEchoSnapshot:
        """Compute TTS echo safety metrics from immutable session data."""
        playback_tests = len(session.tts_echo_test_contexts)
        transcripts_captured = len(session.tts_echo_transcripts)

        live_acceptable_candidates = 0
        for transcript in session.tts_echo_transcripts:
            for context in session.tts_echo_test_contexts:
                if transcript.tts_playback_id == context.playback_id:
                    if transcript.transcript:
                        try:
                            parse_result = self._grammar.parse(transcript.transcript)
                            cmd_id = self._resolve_command_id(parse_result)
                            if cmd_id and cmd_id != "unknown":
                                live_acceptable_candidates += 1
                        except Exception:
                            pass
                    break

        transcripts = tuple(
            TtsEchoTranscriptInfo(
                transcript=t.transcript,
                normalized_transcript=t.normalized_transcript,
                tts_source=t.tts_source,
                captured_during_playback=t.captured_during_playback,
            )
            for t in session.tts_echo_transcripts
        )

        return TtsEchoSnapshot(
            playback_tests=playback_tests,
            transcripts_captured=transcripts_captured,
            live_acceptable_command_candidates=live_acceptable_candidates,
            score_actions=0,
            transcripts=transcripts,
        )

    def compute_confusion_table(self, session: CalibrationSession) -> tuple[CalibrationConfusionEntry, ...]:
        """Build confusion table from immutable calibration data."""
        entries: list[CalibrationConfusionEntry] = []

        for trial in session.trials:
            entries.append(
                CalibrationConfusionEntry(
                    test_type="command_trial",
                    expected=trial.expected_phrase,
                    transcript=trial.raw_transcript,
                    normalized_transcript=trial.normalized_transcript,
                    parser_candidate=trial.resolved_command_id,
                    parser_confidence=trial.parser_confidence,
                    outcome=trial.classification.value,
                )
            )

        for trial in session.negative_trials:
            entries.append(
                CalibrationConfusionEntry(
                    test_type="negative_trial",
                    expected="no_command",
                    transcript=trial.raw_transcript,
                    normalized_transcript=trial.normalized_transcript,
                    parser_candidate=trial.parser_command_id,
                    parser_confidence=trial.parser_confidence,
                    outcome=trial.classification.value,
                )
            )

        for transcript in session.tts_echo_transcripts:
            entries.append(
                CalibrationConfusionEntry(
                    test_type="tts_echo",
                    expected="no_command",
                    transcript=transcript.transcript,
                    normalized_transcript=transcript.normalized_transcript,
                    parser_candidate=None,
                    parser_confidence=None,
                    outcome="echo_captured",
                )
            )

        return tuple(entries)

    def compute_results(self, session: CalibrationSession) -> CalibrationResults:
        """Compute complete Phase 8 calibration results from immutable session data."""
        acoustic_summary = self.compute_acoustic_summary(session)
        command_recognition = self.compute_command_recognition(session)
        negative_speech = self.compute_negative_speech_safety(session)
        tts_echo = self.compute_tts_echo_safety(session)
        confusion_table = self.compute_confusion_table(session)

        safety_outcomes = self._compute_safety_outcomes(
            acoustic_summary=acoustic_summary,
            command_recognition=command_recognition,
            negative_speech=negative_speech,
            tts_echo=tts_echo,
        )

        verdict_reasons = self._compute_verdict_reasons(
            acoustic_summary=acoustic_summary,
            command_recognition=command_recognition,
            negative_speech=negative_speech,
            tts_echo=tts_echo,
            safety_outcomes=safety_outcomes,
        )

        section_outcomes = self._compute_section_outcomes(
            acoustic_summary=acoustic_summary,
            command_recognition=command_recognition,
            negative_speech=negative_speech,
            tts_echo=tts_echo,
            verdict_reasons=verdict_reasons,
        )

        overall_status = self._compute_overall_status(
            safety_outcomes=safety_outcomes,
            section_outcomes=section_outcomes,
        )

        blocking_reasons = tuple(
            r for r in verdict_reasons if r.blocking
        )
        warning_reasons = tuple(
            r for r in verdict_reasons
            if r.status == CalibrationOverallStatus.WARNING
        )
        incomplete_reasons = tuple(
            r for r in verdict_reasons
            if r.status == CalibrationOverallStatus.INCOMPLETE
        )
        invalid_data_reasons = tuple(
            r for r in verdict_reasons
            if r.status == CalibrationOverallStatus.INVALID_DATA
        )

        overall_pass = overall_status == CalibrationOverallStatus.PASS

        return CalibrationResults(
            session_id=session.session_id,
            acoustic_summary=acoustic_summary,
            command_recognition=command_recognition,
            negative_speech=negative_speech,
            tts_echo=tts_echo,
            confusion_table=confusion_table,
            safety_outcomes=safety_outcomes,
            overall_pass=overall_pass,
            overall_status=overall_status,
            section_outcomes=section_outcomes,
            blocking_reasons=blocking_reasons,
            warning_reasons=warning_reasons,
            incomplete_reasons=incomplete_reasons,
            invalid_data_reasons=invalid_data_reasons,
            created_at=time.time(),
        )

    def _compute_safety_outcomes(
        self,
        *,
        acoustic_summary: AcousticSummarySnapshot,
        command_recognition: tuple[CommandRecognitionEntry, ...],
        negative_speech: NegativeSpeechSnapshot,
        tts_echo: TtsEchoSnapshot,
    ) -> tuple[CalibrationSafetyOutcome, ...]:
        """Compute independent pass/warning/fail safety outcomes."""
        outcomes: list[CalibrationSafetyOutcome] = []

        mic_ready = acoustic_summary.measurement_count >= 2
        if mic_ready:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="microphone_environment",
                    outcome="Ready",
                    detail="Acoustic measurements completed.",
                    failure=False,
                )
            )
        else:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="microphone_environment",
                    outcome="Failed",
                    detail="Insufficient acoustic measurements.",
                    failure=True,
                )
            )

        command_ready = any(
            entry.successful_resolutions > 0
            for entry in command_recognition
        )
        if command_ready:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="command_recognition",
                    outcome="Ready",
                    detail="At least one command was recognized.",
                    failure=False,
                )
            )
        else:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="command_recognition",
                    outcome="Warning",
                    detail="No successful command recognitions.",
                    failure=False,
                )
            )

        if negative_speech.trials == 0:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="negative_speech_safety",
                    outcome="Not Tested",
                    detail="No negative-speech trials were conducted.",
                    failure=False,
                )
            )
        elif negative_speech.false_live_acceptable_candidates == 0:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="negative_speech_safety",
                    outcome="Passed",
                    detail="No false live-acceptable candidates from negative speech.",
                    failure=False,
                )
            )
        else:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="negative_speech_safety",
                    outcome="Failed",
                    detail="False live-acceptable candidates detected in negative speech.",
                    failure=True,
                )
            )

        if tts_echo.playback_tests == 0:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="tts_echo_safety",
                    outcome="Not Tested",
                    detail="No TTS echo tests were conducted.",
                    failure=False,
                )
            )
        elif tts_echo.live_acceptable_command_candidates == 0:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="tts_echo_safety",
                    outcome="Passed",
                    detail="No false live-acceptable candidates from TTS/commentary.",
                    failure=False,
                )
            )
        else:
            outcomes.append(
                CalibrationSafetyOutcome(
                    category="tts_echo_safety",
                    outcome="Failed",
                    detail="False live-acceptable candidates detected from TTS/commentary.",
                    failure=True,
                )
            )

        return tuple(outcomes)

    def _compute_overall_status(
        self,
        safety_outcomes: tuple[CalibrationSafetyOutcome, ...],
        section_outcomes: tuple[CalibrationSectionOutcome, ...],
    ) -> CalibrationOverallStatus:
        """Compute overall status from safety outcomes and section outcomes."""
        if any(outcome.failure for outcome in safety_outcomes):
            return CalibrationOverallStatus.FAIL
        if any(
            so.status == CalibrationOverallStatus.NOT_TESTED
            for so in section_outcomes
        ):
            return CalibrationOverallStatus.INCOMPLETE
        if any(
            so.status == CalibrationOverallStatus.WARNING
            for so in section_outcomes
        ):
            return CalibrationOverallStatus.WARNING
        return CalibrationOverallStatus.PASS

    def _compute_verdict_reasons(
        self,
        *,
        acoustic_summary: AcousticSummarySnapshot,
        command_recognition: tuple[CommandRecognitionEntry, ...],
        negative_speech: NegativeSpeechSnapshot,
        tts_echo: TtsEchoSnapshot,
        safety_outcomes: tuple[CalibrationSafetyOutcome, ...],
    ) -> tuple[CalibrationVerdictReason, ...]:
        """Compute typed reasons for each section outcome."""
        reasons: list[CalibrationVerdictReason] = []

        silence_present = acoustic_summary.selected_silence_measurement_id is not None
        speech_present = acoustic_summary.selected_speech_measurement_id is not None

        if not silence_present:
            reasons.append(
                CalibrationVerdictReason(
                    code="ACOUSTIC_SILENCE_MISSING",
                    status=CalibrationOverallStatus.INCOMPLETE,
                    section="microphone_environment",
                    title="Missing silence measurement",
                    explanation="A valid silence baseline measurement is required to assess the microphone environment.",
                    evidence=(
                        f"total_measurements={acoustic_summary.total_measurements}",
                        f"complete_measurements={acoustic_summary.complete_measurements}",
                        f"valid_complete_measurements={acoustic_summary.valid_complete_measurements}",
                        f"silence_measurement_count={acoustic_summary.silence_measurement_count}",
                        f"speech_measurement_count={acoustic_summary.speech_measurement_count}",
                        f"selected_silence_measurement_id={acoustic_summary.selected_silence_measurement_id or 'none'}",
                    ),
                    remediation="Complete one silence baseline measurement.",
                    blocking=True,
                )
            )

        if not speech_present:
            reasons.append(
                CalibrationVerdictReason(
                    code="ACOUSTIC_SPEECH_MISSING",
                    status=CalibrationOverallStatus.INCOMPLETE,
                    section="microphone_environment",
                    title="Missing normal-speech measurement",
                    explanation="A valid normal-speech measurement is required to calibrate speech-level thresholds.",
                    evidence=(
                        f"total_measurements={acoustic_summary.total_measurements}",
                        f"complete_measurements={acoustic_summary.complete_measurements}",
                        f"speech_measurement_count={acoustic_summary.speech_measurement_count}",
                        f"selected_speech_measurement_id={acoustic_summary.selected_speech_measurement_id or 'none'}",
                    ),
                    remediation="Complete one normal-speech measurement at speaking volume.",
                    blocking=True,
                )
            )

        if not silence_present and not speech_present and acoustic_summary.total_measurements > 0:
            reasons.append(
                CalibrationVerdictReason(
                    code="ACOUSTIC_STATE_LOST",
                    status=CalibrationOverallStatus.INVALID_DATA,
                    section="microphone_environment",
                    title="Calibration data exists but could not be reconciled",
                    explanation="Acoustic measurements were recorded but the report could not locate valid silence or speech results. The session state may have been overwritten during a phase transition.",
                    evidence=(
                        f"total_measurements={acoustic_summary.total_measurements}",
                        f"valid_complete_measurements={acoustic_summary.valid_complete_measurements}",
                        f"selected_silence_measurement_id={acoustic_summary.selected_silence_measurement_id or 'none'}",
                        f"selected_speech_measurement_id={acoustic_summary.selected_speech_measurement_id or 'none'}",
                    ),
                    remediation="Recompute the report or reset the calibration session and recapture measurements.",
                    blocking=True,
                )
            )

        if acoustic_summary.clipping_detected:
            reasons.append(
                CalibrationVerdictReason(
                    code="ACOUSTIC_HARD_CLIPPING",
                    status=CalibrationOverallStatus.FAIL,
                    section="microphone_environment",
                    title="Hard clipping detected",
                    explanation="Audio samples exceeded the clipping threshold. Reduce microphone gain.",
                    evidence=("clipping_detected=True",),
                    remediation="Lower microphone gain or increase distance from the microphone.",
                    blocking=True,
                )
            )

        if acoustic_summary.speech_background_difference_db is not None and acoustic_summary.speech_background_difference_db < 12.0:
            reasons.append(
                CalibrationVerdictReason(
                    code="SPEECH_BACKGROUND_SEPARATION_LOW",
                    status=CalibrationOverallStatus.WARNING,
                    section="microphone_environment",
                    title="Low speech-to-background separation",
                    explanation=f"Speech is only {acoustic_summary.speech_background_difference_db:.1f} dB above background noise.",
                    evidence=(
                        f"speech_background_difference_db={acoustic_summary.speech_background_difference_db:.1f}",
                    ),
                    remediation="Move closer to the microphone or reduce background noise.",
                    blocking=False,
                )
            )

        for entry in command_recognition:
            total = entry.attempts
            if total == 0:
                reasons.append(
                    CalibrationVerdictReason(
                        code="COMMAND_SAMPLE_COVERAGE_INSUFFICIENT",
                        status=CalibrationOverallStatus.INCOMPLETE,
                        section="command_recognition",
                        title=f"No trials for command {entry.command_id}",
                        explanation=f"Command '{entry.command_id}' has no trial attempts.",
                        evidence=(f"command_id={entry.command_id}",),
                        remediation="Run command trials for this command.",
                        blocking=True,
                    )
                )
            elif entry.successful_resolutions == 0:
                reasons.append(
                    CalibrationVerdictReason(
                        code="COMMAND_RECOGNITION_RATE_LOW",
                        status=CalibrationOverallStatus.FAIL,
                        section="command_recognition",
                        title=f"No successful recognitions for {entry.command_id}",
                        explanation=f"Command '{entry.command_id}' had {total} attempts with 0 successful resolutions.",
                        evidence=(
                            f"command_id={entry.command_id}",
                            f"attempts={total}",
                            "successful_resolutions=0",
                        ),
                        remediation="Check microphone and try again with the command phrase.",
                        blocking=True,
                    )
                )
            elif entry.unknown_count > 0 and entry.successful_resolutions / total < 0.5:
                reasons.append(
                    CalibrationVerdictReason(
                        code="COMMAND_UNKNOWN_TRANSCRIPT",
                        status=CalibrationOverallStatus.WARNING,
                        section="command_recognition",
                        title=f"High unknown rate for {entry.command_id}",
                        explanation=f"{entry.unknown_count} of {total} attempts were unrecognized.",
                        evidence=(
                            f"command_id={entry.command_id}",
                            f"unknown_count={entry.unknown_count}",
                            f"attempts={total}",
                        ),
                        remediation="Speak more clearly or check the command phrase.",
                        blocking=False,
                    )
                )

        if negative_speech.trials == 0:
            reasons.append(
                CalibrationVerdictReason(
                    code="NEGATIVE_SPEECH_NOT_TESTED",
                    status=CalibrationOverallStatus.NOT_TESTED,
                    section="negative_speech_safety",
                    title="Negative speech safety not tested",
                    explanation="No negative-speech trials were conducted. The system cannot verify that score commands are not falsely accepted.",
                    evidence=("negative_trials=0",),
                    remediation="Run negative-speech trials to verify safety.",
                    blocking=False,
                )
            )
        elif negative_speech.false_live_acceptable_candidates > 0:
            reasons.append(
                CalibrationVerdictReason(
                    code="NEGATIVE_SPEECH_FALSE_CANDIDATE",
                    status=CalibrationOverallStatus.FAIL,
                    section="negative_speech_safety",
                    title="False live-acceptable candidates in negative speech",
                    explanation=f"{negative_speech.false_live_acceptable_candidates} negative-speech trial(s) would be accepted as valid commands.",
                    evidence=(
                        f"false_live_acceptable_candidates={negative_speech.false_live_acceptable_candidates}",
                    ),
                    remediation="Review negative-speech trial transcripts and adjust the parser or vocabulary.",
                    blocking=True,
                )
            )

        if tts_echo.playback_tests == 0:
            reasons.append(
                CalibrationVerdictReason(
                    code="TTS_ECHO_NOT_TESTED",
                    status=CalibrationOverallStatus.NOT_TESTED,
                    section="tts_echo_safety",
                    title="TTS echo safety not tested",
                    explanation="No TTS echo tests were conducted. The system cannot verify that application commentary is not falsely accepted.",
                    evidence=("tts_echo_playback_tests=0",),
                    remediation="Run TTS echo tests to verify safety.",
                    blocking=False,
                )
            )
        elif tts_echo.live_acceptable_command_candidates > 0:
            reasons.append(
                CalibrationVerdictReason(
                    code="TTS_ECHO_FALSE_CANDIDATE",
                    status=CalibrationOverallStatus.FAIL,
                    section="tts_echo_safety",
                    title="False live-acceptable candidates from TTS echo",
                    explanation=f"{tts_echo.live_acceptable_command_candidates} TTS echo transcript(s) would be accepted as valid commands.",
                    evidence=(
                        f"live_acceptable_command_candidates={tts_echo.live_acceptable_command_candidates}",
                    ),
                    remediation="Review TTS echo transcripts and adjust the parser or vocabulary.",
                    blocking=True,
                )
            )

        return tuple(reasons)

    def _compute_section_outcomes(
        self,
        *,
        acoustic_summary: AcousticSummarySnapshot,
        command_recognition: tuple[CommandRecognitionEntry, ...],
        negative_speech: NegativeSpeechSnapshot,
        tts_echo: TtsEchoSnapshot,
        verdict_reasons: tuple[CalibrationVerdictReason, ...],
    ) -> tuple[CalibrationSectionOutcome, ...]:
        """Compute section-level outcomes with typed reasons."""
        sections: list[CalibrationSectionOutcome] = []

        mic_reasons = tuple(
            r for r in verdict_reasons if r.section == "microphone_environment"
        )
        mic_status = CalibrationOverallStatus.PASS
        if acoustic_summary.required_kinds_present < 2:
            mic_status = CalibrationOverallStatus.INCOMPLETE
        elif acoustic_summary.clipping_detected:
            mic_status = CalibrationOverallStatus.FAIL
        elif acoustic_summary.speech_background_difference_db is not None and acoustic_summary.speech_background_difference_db < 12.0:
            mic_status = CalibrationOverallStatus.WARNING
        sections.append(
            CalibrationSectionOutcome(
                section="microphone_environment",
                status=mic_status,
                reasons=mic_reasons,
                evidence_count=acoustic_summary.valid_complete_measurements,
                required_evidence_count=2,
            )
        )

        cmd_reasons = tuple(
            r for r in verdict_reasons if r.section == "command_recognition"
        )
        cmd_status = CalibrationOverallStatus.PASS
        any_command_failed = any(
            r.status == CalibrationOverallStatus.FAIL for r in cmd_reasons
        )
        any_command_incomplete = any(
            r.status == CalibrationOverallStatus.INCOMPLETE for r in cmd_reasons
        )
        any_command_warning = any(
            r.status == CalibrationOverallStatus.WARNING for r in cmd_reasons
        )
        if any_command_failed:
            cmd_status = CalibrationOverallStatus.FAIL
        elif any_command_incomplete:
            cmd_status = CalibrationOverallStatus.INCOMPLETE
        elif any_command_warning:
            cmd_status = CalibrationOverallStatus.WARNING
        sections.append(
            CalibrationSectionOutcome(
                section="command_recognition",
                status=cmd_status,
                reasons=cmd_reasons,
                evidence_count=sum(e.attempts for e in command_recognition),
                required_evidence_count=len(command_recognition) * max(1, command_recognition[0].attempts if command_recognition else 0),
            )
        )

        neg_reasons = tuple(
            r for r in verdict_reasons if r.section == "negative_speech_safety"
        )
        neg_status = CalibrationOverallStatus.PASS
        if negative_speech.trials == 0:
            neg_status = CalibrationOverallStatus.NOT_TESTED
        elif negative_speech.false_live_acceptable_candidates > 0:
            neg_status = CalibrationOverallStatus.FAIL
        sections.append(
            CalibrationSectionOutcome(
                section="negative_speech_safety",
                status=neg_status,
                reasons=neg_reasons,
                evidence_count=negative_speech.trials,
                required_evidence_count=1,
            )
        )

        tts_reasons = tuple(
            r for r in verdict_reasons if r.section == "tts_echo_safety"
        )
        tts_status = CalibrationOverallStatus.PASS
        if tts_echo.playback_tests == 0:
            tts_status = CalibrationOverallStatus.NOT_TESTED
        elif tts_echo.live_acceptable_command_candidates > 0:
            tts_status = CalibrationOverallStatus.FAIL
        sections.append(
            CalibrationSectionOutcome(
                section="tts_echo_safety",
                status=tts_status,
                reasons=tts_reasons,
                evidence_count=tts_echo.playback_tests,
                required_evidence_count=1,
            )
        )

        return tuple(sections)

    def compute_noise_gate_recommendation(self, session: CalibrationSession) -> NoiseGateRecommendation:
        """Compute a noise-gate recommendation from calibration measurements."""
        from tournament_platform.app.services.voice_calibration.recommendations import (
            generate_noise_gate_recommendation,
        )

        silence = None
        speech = None
        for measurement in session.measurements:
            if isinstance(measurement, SilenceBaselineMetrics) and not measurement.capture.skipped:
                silence = measurement
            elif isinstance(measurement, SpeechLevelMetrics) and not measurement.capture.skipped:
                speech = measurement

        policy = NoiseGateRecommendationPolicy()
        return generate_noise_gate_recommendation(silence, speech, policy)

    def compute_live_voice_profile_recommendation(
        self,
        session: CalibrationSession,
        calibration_profile_id: str | None = None,
    ) -> LiveVoiceProfileRecommendation:
        """Compose a complete live voice profile recommendation from calibration data."""
        from tournament_platform.app.services.voice_calibration.recommendations import (
            generate_live_voice_profile_recommendation,
        )

        negative_speech = self.compute_negative_speech_safety(session)
        tts_echo = self.compute_tts_echo_safety(session)

        silence = None
        speech = None
        for measurement in session.measurements:
            if isinstance(measurement, SilenceBaselineMetrics) and not measurement.capture.skipped:
                silence = measurement
            elif isinstance(measurement, SpeechLevelMetrics) and not measurement.capture.skipped:
                speech = measurement

        confirmed_aliases = tuple(
            a for a in session.alias_candidates
            if getattr(a, "confirmed", False)
            or getattr(a, "status", None) == AliasCandidateStatus.CONFIRMED
        )

        return generate_live_voice_profile_recommendation(
            calibration_session_id=session.session_id,
            calibration_profile_id=calibration_profile_id,
            identity=self.build_profile_identity(session=session),
            silence=silence,
            speech=speech,
            negative_speech=negative_speech,
            tts_echo=tts_echo,
            confirmed_aliases=confirmed_aliases,  # type: ignore[arg-type]  # session.alias_candidates mixes types
            preferred_phrases=session.phrase_candidates,
            selected_asr_config=None,
            policy=NoiseGateRecommendationPolicy(),
        )

    def _validate_activation_eligibility(
        self,
        recommendation: LiveVoiceProfileRecommendation,
    ) -> VoiceProfileActivationStatus:
        """Validate whether a recommendation can be activated."""
        if recommendation.status == RecommendationStatus.INVALID_DATA:
            return VoiceProfileActivationStatus.BLOCKED
        if recommendation.status == RecommendationStatus.DEVICE_MISMATCH:
            return VoiceProfileActivationStatus.BLOCKED
        if recommendation.status == RecommendationStatus.UNAVAILABLE:
            return VoiceProfileActivationStatus.BLOCKED
        if recommendation.status == RecommendationStatus.WARNING:
            return VoiceProfileActivationStatus.ACTIVE_NEEDS_VERIFICATION
        if recommendation.status == RecommendationStatus.AVAILABLE:
            return VoiceProfileActivationStatus.ACTIVE_NEEDS_VERIFICATION
        return VoiceProfileActivationStatus.BLOCKED

    def register_phrase_candidates(
        self,
        session: CalibrationSession,
        candidates: tuple[CommandPhraseCandidate, ...],
    ) -> CalibrationSession:
        """Register phrase candidates for phrase comparison.

        Returns a new session with the candidates appended.
        """
        existing = {c.phrase_id: c for c in session.phrase_candidates}
        for candidate in candidates:
            existing[candidate.phrase_id] = candidate
        return replace(session, phrase_candidates=tuple(existing.values()), revision=session.revision + 1)

    def audit_asr_capabilities(
        self,
        provider: str = "faster_whisper",
    ) -> AsrProviderCapabilities:
        """Return the detected capability profile for the requested ASR provider.

        This method must never raise for an unsupported provider name; it
        returns a capability object with safe defaults so callers can decide
        whether to run an experiment.
        """
        if provider != "faster_whisper":
            return AsrProviderCapabilities(
                provider=provider,
                supports_hotwords=False,
                supports_initial_prompt=False,
                supports_condition_on_previous_text=False,
                supports_word_probabilities=False,
                supports_no_speech_probability=False,
                supports_average_log_probability=False,
            )

        return AsrProviderCapabilities(
            provider=provider,
            supports_hotwords=True,
            supports_initial_prompt=True,
            supports_condition_on_previous_text=True,
            supports_word_probabilities=False,
            supports_no_speech_probability=True,
            supports_average_log_probability=True,
        )

    def create_asr_experiment_configs(
        self,
        *,
        session: CalibrationSession | None = None,
        baseline: AsrExperimentConfig | None = None,
        candidate: AsrExperimentConfig | None = None,
    ) -> tuple[AsrExperimentConfig, AsrExperimentConfig]:
        """Return explicit baseline and candidate ASR experiment configurations.

        Callers may override either side; defaults follow the Phase 11 MVP.
        Session is optional because default configs do not depend on it.
        """
        if baseline is None:
            baseline = AsrExperimentConfig(
                config_id="baseline",
                display_name="Current production ASR",
                language="en",
                hotwords=None,
                initial_prompt=None,
                condition_on_previous_text=None,
                beam_size=None,
            )
        if candidate is None:
            candidate = AsrExperimentConfig(
                config_id="candidate",
                display_name="Command-hint configuration",
                language="en",
                hotwords="point red, red point, point to red, point blue, blue point, point to blue, undo point, reset game",
                initial_prompt="Table tennis score commands: point red, point blue, undo, reset game.",
                condition_on_previous_text=False,
                beam_size=5,
            )
        return baseline, candidate

    def create_asr_ab_work_item(
        self,
        *,
        experiment_id: str,
        sample_id: str,
        session: CalibrationSession,
        capture_kind: str,
        audio_bytes: bytes,
        sample_rate_hz: int,
        expected_command_id: str | None = None,
        expected_phrase: str | None = None,
        baseline: AsrExperimentConfig | None = None,
        candidate: AsrExperimentConfig | None = None,
    ) -> AsrAbWorkItem:
        """Create an immutable same-audio A/B work item.

        The caller must discard the resulting work item after both
        transcriptions complete.
        """
        baseline_cfg, candidate_cfg = self.create_asr_experiment_configs(
            session=session,
            baseline=baseline,
            candidate=candidate,
        )
        return AsrAbWorkItem(
            experiment_id=experiment_id,
            sample_id=sample_id,
            calibration_session_id=session.session_id,
            capture_kind=capture_kind,
            expected_command_id=expected_command_id,
            expected_phrase=expected_phrase,
            baseline_config=baseline_cfg,
            candidate_config=candidate_cfg,
            audio_bytes=audio_bytes,
            sample_rate_hz=sample_rate_hz,
        )

    def _parse_experiment_transcript(
        self,
        transcript: str,
    ) -> tuple[str | None, float | None]:
        """Parse a transcript and return (command_id, confidence)."""
        if not transcript or not transcript.strip():
            return None, None
        try:
            parse_result = self._grammar.parse(transcript)
            command_id = self._resolve_command_id(parse_result)
            return command_id, parse_result.confidence
        except Exception:
            return None, None

    def consume_asr_ab_results(
        self,
        session: CalibrationSession,
        result: AsrAbSampleResult,
    ) -> CalibrationSession:
        """Append an A/B result to a session and return a new session."""
        existing = {r.sample_id: r for r in session.asr_ab_results}
        existing[result.sample_id] = result
        return replace(session, asr_ab_results=tuple(existing.values()), revision=session.revision + 1)

    def compute_asr_experiment_aggregate(
        self,
        *,
        session: CalibrationSession,
        config_id: str,
        capture_kind: str | None = None,
    ) -> AsrExperimentAggregate:
        """Aggregate A/B results for a specific configuration."""
        results = [
            r for r in session.asr_ab_results
            if r.baseline.config_id == config_id or r.candidate.config_id == config_id
        ]
        if capture_kind is not None:
            results = [r for r in results if r.capture_kind == capture_kind]

        positive_attempts = 0
        exact_matches = 0
        parser_successes = 0
        wrong_command_count = 0
        unknown_count = 0
        negative_false_candidate_count = 0
        tts_false_candidate_count = 0
        total_negative_samples = 0
        total_tts_samples = 0
        latencies: list[float] = []

        for result in results:
            transcript = result.baseline if result.baseline.config_id == config_id else result.candidate
            if not transcript:
                continue

            latencies.append(transcript.latency_ms)

            if result.capture_kind == CalibrationCaptureKind.COMMAND_TRIAL.value:
                positive_attempts += 1
                if transcript.parser_command_id and transcript.parser_command_id != "unknown":
                    parser_successes += 1
                if (
                    transcript.parser_command_id
                    and transcript.parser_command_id != "unknown"
                    and transcript.parser_command_id == result.expected_command_id
                    and transcript.would_accept_live
                ):
                    exact_matches += 1
                if transcript.parser_command_id and transcript.parser_command_id != "unknown":
                    if transcript.parser_command_id != result.expected_command_id:
                        wrong_command_count += 1
                if transcript.parser_command_id == "unknown":
                    unknown_count += 1

            if result.capture_kind == CalibrationCaptureKind.NEGATIVE_TRIAL.value:
                total_negative_samples += 1
                if transcript.would_accept_live:
                    negative_false_candidate_count += 1

            if result.capture_kind == CalibrationCaptureKind.TTS_ECHO_TEST.value:
                total_tts_samples += 1
                if transcript.would_accept_live:
                    tts_false_candidate_count += 1

        median_latency = None
        p95_latency = None
        if latencies:
            sorted_latencies = sorted(latencies)
            mid = len(sorted_latencies) // 2
            median_latency = (
                sorted_latencies[mid] if len(sorted_latencies) % 2 == 1
                else (sorted_latencies[mid - 1] + sorted_latencies[mid]) / 2
            )
            p95_index = int(len(sorted_latencies) * 0.95)
            p95_index = min(p95_index, len(sorted_latencies) - 1)
            p95_latency = sorted_latencies[p95_index]

        return AsrExperimentAggregate(
            config_id=config_id,
            positive_attempts=positive_attempts,
            exact_matches=exact_matches,
            parser_successes=parser_successes,
            wrong_command_count=wrong_command_count,
            unknown_count=unknown_count,
            negative_false_candidate_count=negative_false_candidate_count,
            tts_false_candidate_count=tts_false_candidate_count,
            total_negative_samples=total_negative_samples,
            total_tts_samples=total_tts_samples,
            median_latency_ms=median_latency,
            p95_latency_ms=p95_latency,
        )

    def recommend_asr_config(
        self,
        *,
        session: CalibrationSession,
        baseline_config_id: str = "baseline",
        candidate_config_id: str = "candidate",
        min_positive_attempts: int = 3,
        min_negative_samples: int = 1,
        min_tts_samples: int = 1,
    ) -> tuple[AsrExperimentRecommendation, str]:
        """Return a deterministic safety-first recommendation for the ASR config.

        Returns (recommendation, reason).
        """
        baseline = self.compute_asr_experiment_aggregate(
            session=session, config_id=baseline_config_id
        )
        candidate = self.compute_asr_experiment_aggregate(
            session=session, config_id=candidate_config_id
        )

        if candidate.negative_false_candidate_count > baseline.negative_false_candidate_count:
            return AsrExperimentRecommendation.CANDIDATE_UNSAFE, "negative_false_candidates_increased"
        if candidate.tts_false_candidate_count > baseline.tts_false_candidate_count:
            return AsrExperimentRecommendation.CANDIDATE_UNSAFE, "tts_false_candidates_increased"
        if candidate.wrong_command_count > baseline.wrong_command_count:
            return AsrExperimentRecommendation.CANDIDATE_UNSAFE, "wrong_command_count_increased"
        if candidate.positive_attempts < min_positive_attempts:
            return AsrExperimentRecommendation.MORE_SAMPLES_REQUIRED, "insufficient_positive_attempts"
        if max(baseline.total_negative_samples, candidate.total_negative_samples) < min_negative_samples:
            return AsrExperimentRecommendation.MORE_SAMPLES_REQUIRED, "insufficient_negative_samples"
        if max(baseline.total_tts_samples, candidate.total_tts_samples) < min_tts_samples:
            return AsrExperimentRecommendation.MORE_SAMPLES_REQUIRED, "insufficient_tts_samples"
        if candidate.parser_successes <= baseline.parser_successes:
            return AsrExperimentRecommendation.BASELINE_RETAINED, "no_parser_success_improvement"

        if candidate.exact_matches > baseline.exact_matches:
            return AsrExperimentRecommendation.CANDIDATE_RECOMMENDED, "exact_match_improved"
        if candidate.parser_successes > baseline.parser_successes:
            return AsrExperimentRecommendation.CANDIDATE_RECOMMENDED, "parser_success_improved"
        if candidate.median_latency_ms is not None and baseline.median_latency_ms is not None:
            if candidate.median_latency_ms <= baseline.median_latency_ms:
                return AsrExperimentRecommendation.CANDIDATE_RECOMMENDED, "latency_improved_or_equal"

        return AsrExperimentRecommendation.BASELINE_RETAINED, "tied_or_latency_regression"

    def create_asr_ab_worker(
        self,
        *,
        max_queue_size: int = 16,
    ) -> AsrAbWorker:
        """Create a configured A/B worker for same-audio experiments."""
        from tournament_platform.app.services.voice_calibration.asr_ab_worker import (
            AsrAbWorker,
        )

        def _transcribe(audio: bytes, config: AsrExperimentConfig) -> TranscriptionResult:
            asr = self._get_experiment_asr()
            if asr is None:
                return TranscriptionResult(text="")
            return asr.transcribe_experiment(audio=audio, config=config)

        def _parse(text: str):
            if not text or not text.strip():
                return type("Parsed", (), {"command_id": None, "confidence": None})()
            try:
                parse_result = self._grammar.parse(text)
                command_id = self._resolve_command_id(parse_result)
                return type("Parsed", (), {"command_id": command_id, "confidence": parse_result.confidence})()
            except Exception:
                return type("Parsed", (), {"command_id": None, "confidence": None})()

        worker = AsrAbWorker(max_queue_size=max_queue_size)
        worker.configure(transcribe_fn=_transcribe, parse_fn=_parse)
        return worker

    def drain_asr_ab_results(
        self,
        session: CalibrationSession,
        worker: AsrAbWorker,
    ) -> CalibrationSession:
        """Drain completed A/B results from the worker into the session."""
        results = worker.drain_results()
        for result in results:
            session = self.consume_asr_ab_results(session, result)
        return session

    def _get_experiment_asr(self):
        """Return an ASR backend for experiments, or None if unavailable."""
        try:
            from tournament_platform.app.services.asr_backends.factory import ASRBackendFactory
            backend = ASRBackendFactory.create()
            if backend.is_available():
                return backend
        except Exception:
            pass
        return None


    def compute_phrase_comparison(
        self,
        session: CalibrationSession,
    ) -> tuple[PhraseComparisonResult, ...]:
        """Aggregate phrase comparison results from immutable trial data.

        Groups command trials by phrase_id and computes metrics per phrase.
        Only includes trials that have an expected_phrase_id set.
        """
        from statistics import median
        from collections import defaultdict

        phrase_groups: dict[str, list[CommandTrial]] = defaultdict(list)
        for trial in session.trials:
            if trial.expected_phrase_id is None:
                continue
            phrase_groups[trial.expected_phrase_id].append(trial)

        # Build candidate lookup for display_phrase and command_id
        candidate_lookup = {c.phrase_id: c for c in session.phrase_candidates}

        results = []
        for phrase_id, trials in phrase_groups.items():
            candidate = candidate_lookup.get(phrase_id)
            command_id = (
                candidate.command_id
                if candidate
                else trials[0].expected_command_id
            )
            display_phrase = (
                candidate.display_phrase
                if candidate
                else trials[0].expected_phrase
            )

            attempts = len(trials)
            exact_matches = sum(
                1
                for t in trials
                if t.classification == TrialClassification.EXACT
            )
            parser_successes = sum(
                1
                for t in trials
                if t.classification
                in {TrialClassification.EXACT, TrialClassification.VARIANT}
            )
            wrong_command_count = sum(
                1
                for t in trials
                if t.classification == TrialClassification.WRONG_COMMAND
            )
            unknown_count = sum(
                1
                for t in trials
                if t.classification == TrialClassification.UNKNOWN
            )
            false_accept_count = sum(
                1
                for t in trials
                if t.resolved_command_id in {"score_point", "undo", "reset_match"}
                and t.resolved_command_id != t.expected_command_id
            )

            latencies = [
                t.asr_latency_ms
                for t in trials
                if t.asr_latency_ms is not None
            ]
            median_latency = median(latencies) if latencies else None
            if latencies:
                sorted_latencies = sorted(latencies)
                p95_index = int(len(sorted_latencies) * 0.95)
                p95_index = min(p95_index, len(sorted_latencies) - 1)
                p95_latency = sorted_latencies[p95_index]
            else:
                p95_latency = None

            results.append(
                PhraseComparisonResult(
                    phrase_id=phrase_id,
                    command_id=command_id,
                    display_phrase=display_phrase,
                    attempts=attempts,
                    exact_matches=exact_matches,
                    parser_successes=parser_successes,
                    wrong_command_count=wrong_command_count,
                    unknown_count=unknown_count,
                    false_accept_count=false_accept_count,
                    median_latency_ms=median_latency,
                    p95_latency_ms=p95_latency,
                )
            )

        return tuple(results)

    def recommend_phrase(
        self,
        session: CalibrationSession,
        command_id: str,
        *,
        canonical_phrase_id: str | None = None,
    ) -> PhraseComparisonResult | None:
        """Recommend the best phrase for a command using
        deterministic safety-first rules.

        Returns None if no reliable preference can be determined.
        """
        negative_safety = self.compute_negative_speech_safety(session)
        if (
            negative_safety.false_live_acceptable_candidates
            > 0
        ):
            return None

        all_results = self.compute_phrase_comparison(session)
        command_results = [
            r for r in all_results if r.command_id == command_id
        ]

        if not command_results:
            return None

        # Filter out unsafe candidates
        safe_results = [
            r for r in command_results
            if r.wrong_command_count == 0 and r.false_accept_count == 0
        ]

        if not safe_results:
            return None

        # Sort by deterministic criteria:
        # 1. Highest parser-success rate
        # 2. Highest exact-match rate
        # 3. Lowest unknown rate
        # 4. Lowest median latency
        # 5. Existing canonical phrase wins ties
        def sort_key(result: PhraseComparisonResult) -> tuple:
            parser_rate = (
                result.parser_successes / result.attempts
                if result.attempts > 0
                else 0.0
            )
            exact_rate = (
                result.exact_matches / result.attempts
                if result.attempts > 0
                else 0.0
            )
            unknown_rate = (
                result.unknown_count / result.attempts
                if result.attempts > 0
                else 1.0
            )
            median_latency = (
                result.median_latency_ms
                if result.median_latency_ms is not None
                else float("inf")
            )
            is_canonical = (
                0 if result.phrase_id == canonical_phrase_id else 1
            )
            return (
                -parser_rate,
                -exact_rate,
                unknown_rate,
                median_latency,
                is_canonical,
                result.phrase_id,
            )

        sorted_results = sorted(safe_results, key=sort_key)
        return sorted_results[0]

    def compute_alias_candidates(
        self,
        *,
        session: CalibrationSession,
        language: str = "en",
    ) -> tuple[AliasConfirmationCandidate, ...]:
        """Inspect positive trials and return alias candidates with eligibility flags."""
        seen: dict[str, AliasConfirmationCandidate] = {}
        for trial in session.trials:
            if trial.classification not in {
                TrialClassification.EXACT,
                TrialClassification.VARIANT,
            }:
                continue
            raw = trial.raw_transcript.strip()
            if not raw:
                continue
            normalized = raw.lower()
            canonical = (trial.expected_phrase or "").strip().lower()
            if not canonical:
                continue
            if normalized == canonical:
                continue

            key = (trial.expected_command_id, normalized)
            if key in seen:
                existing = seen[key]
                seen[key] = dataclasses.replace(
                    existing,
                    occurrence_count=existing.occurrence_count + 1,
                )
                continue

            rejection_reasons: list[str] = []
            words = set(normalized.split())
            if len(words) > 6:
                rejection_reasons.append("transcript_too_long")
            if len(words) == 1:
                rejection_reasons.append("generic_single_word")
            conflicting = words & {"undo", "reset"}
            if conflicting:
                rejection_reasons.append("conflicting_action_words")
            collision_ids: list[str] = []
            for other_trial in session.trials:
                if other_trial.expected_command_id == trial.expected_command_id:
                    continue
                other_norm = (
                    other_trial.raw_transcript or ""
                ).strip().lower()
                if other_norm and other_norm == normalized and other_trial.classification in {
                    TrialClassification.EXACT,
                    TrialClassification.VARIANT,
                }:
                    collision_ids.append(other_trial.expected_command_id)
            if collision_ids:
                rejection_reasons.append(
                    "cross_command_collision:" + ",".join(collision_ids)
                )
            if language not in {"en", ""}:
                rejection_reasons.append("language_mismatch")
            candidate = AliasConfirmationCandidate(
                candidate_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{session.session_id}:{trial.expected_command_id}:{normalized}",
                    )
                ),
                calibration_session_id=session.session_id,
                source_trial_id=trial.trial_id,
                command_id=trial.expected_command_id,
                language=language,
                raw_transcript=raw,
                normalized_alias=normalized,
                expected_phrase=trial.expected_phrase or "",
                occurrence_count=1,
                collision_command_ids=tuple(dict.fromkeys(collision_ids)),
                eligible=not rejection_reasons,
                rejection_reasons=tuple(rejection_reasons),
                status=(
                    AliasCandidateStatus.PENDING
                    if not rejection_reasons
                    else AliasCandidateStatus.INELIGIBLE
                ),
            )
            seen[key] = candidate

        return tuple(seen.values())

    def confirm_alias(
        self,
        *,
        session: CalibrationSession,
        candidate_id: str,
    ) -> CalibrationSession:
        """Confirm an eligible alias candidate. Returns a new session."""
        candidates = self.compute_alias_candidates(session=session)
        target = None
        for c in candidates:
            if c.candidate_id == candidate_id:
                target = c
                break
        if target is None:
            return session
        if not target.eligible:
            return session
        updated_aliases = []
        for a in session.alias_candidates:
            if a.candidate_id == candidate_id:
                if a.status == AliasCandidateStatus.CONFIRMED:
                    return session
                updated_aliases.append(
                    dataclasses.replace(
                        a,
                        status=AliasCandidateStatus.CONFIRMED,
                    )
                )
            else:
                updated_aliases.append(a)
        if not any(a.candidate_id == candidate_id for a in updated_aliases):
            updated_aliases.append(
                AliasConfirmationCandidate(
                    candidate_id=target.candidate_id,
                    calibration_session_id=target.calibration_session_id,
                    source_trial_id=target.source_trial_id,
                    command_id=target.command_id,
                    language=target.language,
                    raw_transcript=target.raw_transcript,
                    normalized_alias=target.normalized_alias,
                    expected_phrase=target.expected_phrase,
                    occurrence_count=target.occurrence_count,
                    collision_command_ids=target.collision_command_ids,
                    eligible=target.eligible,
                    rejection_reasons=target.rejection_reasons,
                    status=AliasCandidateStatus.CONFIRMED,
                )
            )
        return replace(session, alias_candidates=tuple(updated_aliases), revision=session.revision + 1)

    def reject_alias(
        self,
        *,
        session: CalibrationSession,
        candidate_id: str,
    ) -> CalibrationSession:
        """Reject an alias candidate. Returns a new session."""
        candidates = self.compute_alias_candidates(session=session)
        target = None
        for c in candidates:
            if c.candidate_id == candidate_id:
                target = c
                break
        if target is None:
            return session
        updated_aliases = []
        for a in session.alias_candidates:
            if a.candidate_id == candidate_id:
                if a.status == AliasCandidateStatus.REJECTED:
                    return session
                updated_aliases.append(
                    dataclasses.replace(
                        a,
                        status=AliasCandidateStatus.REJECTED,
                    )
                )
            else:
                updated_aliases.append(a)
        if not any(a.candidate_id == candidate_id for a in updated_aliases):
            updated_aliases.append(
                AliasConfirmationCandidate(
                    candidate_id=target.candidate_id,
                    calibration_session_id=target.calibration_session_id,
                    source_trial_id=target.source_trial_id,
                    command_id=target.command_id,
                    language=target.language,
                    raw_transcript=target.raw_transcript,
                    normalized_alias=target.normalized_alias,
                    expected_phrase=target.expected_phrase,
                    occurrence_count=target.occurrence_count,
                    collision_command_ids=target.collision_command_ids,
                    eligible=target.eligible,
                    rejection_reasons=target.rejection_reasons,
                    status=AliasCandidateStatus.REJECTED,
                )
        )
        return replace(session, alias_candidates=tuple(updated_aliases), revision=session.revision + 1)

    def build_profile_identity(
        self,
        *,
        session: CalibrationSession,
        asr_provider: str | None = None,
        asr_model: str | None = None,
        compute_type: str | None = None,
        microphone_device_hash: str | None = None,
        sample_rate_hz: int | None = None,
    ) -> CalibrationProfileIdentity:
        """Build a CalibrationProfileIdentity from session context and ASR config."""
        confirmed_aliases = self._collect_confirmed_aliases(session)
        language = "en"
        if confirmed_aliases:
            first = confirmed_aliases[0]
            if first.language:
                language = first.language
        return CalibrationProfileIdentity(
            language=language,
            asr_provider=asr_provider or "",
            asr_model=asr_model or "",
            compute_type=compute_type,
            microphone_device_hash=microphone_device_hash,
            sample_rate_hz=sample_rate_hz,
            profile_schema_version=1,
        )

    def _collect_confirmed_aliases(
        self, session: CalibrationSession
    ) -> tuple[AliasConfirmationCandidate, ...]:
        """Extract confirmed aliases from a session."""
        confirmed = []
        for a in session.alias_candidates:
            status = getattr(a, "status", None)
            confirmed_flag = getattr(a, "confirmed", False)
            if confirmed_flag or status == AliasCandidateStatus.CONFIRMED:
                confirmed.append(a)
        return tuple(confirmed)

    def build_calibration_profile(
        self,
        *,
        session: CalibrationSession,
        identity: CalibrationProfileIdentity,
        owner_id: str,
        preferred_phrases: tuple[str, ...] | None = None,
        profile_id: str | None = None,
    ) -> VoiceCalibrationProfile:
        """Construct a VoiceCalibrationProfile from calibration session data."""
        now = time.time()
        acoustic_summary = self.compute_acoustic_summary(session)
        negative_speech = self.compute_negative_speech_safety(session)
        tts_echo = self.compute_tts_echo_safety(session)
        confirmed_aliases = self._collect_confirmed_aliases(session)

        return VoiceCalibrationProfile(
            profile_id=profile_id or str(uuid.uuid4()),
            owner_id=owner_id,
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=preferred_phrases or (),
            confirmed_aliases=confirmed_aliases,
            selected_asr_config=None,
            acoustic_summary=acoustic_summary,
            negative_speech_outcome=negative_speech,
            tts_echo_outcome=tts_echo,
            verification_metadata=VerificationMetadata(
                verified_at=now,
                verification_notes=("built_from_calibration_session",),
            ),
            created_at=now,
            updated_at=now,
        )

    def verify_profile_identity(
        self,
        profile: VoiceCalibrationProfile,
        current_identity: CalibrationProfileIdentity,
    ) -> tuple[CalibrationProfileStatus, tuple[str, ...]]:
        """Return the verification status and mismatch reasons for a profile."""
        if profile.identity == current_identity:
            return CalibrationProfileStatus.VERIFIED, ()
        reasons: list[str] = []
        if profile.identity.language != current_identity.language:
            reasons.append("language_mismatch")
        if profile.identity.asr_provider != current_identity.asr_provider:
            reasons.append("asr_provider_mismatch")
        if profile.identity.asr_model != current_identity.asr_model:
            reasons.append("asr_model_mismatch")
        if profile.identity.compute_type != current_identity.compute_type:
            reasons.append("compute_type_mismatch")
        if profile.identity.microphone_device_hash != current_identity.microphone_device_hash:
            reasons.append("microphone_device_hash_mismatch")
        if profile.identity.sample_rate_hz != current_identity.sample_rate_hz:
            reasons.append("sample_rate_hz_mismatch")
        if profile.identity.profile_schema_version != current_identity.profile_schema_version:
            reasons.append("schema_version_mismatch")
        return CalibrationProfileStatus.NEEDS_VERIFICATION, tuple(reasons)

    def save_profile(
        self,
        store: CalibrationProfileStore,
        owner_id: str,
        profile: VoiceCalibrationProfile,
    ) -> None:
        """Persist a calibration profile."""
        store.save(owner_id, profile)

    def load_profile(
        self,
        store: CalibrationProfileStore,
        owner_id: str,
        identity: CalibrationProfileIdentity,
    ) -> VoiceCalibrationProfile | None:
        """Load a calibration profile by owner and identity."""
        return store.load(owner_id, identity)

    def delete_profile(
        self,
        store: CalibrationProfileStore,
        owner_id: str,
        profile_id: str,
    ) -> None:
        """Delete a calibration profile."""
        store.delete(owner_id, profile_id)

    def activate_profile(
        self,
        store: CalibrationProfileStore,
        owner_id: str,
        identity: CalibrationProfileIdentity,
    ) -> VoiceCalibrationProfile | None:
        """Load a profile, verify identity, and mark it active.

        Returns the active profile or None if not found or verification fails.
        """
        profile = store.load(owner_id, identity)
        if profile is None:
            return None
        status, _ = self.verify_profile_identity(profile, identity)
        if status != CalibrationProfileStatus.VERIFIED:
            return None
        return profile

    def deactivate_profile(
        self,
        store: CalibrationProfileStore,
        owner_id: str,
        profile_id: str,
    ) -> None:
        """Remove a profile from the active store."""
        store.delete(owner_id, profile_id)
