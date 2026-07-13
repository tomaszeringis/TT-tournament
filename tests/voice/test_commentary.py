"""
Tests for Commentary Service enhancements (Phase 4).
"""

import time

import pytest

from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    SpokenScoreState,
    ScoreMoment,
    contains_english_commentary,
)


class TestCommentaryService:
    def setup_method(self):
        self.service = CommentaryService()

    def test_streak_commentary_after_three_points(self):
        state = SpokenScoreState(
            score_a=3,
            score_b=0,
            sets_a=0,
            sets_b=0,
            current_set=1,
            player_a="Alice",
            player_b="Bob",
            player_a_id=1,
            player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
            ],
        )
        moment = self.service.classify_score_moment(state)
        assert moment == ScoreMoment.STREAK_A

    def test_commentary_throttled_within_five_seconds(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
        )
        line = self.service.build_score_commentary(
            event_type="point_a",
            state=SpokenScoreState(
                score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
                player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            ),
            settings=settings,
            event_id="evt-1",
        )
        assert line.should_speak is True
        assert self.service.should_speak_commentary("evt-0", "evt-1", settings) is True
        assert self.service.should_speak_commentary("evt-1", "evt-1", settings) is False

    def test_kids_style_template(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.KIDS,
            verbosity=CommentaryVerbosity.STANDARD,
        )
        prev = SpokenScoreState(
            score_a=0,
            score_b=0,
            sets_a=0,
            sets_b=0,
            current_set=1,
            player_a="Alice",
            player_b="Bob",
            player_a_id=1,
            player_b_id=2,
        )
        line = self.service.build_score_commentary(
            event_type="point_a",
            state=SpokenScoreState(
                score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
                player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            ),
            settings=settings,
            event_id="evt-1",
            previous_state=prev,
        )
        assert "Yay" in line.text or "Awesome" in line.text

    def test_silent_verbosity_produces_no_commentary(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.SILENT,
        )
        line = self.service.build_score_commentary(
            event_type="point_a",
            state=SpokenScoreState(
                score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
                player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            ),
            settings=settings,
            event_id="evt-1",
        )
        assert line.text == ""

    def test_comeback_detection(self):
        state = SpokenScoreState(
            score_a=5,
            score_b=5,
            sets_a=0,
            sets_b=0,
            current_set=1,
            player_a="Alice",
            player_b="Bob",
            player_a_id=1,
            player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
            ],
        )
        prev = SpokenScoreState(
            score_a=0,
            score_b=5,
            sets_a=0,
            sets_b=0,
            current_set=1,
            player_a="Alice",
            player_b="Bob",
            player_a_id=1,
            player_b_id=2,
        )
        moment = self.service.classify_score_moment(state, previous_state=prev)
        assert moment == ScoreMoment.COMEBACK_A


class TestLithuanianCommentary:
    def setup_method(self):
        self.service = CommentaryService()

    def _lt_settings(self, style=CommentaryStyle.NEUTRAL):
        return CommentarySettings(
            enabled=True,
            style=style,
            verbosity=CommentaryVerbosity.STANDARD,
            language="lt",
        )

    def test_point_scored_returns_lithuanian_only(self):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        prev = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=self._lt_settings(),
            event_id="evt-lt-1", previous_state=prev,
        )
        assert "Tomas" in line.text
        assert "1–0" in line.text
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False

    def test_deuce_returns_lithuanian_only(self):
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=self._lt_settings(),
            event_id="evt-lt-2",
        )
        assert line.text in ("Lygiosios.", "Rezultatas lygus.", "Lygiųjų būsena.")
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False

    def test_game_won_returns_lithuanian_only(self):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=self._lt_settings(),
            event_id="evt-lt-3",
        )
        assert "Tomas" in line.text
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False

    def test_match_won_returns_lithuanian_only(self):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=self._lt_settings(),
            event_id="evt-lt-4",
        )
        assert "Tomas" in line.text
        assert "3 : 1" in line.text
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False

    def test_lithuanian_diacritics_preserved(self):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Ąžuolas", player_b="Česlovas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=self._lt_settings(),
            event_id="evt-lt-5",
        )
        assert "Ąžuolas" in line.text
        assert "Ą" in line.text

    def test_lt_fallback_never_uses_en(self):
        settings = self._lt_settings(style=CommentaryStyle.ANNOUNCER)
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=settings,
            event_id="evt-lt-6",
        )
        assert "Tomas" in line.text
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False

    def test_mixed_language_rejection_regenerates_lithuanian(self):
        settings = self._lt_settings()
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=settings,
            event_id="evt-lt-7",
        )
        assert line.mixed_language_detected is False

    def test_cache_key_includes_language_and_style(self):
        settings_en = self._lt_settings()
        settings_en.language = "en"
        settings_en.style = CommentaryStyle.NEUTRAL
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line_en = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=settings_en,
            event_id="evt-en-1",
        )
        settings_lt = self._lt_settings()
        line_lt = self.service.build_score_commentary(
            event_type="point_a", state=state, settings=settings_lt,
            event_id="evt-lt-8",
        )
        assert line_en.cache_key != line_lt.cache_key
        assert line_en.cache_hit is False
        assert line_lt.cache_hit is False


class TestContainsEnglishCommentary:
    def test_detects_english_fragment(self):
        assert contains_english_commentary("point for Alice", "lt", ("Alice", "Bob")) is True

    def test_ignores_player_name(self):
        assert contains_english_commentary("Advantage scores 5-3", "lt", ("Advantage", "Bob")) is False

    def test_no_false_positive_for_lithuanian(self):
        assert contains_english_commentary("Tašką laimi Tomas, rezultatas 5–3.", "lt", ("Tomas", "Jonas")) is False

    def test_returns_false_for_en(self):
        assert contains_english_commentary("Point for Alice", "en", ("Alice", "Bob")) is False


class TestBuildSetWinCommentary:
    def setup_method(self):
        self.service = CommentaryService()

    def test_en_set_win_has_correct_winner_and_score(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line = self.service.build_set_win_commentary(
            {
                "event_id": "set_win",
                "game_number": 1,
                "winner": "Alice",
                "loser": "Bob",
                "game_score": "11\u20135",
                "match_score": "1\u20130",
                "completed_games": ["11\u20135"],
                "language": "en",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Alice",
                "player_b": "Bob",
            },
            settings,
        )
        assert line.event_type == "set_win"
        assert line.event_id_str == "set_win"
        assert "Alice" in line.text
        assert "11" in line.text
        assert line.dedupe_key == "set_win:1:Alice:11\u20135"
        assert line.priority == 3
        assert line.tts_language_code == "en-US"

    def test_lt_set_win_no_english_fragments(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="lt",
        )
        line = self.service.build_set_win_commentary(
            {
                "event_id": "set_win",
                "game_number": 2,
                "winner": "Tomas",
                "loser": "Jonas",
                "game_score": "11\u20139",
                "match_score": "2\u20130",
                "completed_games": ["11\u20135", "11\u20139"],
                "language": "lt",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Tomas",
                "player_b": "Jonas",
            },
            settings,
        )
        assert "Tomas" in line.text
        assert contains_english_commentary(line.text, "lt", ("Tomas", "Jonas")) is False
        assert line.tts_language_code == "lt-LT"

    def test_set_win_event_id_is_unique(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line1 = self.service.build_set_win_commentary(
            {
                "event_id": "set_win",
                "game_number": 1,
                "winner": "Alice",
                "loser": "Bob",
                "game_score": "11\u20135",
                "match_score": "1\u20130",
                "completed_games": ["11\u20135"],
                "language": "en",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Alice",
                "player_b": "Bob",
            },
            settings,
        )
        time.sleep(0.0015)
        line2 = self.service.build_set_win_commentary(
            {
                "event_id": "set_win",
                "game_number": 1,
                "winner": "Alice",
                "loser": "Bob",
                "game_score": "11\u20135",
                "match_score": "1\u20130",
                "completed_games": ["11\u20135"],
                "language": "en",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Alice",
                "player_b": "Bob",
            },
            settings,
        )
        assert line1.event_id != line2.event_id
        assert line1.dedupe_key == line2.dedupe_key

    def test_set_win_game_won_alias(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line = self.service.build_set_win_commentary(
            {
                "event_id": "game_won",
                "game_number": 3,
                "winner": "Alice",
                "loser": "Bob",
                "game_score": "11\u20138",
                "match_score": "3\u20130",
                "completed_games": ["11\u20135", "9\u201311", "11\u20138"],
                "language": "en",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Alice",
                "player_b": "Bob",
            },
            settings,
        )
        assert line.event_type == "set_win"
        assert line.event_id_str == "set_win"
        assert "Alice" in line.text

    def test_ollama_rewrite_fallback_on_invalid_output(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
            ollama_rewrite_enabled=True,
        )
        service = CommentaryService()
        service.rewriter._call_ollama = lambda prompt: "Completely different text with wrong score"
        line = service.build_set_win_commentary(
            {
                "event_id": "set_win",
                "game_number": 1,
                "winner": "Alice",
                "loser": "Bob",
                "game_score": "11\u20135",
                "match_score": "1\u20130",
                "completed_games": ["11\u20135"],
                "language": "en",
                "style": "neutral",
                "match_id": "m1",
                "player_a": "Alice",
                "player_b": "Bob",
            },
            settings,
        )
        assert "Alice" in line.text
        assert "11" in line.text
        assert line.used_ollama is False
