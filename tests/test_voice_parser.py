"""
Tests for the voice score parser.
"""

import pytest

from tournament_platform.app.services.voice_parser import (
    VoiceParser,
    VoiceScoreEvent,
    _normalize_number_words,
    _extract_score_pair,
    _is_deuce_allowed,
)


class TestNormalizeNumberWords:
    """Tests for number word normalization."""

    def test_for_to_four(self):
        assert "4" in _normalize_number_words("for")

    def test_to_to_two(self):
        assert "2" in _normalize_number_words("to")

    def test_too_to_two(self):
        assert "2" in _normalize_number_words("too")

    def test_oh_to_zero(self):
        assert "0" in _normalize_number_words("oh")

    def test_zero_to_zero(self):
        assert "0" in _normalize_number_words("zero")

    def test_love_to_zero(self):
        assert "0" in _normalize_number_words("love")

    def test_five_stays_five(self):
        assert "5" in _normalize_number_words("five")

    def test_mixed_sentence(self):
        result = _normalize_number_words("for two oh three")
        assert "4" in result
        assert "2" in result
        assert "0" in result
        assert "3" in result


class TestExtractScorePair:
    """Tests for score pair extraction."""

    def test_number_words(self):
        assert _extract_score_pair("five four") == (5, 4)

    def test_digits(self):
        assert _extract_score_pair("6 4") == (6, 4)

    def test_dash_separated(self):
        assert _extract_score_pair("10-8") == (10, 8)

    def test_dash_with_spaces(self):
        assert _extract_score_pair("11 - 9") == (11, 9)

    def test_en_dash(self):
        assert _extract_score_pair("11–9") == (11, 9)

    def test_insufficient_numbers(self):
        assert _extract_score_pair("five") is None

    def test_no_numbers(self):
        assert _extract_score_pair("hello world") is None


class TestIsDeuceAllowed:
    """Tests for deuce validation."""

    def test_deuce_allowed_at_10_10(self):
        assert _is_deuce_allowed(10, 10) is True

    def test_deuce_allowed_at_11_11(self):
        assert _is_deuce_allowed(11, 11) is True

    def test_deuce_not_allowed_at_5_3(self):
        assert _is_deuce_allowed(5, 3) is False

    def test_deuce_not_allowed_at_9_9(self):
        assert _is_deuce_allowed(9, 9) is False


@pytest.fixture
def parser():
    return VoiceParser()


class TestVoiceParser:
    """Tests for VoiceParser."""

    def test_parse_five_four(self, parser):
        event = parser.parse("five four")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4
        assert event.confidence > 0

    def test_parse_six_all(self, parser):
        event = parser.parse("six all")
        assert event.type == "set_score"
        assert event.score_a == 6
        assert event.score_b == 6

    def test_parse_ten_eight(self, parser):
        event = parser.parse("ten eight")
        assert event.type == "set_score"
        assert event.score_a == 10
        assert event.score_b == 8

    def test_parse_eleven_nine(self, parser):
        event = parser.parse("eleven nine")
        assert event.type == "set_score"
        assert event.score_a == 11
        assert event.score_b == 9

    def test_parse_for_two(self, parser):
        event = parser.parse("for two")
        assert event.type == "set_score"
        assert event.score_a == 4
        assert event.score_b == 2

    def test_parse_oh_three(self, parser):
        event = parser.parse("oh three")
        assert event.type == "set_score"
        assert event.score_a == 0
        assert event.score_b == 3

    def test_parse_zero_three(self, parser):
        event = parser.parse("zero three")
        assert event.type == "set_score"
        assert event.score_a == 0
        assert event.score_b == 3

    def test_parse_love_three(self, parser):
        event = parser.parse("love three")
        assert event.type == "set_score"
        assert event.score_a == 0
        assert event.score_b == 3

    def test_parse_numeric_digits(self, parser):
        event = parser.parse("5 4")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4

    def test_parse_dash_separated(self, parser):
        event = parser.parse("11-9")
        assert event.type == "set_score"
        assert event.score_a == 11
        assert event.score_b == 9

    def test_parse_set_score_seven_five(self, parser):
        event = parser.parse("set score seven five")
        assert event.type == "set_score"
        assert event.score_a == 7
        assert event.score_b == 5

    def test_parse_set_score_explicit(self, parser):
        event = parser.parse("set the score ten eight")
        assert event.type == "set_score"
        assert event.score_a == 10
        assert event.score_b == 8

    def test_parse_point_player_one(self, parser):
        event = parser.parse("point player one")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_point_to_player_one(self, parser):
        event = parser.parse("point to player one")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_last_point_to_player_two(self, parser):
        event = parser.parse("last point to player two")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_player_one_scores(self, parser):
        event = parser.parse("player one scores")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_player_two_scores(self, parser):
        event = parser.parse("player two scores")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_undo(self, parser):
        event = parser.parse("undo")
        assert event.type == "undo"
        assert event.confidence > 0

    def test_parse_take_back(self, parser):
        event = parser.parse("take back")
        assert event.type == "undo"

    def test_parse_remove_point(self, parser):
        event = parser.parse("remove point")
        assert event.type == "undo"

    def test_parse_deuce_when_allowed(self, parser):
        event = parser.parse("deuce", current_score_a=10, current_score_b=10)
        assert event.type == "set_score"
        assert event.score_a == 10
        assert event.score_b == 10

    def test_parse_deuce_when_not_allowed(self, parser):
        event = parser.parse("deuce", current_score_a=5, current_score_b=3)
        assert event.type == "unknown"
        assert event.confidence < 0.5

    def test_parse_deuce_at_9_9_not_allowed(self, parser):
        event = parser.parse("deuce", current_score_a=9, current_score_b=9)
        assert event.type == "unknown"

    def test_parse_empty_transcript(self, parser):
        event = parser.parse("")
        assert event.type == "unknown"
        assert event.confidence == 0.0

    def test_parse_none_transcript(self, parser):
        event = parser.parse(None)
        assert event.type == "unknown"
        assert event.confidence == 0.0

    def test_parse_unknown_transcript(self, parser):
        event = parser.parse("hello world")
        assert event.type == "unknown"
        assert event.confidence == 0.0

    def test_parse_preserves_raw_text(self, parser):
        event = parser.parse("Five Four")
        assert event.raw_text == "Five Four"

    def test_parse_point_player_a(self, parser):
        event = parser.parse("point player a")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_point_player_b(self, parser):
        event = parser.parse("point player b")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_player_1(self, parser):
        event = parser.parse("point player 1")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_player_2(self, parser):
        event = parser.parse("point player 2")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_last_point_player_one(self, parser):
        event = parser.parse("last point to player one")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_last_point_player_two(self, parser):
        event = parser.parse("last point to player two")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_case_insensitive(self, parser):
        event = parser.parse("FIVE FOUR")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4

    def test_parse_with_punctuation(self, parser):
        event = parser.parse("five four!")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4

    def test_parse_twelve_ten(self, parser):
        event = parser.parse("twelve ten")
        assert event.type == "set_score"
        assert event.score_a == 12
        assert event.score_b == 10

    def test_parse_thirteen_eleven(self, parser):
        event = parser.parse("thirteen eleven")
        assert event.type == "set_score"
        assert event.score_a == 13
        assert event.score_b == 11

    def test_parse_stop_listening_returns_unknown(self, parser):
        event = parser.parse("stop listening")
        assert event.type == "unknown"

    def test_parse_repeat_returns_unknown(self, parser):
        event = parser.parse("repeat")
        assert event.type == "unknown"


class TestColorAliases:
    """PingScore-style color alias tests (Phase 4)."""

    def test_parse_blue_scores_a(self, parser):
        event = parser.parse("blue")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_teal_scores_a(self, parser):
        event = parser.parse("teal")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_green_scores_a(self, parser):
        event = parser.parse("green")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_red_scores_b(self, parser):
        event = parser.parse("red")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_orange_scores_b(self, parser):
        event = parser.parse("orange")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_read_asr_error_scores_b(self, parser):
        event = parser.parse("read")
        assert event.type == "increment"
        assert event.player == "B"

    def test_parse_blue_in_sentence(self, parser):
        event = parser.parse("that was blue")
        assert event.type == "increment"
        assert event.player == "A"

    def test_parse_red_in_sentence(self, parser):
        event = parser.parse("point to red")
        assert event.type == "increment"
        assert event.player == "B"

    def test_color_alias_confidence(self, parser):
        event = parser.parse("blue")
        assert event.confidence == 0.85
        assert event.type == "increment"
