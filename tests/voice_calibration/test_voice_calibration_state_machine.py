"""
Tests for voice calibration state machine.
"""

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationPhase,
    CalibrationState,
)
from tournament_platform.app.services.voice_calibration.state_machine import (
    CalibrationPhaseMachine,
)


class TestInitialStateIsIdle:
    def test_initial_state_is_idle(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.IDLE)
        assert state.phase == CalibrationPhase.IDLE

    def test_idle_can_transition_to_environment_check(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.IDLE)
        new = sm.transition(state, CalibrationPhase.ENVIRONMENT_CHECK)
        assert new.phase == CalibrationPhase.ENVIRONMENT_CHECK
        assert new.revision == 1


class TestValidPhaseTransition:
    def test_valid_forward_transition_sequence(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.IDLE)

        state = sm.transition(state, CalibrationPhase.ENVIRONMENT_CHECK)
        assert state.phase == CalibrationPhase.ENVIRONMENT_CHECK

        state = sm.transition(state, CalibrationPhase.MEASURING_SILENCE)
        assert state.phase == CalibrationPhase.MEASURING_SILENCE

        state = sm.transition(state, CalibrationPhase.MEASURING_SPEECH)
        assert state.phase == CalibrationPhase.MEASURING_SPEECH

        state = sm.transition(state, CalibrationPhase.COMMAND_TRIAL)
        assert state.phase == CalibrationPhase.COMMAND_TRIAL

    def test_revision_increments_on_each_transition(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.IDLE, revision=0)

        state = sm.transition(state, CalibrationPhase.ENVIRONMENT_CHECK)
        assert state.revision == 1

        state = sm.transition(state, CalibrationPhase.MEASURING_SILENCE)
        assert state.revision == 2

    def test_command_trial_to_negative_trial(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMMAND_TRIAL)
        new = sm.transition(state, CalibrationPhase.NEGATIVE_TRIAL)
        assert new.phase == CalibrationPhase.NEGATIVE_TRIAL

    def test_negative_trial_back_to_command_trial(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.NEGATIVE_TRIAL)
        new = sm.transition(state, CalibrationPhase.COMMAND_TRIAL)
        assert new.phase == CalibrationPhase.COMMAND_TRIAL


class TestInvalidPhaseTransitionRejected:
    def test_idle_to_command_trial_rejected(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.IDLE)
        with pytest.raises(ValueError, match="Invalid calibration transition"):
            sm.transition(state, CalibrationPhase.COMMAND_TRIAL)

    def test_completed_to_command_trial_rejected(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMPLETED)
        with pytest.raises(ValueError, match="Invalid calibration transition"):
            sm.transition(state, CalibrationPhase.COMMAND_TRIAL)

    def test_completed_to_review_rejected(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMPLETED)
        with pytest.raises(ValueError, match="Invalid calibration transition"):
            sm.transition(state, CalibrationPhase.REVIEW)

    def test_measuring_silence_to_review_rejected(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.MEASURING_SILENCE)
        with pytest.raises(ValueError, match="Invalid calibration transition"):
            sm.transition(state, CalibrationPhase.REVIEW)


class TestCancelFromActivePhase:
    def test_cancel_from_measuring_speech(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.MEASURING_SPEECH)
        new = sm.transition(state, CalibrationPhase.IDLE)
        assert new.phase == CalibrationPhase.IDLE
        assert new.revision == 1

    def test_cancel_from_command_trial(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMMAND_TRIAL)
        new = sm.transition(state, CalibrationPhase.IDLE)
        assert new.phase == CalibrationPhase.IDLE

    def test_cancel_from_negative_trial(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.NEGATIVE_TRIAL)
        new = sm.transition(state, CalibrationPhase.IDLE)
        assert new.phase == CalibrationPhase.IDLE

    def test_cancel_from_review(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.REVIEW)
        new = sm.transition(state, CalibrationPhase.IDLE)
        assert new.phase == CalibrationPhase.IDLE


class TestCompletedSessionCannotResumeWithoutReset:
    def test_completed_can_only_go_to_idle(self):
        sm = CalibrationPhaseMachine()
        state = CalibrationState(session_id="s1", phase=CalibrationPhase.COMPLETED)

        assert sm.transition(state, CalibrationPhase.IDLE).phase == CalibrationPhase.IDLE

        with pytest.raises(ValueError):
            sm.transition(state, CalibrationPhase.COMMAND_TRIAL)

        with pytest.raises(ValueError):
            sm.transition(state, CalibrationPhase.REVIEW)

        with pytest.raises(ValueError):
            sm.transition(state, CalibrationPhase.SAVING)
