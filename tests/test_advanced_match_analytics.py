"""
Tests for Advanced Post-Match Analytics.
"""
from typing import Any, Dict, List, Optional

import pytest

from tournament_platform.app.services.advanced_match_analytics.schemas import (
    AdvancedMatchInsight,
    PointEvent,
    DominationPoint,
    WinProbabilityPoint,
)
from tournament_platform.app.services.advanced_match_analytics.score_probability import (
    game_win_probability,
    build_win_probability_timeline,
)
from tournament_platform.app.services.advanced_match_analytics.pressure import (
    is_pressure_point,
    compute_pressure_summary,
    is_deuce_state,
    is_advantage_state,
    is_game_point,
    is_match_point,
)
from tournament_platform.app.services.advanced_match_analytics.momentum import (
    compute_momentum_summary,
)
from tournament_platform.app.services.advanced_match_analytics.domination import (
    compute_domination,
)
from tournament_platform.app.services.advanced_match_analytics.shot_diversity import (
    compute_shot_diversity,
)
from tournament_platform.app.services.advanced_match_analytics.analyzer import (
    AdvancedMatchAnalyticsService,
)
from tournament_platform.app.services.advanced_match_analytics.formatter import (
    format_insight,
)


def _make_event(
    scorer_side: str = "A",
    score_a_before: int = 0,
    score_b_before: int = 0,
    score_a_after: int = 0,
    score_b_after: int = 0,
    games_a_before: int = 0,
    games_b_before: int = 0,
    games_a_after: int = 0,
    games_b_after: int = 0,
    game_target: int = 11,
    best_of: int = 5,
    **kwargs: Any,
) -> Dict[str, Any]:
    return {
        "match_id": 1,
        "game_index": 0,
        "point_index": 0,
        "scorer_side": scorer_side,
        "player_a_id": 1,
        "player_b_id": 2,
        "score_a_before": score_a_before,
        "score_b_before": score_b_before,
        "score_a_after": score_a_after,
        "score_b_after": score_b_after,
        "games_a_before": games_a_before,
        "games_b_before": games_b_before,
        "games_a_after": games_a_after,
        "games_b_after": games_b_after,
        "game_target": game_target,
        "win_by": 2,
        "best_of": best_of,
        "is_game_winning_point": False,
        "is_match_winning_point": False,
        "timestamp": 0.0,
        "source": "test",
        "server_id": "A",
        "rally_length": None,
        "end_reason": None,
        "shot_type": None,
        "placement": None,
        "notes": None,
        **kwargs,
    }


class TestScoreProbability:
    def test_neutral_start(self):
        prob = game_win_probability(0, 0, p_point_a=0.5, target=11)
        assert abs(prob - 0.5) < 0.01

    def test_deuce_state(self):
        prob = game_win_probability(10, 10, p_point_a=0.5, target=11)
        assert abs(prob - 0.5) < 0.01

    def test_advantage_a(self):
        prob = game_win_probability(11, 10, p_point_a=0.6, target=11)
        assert prob > 0.5

    def test_game_won_a(self):
        prob = game_win_probability(11, 9, p_point_a=0.5, target=11)
        assert prob == 1.0

    def test_game_won_b(self):
        prob = game_win_probability(9, 11, p_point_a=0.5, target=11)
        assert prob == 0.0

    def test_in_progress_8_5(self):
        prob = game_win_probability(8, 5, p_point_a=0.5, target=11)
        assert 0.5 < prob < 1.0

    def test_build_timeline_empty(self):
        assert build_win_probability_timeline([]) == []

    def test_build_timeline_length(self):
        events = [_make_event(score_a_after=5, score_b_after=3), _make_event(score_a_after=5, score_b_after=3)]
        timeline = build_win_probability_timeline(events)
        assert len(timeline) == 2


class TestPressure:
    def test_deuce_detected(self):
        assert is_deuce_state(10, 10, 11)
        assert not is_deuce_state(9, 9, 11)

    def test_advantage_detected(self):
        assert is_advantage_state(11, 10, 11)
        assert not is_advantage_state(10, 9, 11)

    def test_game_point_a(self):
        assert is_game_point(10, 9, 11)
        assert not is_game_point(9, 9, 11)

    def test_game_point_b(self):
        assert is_game_point(9, 10, 11)
        assert not is_game_point(8, 8, 11)

    def test_match_point_a(self):
        assert is_match_point(10, 9, 1, 1, 11, 3)
        assert not is_match_point(10, 9, 2, 1, 11, 3)

    def test_late_close_score(self):
        ev = _make_event(score_a_before=8, score_b_before=8)
        assert is_pressure_point(ev, 11)

    def test_run_stopping(self):
        ev = _make_event(scorer_side="A", score_a_before=4, score_b_before=0)
        assert is_pressure_point(ev, 11)

    def test_pressure_summary_empty(self):
        result = compute_pressure_summary([], 11)
        assert result["total_pressure_points"] == 0
        assert len(result["warnings"]) == 1

    def test_pressure_summary_counts(self):
        events = [
            _make_event(scorer_side="A", score_a_before=10, score_b_before=9, score_a_after=11, score_b_after=9),
        ]
        result = compute_pressure_summary(events, 11)
        assert result["total_pressure_points"] == 1
        assert result["pressure_points_won_a"] == 1


class TestMomentum:
    def test_empty(self):
        result = compute_momentum_summary([])
        assert result["longest_run"] == 0

    def test_longest_run(self):
        events = [_make_event(scorer_side="A"), _make_event(scorer_side="A"), _make_event(scorer_side="B")]
        result = compute_momentum_summary(events)
        assert result["longest_run_player"] == "A"
        assert result["longest_run"] == 2

    def test_lead_changes(self):
        events = [_make_event(scorer_side="A"), _make_event(scorer_side="B"), _make_event(scorer_side="B"), _make_event(scorer_side="A"), _make_event(scorer_side="A")]
        result = compute_momentum_summary(events)
        assert result["lead_changes"] == 2


class TestDomination:
    def test_empty(self):
        gd, winner, timeline = compute_domination([], {}, {}, 11)
        assert gd == 0.0
        assert winner == ""

    def test_values_in_bounds(self):
        events = [_make_event(scorer_side="A"), _make_event(scorer_side="B")]
        gd, winner, timeline = compute_domination(events, {"max_streak_a": 1, "max_streak_b": 1}, {"pressure_points_won_a": 1, "pressure_points_won_b": 1, "total_pressure_points": 2}, 11)
        assert -1.0 <= gd <= 1.0


class TestShotDiversity:
    def test_no_events(self):
        result = compute_shot_diversity([])
        assert result["available"] is False

    def test_missing_annotations(self):
        events = [_make_event(shot_type=None, placement=None, end_reason=None) for _ in range(10)]
        result = compute_shot_diversity(events)
        assert result["available"] is False
        assert "Shot diversity requires point annotations" in result.get("warning", "")

    def test_with_annotations(self):
        events = [_make_event(shot_type="forehand", placement="wide", end_reason="winner") for _ in range(5)]
        result = compute_shot_diversity(events)
        assert result["available"] is True
        assert result["entropy"] >= 0.0


class TestAdvancedMatchAnalyticsService:
    def test_empty_events(self):
        service = AdvancedMatchAnalyticsService(player_a_name="A", player_b_name="B")
        insight = service.analyze([])
        assert insight.match_id is None
        assert "No point history available for advanced analytics." in insight.warnings

    def test_basic_analysis(self):
        service = AdvancedMatchAnalyticsService(player_a_name="A", player_b_name="B")
        events = [
            _make_event(scorer_side="A", score_a_after=1, score_b_after=0),
            _make_event(scorer_side="B", score_a_after=1, score_b_after=1),
            _make_event(scorer_side="A", score_a_after=2, score_b_after=1),
        ]
        insight = service.analyze(events, round_scores=[], games_won_a=0, games_won_b=0)
        assert isinstance(insight, AdvancedMatchInsight)
        assert insight.global_domination != 0.0 or insight.warnings
        assert insight.narrative_summary

    def test_pressure_point_indices_populated(self):
        service = AdvancedMatchAnalyticsService(player_a_name="A", player_b_name="B")
        events = [
            _make_event(scorer_side="A", score_a_before=8, score_b_before=8, score_a_after=9, score_b_after=8),
            _make_event(scorer_side="B", score_a_before=9, score_b_before=8, score_a_after=9, score_b_after=9),
        ]
        insight = service.analyze(events, round_scores=[], games_won_a=0, games_won_b=0)
        assert isinstance(insight.pressure_point_indices, list)
        assert 0 in insight.pressure_point_indices
        assert 1 in insight.pressure_point_indices

    def test_warnings_propagated(self):
        service = AdvancedMatchAnalyticsService(player_a_name="A", player_b_name="B")
        insight = service.analyze([])
        assert insight.warnings


class TestFormatter:
    def test_format_insight(self):
        insight = AdvancedMatchInsight(
            match_id=None,
            player_a_name="A",
            player_b_name="B",
            win_probability_timeline=[],
            domination_timeline=[],
            pressure_summary={"total_pressure_points": 0, "pressure_points_won_a": 0},
            momentum_summary={"longest_run_player": "", "longest_run": 0},
            shot_diversity_summary=None,
            global_domination=0.0,
            domination_winner="",
            biggest_momentum_swing=0.0,
            pressure_points_won_a=0,
            total_pressure_points=0,
            longest_run_player="",
            longest_run=0,
            key_turning_points=[],
            narrative_summary="",
            warnings=[],
        )
        result = format_insight(insight, "A", "B")
        assert "title" in result
        assert "summary" in result
        assert "domination_index" in result
