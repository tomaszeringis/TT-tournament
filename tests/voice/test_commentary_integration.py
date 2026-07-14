"""
Integration tests for the new commentary architecture.
"""

import pytest

from tournament_platform.services.commentary_service import (
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    CommentaryService,
    SpokenScoreState,
)
from tournament_platform.app.services.commentary import (
    CommentaryContextBuilder,
    CommentaryEvent,
    CommentaryEventType,
    CommentaryOrchestrator,
    CommentaryPolicy,
    CommentaryTextGenerator,
)


class TestCommentaryOrchestrator:
    def setup_method(self):
        self.orchestrator = CommentaryOrchestrator()
        self.settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )

    def test_delegates_to_service(self):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.orchestrator.build_score_commentary(
            event_type="point_a", state=state, settings=self.settings, event_id="evt-1"
        )
        assert line.text != ""

    def test_should_generate_delegates(self):
        assert self.orchestrator.should_generate("point_scored", "normal", "every_point", "medium") is True
        assert self.orchestrator.should_generate("point_scored", "normal", "off", "medium") is False

    def test_should_speak_delegates(self):
        assert self.orchestrator.should_speak(None, "evt-1", self.settings) is True
        assert self.orchestrator.should_speak("evt-1", "evt-1", self.settings) is False


class TestEndToEndMoments:
    def setup_method(self):
        self.service = CommentaryService()

    def _settings(self, language="en"):
        return CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
            language=language,
        )

    def test_point_a(self):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Alice" in line.text
        assert line.priority == 2

    def test_deuce(self):
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Deuce" in line.text
        assert line.priority == 3

    def test_advantage_a(self):
        state = SpokenScoreState(
            score_a=11, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Advantage" in line.text
        assert line.priority == 3

    def test_game_point_a(self):
        state = SpokenScoreState(
            score_a=10, score_b=8, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Game point" in line.text
        assert line.priority == 3

    def test_game_won_a(self):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=1, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Alice" in line.text
        assert line.priority == 3

    def test_match_won_a(self):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "Alice" in line.text
        assert line.priority == 3

    def test_undo(self):
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        prev = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary("undo", state, self._settings(), "evt-1", previous_state=prev)
        assert "removed" in line.text.lower() or "undo" in line.text.lower()
        assert line.priority == 2

    def test_reset(self):
        prev = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary("reset", state, self._settings(), "evt-1", previous_state=prev)
        assert "removed" in line.text.lower() or "undo" in line.text.lower() or "reset" in line.text.lower()
        assert line.priority == 2

    def test_streak(self):
        state = SpokenScoreState(
            score_a=3, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
            match_history=[
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
                {"action": "point_added", "player": "A"},
            ],
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1")
        assert "streak" in line.text.lower() or "hot" in line.text.lower() or "un" in line.text.lower()
        assert line.priority == 2

    def test_comeback(self):
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
        prev = SpokenScoreState(
            score_a=0, score_b=5, sets_a=0, sets_b=0, current_set=1,
            player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        )
        line = self.service.build_score_commentary("point_a", state, self._settings(), "evt-1", previous_state=prev)
        assert "comeback" in line.text.lower() or "fight" in line.text.lower()
        assert line.priority == 2
