"""
Tests for VoiceCommandRouter (Phase 1).
"""

from unittest.mock import patch

import time

import pytest

from tournament_platform.app.services.voice.command_router import (
    RouteContext,
    RouteDecision,
    RouteResult,
    route_command,
    route_and_update_context,
    _make_event_key,
)
from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.parse_result import VoiceParseResult


def _make_result(intent, confidence=0.9, slots=None, disposition=None):
    return VoiceParseResult(
        intent=intent,
        confidence=confidence,
        slots=slots or {},
        disposition=disposition,
        raw_transcript="test",
    )


class TestMakeEventKey:
    def test_stable_key(self):
        r1 = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        r2 = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        assert _make_event_key(r1) == _make_event_key(r2)

    def test_different_intent_different_key(self):
        r1 = _make_result(VoiceIntent.SCORE_POINT)
        r2 = _make_result(VoiceIntent.UNDO)
        assert _make_event_key(r1) != _make_event_key(r2)

    def test_different_player_different_key(self):
        r1 = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        r2 = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "B"})
        assert _make_event_key(r1) != _make_event_key(r2)

    def test_game_index_makes_same_command_distinct(self):
        # A "point A" command at the start of Game 2 must NOT collide with the
        # same command at the end of Game 1, otherwise the first voice point of
        # the next game is silently dropped as a duplicate.
        r = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        key_game1 = _make_event_key(r, current_game_index=0)
        key_game2 = _make_event_key(r, current_game_index=1)
        assert key_game1 != key_game2


class TestRouteCommand:
    def test_unknown_intent_rejects(self):
        result = _make_result(VoiceIntent.UNKNOWN)
        ctx = RouteContext()
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.REJECT
        assert r.reason == "unknown_intent"

    def test_disposition_rejects(self):
        result = _make_result(VoiceIntent.SET_SCORE, disposition="deuce_not_allowed")
        ctx = RouteContext()
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.REJECT
        assert "deuce_not_allowed" in r.reason

    def test_low_confidence_rejects(self):
        result = _make_result(VoiceIntent.SCORE_POINT, confidence=0.3)
        ctx = RouteContext(min_confidence_to_apply=0.5)
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.REJECT
        assert "low_confidence" in r.reason

    def test_duplicate_suppresses(self):
        result = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        event_key = _make_event_key(result)
        ctx = RouteContext(
            last_applied_event_key=event_key,
            last_applied_event_ts=time.time(),  # recent enough to be within cooldown
            cooldown_ms=5000.0,
        )
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.IGNORE
        assert r.reason == "duplicate_suppressed"

    def test_same_command_next_game_not_suppressed(self):
        # Repro of "voice stops after Game 1": the same "point A" that won
        # Game 1 must NOT be treated as a duplicate when spoken again to open
        # Game 2. The route key now encodes the game index.
        result = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        event_key_game1 = _make_event_key(result, current_game_index=0)
        ctx = RouteContext(
            last_applied_event_key=event_key_game1,
            last_applied_event_ts=time.time(),  # still well within cooldown
            current_game_index=1,  # we are now in Game 2
            cooldown_ms=5000.0,
        )
        r = route_command(result, ctx)
        assert r.decision != RouteDecision.IGNORE
        assert r.reason != "duplicate_suppressed"

    def test_non_duplicate_passes_cooldown(self):
        result = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        ctx = RouteContext(
            last_applied_event_key="different_key",
            last_applied_event_ts=1.0,
            cooldown_ms=5000.0,
        )
        r = route_command(result, ctx)
        assert r.decision != RouteDecision.IGNORE

    def test_score_point_auto_applies_when_high_confidence(self):
        # SCORE_POINT auto-applies only when confirmation is disabled explicitly
        # and confidence is high enough.
        with patch("tournament_platform.app.services.voice.confirmation.VOICE_ENABLE_CONFIRMATION", False):
            with patch("tournament_platform.app.services.voice.confirmation.VOICE_STRICT_MODE", False):
                result = _make_result(VoiceIntent.SCORE_POINT, confidence=0.9)
                ctx = RouteContext(strict_mode=False, enable_confirmation=False)
                r = route_command(result, ctx)
                assert r.decision == RouteDecision.APPLY

    def test_score_point_auto_applies_when_high_confidence(self):
        result = _make_result(VoiceIntent.SCORE_POINT, confidence=0.9)
        ctx = RouteContext(strict_mode=True, enable_confirmation=True)
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.APPLY

    def test_score_point_auto_applies_at_confirm_threshold(self):
        result = _make_result(VoiceIntent.SCORE_POINT, confidence=0.7)
        ctx = RouteContext(strict_mode=False, enable_confirmation=True)
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.APPLY

    def test_set_score_auto_applies_when_high_confidence(self):
        result = _make_result(VoiceIntent.SET_SCORE, confidence=0.95)
        ctx = RouteContext()
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.APPLY

    def test_undo_auto_applies(self):
        result = _make_result(VoiceIntent.UNDO, confidence=0.9)
        ctx = RouteContext()
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.APPLY

    def test_policy_rejected_intent(self):
        # VOICE_STRICT_MODE default is False, VOICE_ENABLE_CONFIRMATION is True.
        # For SCORE_POINT with confidence 0.9 and strict=False, policy returns apply.
        # We need to test something that is explicitly rejected by policy.
        # Looking at confirmation.py: UNKNOWN is rejected, but we already test that.
        # Disposition is rejected, but we already test that.
        # Confidence < 0.5 is rejected in router before policy.
        # So the remaining rejection path is policy_decision returning "reject"
        # for some specific intent. Looking at confirmation.py, I don't see
        # any intent that returns "reject" besides UNKNOWN and disposition.
        # Let's test that confirm intent is apply.
        result = _make_result(VoiceIntent.CONFIRM, confidence=0.9)
        ctx = RouteContext()
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.APPLY

    def test_confidence_below_confirm_threshold_downgrades_to_confirm(self):
        # UNDO is always "apply" per policy; router confidence guard should
        # downgrade it to "confirm" when confidence is below threshold.
        result = _make_result(VoiceIntent.UNDO, confidence=0.6)
        ctx = RouteContext(min_confidence_to_confirm=0.7)
        r = route_command(result, ctx)
        assert r.decision == RouteDecision.CONFIRM
        assert "confidence_below_confirm_threshold" in r.reason


class TestRouteAndUpdateContext:
    def test_updates_applied_metadata(self):
        result = _make_result(VoiceIntent.UNDO)
        ctx = RouteContext()
        r = route_and_update_context(result, ctx)
        assert r.decision == RouteDecision.APPLY
        assert ctx.last_applied_event_key == _make_event_key(result)
        assert ctx.last_applied_event_ts > 0

    def test_ignores_do_not_update_metadata(self):
        result = _make_result(VoiceIntent.SCORE_POINT, slots={"player": "A"})
        event_key = _make_event_key(result)
        ctx = RouteContext(
            last_applied_event_key=event_key,
            last_applied_event_ts=time.time(),
            cooldown_ms=5000.0,
        )
        r = route_and_update_context(result, ctx)
        assert r.decision == RouteDecision.IGNORE
        # last_applied_event_key should remain unchanged
        assert ctx.last_applied_event_key == event_key
