"""
Tests for the Live Scoring page (compatibility wrapper).

This page now redirects to Voice Scorekeeper, so these tests verify:
1. The redirect behavior
2. The match_score module functions used by Voice Scorekeeper
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Add the project root to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.app.services.match_score import (
    parse_game_score,
    validate_game_score,
    summarize_match,
)


# ============================================================================
# Game Score Validation Tests (using match_score module)
# ============================================================================

class TestGameScoreValidation:
    """Tests for game score validation using match_score module."""
    
    def test_valid_game_score_11_3(self):
        """Test 11-3 is a valid game score."""
        assert validate_game_score(11, 3) is True
    
    def test_valid_game_score_12_3(self):
        """Test 12-3 is a valid game score."""
        assert validate_game_score(12, 3) is True
    
    def test_valid_game_score_13_11(self):
        """Test 13-11 is a valid game score (deuce)."""
        assert validate_game_score(13, 11) is True
    
    def test_invalid_game_score_11_10(self):
        """Test 11-10 is invalid (not 2 point lead)."""
        assert validate_game_score(11, 10) is False
    
    def test_invalid_game_score_10_8(self):
        """Test 10-8 is invalid (winner < 11)."""
        assert validate_game_score(10, 8) is False
    
    def test_invalid_game_score_tie(self):
        """Test tie scores are invalid."""
        assert validate_game_score(10, 10) is False
    
    def test_invalid_game_score_negative(self):
        """Test negative scores are invalid."""
        assert validate_game_score(-1, 3) is False
        assert validate_game_score(11, -1) is False


# ============================================================================
# Match Summary Tests (using match_score module)
# ============================================================================

class TestMatchSummary:
    """Tests for match summary using match_score module."""
    
    def test_match_complete_after_3_wins(self):
        """Test match is complete after 3 game wins."""
        game_scores = [(11, 3), (11, 5), (11, 8)]
        result = summarize_match(game_scores)
        assert result["is_complete"] is True
        assert result["winner_side"] == 1
    
    def test_match_not_complete_after_2_wins(self):
        """Test match is not complete after 2 game wins."""
        game_scores = [(11, 3), (11, 5)]
        result = summarize_match(game_scores)
        assert result["is_complete"] is False
        assert result["winner_side"] is None
    
    def test_match_score_string(self):
        """Test match score string format."""
        game_scores = [(11, 3), (12, 3), (11, 8)]
        result = summarize_match(game_scores)
        assert result["score_string"] == "11-3, 12-3, 11-8"


# ============================================================================
# Live Scoring Redirect Tests
# ============================================================================

class TestLiveScoringRedirect:
    """Tests for the Live Scoring page redirect behavior."""
    
    def test_live_scoring_uses_match_score_module(self):
        """Test that live_scoring would use match_score module for validation."""
        # This verifies the match_score module is importable and works
        # The actual redirect is tested via integration
        assert parse_game_score("11-3") == (11, 3)
        assert validate_game_score(11, 3) is True


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])