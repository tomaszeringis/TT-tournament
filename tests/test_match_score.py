"""
Tests for the match_score module.
"""

import pytest
import sys
import os

# Add the project root to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.app.services.match_score import (
    parse_game_score,
    validate_game_score,
    get_game_winner,
    summarize_match,
)


class TestParseGameScore:
    """Tests for parse_game_score function."""
    
    def test_parse_standard_format(self):
        """Test standard '11-3' format."""
        result = parse_game_score("11-3")
        assert result == (11, 3)
    
    def test_parse_with_spaces(self):
        """Test '11 - 3' format with spaces."""
        result = parse_game_score("11 - 3")
        assert result == (11, 3)
    
    def test_parse_higher_scores(self):
        """Test '12-3' and '13-11' formats."""
        assert parse_game_score("12-3") == (12, 3)
        assert parse_game_score("13-11") == (13, 11)
    
    def test_parse_with_to(self):
        """Test '11 to 3' format."""
        result = parse_game_score("11 to 3")
        assert result == (11, 3)
    
    def test_parse_with_dash(self):
        """Test '11 dash 3' format."""
        result = parse_game_score("11 dash 3")
        assert result == (11, 3)
    
    def test_parse_player_one_wins(self):
        """Test 'player one wins 11 3' format."""
        result = parse_game_score("player one wins 11 3")
        assert result == (11, 3)
    
    def test_parse_player_two_wins(self):
        """Test 'player two wins 12 10' format."""
        result = parse_game_score("player two wins 12 10")
        assert result == (12, 10)
    
    def test_parse_player1_wins(self):
        """Test 'player1 wins 11 3' format."""
        result = parse_game_score("player1 wins 11 3")
        assert result == (11, 3)
    
    def test_parse_invalid_string(self):
        """Test invalid strings return None."""
        assert parse_game_score("") is None
        assert parse_game_score("invalid") is None
        assert parse_game_score("11") is None
        assert parse_game_score("abc-def") is None


class TestValidateGameScore:
    """Tests for validate_game_score function."""
    
    def test_valid_11_3(self):
        """Test 11-3 is valid."""
        assert validate_game_score(11, 3) is True
    
    def test_valid_12_3(self):
        """Test 12-3 is valid."""
        assert validate_game_score(12, 3) is True
    
    def test_valid_13_11(self):
        """Test 13-11 is valid (deuce game)."""
        assert validate_game_score(13, 11) is True
    
    def test_invalid_11_10(self):
        """Test 11-10 is invalid (not 2 point lead)."""
        assert validate_game_score(11, 10) is False
    
    def test_invalid_10_8(self):
        """Test 10-8 is invalid (winner < 11)."""
        assert validate_game_score(10, 8) is False
    
    def test_invalid_7_7(self):
        """Test 7-7 is invalid (tie)."""
        assert validate_game_score(7, 7) is False
    
    def test_invalid_negative(self):
        """Test negative scores are invalid."""
        assert validate_game_score(-1, 3) is False
        assert validate_game_score(11, -1) is False


class TestGetGameWinner:
    """Tests for get_game_winner function."""
    
    def test_player1_wins(self):
        """Test player1 wins when score1 > score2."""
        assert get_game_winner(11, 3) == 1
    
    def test_player2_wins(self):
        """Test player2 wins when score2 > score1."""
        assert get_game_winner(3, 11) == 2
    
    def test_tie_returns_none(self):
        """Test tie returns None."""
        assert get_game_winner(10, 10) is None


class TestSummarizeMatch:
    """Tests for summarize_match function."""
    
    def test_player1_wins_after_3_games(self):
        """Test player1 wins after 3 game wins."""
        game_scores = [(11, 3), (11, 5), (11, 8)]
        result = summarize_match(game_scores)
        assert result["player1_games"] == 3
        assert result["player2_games"] == 0
        assert result["winner_side"] == 1
        assert result["is_complete"] is True
        assert result["score_string"] == "11-3, 11-5, 11-8"
    
    def test_player2_wins_after_3_games(self):
        """Test player2 wins after 3 game wins."""
        game_scores = [(3, 11), (5, 11), (8, 11)]
        result = summarize_match(game_scores)
        assert result["player1_games"] == 0
        assert result["player2_games"] == 3
        assert result["winner_side"] == 2
        assert result["is_complete"] is True
        assert result["score_string"] == "3-11, 5-11, 8-11"
    
    def test_not_complete_after_2_games(self):
        """Test match not complete after 2 game wins."""
        game_scores = [(11, 3), (11, 5)]
        result = summarize_match(game_scores)
        assert result["player1_games"] == 2
        assert result["player2_games"] == 0
        assert result["winner_side"] is None
        assert result["is_complete"] is False
    
    def test_mixed_game_scores(self):
        """Test mixed game scores (player1 wins 3-2)."""
        game_scores = [(11, 3), (8, 11), (11, 5), (7, 11), (11, 9)]
        result = summarize_match(game_scores)
        assert result["player1_games"] == 3
        assert result["player2_games"] == 2
        assert result["winner_side"] == 1
        assert result["is_complete"] is True
        assert result["score_string"] == "11-3, 8-11, 11-5, 7-11, 11-9"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])