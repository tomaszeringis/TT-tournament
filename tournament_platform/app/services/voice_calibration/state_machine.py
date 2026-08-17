"""
Voice Calibration — Pure domain state machine.

Import-safe: no Streamlit, WebRTC, ASR, session state, or scoring imports.
"""

from __future__ import annotations

from tournament_platform.app.services.voice_calibration.models import (
    CalibrationPhase,
    CalibrationState,
)


class CalibrationPhaseMachine:
    """Deterministic state machine for voice calibration phases.

    Guarantees:
    - Only validated phase transitions are accepted.
    - Returns a new immutable CalibrationState on each transition.
    """

    _VALID_TRANSITIONS: dict[CalibrationPhase, set[CalibrationPhase]] = {
        CalibrationPhase.IDLE: {CalibrationPhase.ENVIRONMENT_CHECK},
        CalibrationPhase.ENVIRONMENT_CHECK: {
            CalibrationPhase.MEASURING_SILENCE,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.MEASURING_SILENCE: {
            CalibrationPhase.MEASURING_SPEECH,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.MEASURING_SPEECH: {
            CalibrationPhase.COMMAND_TRIAL,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.COMMAND_TRIAL: {
            CalibrationPhase.NEGATIVE_TRIAL,
            CalibrationPhase.TTS_ECHO_TEST,
            CalibrationPhase.REVIEW,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.NEGATIVE_TRIAL: {
            CalibrationPhase.COMMAND_TRIAL,
            CalibrationPhase.TTS_ECHO_TEST,
            CalibrationPhase.REVIEW,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.TTS_ECHO_TEST: {
            CalibrationPhase.COMMAND_TRIAL,
            CalibrationPhase.REVIEW,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.REVIEW: {
            CalibrationPhase.SAVING,
            CalibrationPhase.COMPLETED,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.SAVING: {
            CalibrationPhase.COMPLETED,
            CalibrationPhase.IDLE,
        },
        CalibrationPhase.COMPLETED: {CalibrationPhase.IDLE},
    }

    def transition(
        self,
        state: CalibrationState,
        target: CalibrationPhase,
    ) -> CalibrationState:
        """Transition to a new phase if the move is valid.

        Returns a new CalibrationState with an incremented revision.
        Raises ValueError if the transition is not allowed.
        """
        allowed = self._VALID_TRANSITIONS.get(state.phase, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid calibration transition from {state.phase} to {target}"
            )
        return CalibrationState(
            session_id=state.session_id,
            phase=target,
            revision=state.revision + 1,
        )
