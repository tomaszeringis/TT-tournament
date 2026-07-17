"""
Tests for the pure score engine (Phase 1 of the PingScore port).

Covers: win-by-two, deuce detection, serve switching (pre/deuce),
best-of-1/3/5 completion, undo (point / serve switch / game completion),
set-score validation, and that manual scoring uses the same engine.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.app.services.score_engine import (
    MatchState,
    ScoreResult,
    add_point,
    best_of_to_games_to_win,
    check_game_winner,
    check_match_winner,
    complete_game,
    create_match,
    games_to_win_to_best_of,
    get_live_stats,
    get_point_log,
    get_serving_player,
    is_deuce,
    reset_match,
    set_score,
    should_switch_serve,
    undo_last_action,
)


def _play(state, points_a, points_b):
    """Helper: add `points_a` points to A then `points_b` points to B."""
    for _ in range(points_a):
        add_point(state, "A")
    for _ in range(points_b):
        add_point(state, "B")


# ---------------------------------------------------------------------------
# Win-by-two logic
# ---------------------------------------------------------------------------

class TestWinByTwo:
    def test_11_9_wins(self):
        s = create_match()
        s.score_a, s.score_b = 11, 9
        assert check_game_winner(s) == "A"

    def test_11_10_not_won(self):
        s = create_match()
        s.score_a, s.score_b = 11, 10
        assert check_game_winner(s) is None

    def test_12_10_wins_after_deuce(self):
        s = create_match()
        s.score_a, s.score_b = 11, 10   # deuce territory, not won
        assert check_game_winner(s) is None
        s.score_a, s.score_b = 12, 10   # 12-10 wins
        assert check_game_winner(s) == "A"

    def test_first_to_15(self):
        s = create_match(points_to_win=15)
        s.score_a, s.score_b = 15, 13
        assert check_game_winner(s) == "A"

    def test_first_to_21(self):
        s = create_match(points_to_win=21)
        s.score_a, s.score_b = 21, 19
        assert check_game_winner(s) == "A"


# ---------------------------------------------------------------------------
# Deuce detection
# ---------------------------------------------------------------------------

class TestDeuceDetection:
    def test_10_10_is_deuce(self):
        s = create_match()
        set_score(s, 10, 10)
        assert is_deuce(s) is True

    def test_9_9_not_deuce(self):
        s = create_match()
        set_score(s, 9, 9)
        assert is_deuce(s) is False

    def test_11_10_is_deuce(self):
        s = create_match()
        set_score(s, 11, 10)
        assert is_deuce(s) is True

    def test_11_9_not_deuce(self):
        s = create_match()
        set_score(s, 11, 9)
        assert is_deuce(s) is False

    def test_13_12_is_deuce(self):
        s = create_match()
        set_score(s, 13, 12)
        assert is_deuce(s) is True


# ---------------------------------------------------------------------------
# Serve switching
# ---------------------------------------------------------------------------

class TestServeSwitching:
    def test_no_switch_after_first_point(self):
        s = create_match(first_server="A")
        add_point(s, "A")  # 1-0
        assert get_serving_player(s) == "A"

    def test_switch_after_two_points(self):
        s = create_match(first_server="A")
        add_point(s, "A")  # 1-0, server A
        add_point(s, "B")  # 1-1, 2 points -> switch
        assert get_serving_player(s) == "B"

    def test_switch_every_two_pre_deuce(self):
        s = create_match(first_server="A")
        _play(s, 2, 2)  # 2-2, switched at 2 then at 4
        # after 4 points: switches=2 -> back to A
        assert get_serving_player(s) == "A"

    def test_switch_every_point_during_deuce(self):
        s = create_match(first_server="A")
        set_score(s, 10, 10)  # deuce, server recomputed to A (total 20 even)
        assert get_serving_player(s) == "A"
        add_point(s, "A")  # 11-10, deuce -> switch
        assert get_serving_player(s) == "B"
        add_point(s, "B")  # 11-11, deuce -> switch
        assert get_serving_player(s) == "A"

    def test_should_switch_serve_helper(self):
        s = create_match()
        assert should_switch_serve(s) is False  # 0 points
        add_point(s, "A")
        assert should_switch_serve(s) is False  # 1 point
        add_point(s, "B")
        assert should_switch_serve(s) is True   # 2 points


# ---------------------------------------------------------------------------
# Best-of match completion
# ---------------------------------------------------------------------------

class TestGamesToWinMapping:
    def test_best_of_3_maps_to_2_games(self):
        assert best_of_to_games_to_win(3) == 2

    def test_best_of_5_maps_to_3_games(self):
        assert best_of_to_games_to_win(5) == 3

    def test_legacy_best_of_1_falls_back_to_2(self):
        assert best_of_to_games_to_win(1) == 2

    def test_unknown_best_of_falls_back_to_2(self):
        assert best_of_to_games_to_win(99) == 2

    def test_2_games_maps_to_best_of_3(self):
        assert games_to_win_to_best_of(2) == 3

    def test_3_games_maps_to_best_of_5(self):
        assert games_to_win_to_best_of(3) == 5

    def test_unknown_games_to_win_falls_back_to_3(self):
        assert games_to_win_to_best_of(99) == 3

    def test_round_trip_2(self):
        assert games_to_win_to_best_of(best_of_to_games_to_win(3)) == 3

    def test_round_trip_3(self):
        assert games_to_win_to_best_of(best_of_to_games_to_win(5)) == 5


class TestBestOfCompletionViaGamesToWin:
    def test_2_games_to_win_completes_after_2(self):
        s = create_match(best_of=games_to_win_to_best_of(2))
        set_score(s, 11, 0)
        assert s.match_status == "game_won"
        set_score(s, 11, 0)
        assert s.match_status == "match_won"
        assert s.games_won_a == 2

    def test_3_games_to_win_completes_after_3(self):
        s = create_match(best_of=games_to_win_to_best_of(3))
        for _ in range(3):
            set_score(s, 11, 0)
        assert s.match_status == "match_won"
        assert s.games_won_a == 3

    def test_not_won_before_majority_3_games(self):
        s = create_match(best_of=games_to_win_to_best_of(3))
        set_score(s, 11, 0)
        set_score(s, 11, 0)
        assert s.match_status != "match_won"
        assert check_match_winner(s) is None


class TestBestOfCompletion:
    def test_best_of_1(self):
        s = create_match(best_of=1)
        set_score(s, 11, 0)
        assert s.match_status == "match_won"
        assert check_match_winner(s) == "A"

    def test_best_of_3(self):
        s = create_match(best_of=3)
        set_score(s, 11, 0)  # game 1 -> A
        assert s.match_status == "game_won"
        set_score(s, 11, 0)  # game 2 -> A wins match
        assert s.match_status == "match_won"
        assert s.games_won_a == 2

    def test_best_of_5(self):
        s = create_match(best_of=5)
        for _ in range(3):
            set_score(s, 11, 0)  # A wins 3 games
        assert s.match_status == "match_won"
        assert s.games_won_a == 3
        assert check_match_winner(s) == "A"

    def test_match_not_won_before_majority(self):
        s = create_match(best_of=5)
        set_score(s, 11, 0)
        set_score(s, 11, 0)  # A leads 2-0
        assert s.match_status != "match_won"
        assert check_match_winner(s) is None


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

class TestUndo:
    def test_undo_after_normal_point(self):
        s = create_match(first_server="A")
        add_point(s, "A")  # 1-0
        assert s.score_a == 1
        res = undo_last_action(s)
        assert res.ok is True
        assert s.score_a == 0
        assert s.score_b == 0
        assert get_serving_player(s) == "A"

    def test_undo_after_serve_switch(self):
        s = create_match(first_server="A")
        add_point(s, "A")  # 1-0, server A
        add_point(s, "B")  # 1-1, server switches to B
        assert get_serving_player(s) == "B"
        undo_last_action(s)  # back to 1-0, server A
        assert s.score_a == 1 and s.score_b == 0
        assert get_serving_player(s) == "A"

    def test_undo_after_game_completion(self):
        s = create_match()
        set_score(s, 10, 9)  # in-progress 10-9
        assert s.score_a == 10 and s.score_b == 9
        add_point(s, "A")     # 11-9 -> game won, scores reset to 0-0
        assert s.games_won_a == 1
        assert s.score_a == 0
        undo_last_action(s)   # restore pre-point in-progress state
        assert s.score_a == 10 and s.score_b == 9
        assert s.games_won_a == 0
        assert s.match_status == "in_progress"

    def test_undo_with_empty_history(self):
        s = create_match()
        res = undo_last_action(s)
        assert res.ok is False
        assert res.rejected_reason == "No actions to undo"

    def test_undo_restores_server_after_game(self):
        s = create_match(first_server="A")
        for _ in range(11):
            add_point(s, "A")  # A wins game 1 (11-0)
        assert s.games_won_a == 1
        assert s.match_status == "game_won"
        # Next game: receiver of game 1 (B) becomes server.
        assert get_serving_player(s) == "B"
        undo_last_action(s)  # back to 10-0, server B (server at that point)
        assert s.score_a == 10 and s.score_b == 0
        assert s.games_won_a == 0
        assert get_serving_player(s) == "B"


# ---------------------------------------------------------------------------
# Set-score validation
# ---------------------------------------------------------------------------

class TestSetScoreValidation:
    def test_valid_set(self):
        s = create_match()
        res = set_score(s, 5, 4)
        assert res.ok is True
        assert s.score_a == 5 and s.score_b == 4

    def test_negative_rejected(self):
        s = create_match()
        res = set_score(s, -1, 0)
        assert res.ok is False
        assert "negative" in res.rejected_reason.lower()

    def test_over_max_rejected(self):
        s = create_match(points_to_win=11)
        res = set_score(s, 100, 0)
        assert res.ok is False
        assert "maximum" in res.rejected_reason.lower()

    def test_set_score_completes_game(self):
        s = create_match()
        res = set_score(s, 11, 3)
        assert res.ok is True
        assert res.game_won == "A"
        assert s.games_won_a == 1
        assert s.score_a == 0  # reset for next game


# ---------------------------------------------------------------------------
# Manual scoring uses the same engine
# ---------------------------------------------------------------------------

class TestManualScoring:
    def test_add_point_directly(self):
        s = create_match()
        res = add_point(s, "A")
        assert res.ok is True
        assert res.point_added == "A"
        assert s.score_a == 1

    def test_add_point_both_players(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "B")
        assert s.score_a == 1 and s.score_b == 1

    def test_reset_match(self):
        s = create_match()
        _play(s, 5, 3)
        res = reset_match(s)
        assert res.ok is True
        assert s.score_a == 0 and s.score_b == 0
        assert s.games_won_a == 0 and s.games_won_b == 0


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_from_dict(self):
        s = create_match(player_a_name="Alice", player_b_name="Bob",
                         points_to_win=15, best_of=3, first_server="B")
        _play(s, 11, 5)
        data = s.to_dict()
        restored = MatchState.from_dict(data)
        assert restored.player_a_name == "Alice"
        assert restored.score_a == 11
        assert restored.points_to_win == 15
        assert restored.best_of == 3
        assert restored.first_server == "B"


# ---------------------------------------------------------------------------
# Point trail
# ---------------------------------------------------------------------------

class TestPointTrail:
    def test_point_trail_records_a(self):
        s = create_match()
        add_point(s, "A")
        assert get_point_log(s) == ["A"]

    def test_point_trail_records_both(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "B")
        assert get_point_log(s) == ["A", "B"]

    def test_undo_clears_trail(self):
        s = create_match()
        add_point(s, "A")
        undo_last_action(s)
        assert get_point_log(s) == []


# ---------------------------------------------------------------------------
# Live stats
# ---------------------------------------------------------------------------

class TestLiveStats:
    def test_current_streak_a(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "A")
        stats = get_live_stats(s)
        assert stats["current_streak_player"] == "A"
        assert stats["current_streak"] == 2

    def test_max_streak(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "B")
        add_point(s, "A")
        add_point(s, "A")
        stats = get_live_stats(s)
        assert stats["max_streak_a"] == 2
        assert stats["max_streak_b"] == 1

    def test_biggest_lead(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "A")
        add_point(s, "B")
        stats = get_live_stats(s)
        assert stats["biggest_lead_player"] == "A"
        assert stats["biggest_lead_margin"] == 2

    def test_biggest_lead_changes(self):
        s = create_match()
        add_point(s, "A")
        add_point(s, "A")
        add_point(s, "B")
        add_point(s, "B")
        add_point(s, "B")
        stats = get_live_stats(s)
        assert stats["biggest_lead_player"] == "A"
        assert stats["biggest_lead_margin"] == 2

    def test_empty_trail(self):
        s = create_match()
        stats = get_live_stats(s)
        assert stats["current_streak"] == 0
        assert stats["max_streak_a"] == 0
        assert stats["max_streak_b"] == 0
        assert stats["biggest_lead_margin"] == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
