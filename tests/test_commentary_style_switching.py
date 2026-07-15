"""
Tests for spoken-commentary style-resolution robustness (coach-freeze fix).

Covers:
* style normalization / aliasing (couch -> coach, commentator -> announcer)
* CommentaryStyle(...) never raises for any normalized value
* every supported style renders each event in en + lt without error/hang
* missing template variables never crash rendering
* empty candidate lists are handled without looping
* silent style yields an empty, non-spoken CommentaryLine
* CommentaryService helpers delegate correctly
"""

import pytest

from tournament_platform.services.commentary_service import (
    CommentaryService,
    CommentarySettings,
    CommentaryStyle,
    CommentaryVerbosity,
    ScoreMoment,
    SpokenScoreState,
)
from tournament_platform.services import commentary_templates as ct
from tournament_platform.app.services.commentary.generator import CommentaryTextGenerator

SUPPORTED = ["neutral", "professional", "coach", "announcer", "minimal", "kids"]

EVENTS = {
    "point_scored": ScoreMoment.POINT_A,
    "deuce": ScoreMoment.DEUCE,
    "advantage": ScoreMoment.ADVANTAGE_A,
    "game_point": ScoreMoment.GAME_POINT_A,
    "set_win": ScoreMoment.GAME_WON_A,
    "match_win": ScoreMoment.MATCH_WON_A,
    "undo": ScoreMoment.UNDO,
    "reset": ScoreMoment.RESET,
    "streak": ScoreMoment.STREAK_A,
    "comeback": ScoreMoment.COMEBACK_A,
}


def _state(moment: ScoreMoment) -> SpokenScoreState:
    scorer_a = moment in (
        ScoreMoment.POINT_A, ScoreMoment.GAME_WON_A, ScoreMoment.MATCH_WON_A,
        ScoreMoment.ADVANTAGE_A, ScoreMoment.GAME_POINT_A, ScoreMoment.STREAK_A,
        ScoreMoment.COMEBACK_A,
    )
    base = dict(
        score_a=1, score_b=0, sets_a=0, sets_b=0, current_set=1,
        player_a="Alice", player_b="Bob", player_a_id=1, player_b_id=2,
        match_history=[{"action": "point_added", "player": "A" if scorer_a else "B"}],
    )
    if moment == ScoreMoment.DEUCE:
        base.update(score_a=10, score_b=10)
    elif moment == ScoreMoment.ADVANTAGE_A:
        base.update(score_a=11, score_b=10)
    elif moment == ScoreMoment.GAME_WON_A:
        base.update(score_a=11, score_b=8, sets_a=1)
    elif moment == ScoreMoment.MATCH_WON_A:
        base.update(score_a=11, score_b=8, sets_a=3, sets_b=1, current_set=5)
    elif moment == ScoreMoment.GAME_POINT_A:
        base.update(score_a=10, score_b=9)
    return SpokenScoreState(**base)


class TestStyleNormalization:
    def test_supported_passthrough(self):
        assert ct.normalize_commentary_style("announcer") == "announcer"
        assert ct.normalize_commentary_style("coach") == "coach"
        assert ct.normalize_commentary_style("neutral") == "neutral"

    def test_aliases(self):
        assert ct.normalize_commentary_style("couch") == "coach"
        assert ct.normalize_commentary_style("couching") == "coach"
        assert ct.normalize_commentary_style("coaching") == "coach"
        assert ct.normalize_commentary_style("commentator") == "announcer"
        assert ct.normalize_commentary_style("sport_commentator") == "announcer"
        assert ct.normalize_commentary_style("energetic") == "announcer"
        assert ct.normalize_commentary_style("beginner") == "neutral"
        assert ct.normalize_commentary_style("simple") == "neutral"

    def test_unknown_falls_back_to_neutral(self):
        assert ct.normalize_commentary_style("bogus") == "neutral"
        assert ct.normalize_commentary_style("") == "neutral"
        assert ct.normalize_commentary_style(None) == "neutral"

    def test_enum_and_case_insensitive(self):
        assert ct.normalize_commentary_style(CommentaryStyle.COACH) == "coach"
        assert ct.normalize_commentary_style("COACH ") == "coach"

    def test_never_raises_when_building_enum(self):
        for raw in ("couch", "commentator", "bogus", "Coach", None, "silent"):
            value = ct.normalize_commentary_style(raw)
            CommentaryStyle(value)  # must not raise

    def test_service_delegates(self):
        assert CommentaryService.normalize_style("couch") == "coach"
        assert list(CommentaryService.get_supported_styles().keys()) == SUPPORTED


class TestStyleRendering:
    def setup_method(self):
        self.generator = CommentaryTextGenerator()

    def _gen(self, style, moment, event_id_str, language):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle(style),
            verbosity=CommentaryVerbosity.STANDARD,
            language=language,
        )
        return self.generator.generate(
            event_type="point_a",
            moment=moment,
            state=_state(moment),
            settings=settings,
            event_id_str=event_id_str,
            event_id="evt-1",
        )

    @pytest.mark.parametrize("style", SUPPORTED)
    @pytest.mark.parametrize("language", ["en", "lt"])
    def test_every_supported_style_renders_without_error(self, style, language):
        for event_id_str, moment in EVENTS.items():
            line = self._gen(style, moment, event_id_str, language)
            assert isinstance(line.text, str)
            # should_speak is a boolean and no exception escaped
            assert isinstance(line.should_speak, bool)

    def test_legacy_coach_alias_renders(self):
        # A persisted "couch" value, once normalized, must render as coach.
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle(ct.normalize_commentary_style("couch")),
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=ScoreMoment.POINT_A,
            state=_state(ScoreMoment.POINT_A),
            settings=settings,
            event_id_str="point_scored",
            event_id="evt-1",
        )
        assert "Alice" in line.text
        assert line.should_speak is True

    def test_silent_style_yields_empty_line(self):
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle.SILENT,
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line = self.generator.generate(
            event_type="point_a",
            moment=ScoreMoment.POINT_A,
            state=_state(ScoreMoment.POINT_A),
            settings=settings,
            event_id_str="point_scored",
            event_id="evt-1",
        )
        assert line.text == ""
        assert line.should_speak is False


class TestTemplateSelectionSafety:
    def test_render_template_missing_var_is_empty(self):
        assert ct.render_template("{missing}", {}) == ""
        assert ct.render_template("{player_a}", {}) == ""

    def test_select_template_empty_candidates_does_not_loop(self):
        # A category with no templates must return an empty selection quickly,
        # never looping or raising.
        chosen, text, recent = ct.select_template("en", "no_such_category", "coach", "normal", {})
        assert chosen is None
        assert text == ""
        assert recent == []

    def test_get_template_candidates_empty_for_unknown(self):
        # An empty candidate set returns [] rather than raising.
        assert ct.get_template_candidates("en", "point_won", "coach", "minimal") == []


class TestServiceBuildScoreCommentary:
    def test_build_score_commentary_handles_legacy_style(self):
        service = CommentaryService()
        settings = CommentarySettings(
            enabled=True,
            style=CommentaryStyle(ct.normalize_commentary_style("commentator")),
            verbosity=CommentaryVerbosity.STANDARD,
            language="en",
        )
        line = service.build_score_commentary(
            event_type="point_a",
            state=_state(ScoreMoment.POINT_A),
            settings=settings,
            event_id="evt-1",
        )
        assert isinstance(line.text, str)
        assert line.should_speak is True
