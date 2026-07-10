"""
Tests for Commentary Service enhancements (Phase 4).
"""

import pytest

from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    SpokenScoreState,
    ScoreMoment,
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
