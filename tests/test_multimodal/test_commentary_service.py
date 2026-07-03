"""
Tests for the CommentaryService — deterministic spoken commentary generation.
"""

import pytest
from unittest.mock import Mock

from tournament_platform.services.commentary_service import (
    CommentaryLine,
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    ScoreMoment,
    SpokenScoreState,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def service():
    return CommentaryService()


@pytest.fixture
def base_state():
    """A neutral 0-0 state with no history."""
    return SpokenScoreState(
        score_a=0,
        score_b=0,
        sets_a=0,
        sets_b=0,
        current_set=1,
        player_a="Anna",
        player_b="Mark",
        player_a_id=1,
        player_b_id=2,
        match_history=[],
    )


@pytest.fixture
def neutral_settings():
    return CommentarySettings(
        enabled=True,
        style=CommentaryStyle.NEUTRAL,
        verbosity=CommentaryVerbosity.STANDARD,
        muted=False,
    )


# ============================================================================
# classify_score_moment
# ============================================================================

class TestClassifyScoreMoment:
    def test_point_a(self, service, base_state):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.POINT_A

    def test_point_b(self, service, base_state):
        state = SpokenScoreState(
            score_a=0, score_b=1, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "B"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.POINT_B

    def test_deuce_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.DEUCE

    def test_advantage_a_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=11, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.ADVANTAGE_A

    def test_advantage_b_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=10, score_b=11, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "B"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.ADVANTAGE_B

    def test_game_point_a_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=10, score_b=8, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.GAME_POINT_A

    def test_game_point_b_detection(self, service, base_state):
        prev = SpokenScoreState(
            score_a=8, score_b=9, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[],
        )
        state = SpokenScoreState(
            score_a=8, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "B"}],
        )
        moment = service.classify_score_moment(state, prev)
        assert moment == ScoreMoment.GAME_POINT_B

    def test_game_won_a_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.GAME_WON_A

    def test_game_won_b_detection(self, service, base_state):
        prev = SpokenScoreState(
            score_a=8, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[],
        )
        state = SpokenScoreState(
            score_a=8, score_b=11, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "B"}],
        )
        moment = service.classify_score_moment(state, prev)
        assert moment == ScoreMoment.GAME_WON_B

    def test_match_won_a_detection(self, service, base_state):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, base_state)
        assert moment == ScoreMoment.MATCH_WON_A

    def test_match_won_b_detection(self, service, base_state):
        prev = SpokenScoreState(
            score_a=8, score_b=10, sets_a=1, sets_b=3, current_set=5,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[],
        )
        state = SpokenScoreState(
            score_a=8, score_b=11, sets_a=1, sets_b=3, current_set=5,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "B"}],
        )
        moment = service.classify_score_moment(state, prev)
        assert moment == ScoreMoment.MATCH_WON_B

    def test_undo_detection(self, service, base_state):
        prev = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[],
        )
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        moment = service.classify_score_moment(state, prev)
        assert moment == ScoreMoment.UNDO

    def test_invalid_when_no_change(self, service, base_state):
        moment = service.classify_score_moment(base_state, base_state)
        assert moment == ScoreMoment.INVALID


# ============================================================================
# format_score_spoken
# ============================================================================

class TestFormatScoreSpoken:
    def test_basic(self, service, base_state):
        assert service.format_score_spoken(base_state) == "0 to 0"

    def test_nonzero(self, service, base_state):
        state = SpokenScoreState(
            score_a=5, score_b=3, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
        )
        assert service.format_score_spoken(state) == "5 to 3"


# ============================================================================
# get_commentary_templates
# ============================================================================

class TestGetCommentaryTemplates:
    def test_neutral_standard_point_a(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.NEUTRAL, ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD
        )
        assert len(templates) > 0
        assert "{player_a}" in templates[0]

    def test_neutral_minimal_point_a_returns_empty(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.NEUTRAL, ScoreMoment.POINT_A, CommentaryVerbosity.MINIMAL
        )
        assert templates == []

    def test_minimal_deuce_returns_template(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.MINIMAL, ScoreMoment.DEUCE, CommentaryVerbosity.MINIMAL
        )
        assert templates == ["Deuce."]

    def test_coach_standard_point_a(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.COACH, ScoreMoment.POINT_A, CommentaryVerbosity.STANDARD
        )
        assert len(templates) > 0
        assert "Good point" in templates[0] or "Nice one" in templates[0]

    def test_announcer_standard_deuce(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.ANNOUNCER, ScoreMoment.DEUCE, CommentaryVerbosity.STANDARD
        )
        assert len(templates) > 0
        assert "Deuce!" in templates[0]

    def test_expressive_point_a(self, service):
        templates = service.get_commentary_templates(
            CommentaryStyle.NEUTRAL, ScoreMoment.POINT_A, CommentaryVerbosity.EXPRESSIVE
        )
        assert len(templates) > 0
        assert "Nice shot" in templates[0] or "Keep it going" in templates[0]


# ============================================================================
# build_score_commentary
# ============================================================================

class TestBuildScoreCommentary:
    def test_point_a_commentary(self, service, base_state, neutral_settings):
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=neutral_settings,
            event_id="evt-1",
            previous_state=base_state,
        )
        assert line.should_speak is True
        assert "Anna" in line.text
        assert "1 to 0" in line.text
        assert line.event_type == "point_a"
        assert line.event_id == "evt-1"

    def test_deuce_commentary(self, service, base_state, neutral_settings):
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=neutral_settings,
            event_id="evt-2",
            previous_state=base_state,
        )
        assert line.text == "Deuce. 10 to 10."

    def test_game_won_commentary(self, service, base_state, neutral_settings):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=neutral_settings,
            event_id="evt-3",
            previous_state=base_state,
        )
        assert line.text == "Game to Anna, 11 to 8."
        assert line.priority == 3

    def test_match_won_commentary(self, service, base_state, neutral_settings):
        state = SpokenScoreState(
            score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=neutral_settings,
            event_id="evt-4",
            previous_state=base_state,
        )
        assert line.text == "Match complete. Anna wins 3 games to 1."
        assert line.priority == 3

    def test_minimal_verbosity_suppresses_point(self, service, base_state):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.MINIMAL,
            muted=False,
        )
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=settings,
            event_id="evt-5",
            previous_state=base_state,
        )
        assert line.should_speak is False
        assert line.text == ""

    def test_minimal_verbosity_keeps_deuce(self, service, base_state):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.MINIMAL,
            muted=False,
        )
        state = SpokenScoreState(
            score_a=10, score_b=10, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=settings,
            event_id="evt-6",
            previous_state=base_state,
        )
        assert line.should_speak is True
        assert line.text == "Deuce."

    def test_disabled_settings_returns_no_speak(self, service, base_state):
        settings = CommentarySettings(enabled=False)
        state = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=settings,
            event_id="evt-7",
            previous_state=base_state,
        )
        assert line.should_speak is False


# ============================================================================
# should_speak_commentary
# ============================================================================

class TestShouldSpeakCommentary:
    def test_enabled_and_not_muted(self, service):
        settings = CommentarySettings(enabled=True, muted=False)
        assert service.should_speak_commentary(None, "evt-1", settings) is True

    def test_disabled(self, service):
        settings = CommentarySettings(enabled=False, muted=False)
        assert service.should_speak_commentary(None, "evt-1", settings) is False

    def test_muted(self, service):
        settings = CommentarySettings(enabled=True, muted=True)
        assert service.should_speak_commentary(None, "evt-1", settings) is False

    def test_duplicate_event_id(self, service):
        settings = CommentarySettings(enabled=True, muted=False)
        assert service.should_speak_commentary("evt-1", "evt-1", settings) is False

    def test_different_event_id(self, service):
        settings = CommentarySettings(enabled=True, muted=False)
        assert service.should_speak_commentary("evt-1", "evt-2", settings) is True


# ============================================================================
# choose_commentary_template
# ============================================================================

class TestChooseCommentaryTemplate:
    def test_empty_list(self, service):
        assert service.choose_commentary_template([]) == ""

    def test_single_template(self, service):
        assert service.choose_commentary_template(["hello"]) == "hello"

    def test_multiple_templates_deterministic(self, service):
        templates = ["first", "second", "third"]
        assert service.choose_commentary_template(templates) == "first"


# ============================================================================
# Integration: full flow
# ============================================================================

class TestFullFlow:
    def test_point_a_full_flow(self, service, base_state):
        prev = base_state
        state = SpokenScoreState(
            score_a=3, score_b=1, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
        )
        event_id = "evt-full-1"
        line = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=settings,
            event_id=event_id,
            previous_state=prev,
        )
        assert line.should_speak is True
        assert "Anna" in line.text
        assert "3 to 1" in line.text
        assert service.should_speak_commentary(None, event_id, settings) is True
        assert service.should_speak_commentary(event_id, event_id, settings) is False

    def test_undo_full_flow(self, service, base_state):
        prev = SpokenScoreState(
            score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[],
        )
        state = SpokenScoreState(
            score_a=0, score_b=0, sets_a=0, sets_b=0, current_set=1,
            player_a="Anna", player_b="Mark", player_a_id=1, player_b_id=2,
            match_history=[{"action": "point_added", "player": "A"}],
        )
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.NEUTRAL,
            verbosity=CommentaryVerbosity.STANDARD,
        )
        event_id = "evt-undo-1"
        line = service.build_score_commentary(
            event_type="undo",
            state=state,
            settings=settings,
            event_id=event_id,
            previous_state=prev,
        )
        assert line.should_speak is True
        # Undo templates include "removed" or "undo"
        assert "removed" in line.text.lower() or "undo" in line.text.lower()
