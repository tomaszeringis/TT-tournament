"""
Tests for the VoiceEvent schema and EventFactory.
"""

import pytest
from datetime import datetime

from tournament_platform.services.voice_event_schema import (
    VoiceEvent,
    EventType,
    EventFactory,
)


class TestVoiceEvent:
    """Tests for VoiceEvent model."""

    def test_create_basic_event(self):
        """Test creating a basic VoiceEvent."""
        event = VoiceEvent(
            event_type=EventType.POINT_WON,
            player="Alice",
            score_after="6-3",
            source_transcript="Point to Alice",
        )
        assert event.event_type == EventType.POINT_WON
        assert event.player == "Alice"
        assert event.score_after == "6-3"
        assert event.source_transcript == "Point to Alice"
        assert event.event_id is not None  # Auto-generated

    def test_event_with_all_fields(self):
        """Test creating a VoiceEvent with all fields."""
        event = VoiceEvent(
            event_id="test-id-123",
            event_type=EventType.MATCH_RESULT,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            match_id=123,
            tournament_id=1,
            player="Alice",
            opponent="Bob",
            score_before="0-0",
            score_after="3-1",
            game_number=1,
            confidence=0.95,
            source_transcript="Alice beat Bob 3-1",
            entities={"winner": "Alice", "score": "3-1"},
            requires_confirmation=True,
        )
        assert event.event_id == "test-id-123"
        assert event.match_id == 123
        assert event.tournament_id == 1
        assert event.requires_confirmation is True

    def test_event_to_dict(self):
        """Test VoiceEvent serialization."""
        event = VoiceEvent(
            event_type=EventType.POINT_WON,
            player="Alice",
            score_after="6-3",
        )
        event_dict = event.model_dump()
        assert event_dict["event_type"] == "point_won"
        assert event_dict["player"] == "Alice"


class TestEventFactory:
    """Tests for EventFactory."""

    def test_create_point_event(self):
        """Test creating a point event."""
        event = EventFactory.create_point_event(
            player="Alice",
            score_before="5-3",
            score_after="6-3",
            source_transcript="Point to Alice",
        )
        assert event.event_type == EventType.POINT_WON
        assert event.player == "Alice"
        assert event.score_before == "5-3"
        assert event.score_after == "6-3"
        assert event.opponent is None

    def test_create_point_event_with_opponent(self):
        """Test creating a point event with opponent."""
        event = EventFactory.create_point_event(
            player="Alice",
            opponent="Bob",
            score_before="5-3",
            score_after="6-3",
            source_transcript="Point to Alice",
        )
        assert event.opponent == "Bob"

    def test_create_undo_event(self):
        """Test creating an undo event."""
        event = EventFactory.create_undo_event(
            score_before="1-0",
            score_after="0-0",
            source_transcript="Undo",
        )
        assert event.event_type == EventType.UNDO
        assert event.entities.get("action") == "undo"

    def test_create_reset_event(self):
        """Test creating a reset event."""
        event = EventFactory.create_reset_event(
            source_transcript="Reset match",
        )
        assert event.event_type == EventType.RESET
        assert event.score_after == "0-0"
        assert event.entities.get("action") == "reset"

    def test_create_score_query_event(self):
        """Test creating a score query event."""
        event = EventFactory.create_score_query_event(
            score="5-3",
            source_transcript="What's the score?",
        )
        assert event.event_type == EventType.SCORE_QUERY
        assert event.score_after == "5-3"

    def test_create_match_result_event(self):
        """Test creating a match result event."""
        event = EventFactory.create_match_result_event(
            player_a="Alice",
            player_b="Bob",
            winner="Alice",
            score="3-1",
            source_transcript="Alice beat Bob 3-1",
        )
        assert event.event_type == EventType.MATCH_RESULT
        assert event.player == "Alice"
        assert event.opponent == "Bob"
        assert event.score_after == "3-1"
        assert event.requires_confirmation is True

    def test_create_server_change_event(self):
        """Test creating a server change event."""
        event = EventFactory.create_server_change_event(
            server="Alice",
            source_transcript="Alice serves",
        )
        assert event.event_type == EventType.SERVER_CHANGE
        assert event.player == "Alice"
        assert event.entities.get("server") == "Alice"

    def test_create_deuce_event(self):
        """Test creating a deuce event."""
        event = EventFactory.create_deuce_event(
            score="10-10",
            source_transcript="Deuce",
        )
        assert event.event_type == EventType.DEUCE
        assert event.score_after == "10-10"

    def test_create_game_point_event(self):
        """Test creating a game point event."""
        event = EventFactory.create_game_point_event(
            player="Alice",
            score="10-8",
            source_transcript="Game point for Alice",
        )
        assert event.event_type == EventType.GAME_POINT
        assert event.player == "Alice"

    def test_create_game_won_event(self):
        """Test creating a game won event."""
        event = EventFactory.create_game_won_event(
            winner="Alice",
            score="11-8",
            sets="1-0",
            source_transcript="Game to Alice",
        )
        assert event.event_type == EventType.GAME_WON
        assert event.player == "Alice"
        assert event.entities.get("sets") == "1-0"


class TestEventType:
    """Tests for EventType enum."""

    def test_all_event_types_exist(self):
        """Test that all required event types are defined."""
        assert EventType.POINT_WON.value == "point_won"
        assert EventType.GAME_WON.value == "game_won"
        assert EventType.MATCH_SUBMITTED.value == "match_submitted"
        assert EventType.UNDO.value == "undo"
        assert EventType.RESET.value == "reset"
        assert EventType.SERVER_CHANGE.value == "server_change"
        assert EventType.DEUCE.value == "deuce"
        assert EventType.GAME_POINT.value == "game_point"
        assert EventType.MATCH_POINT.value == "match_point"
        assert EventType.SCORE_QUERY.value == "score_query"
        assert EventType.MATCH_RESULT.value == "match_result"