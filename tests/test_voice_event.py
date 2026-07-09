"""
Tests for the hardened VoiceScoreEvent schema and the EventLogger (Phase 1).

These verify that the event object now carries observability metadata
(timestamp, source, event_id, etc.) without changing existing parser behavior,
and that the EventLogger records/exports structured events safely.
"""

from tournament_platform.app.services.voice_parser import VoiceParser, VoiceScoreEvent
from tournament_platform.app.services.voice_audit import EventLogger


class TestVoiceScoreEventHardening:
    """Hardened schema fields are present and safe by default."""

    def test_auto_event_id_and_timestamp(self):
        event = VoiceScoreEvent(type="unknown")
        assert event.event_id
        assert isinstance(event.event_id, str)
        assert event.timestamp > 0

    def test_defaults_are_safe(self):
        event = VoiceScoreEvent(type="set_score", score_a=5, score_b=4)
        assert event.source == "asr"
        assert event.language == "en"
        assert event.speaker_label is None
        assert event.asr_latency_ms is None
        assert event.noise_rms is None
        assert event.requires_confirmation is False
        assert event.uncertainty == 0.0
        assert event.confidence == 0.0

    def test_parse_populates_hardened_fields(self):
        parser = VoiceParser()
        event = parser.parse("five four")
        assert event.type == "set_score"
        assert event.score_a == 5
        assert event.score_b == 4
        assert event.source == "asr"
        assert event.language == "en"
        assert event.event_id
        assert event.timestamp > 0

    def test_parse_english_behavior_unchanged(self):
        # Regression: existing parser behavior must not change.
        parser = VoiceParser()
        assert parser.parse("six all").type == "set_score"
        assert parser.parse("undo").type == "undo"
        assert parser.parse("point player one").type == "increment"
        assert parser.parse("hello world").type == "unknown"


class TestEventLogger:
    """EventLogger stores, bounds, and exports structured voice events."""

    def test_record_stores_hardened_event(self):
        logger = EventLogger()
        event = VoiceParser().parse("five four")
        logger.record(event, accepted=True, previous_score="0-0", new_score="5-4")
        recent = logger.recent()
        assert len(recent) == 1
        entry = recent[0]
        assert entry["type"] == "set_score"
        assert entry["score_a"] == 5
        assert entry["accepted"] is True
        assert entry["previous_score"] == "0-0"
        assert entry["new_score"] == "5-4"
        assert "event_id" in entry
        assert "timestamp" in entry

    def test_record_rejected_event(self):
        logger = EventLogger()
        event = VoiceParser().parse("hello world")
        logger.record(event, accepted=False, note="unrecognized")
        entry = logger.recent()[0]
        assert entry["accepted"] is False
        assert entry["note"] == "unrecognized"

    def test_recent_limits_and_export(self):
        logger = EventLogger(max_events=3)
        for _ in range(5):
            logger.record(VoiceParser().parse("five four"), accepted=True)
        assert len(logger.recent()) == 3
        assert len(logger.export()) == 3

    def test_clear(self):
        logger = EventLogger()
        logger.record(VoiceParser().parse("five four"), accepted=True)
        logger.clear()
        assert logger.recent() == []

    def test_ring_buffer_bounded(self):
        logger = EventLogger(max_events=2)
        for _ in range(10):
            logger.record(VoiceParser().parse("undo"), accepted=True)
        assert len(logger.export()) == 2
