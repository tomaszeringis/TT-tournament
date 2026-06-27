"""
Unit tests for the match result parser service.

Tests cover:
- Number-word mapping
- Score normalisation
- Deterministic fallback parser patterns
- High-level parse_match_result integration
"""

import pytest
from unittest.mock import MagicMock, patch

from tournament_platform.services.match_parser import (
    word_to_int,
    normalize_score,
    parse_match_result_fallback,
    parse_match_result,
    _extract_players_and_score,
)


# ---------------------------------------------------------------------------
# Number-word mapping tests
# ---------------------------------------------------------------------------

class TestWordToInt:
    def test_digit_strings(self):
        assert word_to_int("0") == 0
        assert word_to_int("3") == 3
        assert word_to_int("7") == 7

    def test_number_words(self):
        assert word_to_int("zero") == 0
        assert word_to_int("one") == 1
        assert word_to_int("two") == 2
        assert word_to_int("three") == 3
        assert word_to_int("four") == 4
        assert word_to_int("five") == 5
        assert word_to_int("six") == 6
        assert word_to_int("seven") == 7

    def test_alternate_words(self):
        assert word_to_int("none") == 0
        assert word_to_int("nought") == 0
        assert word_to_int("love") == 0
        assert word_to_int("won") == 1

    def test_unknown_word_returns_none(self):
        assert word_to_int("eleven") is None
        assert word_to_int("") is None
        assert word_to_int("abc") is None

    def test_case_insensitive(self):
        assert word_to_int("THREE") == 3
        assert word_to_int("Three") == 3


# ---------------------------------------------------------------------------
# Score normalisation tests
# ---------------------------------------------------------------------------

class TestNormalizeScore:
    def test_digit_hyphen(self):
        assert normalize_score("3-1") == "3-1"

    def test_digit_to(self):
        assert normalize_score("3 to 1") == "3-1"

    def test_digit_colon(self):
        assert normalize_score("3:1") == "3-1"

    def test_word_hyphen(self):
        assert normalize_score("three-one") == "3-1"

    def test_word_to(self):
        assert normalize_score("three to one") == "3-1"

    def test_word_space(self):
        assert normalize_score("three one") == "3-1"

    def test_mixed(self):
        assert normalize_score("3-one") == "3-1"

    def test_invalid_returns_none(self):
        assert normalize_score("abc") is None
        assert normalize_score("3") is None
        assert normalize_score("3-1-2") is None
        assert normalize_score("") is None

    def test_whitespace_handling(self):
        assert normalize_score("  3 - 1  ") == "3-1"


# ---------------------------------------------------------------------------
# Deterministic fallback parser tests
# ---------------------------------------------------------------------------

class TestParseMatchResultFallback:
    def test_alice_beat_bob_3_1(self):
        result = parse_match_result_fallback("Alice beat Bob 3-1")
        assert result["status"] == "success"
        assert result["player1"] == "Alice"
        assert result["player2"] == "Bob"
        assert result["winner"] == "Alice"
        assert result["score"] == "3-1"
        assert result["confidence"] == 0.9
        assert result["warnings"] == []

    def test_alice_defeated_bob_three_one(self):
        result = parse_match_result_fallback("Alice defeated Bob three-one")
        assert result["status"] == "success"
        assert result["player1"] == "Alice"
        assert result["player2"] == "Bob"
        assert result["winner"] == "Alice"
        assert result["score"] == "3-1"

    def test_alice_wins_over_bob_3_to_2(self):
        result = parse_match_result_fallback("Alice wins over Bob 3 to 2")
        assert result["status"] == "success"
        assert result["player1"] == "Alice"
        assert result["player2"] == "Bob"
        assert result["winner"] == "Alice"
        assert result["score"] == "3-2"

    def test_bob_lost_to_alice_1_3(self):
        result = parse_match_result_fallback("Bob lost to Alice 1-3")
        assert result["status"] == "success"
        assert result["player1"] == "Alice"
        assert result["player2"] == "Bob"
        assert result["winner"] == "Alice"
        assert result["score"] == "1-3"

    def test_table_3_alice_beat_bob_three_one(self):
        """Table prefix should be ignored by the regex (captured as part of player name)."""
        result = parse_match_result_fallback("Table 3 Alice beat Bob three one")
        # The regex is greedy but should still capture Alice and Bob
        assert result["player1"] == "Table 3 Alice" or result["player1"] == "Alice"
        assert result["player2"] is not None
        assert result["score"] == "3-1"

    def test_unrecognised_pattern_needs_review(self):
        result = parse_match_result_fallback("The match was really exciting")
        assert result["status"] == "needs_review"
        assert result["player1"] is None
        assert result["player2"] is None
        assert result["warnings"]

    def test_empty_text_returns_error(self):
        result = parse_match_result_fallback("")
        assert result["status"] == "error"
        assert result["warnings"]

    def test_identical_player_names_warning(self):
        result = parse_match_result_fallback("Alice beat Alice 3-1")
        assert result["status"] == "needs_review"
        assert any("identical" in w.lower() for w in result["warnings"])

    def test_unparseable_score_lowers_confidence(self):
        result = parse_match_result_fallback("Alice beat Bob eleven")
        assert result["status"] == "needs_review"
        assert result["score"] is None
        assert result["confidence"] < 0.7

    def test_winner_not_in_players(self):
        # This shouldn't happen with our patterns, but test the guard
        result = parse_match_result_fallback("Alice beat Bob 3-1")
        assert result["winner"] in (result["player1"], result["player2"])


# ---------------------------------------------------------------------------
# High-level parse_match_result integration tests
# ---------------------------------------------------------------------------

class TestParseMatchResultIntegration:
    def test_fallback_success_without_ai(self):
        result = parse_match_result("Alice beat Bob 3-1")
        assert result["status"] == "success"
        assert result["player1"] == "Alice"
        assert result["player2"] == "Bob"
        assert result["score"] == "3-1"

    def test_fallback_needs_review_without_ai(self):
        result = parse_match_result("Something random")
        assert result["status"] == "needs_review"

    def test_ai_engine_fallback_on_exception(self):
        mock_ai = MagicMock()
        mock_ai.parse_match_result.side_effect = Exception("Ollama down")

        result = parse_match_result("Alice beat Bob 3-1", ai_engine=mock_ai)
        # Should still get a valid result from deterministic parser
        assert result["status"] == "success"
        assert result["player1"] == "Alice"

    def test_ai_engine_used_when_fallback_low_confidence(self):
        mock_ai = MagicMock()
        mock_ai.parse_match_result.return_value = MagicMock(
            player_a="Charlie",
            player_b="Dave",
            player_a_score=2,
            player_b_score=3,
            winner="Dave",
        )

        # Use a pattern the fallback can't handle
        result = parse_match_result("Charlie versus Dave, Dave wins 3-2", ai_engine=mock_ai)
        # AI should have been called
        mock_ai.parse_match_result.assert_called_once()

    def test_no_database_writes(self):
        """Ensure parse_match_result never touches the database."""
        # This is a structural test: the function signature has no db parameter
        import inspect
        sig = inspect.signature(parse_match_result)
        assert "db" not in sig.parameters
        assert "session" not in sig.parameters
