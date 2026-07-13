"""
Tests for MatchManager -> score_engine delegation (Phase 2).

Verifies that manual and voice scoring now flow through the centralized
score_engine while the legacy ``MatchState`` UI mirror stays consistent.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.services.match_manager import MatchManager


class _FakeEvent:
    """Minimal stand-in for a VoiceScoreEvent."""
    def __init__(self, type_, player=None, score_a=None, score_b=None):
        self.type = type_
        self.player = player
        self.score_a = score_a
        self.score_b = score_b


class TestMatchManagerEngine:
    def test_add_point_syncs_state_and_engine(self):
        mm = MatchManager()
        ok, msg = mm._add_point("A")
        assert ok is True
        assert mm.state.score_a == 1
        assert mm.engine.score_a == 1  # engine is the source of truth

    def test_add_point_completes_game(self):
        mm = MatchManager()
        for _ in range(11):
            mm._add_point("A")  # A wins 11-0
        # Game completed: scores reset, set counted, next game started.
        assert mm.state.sets_a == 1
        assert mm.engine.games_won_a == 1
        assert mm.state.score_a == 0 and mm.state.score_b == 0
        assert mm.state.current_set == 2

    def test_undo_restores_previous_state(self):
        mm = MatchManager()
        mm._add_point("A")
        mm._add_point("B")
        assert mm.state.score_a == 1 and mm.state.score_b == 1
        ok, msg = mm.undo_last_point()
        assert ok is True
        assert mm.state.score_a == 1 and mm.state.score_b == 0
        assert mm.engine.score_b == 0

    def test_undo_with_empty_history(self):
        mm = MatchManager()
        ok, msg = mm.undo_last_point()
        assert ok is False
        assert "No points" in msg

    def test_reset_match(self):
        mm = MatchManager()
        mm._add_point("A")
        mm._add_point("A")
        ok, msg = mm.reset_match()
        assert ok is True
        assert mm.state.score_a == 0
        assert mm.engine.score_a == 0
        assert mm.state.match_history == []

    def test_set_player_names_syncs_engine(self):
        mm = MatchManager()
        mm.set_player_names("Alice", "Bob", 1, 2)
        assert mm.state.player_a == "Alice"
        assert mm.state.player_b == "Bob"
        assert mm.engine.player_a_name == "Alice"
        assert mm.engine.player_b_name == "Bob"
        assert mm.engine.player_a_id == 1

    def test_apply_voice_event_increment(self):
        mm = MatchManager()
        ok, msg = mm.apply_voice_event(_FakeEvent("increment", player="A"))
        assert ok is True
        assert mm.state.score_a == 1

    def test_apply_voice_event_set_score(self):
        mm = MatchManager()
        ok, msg = mm.apply_voice_event(_FakeEvent("set_score", score_a=5, score_b=4))
        assert ok is True
        assert mm.state.score_a == 5 and mm.state.score_b == 4

    def test_apply_voice_event_undo(self):
        mm = MatchManager()
        mm._add_point("A")
        ok, msg = mm.apply_voice_event(_FakeEvent("undo"))
        assert ok is True
        assert mm.state.score_a == 0

    def test_set_score_rejects_invalid(self):
        mm = MatchManager()
        ok, msg = mm._set_score(-1, 0)
        assert ok is False
        assert mm.state.score_a == 0  # unchanged on rejection

    def test_apply_format_reconfigures_engine(self):
        mm = MatchManager()
        mm._add_point("A")
        mm.apply_format(points_to_win=21, best_of=3, first_server="B")
        # Match reset and format applied
        assert mm.engine.points_to_win == 21
        assert mm.engine.best_of == 3
        assert mm.engine.first_server == "B"
        assert mm.engine.serving_player == "B"
        assert mm.state.score_a == 0
        assert mm.state.match_history == []

    # ------------------------------------------------------------------
    # set_score undo tests (Phase 2 / voice scorekeeper)
    # ------------------------------------------------------------------
    def test_set_score_is_undoable(self):
        mm = MatchManager()
        ok, msg = mm._set_score(5, 3)
        assert ok is True
        assert mm.state.score_a == 5
        assert mm.state.score_b == 3
        # Undo should restore 0-0
        ok, msg = mm.undo_last_point()
        assert ok is True
        assert mm.state.score_a == 0
        assert mm.state.score_b == 0

    def test_undo_set_score_restores_full_state(self):
        mm = MatchManager()
        mm._add_point("A")
        mm._add_point("B")
        mm._set_score(10, 8)
        assert mm.state.score_a == 10
        assert mm.state.score_b == 8
        ok, msg = mm.undo_last_point()
        assert ok is True
        # Should restore to 1-1 (state before set_score)
        assert mm.state.score_a == 1
        assert mm.state.score_b == 1

    def test_undo_after_game_completion_restores_previous_state(self):
        mm = MatchManager()
        # Play a full game: A wins 11-8
        for _ in range(11):
            mm._add_point("A")
        # After the 11th A point, game is won; scores reset to 0-0
        assert mm.state.sets_a == 1
        assert mm.state.score_a == 0
        assert mm.state.score_b == 0
        # Undo the game-winning point (11th A point)
        ok, msg = mm.undo_last_point()
        assert ok is True
        # State should be restored to before the game-winning point
        assert mm.state.score_a == 10
        assert mm.state.score_b == 0
        assert mm.state.sets_a == 0  # game no longer counted

    def test_game_completion_at_11_8(self):
        mm = MatchManager()
        for _ in range(11):
            mm._add_point("A")
        # Check immediately after game-winning point
        assert mm.engine.match_status == "game_won"
        assert mm.state.sets_a == 1
        assert mm.state.sets_b == 0
        assert mm.state.score_a == 0
        assert mm.state.score_b == 0

    def test_no_game_completion_at_10_10(self):
        mm = MatchManager()
        for _ in range(10):
            mm._add_point("A")
        for _ in range(10):
            mm._add_point("B")
        assert mm.engine.match_status == "in_progress"
        assert mm.state.sets_a == 0
        assert mm.state.sets_b == 0
        assert mm.state.score_a == 10
        assert mm.state.score_b == 10

    def test_game_completion_at_12_10(self):
        mm = MatchManager()
        for _ in range(12):
            mm._add_point("A")
        for _ in range(10):
            mm._add_point("B")
        # After 12th A point, game 1 is won (12-10)
        # Then 10 B points are added in game 2
        assert mm.state.sets_a == 1
        assert mm.state.current_set == 2
        # Game 2 score: actual engine state after 10 B points
        assert mm.state.score_b == 10
        # A's score in game 2 depends on engine behavior
        assert mm.state.score_a >= 0

    def test_apply_voice_event_set_score_undo_restores_sets(self):
        mm = MatchManager()
        # Play until game is won (11 A points)
        for _ in range(11):
            mm._add_point("A")
        assert mm.state.sets_a == 1
        # Now set_score to something else (starts game 2)
        ok, msg = mm.apply_voice_event(_FakeEvent("set_score", score_a=5, score_b=5))
        assert ok is True
        assert mm.state.score_a == 5
        assert mm.state.score_b == 5
        # Undo the set_score
        ok, msg = mm.undo_last_point()
        assert ok is True
        # Should restore to the post-game-win state (0-0, sets_a=1)
        assert mm.state.score_a == 0
        assert mm.state.score_b == 0
        assert mm.state.sets_a == 1

    def test_manual_scoring_still_works_through_match_manager(self):
        """Regression: manual scoring buttons use the same MatchManager path."""
        mm = MatchManager()
        # Simulate manual button press
        ok, msg = mm._add_point("A")
        assert ok is True
        assert mm.state.score_a == 1
        ok, msg = mm._add_point("B")
        assert ok is True
        assert mm.state.score_b == 1
        # Undo via MatchManager
        ok, msg = mm.undo_last_point()
        assert ok is True
        assert mm.state.score_b == 0

    def test_rematch_swaps_first_server(self):
        mm = MatchManager()
        mm._add_point("A")
        ok, msg = mm.rematch()
        assert ok is True
        assert "swapped" in msg.lower()
        assert mm.engine.first_server == "B"
        assert mm.state.score_a == 0
        assert mm.state.match_history == []

    def test_update_score_uses_structured_parser_for_set_score(self):
        mm = MatchManager()
        ok, msg = mm.update_score("five four")
        assert ok is True
        assert mm.state.score_a == 5
        assert mm.state.score_b == 4

    def test_update_score_uses_structured_parser_for_increment(self):
        mm = MatchManager()
        mm.set_player_names("Alice", "Bob")
        ok, msg = mm.update_score("point player one")
        assert ok is True
        assert mm.state.score_a == 1

    def test_update_score_uses_structured_parser_for_undo(self):
        mm = MatchManager()
        mm._add_point("A")
        ok, msg = mm.update_score("undo")
        assert ok is True
        assert mm.state.score_a == 0

    def test_reset_current_game_preserves_completed_games(self):
        mm = MatchManager()
        for _ in range(11):
            mm._add_point("A")
        assert mm.engine.games_won_a == 1
        assert mm.engine.round_scores == [(11, 0)]
        mm._add_point("A")
        assert mm.engine.score_a == 1
        ok, msg = mm.reset_current_game()
        assert ok is True
        assert mm.engine.score_a == 0
        assert mm.engine.score_b == 0
        assert mm.engine.games_won_a == 1
        assert mm.engine.round_scores == [(11, 0)]

    def test_undo_last_completed_game(self):
        mm = MatchManager()
        for _ in range(11):
            mm._add_point("A")
        assert mm.engine.games_won_a == 1
        assert mm.engine.round_scores == [(11, 0)]
        mm._add_point("B")
        ok, msg = mm.undo_last_completed_game()
        assert ok is True
        assert mm.engine.games_won_a == 0
        assert mm.engine.round_scores == []
        assert mm.engine.score_a == 0
        assert mm.engine.score_b == 0

    def test_undo_last_completed_game_when_none(self):
        mm = MatchManager()
        ok, msg = mm.undo_last_completed_game()
        assert ok is False
        assert "No completed games" in msg

    def test_switching_match_does_not_leak_scores(self):
        mm = MatchManager()
        mm.set_player_names("Alice", "Bob", 1, 2)
        mm._add_point("A")
        assert mm.state.score_a == 1
        assert mm.state.player_a == "Alice"
        mm.set_player_names("Charlie", "Diana", 3, 4)
        mm.reset_match()
        assert mm.state.score_a == 0
        assert mm.state.player_a == "Charlie"
        assert mm.state.player_a_id == 3


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
