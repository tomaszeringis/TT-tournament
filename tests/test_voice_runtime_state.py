"""
Tests for VoiceRuntimeState (Phase 1).
"""

import pytest

from tournament_platform.app.services.voice.runtime_state import (
    VoiceRuntimeState,
    get_state,
    set_state,
    reset_state,
    migrate_from_session_state,
    sync_legacy_keys,
)


class TestVoiceRuntimeStateDataclass:
    """Test the dataclass defaults and serialization."""

    def test_defaults(self):
        state = VoiceRuntimeState()
        assert state.selected_match_id is None
        assert state.listening is False
        assert state.mode == "push_to_talk"
        assert state.asr_engine == "faster_whisper"
        assert state.pending_confirmations == []
        assert state.command_log == []
        assert state.rms_samples == []

    def test_to_dict_roundtrip(self):
        state = VoiceRuntimeState(
            selected_match_id=42,
            listening=True,
            mode="continuous",
            last_transcript="hello",
            pending_confirmations=[{"intent": "score_point"}],
        )
        data = state.to_dict()
        restored = VoiceRuntimeState.from_dict(data)
        assert restored.selected_match_id == 42
        assert restored.listening is True
        assert restored.mode == "continuous"
        assert restored.last_transcript == "hello"
        assert restored.pending_confirmations == [{"intent": "score_point"}]

    def test_to_dict_drops_nonserializable(self):
        state = VoiceRuntimeState()
        state.event_logger = object()  # type: ignore
        data = state.to_dict()
        assert "event_logger" not in data


class TestGetSetState:
    """Test session_state helpers."""

    def test_get_state_initializes(self):
        session_state_dict = {}
        state = get_state(session_state_dict)
        assert isinstance(state, VoiceRuntimeState)
        assert state.mode == "push_to_talk"

    def test_set_state_persists(self):
        session_state_dict = {}
        state = get_state(session_state_dict)
        state.selected_match_id = 99
        set_state(state, session_state_dict)
        raw = session_state_dict["voice_runtime_state"]
        assert isinstance(raw, dict)
        assert raw["selected_match_id"] == 99

    def test_reset_state_clears(self):
        session_state_dict = {}
        state = get_state(session_state_dict)
        state.selected_match_id = 99
        set_state(state, session_state_dict)
        reset_state(session_state_dict)
        assert session_state_dict.get("voice_runtime_state") is None


class TestMigrateFromSessionState:
    """Test one-time migration from legacy keys."""

    def test_migrates_legacy_match_keys(self):
        session_state_dict = {
            "voice_selected_match_id": 7,
            "voice_selected_player1_name": "Alice",
            "voice_selected_player2_name": "Bob",
        }
        migrate_from_session_state(session_state_dict)
        state = get_state(session_state_dict)
        assert state.selected_match_id == 7
        assert state.selected_player1_name == "Alice"
        assert state.selected_player2_name == "Bob"

    def test_no_migration_if_already_populated(self):
        session_state_dict = {
            "voice_selected_match_id": 999,
        }
        # Pre-populate new state
        state = get_state(session_state_dict)
        state.selected_match_id = 1
        set_state(state, session_state_dict)
        migrate_from_session_state(session_state_dict)
        state = get_state(session_state_dict)
        assert state.selected_match_id == 1

    def test_sync_legacy_keys_writes_back(self):
        session_state_dict = {}
        state = get_state(session_state_dict)
        state.listening = True
        state.last_transcript = "test"
        sync_legacy_keys(state, session_state_dict)
        assert session_state_dict["voice_listening"] is True
        assert session_state_dict["last_voice_transcript"] == "test"
