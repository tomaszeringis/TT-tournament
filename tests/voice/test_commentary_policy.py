"""
Tests for CommentaryPolicy.
"""

import pytest

from tournament_platform.app.services.commentary.policy import CommentaryPolicy
from tournament_platform.app.services.commentary.events import CommentaryEventType


class TestCommentaryPolicy:
    def test_rank_importance_normal(self):
        assert CommentaryPolicy.rank_importance(CommentaryEventType.POINT_WON.value) == "normal"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.SERVE_CHANGE.value) == "normal"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.UNDO.value) == "normal"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.RESET.value) == "normal"

    def test_rank_importance_important(self):
        assert CommentaryPolicy.rank_importance(CommentaryEventType.ADVANTAGE.value) == "important"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.GAME_POINT.value) == "important"

    def test_rank_importance_critical(self):
        assert CommentaryPolicy.rank_importance(CommentaryEventType.DEUCE.value) == "critical"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.GAME_WON.value) == "critical"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.MATCH_WON.value) == "critical"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.RESULT_SUBMITTED.value) == "critical"
        assert CommentaryPolicy.rank_importance(CommentaryEventType.VOICE_COMMAND_REJECTED.value) == "critical"

    def test_unknown_event_defaults_normal(self):
        assert CommentaryPolicy.rank_importance("unknown_event") == "normal"

    def test_is_duplicate_new_id(self):
        is_dup, seen = CommentaryPolicy.is_duplicate("evt-1", set())
        assert is_dup is False
        assert seen == {"evt-1"}

    def test_is_duplicate_seen_id(self):
        is_dup, seen = CommentaryPolicy.is_duplicate("evt-1", {"evt-1"})
        assert is_dup is True
        assert seen == {"evt-1"}

    def test_cooldown_ok_for_non_point(self):
        now = 1000.0
        assert CommentaryPolicy.cooldown_ok("undo", 0.0, 5.0, now) is True
        assert CommentaryPolicy.cooldown_ok("deuce", 0.0, 5.0, now) is True

    def test_cooldown_ok_for_point(self):
        assert CommentaryPolicy.cooldown_ok("point_won", 0.0, 5.0, 3.0) is False
        assert CommentaryPolicy.cooldown_ok("point_won", 0.0, 5.0, 6.0) is True

    def test_should_suppress_off(self):
        assert CommentaryPolicy.should_suppress("off", "medium", "critical") is True

    def test_should_suppress_visual_only(self):
        assert CommentaryPolicy.should_suppress("visual_only", "medium", "critical") is False

    def test_should_suppress_important_only(self):
        assert CommentaryPolicy.should_suppress("important_only", "medium", "normal") is True
        assert CommentaryPolicy.should_suppress("important_only", "medium", "important") is False
        assert CommentaryPolicy.should_suppress("important_only", "medium", "critical") is False

    def test_should_suppress_after_every_game(self):
        assert CommentaryPolicy.should_suppress("after_every_game", "medium", "normal") is True
        assert CommentaryPolicy.should_suppress("after_every_game", "medium", "critical") is False

    def test_should_suppress_every_point(self):
        assert CommentaryPolicy.should_suppress("every_point", "medium", "normal") is False

    def test_should_suppress_spoken_low(self):
        assert CommentaryPolicy.should_suppress("spoken", "low", "important") is True
        assert CommentaryPolicy.should_suppress("spoken", "low", "critical") is False

    def test_should_suppress_spoken_medium(self):
        assert CommentaryPolicy.should_suppress("spoken", "medium", "normal") is True
        assert CommentaryPolicy.should_suppress("spoken", "medium", "important") is False

    def test_should_suppress_spoken_high(self):
        assert CommentaryPolicy.should_suppress("spoken", "high", "normal") is False
