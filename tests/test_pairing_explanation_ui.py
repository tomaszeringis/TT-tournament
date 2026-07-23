"""
Tests for the pairing explanation UI component.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Match, MatchStatus, Stage, Player, Entry, Tournament
from tournament_platform.app.components.pairing_explanation_component import (
    PairingExplanation,
    get_pairing_explanation,
    _derive_confidence,
)


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _make_player(db, name):
    p = Player(name=name, rating=1200)
    db.add(p)
    db.flush()
    return p


class TestPairingExplanation:
    def test_unavailable_when_no_reasons(self):
        explanation = PairingExplanation(reasons=[], confidence="unavailable")
        assert explanation.is_available is False

    def test_available_when_reasons_present(self):
        explanation = PairingExplanation(reasons=["Swiss round"], confidence="derived")
        assert explanation.is_available is True

    def test_derive_confidence_stored(self):
        m = Match(stage_id=1, bracket_index=1)
        reasons = ["Group stage match"]
        assert _derive_confidence(m, reasons) == "stored"

    def test_derive_confidence_derived(self):
        m = Match()
        reasons = ["Similar record", "Rematch avoided"]
        assert _derive_confidence(m, reasons) == "derived"

    def test_derive_confidence_partial(self):
        m = Match(stage_id=1)
        reasons = ["Similar record", "Group stage match"]
        assert _derive_confidence(m, reasons) == "partial"

    def test_derive_confidence_unavailable(self):
        m = Match()
        reasons = []
        assert _derive_confidence(m, reasons) == "unavailable"

    def test_get_pairing_explanation_swiss(self):
        engine, Session = _make_db()
        db = Session()
        try:
            a = _make_player(db, "Alice")
            b = _make_player(db, "Bob")
            stage = Stage(stage_type="swiss", name="Swiss Round 1")
            db.add(stage)
            db.flush()
            m = Match(
                player1=a.name, player2=b.name,
                player1_id=a.id, player2_id=b.id,
                stage=stage, status=MatchStatus.pending,
            )
            db.add(m)
            db.commit()

            explanation = get_pairing_explanation(m.id, db)
            assert explanation.is_available is True
            assert any("record" in r.lower() for r in explanation.reasons)
            assert explanation.confidence in ("stored", "derived", "partial")
        finally:
            db.close()
            engine.dispose()

    def test_get_pairing_explanation_byes(self):
        engine, Session = _make_db()
        db = Session()
        try:
            m = Match(player1="Alice", player2=None, player1_id=None)
            db.add(m)
            db.commit()

            explanation = get_pairing_explanation(m.id, db)
            assert explanation.is_available is True
            assert any("Bye" in r for r in explanation.reasons)
        finally:
            db.close()
            engine.dispose()

    def test_get_pairing_explanation_unknown_match(self):
        engine, Session = _make_db()
        db = Session()
        try:
            explanation = get_pairing_explanation(99999, db)
            assert explanation.is_available is False
            assert explanation.confidence == "unavailable"
        finally:
            db.close()
            engine.dispose()
