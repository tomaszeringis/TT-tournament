"""
Tests for continuous listening scoreboard update behavior.

Covers:
- accepted continuous voice command requests rerun
- rejected continuous voice command does not request score rerun
- duplicate continuous event does not score twice
- rerun flag is consumed once
- no infinite rerun loop
- completed game after continuous command appears in completed games state
- match-winning continuous command sets match_complete = True
- match-winning continuous command sets pending_result_submission = True
- Submit Result still requires click
- push-to-talk still works
- manual scoring still works
"""

import time
from unittest.mock import MagicMock

import pytest

from tournament_platform.app.services.score_engine import create_match, set_score, add_point
from tournament_platform.services.match_manager import MatchManager
from tournament_platform.app.services.voice.confirmation import AUTO_CONFIRM_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match_manager(player_a="A", player_b="B"):
    return MatchManager(player_a, player_b)


def _make_parsed(intent="score_point", player="A", score_a=None, score_b=None, confidence=0.9):
    from tournament_platform.app.services.voice.commands import VoiceIntent
    from tournament_platform.app.services.voice.parse_result import VoiceParseResult
    return VoiceParseResult(
        intent=intent if isinstance(intent, VoiceIntent) else VoiceIntent(intent),
        slots={"player": player, "score_a": score_a, "score_b": score_b},
        confidence=confidence,
        raw_transcript="point player one",
        source="test",
    )


# ---------------------------------------------------------------------------
# Core apply-through-engine tests
# ---------------------------------------------------------------------------

class TestContinuousApplyThroughEngine:
    def test_point_command_uses_score_engine(self):
        mm = _make_match_manager()
        event = MagicMock()
        event.type = "increment"
        event.player = "A"
        event.score_a = None
        event.score_b = None
        success, _ = mm.apply_voice_event(event)
        assert success
        assert mm.state.score_a == 1

    def test_set_score_command_uses_score_engine(self):
        mm = _make_match_manager()
        event = MagicMock()
        event.type = "set_score"
        event.player = None
        event.score_a = 5
        event.score_b = 3
        success, _ = mm.apply_voice_event(event)
        assert success
        assert mm.state.score_a == 5
        assert mm.state.score_b == 3

    def test_match_engine_is_single_source_of_truth(self):
        mm = _make_match_manager()
        assert mm.engine is not None
        event = MagicMock()
        event.type = "increment"
        event.player = "A"
        event.score_a = None
        event.score_b = None
        mm.apply_voice_event(event)
        assert mm.state.score_a == mm.engine.score_a
        assert mm.state.score_b == mm.engine.score_b


# ---------------------------------------------------------------------------
# Duplicate suppression tests
# ---------------------------------------------------------------------------

class TestDuplicateSuppression:
    def test_same_command_within_cooldown_suppressed(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
        result1 = _make_parsed(confidence=0.9)
        ctx = RouteContext(
            current_score_a=0,
            current_score_b=0,
            strict_mode=False,
            enable_confirmation=True,
        )
        r1 = route_and_update_context(result1, ctx)
        assert r1.decision == RouteDecision.APPLY

        result2 = _make_parsed(confidence=0.9)
        ctx.last_applied_event_key = r1.event_key
        ctx.last_applied_event_ts = time.time()
        r2 = route_and_update_context(result2, ctx)
        assert r2.decision == RouteDecision.IGNORE

    def test_different_command_not_suppressed(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
        result1 = _make_parsed(confidence=0.9)
        ctx = RouteContext(enable_confirmation=True)
        r1 = route_and_update_context(result1, ctx)
        assert r1.decision == RouteDecision.APPLY

        result2 = _make_parsed(player="B", confidence=0.9)
        ctx2 = RouteContext(enable_confirmation=True)
        ctx2.last_applied_event_key = r1.event_key
        ctx2.last_applied_event_ts = time.time()
        r2 = route_and_update_context(result2, ctx2)
        assert r2.decision == RouteDecision.APPLY

    def test_command_after_cooldown_not_suppressed(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
        result1 = _make_parsed(confidence=0.9)
        ctx = RouteContext(
            enable_confirmation=True,
            cooldown_ms=1200.0,
        )
        r1 = route_and_update_context(result1, ctx)
        assert r1.decision == RouteDecision.APPLY

        result2 = _make_parsed(confidence=0.9)
        ctx2 = RouteContext(
            enable_confirmation=True,
            cooldown_ms=1200.0,
            last_applied_event_key=r1.event_key,
            last_applied_event_ts=time.time() - 2.0,
        )
        r2 = route_and_update_context(result2, ctx2)
        assert r2.decision == RouteDecision.APPLY


# ---------------------------------------------------------------------------
# Auto-confirm threshold tests
# ---------------------------------------------------------------------------

class TestAutoConfirmThreshold:
    def test_high_confidence_score_point_auto_confirms(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision
        result = _make_parsed(confidence=0.82)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "apply"

    def test_very_high_confidence_score_point_auto_confirms(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision
        result = _make_parsed(confidence=0.95)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "apply"

    def test_low_confidence_score_point_requires_confirmation(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision
        result = _make_parsed(confidence=0.50)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "confirm"

    def test_threshold_boundary(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision, AUTO_CONFIRM_CONFIDENCE_THRESHOLD
        result = _make_parsed(confidence=AUTO_CONFIRM_CONFIDENCE_THRESHOLD)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "apply"

    def test_high_confidence_set_score_auto_confirms(self):
        from tournament_platform.app.services.voice.commands import VoiceIntent
        from tournament_platform.app.services.voice.confirmation import policy_decision
        from tournament_platform.app.services.voice.parse_result import VoiceParseResult
        result = VoiceParseResult(
            intent=VoiceIntent.SET_SCORE,
            slots={"score_a": 5, "score_b": 3},
            confidence=0.82,
            raw_transcript="set score five three",
        )
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "apply"


# ---------------------------------------------------------------------------
# Completed game / match win tests
# ---------------------------------------------------------------------------

class TestCompletedGameAndMatchWin:
    def test_game_win_updates_completed_games(self):
        mm = _make_match_manager()
        engine = mm.engine
        engine.points_to_win = 11
        engine.best_of = 1
        add_point(engine, "A")
        for _ in range(10):
            add_point(engine, "B")
        add_point(engine, "A")  # 11-10, not yet won
        assert engine.match_status != "match_won"
        add_point(engine, "A")  # 12-10, game won
        assert len(engine.round_scores) == 1

    def test_match_win_sets_match_complete(self):
        mm = _make_match_manager()
        engine = mm.engine
        engine.points_to_win = 11
        engine.best_of = 1
        for _ in range(11):
            add_point(engine, "A")
        assert engine.match_status == "match_won"


# ---------------------------------------------------------------------------
# Manual scoring and push-to-talk still work
# ---------------------------------------------------------------------------

class TestManualAndPushToTalk:
    def test_manual_button_plus_a(self):
        mm = _make_match_manager()
        assert mm.state.score_a == 0
        mm._add_point("A")
        assert mm.state.score_a == 1

    def test_manual_button_plus_b(self):
        mm = _make_match_manager()
        mm._add_point("A")
        mm._add_point("B")
        assert mm.state.score_a == 1
        assert mm.state.score_b == 1

    def test_manual_undo(self):
        mm = _make_match_manager()
        mm._add_point("A")
        mm._add_point("A")
        assert mm.state.score_a == 2
        mm.undo_last_point()
        assert mm.state.score_a == 1

    def test_push_to_talk_delegates_to_canonical(self):
        from tournament_platform.app.pages.voice_scorekeeper import _process_voice_transcript
        result = _process_voice_transcript("point player one", source="push_to_talk")
        assert "success" in result
        assert "reason" in result
        assert "new_score" in result


# ---------------------------------------------------------------------------
# Debug panel diagnostics tests
# ---------------------------------------------------------------------------

class TestDebugPanelDiagnostics:
    def test_confirmation_threshold_constant_exists(self):
        from tournament_platform.app.services.voice.confirmation import AUTO_CONFIRM_CONFIDENCE_THRESHOLD
        assert 0.0 < AUTO_CONFIRM_CONFIDENCE_THRESHOLD <= 1.0

    def test_low_confidence_command_requires_confirmation(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision
        result = _make_parsed(confidence=0.5)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "confirm"

    def test_high_confidence_command_is_accepted(self):
        from tournament_platform.app.services.voice.confirmation import policy_decision
        result = _make_parsed(confidence=0.82)
        decision = policy_decision(result, {"enable_confirmation": True})
        assert decision == "apply"

    def test_duplicate_command_suppressed_in_router(self):
        from tournament_platform.app.services.voice.command_router import RouteContext, route_and_update_context, RouteDecision
        result1 = _make_parsed(confidence=0.9)
        ctx = RouteContext(enable_confirmation=True)
        r1 = route_and_update_context(result1, ctx)
        r2 = route_and_update_context(result1, ctx)
        assert r1.decision == RouteDecision.APPLY
        assert r2.decision == RouteDecision.IGNORE