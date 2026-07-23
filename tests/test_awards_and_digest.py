"""
Tests for Awards Service and Daily Digest Service.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from tournament_platform.models import Base, Tournament, Player, Match, MatchStatus
from tournament_platform.app.services.awards_service import get_awards
from tournament_platform.app.services.daily_digest_service import build_daily_digest, post_daily_digest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _seed(db, tournament, p1, p2, score, winner, started_at=None, completed_at=None, game_scores=None):
    from tournament_platform.services.match_reporting import ReportMatchCommand
    m = Match(
        tournament_id=tournament.id,
        player1=p1.name,
        player2=p2.name,
        player1_id=p1.id,
        player2_id=p2.id,
        status=MatchStatus.completed,
        score=score,
        winner=winner,
        game_scores=game_scores,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class TestAwardsService:
    def test_no_matches_returns_empty_awards(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = Tournament(name="Test", tournament_type="knockout")
            db.add(t)
            db.commit()
            awards = get_awards(db, t.id)
            assert awards["champion"] is None
            assert awards["runner_up"] is None
        finally:
            db.close()
            engine.dispose()

    def test_champion_is_latest_winner(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            now = datetime.now(timezone.utc)
            _seed(db, t, p1, p2, "3-1", p1.name, completed_at=now - timedelta(minutes=10))
            _seed(db, t, p2, p1, "3-2", p2.name, completed_at=now)

            awards = get_awards(db, t.id)
            assert awards["champion"] == p2.name
            assert awards["runner_up"] == p1.name
        finally:
            db.close()
            engine.dispose()

    def test_most_dominant_win(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            now = datetime.now(timezone.utc)
            _seed(db, t, p1, p2, "3-1", p1.name, game_scores="11-1, 11-3, 9-11, 11-2", completed_at=now)

            awards = get_awards(db, t.id)
            assert awards["most_dominant_win"] is not None
            assert awards["most_dominant_win"]["max_margin"] == 10
        finally:
            db.close()
            engine.dispose()

    def test_upset_requires_ratings(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            now = datetime.now(timezone.utc)
            _seed(db, t, p1, p2, "3-2", p1.name, completed_at=now)

            awards = get_awards(db, t.id)
            # No ratings set -> no upset
            assert awards["upset_of_the_day"] is None
        finally:
            db.close()
            engine.dispose()


class TestDailyDigestService:
    def test_empty_digest_when_no_matches(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t = Tournament(name="Test", tournament_type="knockout")
            db.add(t)
            db.commit()
            db.refresh(t)

            text = build_daily_digest(db, t.id)
            assert "No completed matches today" in text
            assert t.name in text
        finally:
            db.close()
            engine.dispose()

    def test_digest_includes_today_matches(self):
        engine, Session = _make_db()
        db = Session()
        try:
            t, p1, p2, _ = _seed_tournament_and_players(db)
            now_utc = datetime.now(timezone.utc)
            _seed(db, t, p1, p2, "3-1", p1.name, completed_at=now_utc)

            text = build_daily_digest(db, t.id)
            assert "Daily Digest" in text
            assert "Alice" in text
        finally:
            db.close()
            engine.dispose()


def _seed_tournament_and_players(db):
    t = Tournament(name="T1", tournament_type="knockout")
    db.add(t)
    db.commit()
    db.refresh(t)

    p1 = Player(name="Alice", rating=1500)
    p2 = Player(name="Bob", rating=1400)
    p3 = Player(name="Carol", rating=1300)
    db.add_all([p1, p2, p3])
    db.commit()
    return t, p1, p2, p3
