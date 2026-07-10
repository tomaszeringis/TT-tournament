"""
Tests for VoiceConfirmationStateMachine (Phase 1).
"""

import time

import pytest

from tournament_platform.app.services.voice.confirmation import (
    ConfirmationState,
    VoiceConfirmationStateMachine,
)
from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult


def _make_result(intent=VoiceIntent.SET_SCORE, confidence=0.9):
    return VoiceParseResult(
        intent=intent,
        confidence=confidence,
        raw_transcript="set score five four",
        slots={"score_a": 5, "score_b": 4},
    )


class TestVoiceConfirmationStateMachine:
    def test_initial_state_is_idle(self):
        sm = VoiceConfirmationStateMachine()
        assert sm.state == ConfirmationState.IDLE
        assert sm.pending_result() is None
        assert sm.is_idle() is True

    def test_submit_enters_pending(self):
        sm = VoiceConfirmationStateMachine()
        result = _make_result()
        decision = sm.submit(result)
        assert decision == "pending"
        assert sm.state == ConfirmationState.PENDING
        assert sm.pending_result() is result

    def test_submit_rejects_when_already_pending(self):
        sm = VoiceConfirmationStateMachine()
        sm.submit(_make_result())
        decision = sm.submit(_make_result(VoiceIntent.UNDO))
        assert decision == "reject"
        assert sm.state == ConfirmationState.PENDING

    def test_confirm_returns_result_and_enters_confirmed(self):
        sm = VoiceConfirmationStateMachine()
        result = _make_result()
        sm.submit(result)
        confirmed = sm.confirm()
        assert confirmed is result
        assert sm.state == ConfirmationState.CONFIRMED
        assert sm.pending_result() is None

    def test_confirm_returns_none_when_idle(self):
        sm = VoiceConfirmationStateMachine()
        assert sm.confirm() is None

    def test_cancel_enters_cancelled(self):
        sm = VoiceConfirmationStateMachine()
        sm.submit(_make_result())
        sm.cancel()
        assert sm.state == ConfirmationState.CANCELLED
        assert sm.pending_result() is None

    def test_expire_enters_expired(self):
        sm = VoiceConfirmationStateMachine()
        sm.submit(_make_result())
        sm.expire()
        assert sm.state == ConfirmationState.EXPIRED
        assert sm.pending_result() is None

    def test_tick_expires_after_ttl(self):
        sm = VoiceConfirmationStateMachine(ttl_seconds=0.1)
        sm.submit(_make_result())
        assert sm.tick() == ConfirmationState.PENDING.value
        time.sleep(0.15)
        assert sm.tick() == ConfirmationState.EXPIRED.value

    def test_tick_does_not_expire_before_ttl(self):
        sm = VoiceConfirmationStateMachine(ttl_seconds=10.0)
        sm.submit(_make_result())
        assert sm.tick() == ConfirmationState.PENDING.value

    def test_reset_returns_to_idle(self):
        sm = VoiceConfirmationStateMachine()
        sm.submit(_make_result())
        sm.confirm()
        assert sm.state == ConfirmationState.CONFIRMED
        sm.reset()
        assert sm.state == ConfirmationState.IDLE

    def test_multiple_cycles(self):
        sm = VoiceConfirmationStateMachine()
        r1 = _make_result(VoiceIntent.SET_SCORE)
        r2 = _make_result(VoiceIntent.UNDO)

        sm.submit(r1)
        sm.cancel()
        assert sm.is_idle() is False  # CANCELLED, not IDLE
        sm.reset()
        assert sm.is_idle() is True

        sm.submit(r2)
        sm.confirm()
        sm.reset()
        assert sm.is_idle() is True
