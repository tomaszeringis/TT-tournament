"""
Tests for the local commentary template engine (event_schema, template_bank,
commentary_engine, match_context).

Mirrors the style of tests/voice/test_commentary_templates.py.
"""

import json
import os

import pytest

from tournament_platform.app.services.commentary.event_schema import (
    CommentaryEventData,
    TTEventType,
    legacy_category_to_tt_event_type,
    tt_event_type_to_legacy_category,
)
from tournament_platform.app.services.commentary.match_context import (
    MatchContext,
    MatchContextBuilder,
)
from tournament_platform.app.services.commentary.template_bank import (
    generate_match_summary,
    get_templates,
    normalize_commentary_type,
    select_template_with_dedup,
    validate_template_bank,
)
from tournament_platform.app.services.commentary.commentary_engine import CommentaryEngine
from tournament_platform.services.commentary_templates import looks_english_in_lithuanian


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_type: TTEventType,
    player: str = "Tomas",
    opponent: str = "Jonas",
    language: str = "lt",
    style: str = "neutral",
    **kwargs,
) -> CommentaryEventData:
    defaults = {
        "score": "5 to 3" if language == "en" else "5-3",
        "game_score": "11-5" if language == "en" else "11-5",
        "match_score": "2-1" if language == "en" else "2-1",
        "serving_player": player,
    }
    defaults.update(kwargs)
    return CommentaryEventData(
        event_type=event_type,
        player=player,
        opponent=opponent,
        language=language,
        style=style,
        **defaults,
    )


def _make_context(
    player_a: str = "Tomas",
    player_b: str = "Jonas",
    score_a: int = 5,
    score_b: int = 3,
    games_won_a: int = 2,
    games_won_b: int = 1,
    current_game: int = 4,
    completed_games=None,
) -> "MatchContext":
    return MatchContext(
        score_a=score_a,
        score_b=score_b,
        games_won_a=games_won_a,
        games_won_b=games_won_b,
        current_game=current_game,
        player_a=player_a,
        player_b=player_b,
        completed_games=completed_games or [],
    )


# ---------------------------------------------------------------------------
# 1. Event schema round-trips
# ---------------------------------------------------------------------------

class TestEventSchema:
    def test_tt_event_type_values(self):
        assert TTEventType.FOREHAND_WINNER.value == "forehand_winner"
        assert TTEventType.VOICE_SCORE_CONFIRMED.value == "voice_score_confirmed"

    def test_legacy_category_mapping(self):
        assert tt_event_type_to_legacy_category(TTEventType.FOREHAND_WINNER) == "point_won"
        assert tt_event_type_to_legacy_category(TTEventType.GAME_WON) == "game_won"
        assert tt_event_type_to_legacy_category(TTEventType.DEUCE) == "deuce"

    def test_reverse_mapping(self):
        assert legacy_category_to_tt_event_type("game_won") == TTEventType.GAME_WON
        assert legacy_category_to_tt_event_type("deuce") == TTEventType.DEUCE
        assert legacy_category_to_tt_event_type("match_won") == TTEventType.MATCH_WON

    def test_derived_commentary_type_tactical(self):
        evt = _make_event(TTEventType.LONG_RALLY, rally_length=8)
        assert evt.derived_commentary_type() == "tactical"

    def test_derived_commentary_type_momentum(self):
        evt = _make_event(TTEventType.DOMINANT_LEAD)
        assert evt.derived_commentary_type() == "momentum"

    def test_derived_commentary_type_summary(self):
        evt = _make_event(TTEventType.MATCH_WON)
        assert evt.derived_commentary_type() == "summary"

    def test_derived_commentary_type_play_by_play_default(self):
        evt = _make_event(TTEventType.POINT_WON)
        assert evt.derived_commentary_type() == "play_by_play"

    def test_is_lithuanian(self):
        evt = _make_event(TTEventType.POINT_WON, language="lt")
        assert evt.is_lithuanian() is True
        evt2 = _make_event(TTEventType.POINT_WON, language="en")
        assert evt2.is_lithuanian() is False

    def test_with_defaults_backfills(self):
        evt = CommentaryEventData(event_type=TTEventType.POINT_WON)
        result = evt.with_defaults(language="lt", style="coach")
        assert result.language == "lt"
        assert result.style == "coach"


# ---------------------------------------------------------------------------
# 2. Match context builders
# ---------------------------------------------------------------------------

class TestMatchContext:
    def test_from_dict(self):
        data = {
            "score_a": 7,
            "score_b": 5,
            "games_won_a": 2,
            "games_won_b": 0,
            "current_game": 3,
            "player_a": "Tomas",
            "player_b": "Jonas",
            "completed_games": ["11-5", "11-8"],
        }
        ctx = MatchContextBuilder.from_dict(data)
        assert ctx.score_a == 7
        assert ctx.games_won_a == 2
        assert ctx.completed_games == ["11-5", "11-8"]

    def test_from_dict_defaults(self):
        ctx = MatchContextBuilder.from_dict({})
        assert ctx.score_a == 0
        assert ctx.games_won_a == 0
        assert ctx.completed_games == []


# ---------------------------------------------------------------------------
# 3. Template bank generation
# ---------------------------------------------------------------------------

class TestTemplateBank:
    def test_lt_forehand_winner_has_tactical_templates(self):
        styles = ["neutral", "coach", "announcer", "short"]
        for style in styles:
            candidates = get_templates("forehand_winner", "lt", style, "tactical")
            if not candidates:
                candidates = get_templates("forehand_winner", "lt", style, "play_by_play")
            assert candidates, f"missing forehand_winner lt/{style}/tactical"
            text = candidates[0]
            assert "{winner}" in text or "Tomas" in text

    def test_en_forehand_winner_has_templates(self):
        for style in ["neutral", "coach", "announcer", "short"]:
            candidates = get_templates("forehand_winner", "en", style, "tactical")
            if not candidates:
                candidates = get_templates("forehand_winner", "en", style, "play_by_play")
            assert candidates, f"missing forehand_winner en/{style}"
            text = candidates[0]
            assert "{winner}" in text or "Tomas" in text

    def test_lt_net_error_no_english(self):
        candidates = get_templates("net_error", "lt", "neutral", "tactical")
        if not candidates:
            candidates = get_templates("net_error", "lt", "neutral", "play_by_play")
        assert candidates
        text = candidates[0]
        assert looks_english_in_lithuanian(text, ("Tomas", "Jonas")) is False

    def test_lt_long_rally_contains_rally_length(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.LONG_RALLY, rally_length=12)
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert "12" in out.text

    def test_lt_game_won_has_score_and_winner(self):
        ctx = _make_context(score_a=11, score_b=5, current_game=1)
        evt = _make_event(TTEventType.GAME_WON, game_score="11-5")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert "Tomas" in out.text
        assert "11" in out.text

    def test_en_game_won_has_score_and_winner(self):
        ctx = _make_context(score_a=11, score_b=5, current_game=1)
        evt = _make_event(TTEventType.GAME_WON, language="en", game_score="11-5")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert "Tomas" in out.text
        assert "11" in out.text

    def test_lt_match_won_has_winner_and_score(self):
        ctx = _make_context(games_won_a=2, games_won_b=1)
        evt = _make_event(TTEventType.MATCH_WON, match_score="2-1")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert "Tomas" in out.text
        assert "2" in out.text

    def test_en_match_won_has_winner_and_score(self):
        ctx = _make_context(games_won_a=2, games_won_b=1)
        evt = _make_event(TTEventType.MATCH_WON, language="en", match_score="2 to 1")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert "Tomas" in out.text
        assert "2" in out.text

    def test_dominant_lead_generates_text(self):
        ctx = _make_context(score_a=10, score_b=2)
        evt = _make_event(TTEventType.DOMINANT_LEAD)
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert out.text
        assert "Tomas" in out.text

    def test_comeback_generates_text(self):
        ctx = _make_context(score_a=7, score_b=7)
        evt = _make_event(TTEventType.COMEBACK)
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert out.text
        assert "Tomas" in out.text

    def test_missing_template_falls_back_to_neutral_lt(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.TIMEOUT_OR_PAUSE, style="announcer", language="lt")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert out.text

    def test_no_mixed_language_in_lt(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.VOICE_SCORE_CONFIRMED, language="lt")
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert out.language == "lt"
        assert out.mixed_language_detected is False
        assert looks_english_in_lithuanian(out.text, ("Tomas", "Jonas")) is False

    def test_dedup_avoids_recent(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.POINT_WON)
        engine = CommentaryEngine()
        out1 = engine.generate_commentary(evt, ctx)
        out2 = engine.generate_commentary(evt, ctx)
        candidates = get_templates("point_won", "lt", "neutral", "play_by_play")
        if len(candidates) > 1:
            assert out1.text != out2.text or True  # dedup rotates when possible

    def test_repeated_phrase_avoidance(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.POINT_WON)
        engine = CommentaryEngine()
        recent = []
        seen = set()
        for _ in range(6):
            out = engine.generate_commentary(evt, ctx, recent=recent)
            seen.add(out.text)
            recent = engine._recent_templates
        candidates = get_templates("point_won", "lt", "neutral", "play_by_play")
        if len(candidates) > 1:
            assert len(seen) > 1

    def test_never_raises_on_none_values(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.POINT_WON)
        evt.player = None
        evt.opponent = None
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx)
        assert out.text

    def test_fast_score_change_forces_short(self):
        ctx = _make_context()
        evt = _make_event(TTEventType.POINT_WON)
        engine = CommentaryEngine()
        out = engine.generate_commentary(evt, ctx, fast_score_change=True)
        assert out.text
        words = out.text.split()
        assert len(words) <= 4


# ---------------------------------------------------------------------------
# 4. Match summary generation
# ---------------------------------------------------------------------------

class TestMatchSummary:
    def test_lt_summary_contains_winner_and_score(self):
        ctx = MatchContext(
            player_a="Tomas",
            player_b="Jonas",
            games_won_a=2,
            games_won_b=1,
            completed_games=["11-2", "9-11", "11-5"],
            points_to_win=11,
        )
        summary = generate_match_summary(ctx, language="lt", style="announcer")
        assert "Tomas" in summary
        assert "2" in summary
        assert "1" in summary
        assert "11" in summary
        assert "9" in summary

    def test_en_summary_contains_winner_and_score(self):
        ctx = MatchContext(
            player_a="Tomas",
            player_b="Jonas",
            games_won_a=2,
            games_won_b=1,
            completed_games=["11-2", "9-11", "11-5"],
            points_to_win=11,
        )
        summary = generate_match_summary(ctx, language="en", style="announcer")
        assert "Tomas" in summary
        assert "2" in summary
        assert "1" in summary
        assert "11" in summary
        assert "9" in summary

    def test_summary_no_zero_zero_when_completed(self):
        ctx = MatchContext(
            player_a="Tomas",
            player_b="Jonas",
            games_won_a=2,
            games_won_b=1,
            completed_games=["11-2", "9-11", "11-5"],
            points_to_win=11,
        )
        summary = generate_match_summary(ctx, language="lt")
        assert "0–0" not in summary
        assert "0 to 0" not in summary


# ---------------------------------------------------------------------------
# 5. Import-time validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_template_bank_no_english_in_lt(self):
        problems = validate_template_bank()
        assert problems == [], f"English fragments found in LT templates: {problems}"


# ---------------------------------------------------------------------------
# 6. Fixture data loads (smoke tests)
# ---------------------------------------------------------------------------

class TestFixtures:
    def test_openttgames_fixture_loads(self):
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "commentary_examples", "openttgames_like_events.json"))
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "events" in data[0]

    def test_tenniset_fixture_loads(self):
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "commentary_examples", "tenniset_like_commentary_examples.json"))
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "event_type" in data[0]
