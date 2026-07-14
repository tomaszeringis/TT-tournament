"""
Tests for CommentaryTextGenerator.
"""

import pytest

from tournament_platform.services.commentary_service import (
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    SpokenScoreState,
)
from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator


class TestCommentaryTextGenerator:
    def setup_method(self):
        self.generator = CommentaryTextGenerator()

    def test_generate_en_point(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.POINT_A,
            state=state,
            settings=settings,
            event_id_str="point_scored",
            event_id="evt-1",
        )
        assert "Alice" in line.text
        assert line.priority == 2
        assert line.should_speak is True
        assert line.cache_key is None
        assert line.cache_hit is False

    def test_generate_lt_point(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="lt",
        )
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Tomas", player_b="Jonas", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.POINT_A,
            state=state,
            settings=settings,
            event_id_str="point_scored",
            event_id="evt-1",
        )
        assert "Tomas" in line.text
        assert "1–0" in line.text

    def test_generate_game_won(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=1, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.GAME_WON_A,
            state=state,
            settings=settings,
            event_id_str="set_win",
            event_id="evt-1",
        )
        assert line.priority == 3
        assert "Alice" in line.text

    def test_generate_deuce(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.DEUCE,
            state=state,
            settings=settings,
            event_id_str="deuce",
            event_id="evt-1",
        )
        assert line.priority == 3
        assert "Deuce" in line.text

    def test_generate_advantage(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=11, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.ADVANTAGE_A,
            state=state,
            settings=settings,
            event_id_str="advantage",
            event_id="evt-1",
        )
        assert line.priority == 3
        assert "Advantage" in line.text

    def test_generate_match_won(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.MATCH_WON_A,
            state=state,
            settings=settings,
            event_id_str="match_win",
            event_id="evt-1",
        )
        assert line.priority == 3
        assert "Alice" in line.text

    def test_generate_undo(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.generator.generate(
            event_type="undo",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.UNDO,
            state=state,
            settings=settings,
            event_id_str="undo",
            event_id="evt-1",
        )
        assert "removed" in line.text.lower() or "undo" in line.text.lower()

    def test_generate_reset(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.generator.generate(
            event_type="reset",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.RESET,
            state=state,
            settings=settings,
            event_id_str="reset",
            event_id="evt-1",
        )
        assert "reset" in line.text.lower()

    def test_generate_with_ollama_disabled(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
            ollama_rewrite_enabled=False,
        )
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=__import__("tournament_platform.services.commentary_service", fromlist=["ScoreMoment"]).ScoreMoment.POINT_A,
            state=state,
            settings=settings,
            event_id_str="point_scored",
            event_id="evt-1",
        )
        assert line.used_ollama is False
