"""
Tests for voice dataset recorder (Phase 4).
"""

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tournament_platform.models import Base, VoiceCommand
from tournament_platform.app.services.voice.dataset_recorder import VoiceDatasetRecorder, VoiceDatasetSample
from tournament_platform.services.settings import VOICE_DATASET_OPT_IN


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
def recorder_enabled(db):
    with patch("tournament_platform.app.services.voice.dataset_recorder.VOICE_DATASET_OPT_IN", True):
        yield VoiceDatasetRecorder(enabled=True)


@pytest.fixture
def recorder_disabled():
    return VoiceDatasetRecorder(enabled=False)


class TestVoiceDatasetRecorder:
    def test_disabled_returns_none(self, recorder_disabled):
        result = recorder_disabled.record(transcript="hello")
        assert result is None

    def test_record_returns_sample(self, recorder_enabled, db):
        sample = recorder_enabled.record(
            transcript="point to player one",
            parsed_intent="increment",
            expected_intent="increment",
            match_id=1,
            mic_type="headset",
            noise_condition="low",
            db=db,
        )
        assert sample is not None
        assert sample.transcript == "point to player one"
        assert sample.parsed_intent == "increment"
        assert sample.expected_intent == "increment"
        assert sample.matched is True
        assert sample.match_id == 1
        assert sample.mic_type == "headset"

    def test_record_mismatch_sets_correction(self, recorder_enabled, db):
        sample = recorder_enabled.record(
            transcript="point to player one",
            parsed_intent="set_score",
            expected_intent="increment",
            db=db,
        )
        assert sample.matched is False
        assert sample.correction == "increment"

    def test_audio_not_stored_by_default(self, recorder_enabled, db):
        sample = recorder_enabled.record(transcript="hello", db=db)
        assert sample.audio_stored is False

    def test_audio_stored_when_enabled(self, recorder_enabled, db):
        sample = recorder_enabled.record(transcript="hello", record_audio=True, db=db)
        assert sample.audio_stored is True

    def test_get_samples_empty(self, recorder_enabled, db):
        samples = recorder_enabled.get_samples(db=db)
        assert samples == []

    def test_get_samples_returns_recorded(self, recorder_enabled, db):
        recorder_enabled.record(transcript="hello", parsed_intent="unknown", db=db)
        samples = recorder_enabled.get_samples(db=db)
        assert len(samples) == 1
        assert samples[0].transcript == "hello"

    def test_export_jsonl(self, recorder_enabled, db):
        recorder_enabled.record(transcript="hello", parsed_intent="unknown", db=db)
        jsonl = recorder_enabled.export_jsonl(db=db)
        assert "hello" in jsonl
        assert "unknown" in jsonl

    def test_export_csv(self, recorder_enabled, db):
        recorder_enabled.record(transcript="hello", parsed_intent="unknown", db=db)
        csv_data = recorder_enabled.export_csv(db=db)
        assert "hello" in csv_data
        assert "transcript" in csv_data

    def test_accuracy_summary_empty(self, recorder_enabled, db):
        summary = recorder_enabled.accuracy_summary(db=db)
        assert summary["total"] == 0
        assert summary["accuracy"] == 0.0

    def test_accuracy_summary_matched(self, recorder_enabled, db):
        recorder_enabled.record(transcript="a", parsed_intent="increment", expected_intent="increment", db=db)
        recorder_enabled.record(transcript="b", parsed_intent="set_score", expected_intent="increment", db=db)
        summary = recorder_enabled.accuracy_summary(db=db)
        assert summary["total"] == 2
        assert summary["matched"] == 1
        assert summary["mismatched"] == 1
        assert abs(summary["accuracy"] - 0.5) < 1e-9
