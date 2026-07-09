"""
Tests for the voice service layer (Phase 8).
"""

import pytest

from tournament_platform.app.services.voice_service import VoiceService, VoiceServiceError
from tournament_platform.services.match_manager import MatchManager


class TestVoiceService:
    """Tests for VoiceService."""

    @pytest.fixture
    def match_manager(self):
        return MatchManager(player_a="Alice", player_b="Bob")

    @pytest.fixture
    def voice_service(self, match_manager):
        return VoiceService(match_manager=match_manager)

    def test_get_match_state(self, voice_service):
        state = voice_service.get_match_state()
        assert state["score_a"] == 0
        assert state["score_b"] == 0
        assert state["player_a"] == "Alice"
        assert state["player_b"] == "Bob"
        assert state["history_count"] == 0

    def test_get_match_state_no_match(self):
        service = VoiceService(match_manager=None)
        with pytest.raises(VoiceServiceError, match="No active match"):
            service.get_match_state()

    def test_create_match(self, voice_service):
        state = voice_service.create_match("Charlie", "Dana", format="best_of_5")
        assert state["player_a"] == "Charlie"
        assert state["player_b"] == "Dana"
        assert state["history_count"] == 0

    def test_process_transcript_empty(self, voice_service):
        with pytest.raises(VoiceServiceError, match="Empty transcript"):
            voice_service.process_transcript("")

    def test_process_transcript_point(self, voice_service):
        processed, event = voice_service.process_transcript("point to player one")
        assert event.type == "increment"
        assert event.player == "A"

    def test_process_transcript_undo(self, voice_service):
        processed, event = voice_service.process_transcript("undo")
        assert event.type == "undo"

    def test_apply_voice_event_increment(self, voice_service):
        processed, event = voice_service.process_transcript("point to player one")
        result = voice_service.apply_voice_event(event)
        assert result["status"] == "accepted"
        assert result["new_score"] == "1-0"

    def test_apply_voice_event_undo(self, voice_service):
        # First add a point
        processed, event = voice_service.process_transcript("point to player one")
        voice_service.apply_voice_event(event)
        # Then undo
        processed, event = voice_service.process_transcript("undo")
        result = voice_service.apply_voice_event(event)
        assert result["status"] == "accepted"
        assert result["new_score"] == "0-0"

    def test_apply_voice_event_unknown_rejected(self, voice_service):
        processed, event = voice_service.process_transcript("gibberish")
        result = voice_service.apply_voice_event(event)
        assert result["status"] == "rejected"
        assert "unknown" in result["message"].lower()

    def test_get_audit_log_empty(self, voice_service):
        # LLM interpreter is disabled by default
        assert voice_service.get_audit_log() == []
