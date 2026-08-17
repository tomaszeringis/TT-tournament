"""
Phase 7 — Negative Speech and TTS Echo Safety tests.
"""

from __future__ import annotations

import time

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationCaptureContext,
    CalibrationCaptureKind,
    CalibrationMeasurementKind,
    CalibrationPhase,
    CalibrationSession,
    CalibrationState,
    NegativeTrial,
    NegativeTrialClassification,
    TtsEchoTestContext,
    TtsEchoTranscript,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


class TestNegativeTrialEvaluation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_red_in_unrelated_sentence_does_not_score(self):
        trial = self.service.evaluate_negative_trial("I like the red shirt")
        assert trial.parser_command_id == "score_point"
        assert trial.would_accept_live is True
        assert trial.classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE

    def test_blue_in_unrelated_sentence_does_not_score(self):
        trial = self.service.evaluate_negative_trial("Blue is my favorite color")
        assert trial.parser_command_id == "score_point"
        assert trial.would_accept_live is True
        assert trial.classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE

    def test_player_name_without_command_does_not_score(self):
        trial = self.service.evaluate_negative_trial("Tomas played well")
        assert trial.classification == NegativeTrialClassification.CORRECTLY_REJECTED

    def test_negative_trial_wrong_command_is_recorded(self):
        trial = self.service.evaluate_negative_trial("point blue")
        assert trial.classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE
        assert trial.parser_command_id == "score_point"
        assert trial.classification == "false_point_candidate"

    def test_blue_in_unrelated_sentence_does_not_score(self):
        trial = self.service.evaluate_negative_trial("Blue is my favorite color")
        assert trial.parser_command_id == "score_point"

    def test_player_name_without_command_does_not_score(self):
        trial = self.service.evaluate_negative_trial("Tomas played well")
        assert trial.classification == "correctly_rejected"

    def test_negative_trial_wrong_command_is_recorded(self):
        trial = self.service.evaluate_negative_trial("point blue")
        assert trial.classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE
        assert trial.parser_command_id == "score_point"

    def test_negative_trial_never_creates_alias_candidate(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_negative_trial("point red")
        updated = self.service.consume_negative_trials(session, (trial,))
        assert len(updated.negative_trials) == 1
        assert len(updated.alias_candidates) == 0

    def test_false_undo_candidate_classified(self):
        trial = self.service.evaluate_negative_trial("undo")
        assert trial.classification == "false_undo_candidate"

    def test_empty_transcript_does_not_score(self):
        trial = self.service.evaluate_negative_trial("")
        assert trial.classification == NegativeTrialClassification.NO_AUDIO

    def test_negative_trials_idempotent_by_trial_id(self):
        session = self.service.start_session("s1")
        trial = self.service.evaluate_negative_trial("point red")
        updated1 = self.service.consume_negative_trials(session, (trial,))
        updated2 = self.service.consume_negative_trials(updated1, (trial,))
        assert len(updated2.negative_trials) == 1


class TestTtsEchoTranscript:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_score_confirmation_echo_cannot_score(self):
        transcript = self.service.create_tts_echo_transcript(
            "point red",
            tts_source="score_confirmation",
        )
        assert transcript.tts_source == "score_confirmation"
        assert transcript.transcript == "point red"

    def test_commentary_echo_cannot_score(self):
        transcript = self.service.create_tts_echo_transcript(
            "Tomas played well",
            tts_source="commentary",
        )
        assert transcript.tts_source == "commentary"

    def test_tts_echo_result_is_recorded(self):
        session = self.service.start_session("s1")
        transcript = self.service.create_tts_echo_transcript("point red")
        updated = self.service.consume_tts_echo_transcripts(session, (transcript,))
        assert len(updated.tts_echo_transcripts) == 1

    def test_tts_guard_does_not_remain_active_after_test(self):
        session = self.service.start_session("s1")
        transcript = self.service.create_tts_echo_transcript("point red")
        updated = self.service.consume_tts_echo_transcripts(session, (transcript,))
        assert len(updated.tts_echo_transcripts) == 1
        assert updated.measurements == tuple()
        assert updated.trials == tuple()

    def test_live_scoring_resumes_after_echo_test(self):
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.TTS_ECHO_TEST)
        machine = VoiceCalibrationService()._phase_machine
        new_state = machine.transition(state, CalibrationPhase.REVIEW)
        assert new_state.phase == CalibrationPhase.REVIEW

    def test_tts_echo_transcripts_idempotent_by_transcript_id(self):
        session = self.service.start_session("s1")
        transcript = self.service.create_tts_echo_transcript("point red")
        updated1 = self.service.consume_tts_echo_transcripts(session, (transcript,))
        updated2 = self.service.consume_tts_echo_transcripts(updated1, (transcript,))
        assert len(updated2.tts_echo_transcripts) == 1


class TestPhase7StateMachine:
    def test_command_trial_to_negative_trial(self):
        machine = VoiceCalibrationService()._phase_machine
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMMAND_TRIAL)
        new_state = machine.transition(state, CalibrationPhase.NEGATIVE_TRIAL)
        assert new_state.phase == CalibrationPhase.NEGATIVE_TRIAL

    def test_negative_trial_to_tts_echo_test(self):
        machine = VoiceCalibrationService()._phase_machine
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.NEGATIVE_TRIAL)
        new_state = machine.transition(state, CalibrationPhase.TTS_ECHO_TEST)
        assert new_state.phase == CalibrationPhase.TTS_ECHO_TEST

    def test_tts_echo_test_to_review(self):
        machine = VoiceCalibrationService()._phase_machine
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.TTS_ECHO_TEST)
        new_state = machine.transition(state, CalibrationPhase.REVIEW)
        assert new_state.phase == CalibrationPhase.REVIEW


class TestRaceConditionAndLifecycle:
    def test_delayed_negative_event_cannot_become_tts_echo(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        negative_ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.NEGATIVE_TRIAL,
        )
        tts_ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t2",
            capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST,
        )

        assert negative_ctx.capture_kind == CalibrationCaptureKind.NEGATIVE_TRIAL
        assert tts_ctx.capture_kind == CalibrationCaptureKind.TTS_ECHO_TEST
        assert negative_ctx.capture_kind != tts_ctx.capture_kind

    def test_delayed_tts_echo_event_cannot_become_command_trial(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        command_ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t1",
            capture_kind=CalibrationCaptureKind.COMMAND_TRIAL,
            expected_command_id="point_red",
            expected_phrase="point red",
        )
        tts_ctx = CalibrationCaptureContext(
            calibration_session_id="s1",
            calibration_trial_id="t2",
            capture_kind=CalibrationCaptureKind.TTS_ECHO_TEST,
        )

        assert command_ctx.capture_kind == CalibrationCaptureKind.COMMAND_TRIAL
        assert tts_ctx.capture_kind == CalibrationCaptureKind.TTS_ECHO_TEST
        assert command_ctx.capture_kind != tts_ctx.capture_kind

    def test_previous_phase_event_rejected_after_phase_change(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        negative_trial = service.evaluate_negative_trial("point red")
        updated = service.consume_negative_trials(session, (negative_trial,))
        assert len(updated.negative_trials) == 1
        assert len(updated.trials) == 0

    def test_cancel_during_negative_asr_rejects_late_result(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMMAND_TRIAL)
        state = service.transition(state, CalibrationPhase.NEGATIVE_TRIAL)
        negative_trial = service.evaluate_negative_trial("point red")
        updated = service.consume_negative_trials(session, (negative_trial,))
        assert len(updated.negative_trials) == 1
        assert updated.negative_trials[0].classification == NegativeTrialClassification.FALSE_POINT_CANDIDATE

    def test_cancel_during_tts_playback_rejects_late_result(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        session, ctx = service.start_tts_echo_test(session, text="point red", voice_provider="browser")
        session = service.complete_tts_echo_test(session, ctx.playback_id)
        echo_transcript = service.create_tts_echo_transcript("point red", tts_playback_id=ctx.playback_id)
        updated = service.consume_tts_echo_transcripts(session, (echo_transcript,))
        assert len(updated.tts_echo_transcripts) == 1
        assert updated.tts_echo_transcripts[0].tts_playback_id == ctx.playback_id

    def test_tts_playback_guard_clears_after_exception(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        session, ctx = service.start_tts_echo_test(session, text="point red")
        assert len(session.tts_echo_test_contexts) == 1
        session = service.complete_tts_echo_test(session, ctx.playback_id)
        assert len(session.tts_echo_test_contexts) == 1
        assert session.tts_echo_test_contexts[0].playback_ended_at is not None

    def test_live_operator_speech_works_after_echo_test(self):
        service = VoiceCalibrationService()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.TTS_ECHO_TEST)
        new_state = service.transition(state, CalibrationPhase.REVIEW)
        assert new_state.phase == CalibrationPhase.REVIEW

    def test_tts_echo_test_does_not_leave_audio_playing(self):
        service = VoiceCalibrationService()
        session = service.start_session("s1")
        session, ctx = service.start_tts_echo_test(session, text="point red")
        assert len(session.tts_echo_test_contexts) == 1
        assert session.tts_echo_test_contexts[0].playback_ended_at is None
