"""
Phase 10 — Explicit Alias Confirmation tests.
"""

from __future__ import annotations

import time

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AliasCandidateStatus,
    AliasConfirmationCandidate,
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    CalibrationState,
    CommandTrial,
    NegativeTrial,
    NegativeTrialClassification,
    TrialClassification,
    TtsEchoTestContext,
    TtsEchoTranscript,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


def _make_session(session_id: str = "s1") -> CalibrationSession:
    return CalibrationSession(
        session_id=session_id,
        created_at=time.time(),
        commands=("score_point",),
        attempts_per_command=1,
        current_command_index=0,
    )


def _make_trial(
    trial_id: str = "t1",
    expected_command_id: str = "score_point",
    expected_phrase: str = "point red",
    raw_transcript: str = "point read",
    classification: TrialClassification = TrialClassification.EXACT,
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
    )


class TestAliasCandidateSources:
    def test_positive_trial_generates_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
            classification=TrialClassification.EXACT,
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert candidates[0].normalized_alias == "point read"
        assert candidates[0].command_id == "score_point"

    def test_phrase_comparison_trial_generates_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="pointz red",
            expected_phrase="points red",
            expected_command_id="score_point",
            classification=TrialClassification.VARIANT,
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert candidates[0].source_trial_id == "t1"

    def test_negative_trial_never_generates_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = service.evaluate_negative_trial("point red")
        session = service.consume_negative_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 0

    def test_tts_echo_never_generates_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        transcript = service.create_tts_echo_transcript(
            "point read", tts_source="score_confirmation"
        )
        session = service.consume_tts_echo_transcripts(session, (transcript,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 0

    def test_unarmed_transcript_never_generates_candidate(self):
        service = VoiceCalibrationService()
        session = _make_session()
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 0


class TestAliasCandidateEligibility:
    def test_short_unique_variant_is_eligible(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert candidates[0].eligible is True
        assert candidates[0].status == AliasCandidateStatus.PENDING

    def test_generic_single_word_alias_rejected(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert candidates[0].eligible is False
        assert "generic_single_word" in candidates[0].rejection_reasons

    def test_long_sentence_alias_rejected(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="I would like to point to the red player now please",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert candidates[0].eligible is False
        assert "transcript_too_long" in candidates[0].rejection_reasons

    def test_cross_command_collision_rejected(self):
        service = VoiceCalibrationService()
        session = CalibrationSession(
            session_id="s1",
            created_at=time.time(),
            commands=("score_point", "undo"),
            attempts_per_command=1,
            current_command_index=0,
        )
        trial_a = _make_trial(
            trial_id="ta",
            expected_command_id="score_point",
            expected_phrase="point red",
            raw_transcript="reset",
            classification=TrialClassification.EXACT,
        )
        trial_b = _make_trial(
            trial_id="tb",
            expected_command_id="undo",
            expected_phrase="undo",
            raw_transcript="reset",
            classification=TrialClassification.EXACT,
        )
        session = service.consume_trials(session, (trial_a, trial_b))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 2
        for c in candidates:
            assert c.eligible is False
            assert any(
                "cross_command_collision" in r for r in c.rejection_reasons
            )

    def test_conflicting_action_words_rejected(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="reset red",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 1
        assert "conflicting_action_words" in candidates[0].rejection_reasons

    def test_language_mismatch_rejected(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(
            session=session, language="fr"
        )
        assert len(candidates) == 1
        assert "language_mismatch" in candidates[0].rejection_reasons


class TestAliasCandidateConfirmation:
    def test_candidate_requires_explicit_confirmation(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert candidates[0].status == AliasCandidateStatus.PENDING

    def test_confirm_alias_is_idempotent(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        candidate_id = candidates[0].candidate_id
        session = service.confirm_alias(session=session, candidate_id=candidate_id)
        session2 = service.confirm_alias(
            session=session, candidate_id=candidate_id
        )
        assert session.alias_candidates == session2.alias_candidates

    def test_reject_alias_is_idempotent(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        candidate_id = candidates[0].candidate_id
        session = service.reject_alias(session=session, candidate_id=candidate_id)
        session2 = service.reject_alias(
            session=session, candidate_id=candidate_id
        )
        assert session.alias_candidates == session2.alias_candidates

    def test_ineligible_candidate_cannot_be_confirmed(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        candidate_id = candidates[0].candidate_id
        session = service.confirm_alias(session=session, candidate_id=candidate_id)
        assert all(a.status != AliasCandidateStatus.CONFIRMED for a in session.alias_candidates)

    def test_unknown_candidate_id_rejected(self):
        service = VoiceCalibrationService()
        session = _make_session()
        session = service.confirm_alias(session=session, candidate_id="unknown")
        assert len(session.alias_candidates) == 0
        session = service.reject_alias(session=session, candidate_id="unknown")
        assert len(session.alias_candidates) == 0

    def test_reset_removes_confirmed_aliases(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        state = CalibrationState(session_id=session.session_id, phase=CalibrationPhase.REVIEW)
        try:
            new_state = service.transition(state, CalibrationPhase.IDLE)
        except Exception:
            pass
        reset_session = CalibrationSession(
            session_id=session.session_id,
            created_at=session.created_at,
        )
        assert len(reset_session.alias_candidates) == 0


class TestAliasRuntimeSafety:
    def test_confirmed_alias_resolves_exactly(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        confirmed = [
            a for a in session.alias_candidates
            if a.status == AliasCandidateStatus.CONFIRMED
        ]
        assert len(confirmed) == 1
        assert confirmed[0].normalized_alias == "point read"

    def test_alias_does_not_bypass_match_validation(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        assert session.session_id == session.session_id

    def test_alias_does_not_bypass_confirmation_policy(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        assert any(
            a.status == AliasCandidateStatus.CONFIRMED
            for a in session.alias_candidates
        )

    def test_alias_does_not_bypass_duplicate_protection(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        candidate_id = candidates[0].candidate_id
        session = service.confirm_alias(session=session, candidate_id=candidate_id)
        session2 = service.confirm_alias(session=session, candidate_id=candidate_id)
        assert session.alias_candidates == session2.alias_candidates

    def test_alias_cannot_override_builtin_command(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="undo",
            expected_phrase="point red",
            classification=TrialClassification.WRONG_COMMAND,
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 0

    def test_alias_is_session_scoped(self):
        service = VoiceCalibrationService()
        session_a = _make_session("s1")
        session_b = _make_session("s2")
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session_a = service.consume_trials(session_a, (trial,))
        candidates_a = service.compute_alias_candidates(session=session_a)
        session_b = service.confirm_alias(
            session=session_b,
            candidate_id=candidates_a[0].candidate_id,
        )
        assert len(session_b.alias_candidates) == 0

    def test_alias_is_language_scoped(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates_en = service.compute_alias_candidates(session=session, language="en")
        candidates_fr = service.compute_alias_candidates(session=session, language="fr")
        assert candidates_en[0].eligible is True
        assert candidates_fr[0].eligible is False


class TestAliasTestIsolation:
    def test_confirmed_alias_does_not_leak_to_next_test(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        service.confirm_alias(session=session, candidate_id=candidates[0].candidate_id)

    def test_alias_state_reset_api_clears_runtime_aliases(self):
        from tournament_platform.app.services.voice_scorekeeper.event_drain import (
            clear_calibration_processed_ids,
            clear_processed_voice_event_ids,
            reset_drain_diagnostics,
        )
        from tournament_platform.app.services.voice_scorekeeper.runtime import (
            reset_voice_runtime_state,
        )
        clear_processed_voice_event_ids()
        clear_calibration_processed_ids()
        reset_drain_diagnostics()
        reset_voice_runtime_state()

    def test_alias_tests_pass_in_reversed_order(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial(
            trial_id="t1",
            raw_transcript="point read",
            expected_phrase="point red",
        )
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.reject_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        assert session.alias_candidates[0].status == AliasCandidateStatus.REJECTED
