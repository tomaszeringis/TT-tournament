"""
Tests for the pairing explanation read-model (Phase 4).

Reasons must be derived ONLY from available data; never fabricated.
"""

import time

import pytest

from tournament_platform.models import (
    SessionLocal, Player, Tournament, Match, MatchStatus, Stage, Event, Entry, init_db,
)
from tournament_platform.services.pairing_explanation import explain_pairing

_COUNTER = {"n": 0}


def _uid(prefix: str) -> str:
    _COUNTER["n"] += 1
    return f"{prefix}{int(time.time()*1000)}{_COUNTER['n']}"


@pytest.fixture
def db_session():
    init_db()
    db = SessionLocal()
    yield db
    db.rollback()
    db.close()


def _make_player(db, name):
    p = db.query(Player).filter(Player.name == name).first()
    if not p:
        p = Player(name=name, email=f"{name}@test.local", rating=1200)
        db.add(p)
        db.flush()
    return p


class TestPairingExplanation:
    def test_bye_reason_when_opponent_missing(self):
        m = Match(player1="Alice", player2=None, player1_id=None)
        reasons = explain_pairing(m, db=None)
        assert any("Bye" in r for r in reasons)

    def test_unknown_format_omits_reasons(self):
        m = Match(player1="Alice", player2="Bob")
        reasons = explain_pairing(m, db=None)
        assert reasons == []

    def test_swiss_record_and_rematch_avoidance(self, db_session):
        a = _make_player(db_session, _uid("SwissA"))
        b = _make_player(db_session, _uid("SwissB"))
        db_session.commit()

        stage = Stage(stage_type="swiss", name=_uid("SwissStage"))
        db_session.add(stage)
        db_session.flush()

        m = Match(
            player1=a.name, player2=b.name,
            player1_id=a.id, player2_id=b.id,
            stage=stage, status=MatchStatus.pending,
        )
        db_session.add(m)
        db_session.commit()

        reasons = explain_pairing(m, db_session)
        assert any("similar record" in r.lower() for r in reasons)
        assert any("not met before" in r for r in reasons)

    def test_swiss_rematch_not_claimed_when_already_met(self, db_session):
        a = _make_player(db_session, _uid("MetA"))
        b = _make_player(db_session, _uid("MetB"))
        db_session.commit()

        stage = Stage(stage_type="swiss", name=_uid("SwissStage"))
        db_session.add(stage)
        db_session.flush()

        prior = Match(
            player1=a.name, player2=b.name,
            player1_id=a.id, player2_id=b.id,
            stage=stage, status=MatchStatus.completed, winner=a.name, winner_id=a.id,
        )
        db_session.add(prior)

        m = Match(
            player1=a.name, player2=b.name,
            player1_id=a.id, player2_id=b.id,
            stage=stage, status=MatchStatus.pending,
        )
        db_session.add(m)
        db_session.commit()

        reasons = explain_pairing(m, db_session)
        assert not any("not met before" in r for r in reasons)

    def test_knockout_seed_reason(self, db_session):
        a = _make_player(db_session, _uid("SeedA"))
        b = _make_player(db_session, _uid("SeedB"))
        event = Event(name=_uid("SeedEvent"), event_type="knockout")
        db_session.add(event)
        db_session.flush()
        db_session.add_all([
            Entry(event_id=event.id, player1_id=a.id, seed_position=1),
            Entry(event_id=event.id, player1_id=b.id, seed_position=2),
        ])
        db_session.commit()

        stage = Stage(stage_type="knockout", name=_uid("Knockout"), event_id=event.id)
        db_session.add(stage)
        db_session.flush()

        m = Match(
            player1=a.name, player2=b.name,
            player1_id=a.id, player2_id=b.id,
            stage=stage, status=MatchStatus.pending,
        )
        db_session.add(m)
        db_session.commit()

        reasons = explain_pairing(m, db_session)
        assert any("Seeded match" in r for r in reasons)
