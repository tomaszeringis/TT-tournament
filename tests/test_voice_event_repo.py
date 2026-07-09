"""
Tests for voice event persistence (Phase 2).
"""

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, Match, Player, MatchStatus
from tournament_platform.app.services.voice.event_log import VoiceEventRepository, VoiceCommandRepository
from tournament_platform.app.services.voice_service import VoiceService, VoiceServiceError
from tournament_platform.services.match_manager import MatchManager


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def match(db):
    m = Match(player1="Alice", player2="Bob", status=MatchStatus.active)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class TestVoiceEventRepository:
    def test_record_and_get_by_match(self, db, match):
        payload = {
            "match_id": match.id,
            "intent": "score_point",
            "raw_transcript": "point to player one",
            "normalized_text": "point to player one",
            "slots": {"player": "A"},
            "confidence": 0.9,
            "score_before": "0-0",
            "score_after": "1-0",
            "status": "accepted",
            "source": "asr",
        }
        event = VoiceEventRepository.record(payload, db=db)
        assert event.id is not None
        assert event.intent == "score_point"
        assert event.confidence == 0.9

        results = VoiceEventRepository.get_by_match(match.id, db=db)
        assert len(results) == 1
        assert results[0].id == event.id

    def test_cleanup_old(self, db, match):
        from datetime import datetime, timedelta
        old_payload = {
            "match_id": match.id,
            "intent": "score_point",
            "raw_transcript": "old",
            "status": "accepted",
            "created_at": datetime.utcnow() - timedelta(days=40),
        }
        new_payload = {
            "match_id": match.id,
            "intent": "score_point",
            "raw_transcript": "new",
            "status": "accepted",
            "created_at": datetime.utcnow(),
        }
        VoiceEventRepository.record(old_payload, db=db)
        VoiceEventRepository.record(new_payload, db=db)
        results = VoiceEventRepository.get_by_match(match.id, db=db)
        assert len(results) == 2
        with patch("tournament_platform.app.services.voice.event_log.VOICE_RETENTION_DAYS", 30):
            deleted = VoiceEventRepository.cleanup_old(db=db)
        assert deleted == 1
        results = VoiceEventRepository.get_by_match(match.id, db=db)
        assert len(results) == 1


class TestVoiceCommandRepository:
    def test_record_dataset_sample(self, db, match):
        payload = {
            "match_id": match.id,
            "transcript": "point to player one",
            "parsed_intent": "score_point",
            "expected_intent": "score_point",
            "matched": True,
            "mic_type": "headset",
            "noise_condition": "low",
        }
        cmd = VoiceCommandRepository.record(payload, db=db)
        assert cmd.id is not None
        assert cmd.transcript == "point to player one"
        assert cmd.matched is True


class TestVoiceServicePersistence:
    def test_persist_event(self, db, match):
        mm = MatchManager(player_a="Alice", player_b="Bob")
        service = VoiceService(match_manager=mm)
        payload = {
            "match_id": match.id,
            "intent": "score_point",
            "raw_transcript": "point to player one",
            "slots": {"player": "A"},
            "confidence": 0.9,
            "score_before": "0-0",
            "score_after": "1-0",
            "status": "accepted",
        }
        result = service.persist_event(payload, db=db)
        assert result is not None
        assert result["status"] == "persisted"
        assert result["intent"] == "score_point"

    def test_record_dataset_sample_disabled(self):
        mm = MatchManager(player_a="Alice", player_b="Bob")
        service = VoiceService(match_manager=mm)
        payload = {"transcript": "hello"}
        with patch("tournament_platform.app.services.voice_service.VOICE_DATASET_OPT_IN", False):
            result = service.record_dataset_sample(payload)
        assert result is None

    def test_confirm_event_apply(self, db, match):
        mm = MatchManager(player_a="Alice", player_b="Bob")
        service = VoiceService(match_manager=mm)
        payload = {
            "match_id": match.id,
            "intent": "increment",
            "raw_transcript": "point to player one",
            "slots": {"player": "A"},
            "confidence": 0.9,
            "score_before": "0-0",
            "score_after": "1-0",
            "status": "pending_confirm",
            "source": "asr",
        }
        event = VoiceEventRepository.record(payload, db=db)
        result = service.confirm_event(event.id, db=db)
        assert result["status"] == "accepted"
        assert result["new_score"] == "1-0"

