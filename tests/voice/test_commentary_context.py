"""
Tests for CommentaryContext and CommentaryContextBuilder.
"""

import pytest

from tournament_platform.app.services.commentary.context import (
    CommentaryContext,
    CommentaryContextBuilder,
)


class TestCommentaryContext:
    def test_defaults(self):
        ctx = CommentaryContext()
        assert ctx.score_a == 0
        assert ctx.score_b == 0
        assert ctx.streak is None
        assert ctx.comeback is False
        assert ctx.pressure_point is False
        assert ctx.deciding_game is False


class TestCommentaryContextBuilderFromSpokenScoreState:
    def test_basic_fields(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=5, score_b=3, sets_a=1, sets_b=0, current_set=2,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.score_a == 5
        assert ctx.score_b == 3
        assert ctx.sets_a == 1
        assert ctx.sets_b == 0
        assert ctx.player_a == "Alice"
        assert ctx.player_b == "Bob"

    def test_detect_streak(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=3, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
            ],
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.streak == "A"

    def test_no_streak_when_mixed(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=2, score_b=1, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "B"},
                {"action": "point_added", "player": "A"},
            ],
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.streak is None

    def test_detect_comeback(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=5, score_b=5, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A", "previous_score_a": 0, "previous_score_b": 5},
                {"action": "point_added", "player": "A", "previous_score_a": 1, "previous_score_b": 5},
                {"action": "point_added", "player": "A", "previous_score_a": 2, "previous_score_b": 5},
                {"action": "point_added", "player": "A", "previous_score_a": 3, "previous_score_b": 5},
                {"action": "point_added", "player": "A", "previous_score_a": 4, "previous_score_b": 5},
            ],
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.comeback is True

    def test_detect_pressure_point(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=10, score_b=9, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.pressure_point is True

    def test_no_pressure_point_early(self):
        from tournament_platform.services.commentary_service import SpokenScoreState
        state = SpokenScoreState(
            score_a=3, score_b=2, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        ctx = CommentaryContextBuilder.from_spoken_score_state(state)
        assert ctx.pressure_point is False


class TestCommentaryContextBuilderFromMatchManager:
    def test_reads_engine_state(self):
        from tournament_platform.services.match_manager import MatchManager
        mm = MatchManager(player_a="Alice", player_b="Bob")
        ctx = CommentaryContextBuilder.from_match_manager(mm)
        assert ctx.player_a == "Alice"
        assert ctx.player_b == "Bob"
        assert ctx.score_a == 0
        assert ctx.sets_a == 0

    def test_deciding_game(self):
        from tournament_platform.services.match_manager import MatchManager
        from tournament_platform.app.services.score_engine import add_point, check_game_winner, complete_game, create_match
        mm = MatchManager(player_a="Alice", player_b="Bob")
        mm.engine = create_match(player_a_name="Alice", player_b_name="Bob", best_of=3)
        for _ in range(11):
            add_point(mm.engine, "A")
            if check_game_winner(mm.engine):
                complete_game(mm.engine)
                break
        ctx = CommentaryContextBuilder.from_match_manager(mm)
        assert ctx.deciding_game is True
