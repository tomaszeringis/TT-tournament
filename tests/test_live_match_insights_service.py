"""
Tests for live_match_insights_service.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, MatchPointEvent, Match, Tournament, Player, MatchStatus
from tournament_platform.app.services.live_match_insights_service import compute_match_insight, batch_compute_insights, MatchInsight


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _seed_match(db, tournament, player1, player2, status, call_status, score=None, winner=None):
    m = Match(
        tournament_id=tournament.id,
        player1=player1.name,
        player2=player2.name,
        player1_id=player1.id,
        player2_id=player2.id,
        status=status,
        call_status=call_status,
        score=score,
        winner=winner,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_event(match_id, scorer_side, score_a_before, score_b_before, score_a_after, score_b_after,
                games_a_before=0, games_b_before=0, games_a_after=0, games_b_after=0,
                game_target=11, best_of=5, point_index=0):
    return MatchPointEvent(
        match_id=match_id,
        game_index=0,
        point_index=point_index,
        scorer_side=scorer_side,
        score_a_before=score_a_before,
        score_b_before=score_b_before,
        score_a_after=score_a_after,
        score_b_after=score_b_after,
        games_a_before=games_a_before,
        games_b_before=games_b_before,
        games_a_after=games_a_after,
        games_b_after=games_b_after,
        game_target=game_target,
        best_of=best_of,
    )


class TestComputeMatchInsight:
    def test_no_events_returns_no_data(self):
        insight = compute_match_insight([])
        assert insight.point_events_available is False
        assert insight.momentum_label == "No data"
        assert insight.match_id == 0

    def test_single_point_winner(self):
        events = [_make_event(1, "A", 0, 0, 1, 0)]
        insight = compute_match_insight(events)
        assert insight.last_scorer == "A"
        assert insight.current_game_score == (1, 0)
        assert insight.last_3_points == ["A"]

    def test_streak_detection(self):
        events = [
            _make_event(1, "A", 0, 0, 1, 0, point_index=0),
            _make_event(1, "A", 1, 0, 2, 0, point_index=1),
            _make_event(1, "A", 2, 0, 3, 0, point_index=2),
        ]
        insight = compute_match_insight(events)
        assert insight.momentum_label == "Hot streak: A×3"
        assert insight.momentum_color == "red"

    def test_tight_game_when_no_streak(self):
        events = [
            _make_event(1, "A", 0, 0, 1, 0, point_index=0),
            _make_event(1, "B", 1, 0, 1, 1, point_index=1),
            _make_event(1, "A", 1, 1, 2, 1, point_index=2),
        ]
        insight = compute_match_insight(events)
        assert insight.momentum_label == "Tight game"
        assert insight.momentum_color == "green"

    def test_game_point_detection(self):
        events = [_make_event(1, "A", 10, 5, 11, 5)]
        insight = compute_match_insight(events)
        assert insight.is_game_point is True
        assert insight.is_match_point is False

    def test_match_point_detection(self):
        events = [_make_event(1, "A", 5, 3, 6, 3, games_a_before=3, games_b_before=1, games_a_after=4, games_b_after=1, best_of=7)]
        insight = compute_match_insight(events)
        assert insight.is_match_point is True

    def test_last_3_points_window(self):
        events = [
            _make_event(1, "A", 0, 0, 1, 0, point_index=0),
            _make_event(1, "B", 1, 0, 1, 1, point_index=1),
            _make_event(1, "A", 1, 1, 2, 1, point_index=2),
            _make_event(1, "B", 2, 1, 2, 2, point_index=3),
        ]
        insight = compute_match_insight(events)
        assert insight.last_3_points == ["B", "A", "B"]


class TestBatchComputeInsights:
    def test_batch_computes_multiple_matches(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = Tournament(name="Test", tournament_type="knockout")
            db.add(t)
            db.commit()
            db.refresh(t)

            p1 = Player(name="Alice", rating=1500)
            p2 = Player(name="Bob", rating=1400)
            p3 = Player(name="Carol", rating=1300)
            db.add_all([p1, p2, p3])
            db.commit()

            m1 = _seed_match(db, t, p1, p2, MatchStatus.active, "active")
            m2 = _seed_match(db, t, p2, p3, MatchStatus.active, "active")

            db.add_all([
                _make_event(m1.id, "A", 0, 0, 1, 0),
                _make_event(m2.id, "B", 0, 0, 1, 0),
            ])
            db.commit()

            insights = batch_compute_insights([m1.id, m2.id], db)
            assert len(insights) == 2
            assert insights[m1.id].last_scorer == "A"
            assert insights[m2.id].last_scorer == "B"
        finally:
            db.close()
            engine.dispose()

    def test_empty_match_ids_returns_empty(self):
        engine, Session = _make_db()
        db = Session()
        try:
            insights = batch_compute_insights([], db)
            assert insights == {}
        finally:
            db.close()
            engine.dispose()
