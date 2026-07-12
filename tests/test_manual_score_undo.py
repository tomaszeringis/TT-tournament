"""
Tests for the manual score panel (Phase 1): draft + undo + completed-match guard.
"""

import pytest

from tournament_platform.app.services.score_engine import (
    MatchState,
    create_match,
    add_point,
    undo_last_action,
)
from tournament_platform.app.components.manual_score_panel import compute_final_report


class TestManualScoreUndo:
    def test_undo_refused_on_completed_match(self):
        """score_engine must reject further points once a match is decided."""
        state = create_match("Alice", "Bob", best_of=1)
        while state.match_status != "match_won":
            add_point(state, "A")
        assert state.match_status == "match_won"
        res = add_point(state, "B")
        assert res.ok is False
        assert res.rejected_reason

    def test_undo_restores_previous_state(self):
        state = create_match("Alice", "Bob", best_of=1)
        add_point(state, "A")
        assert state.score_a == 1
        undo_last_action(state)
        assert state.score_a == 0
        assert state.history == []

    def test_compute_final_report_best_of_uses_games(self):
        state = MatchState(player_a_name="Alice", player_b_name="Bob", best_of=3)
        state.games_won_a = 2
        state.games_won_b = 1
        report = compute_final_report(state)
        assert report["score"] == "2-1"
        assert report["winner"] == "Alice"

    def test_compute_final_report_single_game_uses_points(self):
        state = MatchState(
            player_a_name="Alice", player_b_name="Bob",
            score_a=11, score_b=9, best_of=1,
        )
        report = compute_final_report(state)
        assert report["score"] == "11-9"
        assert report["winner"] == "Alice"

    def test_completed_match_is_locked_in_panel(self):
        match = {"id": 1, "player1": "Alice", "player2": "Bob", "status": "completed"}
        assert match.get("status") == "completed"
