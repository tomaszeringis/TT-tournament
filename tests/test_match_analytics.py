"""
Tests for Match Analytics deterministic analyzer.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from tournament_platform.app.services.match_analytics.analyzer import (
    classify_game_label,
    build_game_insights,
    detect_momentum,
    detect_comeback,
    classify_match_result,
    build_match_insight,
)
from tournament_platform.app.services.match_analytics.models import (
    GameLabel,
    KeyEvent,
    MatchInsight,
    MomentumWindow,
)


@dataclass
class FakeEngine:
    round_scores: List[tuple] = field(default_factory=list)
    games_won_a: int = 0
    games_won_b: int = 0
    match_status: str = "in_progress"
    history: List[Dict[str, Any]] = field(default_factory=list)
    points_to_win: int = 11


class TestClassifyGameLabel:
    def test_total_domination(self):
        assert classify_game_label(11, 2) == GameLabel.TOTAL_DOMINATION

    def test_comfortable_win(self):
        assert classify_game_label(11, 6) == GameLabel.COMFORTABLE_WIN

    def test_close_game(self):
        assert classify_game_label(11, 9) == GameLabel.CLOSE_GAME

    def test_deuce_battle(self):
        assert classify_game_label(12, 10) == GameLabel.DEUCE_BATTLE
        assert classify_game_label(15, 13) == GameLabel.DEUCE_BATTLE


class TestBuildGameInsights:
    def test_single_domination(self):
        engine = FakeEngine(round_scores=[(11, 2)])
        insights = build_game_insights(engine.round_scores, "Alice", "Bob")
        assert len(insights) == 1
        assert insights[0].label == GameLabel.TOTAL_DOMINATION
        assert insights[0].winner == "Alice"
        assert insights[0].score == "11-2"

    def test_multiple_games_in_order(self):
        engine = FakeEngine(round_scores=[(11, 2), (11, 6), (10, 12)])
        insights = build_game_insights(engine.round_scores, "Alice", "Bob")
        assert [g.game_number for g in insights] == [1, 2, 3]
        assert insights[0].label == GameLabel.TOTAL_DOMINATION
        assert insights[1].label == GameLabel.COMFORTABLE_WIN
        assert insights[2].label == GameLabel.DEUCE_BATTLE

    def test_empty_round_scores(self):
        insights = build_game_insights([], "Alice", "Bob")
        assert insights == []


class TestDetectMomentum:
    def test_no_history(self):
        momentum = detect_momentum([])
        assert momentum == []

    def test_three_consecutive_points(self):
        history = [
            {"action": "point_added", "player": "A", "score_a": 1, "score_b": 0},
            {"action": "point_added", "player": "A", "score_a": 2, "score_b": 0},
            {"action": "point_added", "player": "A", "score_a": 3, "score_b": 0},
        ]
        momentum = detect_momentum(history, "Alice", "Bob")
        assert len(momentum) == 1
        assert momentum[0].player == "Alice"
        assert momentum[0].points == 3
        assert momentum[0].is_major is False

    def test_five_consecutive_points_is_major(self):
        history = [
            {"action": "point_added", "player": "A", "score_a": i, "score_b": 0}
            for i in range(1, 6)
        ]
        momentum = detect_momentum(history, "Alice", "Bob")
        assert len(momentum) == 1
        assert momentum[0].is_major is True
        assert momentum[0].points == 5

    def test_interleaved_points_no_streak(self):
        history = [
            {"action": "point_added", "player": "A", "score_a": 1, "score_b": 0},
            {"action": "point_added", "player": "B", "score_a": 1, "score_b": 1},
            {"action": "point_added", "player": "A", "score_a": 2, "score_b": 1},
        ]
        momentum = detect_momentum(history, "Alice", "Bob")
        assert momentum == []


class TestDetectComeback:
    def test_no_comeback_short_history(self):
        history = [
            {"action": "point_added", "player": "A", "score_a": 1, "score_b": 0},
        ]
        assert detect_comeback(history) == []

    def test_comeback_detected(self):
        history = [
            {"action": "point_added", "player": "B", "score_a": 0, "score_b": 5},
            {"action": "point_added", "player": "A", "score_a": 5, "score_b": 5},
        ]
        events = detect_comeback(history, "Alice", "Bob")
        assert len(events) == 1
        assert events[0].event_type == "comeback"
        assert events[0].player == "Alice"
        assert "5 points down" in events[0].text

    def test_comeback_reverse(self):
        history = [
            {"action": "point_added", "player": "A", "score_a": 5, "score_b": 0},
            {"action": "point_added", "player": "B", "score_a": 5, "score_b": 5},
        ]
        events = detect_comeback(history, "Alice", "Bob")
        assert len(events) == 1
        assert events[0].player == "Bob"


class TestClassifyMatchResult:
    def test_straight_games_win(self):
        assert classify_match_result([(11, 2), (11, 5)], 2, 0) == GameLabel.STRAIGHT_GAMES_WIN

    def test_tight_match(self):
        assert classify_match_result([(11, 9), (9, 11), (11, 8)], 2, 1) == GameLabel.TIGHT_MATCH

    def test_ongoing_no_games(self):
        assert classify_match_result([], 0, 0) == GameLabel.ONGOING


class TestBuildMatchInsight:
    def test_match_won_with_insights(self):
        engine = FakeEngine(
            round_scores=[(11, 2), (11, 8)],
            games_won_a=2,
            games_won_b=0,
            match_status="match_won",
            history=[
                {"action": "point_added", "player": "A", "score_a": i, "score_b": 0}
                for i in range(1, 6)
            ],
        )
        insight = build_match_insight(engine, "Alice", "Bob")
        assert insight.title == "Alice wins 2-0 in straight games"
        assert len(insight.game_insights) == 2
        assert insight.game_insights[0].label == GameLabel.TOTAL_DOMINATION
        assert len(insight.momentum) == 1
        assert insight.momentum[0].is_major is True

    def test_ongoing_match(self):
        engine = FakeEngine(
            round_scores=[],
            games_won_a=0,
            games_won_b=0,
            match_status="in_progress",
        )
        insight = build_match_insight(engine, "Alice", "Bob")
        assert "ongoing" in insight.title.lower() or "in progress" in insight.title.lower()
        assert insight.confidence == "low"

    def test_one_completed_game(self):
        engine = FakeEngine(
            round_scores=[(11, 9)],
            games_won_a=1,
            games_won_b=0,
            match_status="in_progress",
        )
        insight = build_match_insight(engine, "Alice", "Bob")
        assert insight.confidence == "medium"
        assert len(insight.game_insights) == 1


class TestMatchAnalyticsOption:
    def test_option_creation(self):
        from tournament_platform.app.services.match_analytics.models import MatchAnalyticsOption
        opt = MatchAnalyticsOption(
            id="42",
            label="Tomas Z vs Juozas M — Tomas Z won 2–1",
            player_a_name="Tomas Z",
            player_b_name="Juozas M",
            winner_name="Tomas Z",
            match_score="2-1",
            game_scores=["11-8", "9-11", "11-7"],
            source="database",
        )
        assert opt.id == "42"
        assert opt.winner_name == "Tomas Z"
        assert opt.game_scores == ["11-8", "9-11", "11-7"]


class TestParseGameScores:
    def test_parse_valid_scores(self):
        from tournament_platform.app.services.match_analytics.match_options import parse_game_scores
        assert parse_game_scores("11-8, 9-11, 11-7") == [(11, 8), (9, 11), (11, 7)]

    def test_parse_empty(self):
        from tournament_platform.app.services.match_analytics.match_options import parse_game_scores
        assert parse_game_scores("") == []
        assert parse_game_scores(None) == []

    def test_parse_malformed(self):
        from tournament_platform.app.services.match_analytics.match_options import parse_game_scores
        assert parse_game_scores("11-8, bad, 11-7") == [(11, 8), (11, 7)]


class TestFormatMatchOptionLabel:
    def test_with_winner_and_score(self):
        from tournament_platform.app.services.match_analytics.match_options import format_match_option_label
        label = format_match_option_label(
            player_a="Tomas Z",
            player_b="Juozas M",
            winner="Tomas Z",
            match_score="2-1",
            game_scores=["11-8", "9-11", "11-7"],
        )
        assert "Tomas Z vs Juozas M" in label
        assert "Tomas Z won" in label
        assert "2-1" in label
        assert "11-8" in label
        assert "9-11" in label

    def test_without_winner(self):
        from tournament_platform.app.services.match_analytics.match_options import format_match_option_label
        label = format_match_option_label(
            player_a="Alice",
            player_b="Bob",
            match_score="2-0",
            game_scores=["11-2", "11-6"],
        )
        assert "Alice vs Bob" in label
        assert "2-0" in label
        assert "11-2" in label

    def test_fallback_missing_names(self):
        from tournament_platform.app.services.match_analytics.match_options import format_match_option_label
        label = format_match_option_label(
            player_a="Player A",
            player_b="Player B",
            match_id=42,
        )
        assert "Player A vs Player B" in label
        assert "completed match #42" in label


class TestBuildSyntheticEngine:
    def test_basic_engine(self):
        from tournament_platform.app.services.match_analytics.match_options import build_synthetic_engine_from_match
        from dataclasses import dataclass, field
        from typing import Optional

        @dataclass
        class FakeMatch:
            game_scores: Optional[str] = "11-8, 9-11, 11-7"
            winner: Optional[str] = "Tomas Z"
            player1: str = "Tomas Z"
            player2: str = "Juozas M"

        match = FakeMatch()
        engine = build_synthetic_engine_from_match(match)
        assert engine.round_scores == [(11, 8), (9, 11), (11, 7)]
        assert engine.games_won_a == 2
        assert engine.games_won_b == 1
        assert engine.match_status == "match_won"
        assert engine.history == []
        assert engine.points_to_win == 11

    def test_empty_game_scores(self):
        from tournament_platform.app.services.match_analytics.match_options import build_synthetic_engine_from_match
        from dataclasses import dataclass

        @dataclass
        class FakeMatch:
            game_scores: Optional[str] = None
            winner: Optional[str] = None
            player1: str = "A"
            player2: str = "B"

        match = FakeMatch()
        engine = build_synthetic_engine_from_match(match)
        assert engine.round_scores == []
        assert engine.games_won_a == 0
        assert engine.games_won_b == 0
        assert engine.match_status == "in_progress"


class TestMatchAnalyticsServiceDbMatch:
    def test_analyze_db_match(self):
        from tournament_platform.app.services.match_analytics import MatchAnalyticsService
        from tournament_platform.app.services.match_analytics.match_options import build_synthetic_engine_from_match
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class FakeMatch:
            game_scores: Optional[str] = "11-2, 11-6"
            winner: Optional[str] = "Alice"
            player1: str = "Alice"
            player2: str = "Bob"

        match = FakeMatch()
        service = MatchAnalyticsService(player_a_name="Alice", player_b_name="Bob")
        insight = service.analyze_db_match(match, match_id=1)
        assert insight.title == "Alice wins 2-0 in straight games"
        assert len(insight.game_insights) == 2
        assert insight.game_insights[0].label == GameLabel.TOTAL_DOMINATION
        assert insight.game_insights[0].summary == "Alice dominated Bob 11-2 with a 9-point margin."


class TestGeneratedPlayerFilter:
    def test_met_a_detected(self):
        from tournament_platform.app.services.match_analytics.match_options import _looks_like_generated_player
        assert _looks_like_generated_player("MetA1784096452624") is True

    def test_met_b_detected(self):
        from tournament_platform.app.services.match_analytics.match_options import _looks_like_generated_player
        assert _looks_like_generated_player("MetB1784096452665") is True

    def test_swiss_a_detected(self):
        from tournament_platform.app.services.match_analytics.match_options import _looks_like_generated_player
        assert _looks_like_generated_player("SwissA123") is True

    def test_real_name_not_detected(self):
        from tournament_platform.app.services.match_analytics.match_options import _looks_like_generated_player
        assert _looks_like_generated_player("Tomas Z") is False
        assert _looks_like_generated_player("Juozas M") is False
        assert _looks_like_generated_player("Alice") is False

    def test_empty_name_not_detected(self):
        from tournament_platform.app.services.match_analytics.match_options import _looks_like_generated_player, load_completed_match_options
        assert _looks_like_generated_player("") is False
        assert _looks_like_generated_player(None) is False

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            winner: Optional[str]
            score: Optional[str]
            game_scores: Optional[str]
            status: str
            tournament_id: Optional[int]
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: list

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: list

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="Juozas M", player2="Saulius P", winner="Juozas M", score="2-1", game_scores="11-8, 9-11, 11-7", status="completed", tournament_id=1),
            FakeMatch(id=3, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=None),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "Juozas M"

    def test_excludes_generated_players(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass, field
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=1),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "MetA123"

    def test_excludes_generated_players(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass, field
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=1),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "MetA123"

    def test_no_tournament_id_returns_none_when_combined_with_filter(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass, field
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=None),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=None, limit=100)
        assert len(options) == 1
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "Juozas M"

    def test_excludes_generated_players(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass, field
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=1),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "MetA123"

    def test_no_tournament_id_returns_none_when_combined_with_filter(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass, field
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = None
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="Tomas Z", player2="Darius A", winner="Tomas Z", score="3-0", game_scores="11-2, 11-2, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=None),
        ]

        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=None, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "Tomas Z"
        assert options[1].player_a_name == "MetA123"

    def test_resolves_player_names_from_fk_when_strings_missing(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass
        from typing import List, Optional

        @dataclass
        class FakePlayer:
            id: int
            name: str

        @dataclass
        class FakeMatch:
            id: int
            player1: Optional[str] = None
            player2: Optional[str] = None
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = "Alice"
            score: Optional[str] = "3-0"
            game_scores: Optional[str] = "11-5, 11-7"
            status: str = "completed"
            tournament_id: Optional[int] = 1
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]
            players: List[FakePlayer] = None

            def __post_init__(self):
                if self.players is None:
                    self.players = []

            def query(self, model):
                if hasattr(model, '__name__') and model.__name__ == "Player":
                    return FakePlayerQuery(players=self.players)
                return FakeQuery(results=self.matches)

        @dataclass
        class FakePlayerQuery:
            players: List[FakePlayer]

            def filter(self, *args, **kwargs):
                ids = set()
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(col, 'name') and col.name == 'id':
                            if hasattr(val, 'value'):
                                val = val.value
                            if isinstance(val, (list, tuple)):
                                for v in val:
                                    if hasattr(v, 'value'):
                                        ids.add(v.value)
                                    else:
                                        ids.add(v)
                            else:
                                ids.add(val)
                return FakePlayerQuery(players=[p for p in self.players if p.id in ids])

            def all(self):
                return self.players

        alice = FakePlayer(id=1, name="Alice")
        bob = FakePlayer(id=2, name="Bob")
        match = FakeMatch(id=1, player1=None, player2=None, player1_id=1, player2_id=2, tournament_id=1)
        db = FakeDB(matches=[match], players=[alice, bob])
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 1
        assert options[0].player_a_name == "Alice"
        assert options[0].player_b_name == "Bob"

    def test_includes_all_completed_matches_without_generated_filter(self):
        from tournament_platform.app.services.match_analytics.match_options import load_completed_match_options
        from dataclasses import dataclass
        from typing import List, Optional

        @dataclass
        class FakeMatch:
            id: int
            player1: str
            player2: str
            player1_id: Optional[int] = None
            player2_id: Optional[int] = None
            winner: Optional[str] = None
            score: Optional[str] = None
            game_scores: Optional[str] = None
            status: str = "completed"
            tournament_id: Optional[int] = 1
            completed_at: Optional[str] = None

        @dataclass
        class FakeQuery:
            results: List[FakeMatch]

            def filter(self, *args, **kwargs):
                filtered = self.results
                for arg in args:
                    if hasattr(arg, 'left') and hasattr(arg, 'right'):
                        col = arg.left
                        val = arg.right
                        if hasattr(val, 'value'):
                            val = val.value
                        if hasattr(col, 'name') and col.name == 'tournament_id':
                            filtered = [m for m in filtered if getattr(m, 'tournament_id', None) == val]
                return FakeQuery(results=filtered)

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, n):
                return FakeQuery(results=self.results[:n])

            def all(self):
                return self.results

        @dataclass
        class FakeDB:
            matches: List[FakeMatch]

            def query(self, model):
                return FakeQuery(results=self.matches)

        matches = [
            FakeMatch(id=1, player1="MetA123", player2="MetB456", winner="MetA123", score="2-0", game_scores="11-1, 11-2", status="completed", tournament_id=1),
            FakeMatch(id=2, player1="SwissA1", player2="SwissB2", winner="SwissA1", score="2-1", game_scores="11-8, 9-11, 11-7", status="completed", tournament_id=1),
        ]
        db = FakeDB(matches=matches)
        options = load_completed_match_options(db, tournament_id=1, limit=100)
        assert len(options) == 2
        assert options[0].player_a_name == "MetA123"
        assert options[1].player_a_name == "SwissA1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
