"""
Tests for the voice LLM interpreter (Phase 7).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tournament_platform.app.services.voice_llm import (
    LLMInterpreter,
    LLMInterpreterError,
    LLMProposedEvent,
)


class TestLLMProposedEvent:
    """Tests for the strict LLM output schema."""

    def test_defaults(self):
        event = LLMProposedEvent()
        assert event.type == "unknown"
        assert event.score_a == 0
        assert event.score_b == 0
        assert event.player == "A"
        assert event.confidence == 0.0
        assert event.reasoning == ""
        assert event.requires_confirmation is False

    def test_to_dict_roundtrip(self):
        event = LLMProposedEvent(
            type="increment",
            score_a=5,
            score_b=3,
            player="B",
            confidence=0.9,
            reasoning="Player B scored",
            requires_confirmation=False,
        )
        data = event.to_dict()
        restored = LLMProposedEvent.from_dict(data)
        assert restored.type == "increment"
        assert restored.score_a == 5
        assert restored.score_b == 3
        assert restored.player == "B"
        assert restored.confidence == 0.9
        assert restored.reasoning == "Player B scored"
        assert restored.requires_confirmation is False

    def test_from_dict_with_defaults(self):
        event = LLMProposedEvent.from_dict({"type": "undo"})
        assert event.type == "undo"
        assert event.score_a == 0
        assert event.confidence == 0.0


class TestLLMInterpreter:
    """Tests for LLMInterpreter."""

    @pytest.fixture
    def interpreter(self):
        return LLMInterpreter(enabled=True, model="test-model")

    def test_disabled_raises(self, interpreter):
        interpreter.enabled = False
        with pytest.raises(LLMInterpreterError, match="disabled"):
            interpreter.interpret("point to player one")

    def test_empty_transcript_raises(self, interpreter):
        with pytest.raises(LLMInterpreterError, match="Empty transcript"):
            interpreter.interpret("")

    def test_interpret_valid_increment(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": json.dumps({
                "type": "increment",
                "score_a": 5,
                "score_b": 3,
                "player": "B",
                "confidence": 0.9,
                "reasoning": "Player B scored",
                "requires_confirmation": False,
            })}
        }
        interpreter._client = mock_client

        event = interpreter.interpret("point to player two", current_score_a=5, current_score_b=3)
        assert event.type == "increment"
        assert event.score_a == 5
        assert event.score_b == 3
        assert event.player == "B"
        assert event.confidence == 0.9

    def test_interpret_valid_undo(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": json.dumps({
                "type": "undo",
                "score_a": 5,
                "score_b": 3,
                "player": "A",
                "confidence": 0.95,
                "reasoning": "Undo last point",
                "requires_confirmation": False,
            })}
        }
        interpreter._client = mock_client

        event = interpreter.interpret("undo", current_score_a=5, current_score_b=3)
        assert event.type == "undo"

    def test_interpret_unknown_type(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": json.dumps({
                "type": "invalid_type",
                "confidence": 0.5,
            })}
        }
        interpreter._client = mock_client

        with pytest.raises(LLMInterpreterError, match="Invalid event type"):
            interpreter.interpret("something weird")

    def test_interpret_invalid_json_raises(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "not valid json"}
        }
        interpreter._client = mock_client

        with pytest.raises(LLMInterpreterError, match="not valid JSON"):
            interpreter.interpret("point to player one")

    def test_interpret_ollama_import_error(self, interpreter):
        import sys
        original_ollama = sys.modules.get("ollama")
        sys.modules["ollama"] = None
        try:
            interpreter._client = None  # reset cached client
            with pytest.raises(LLMInterpreterError, match="ollama package not installed"):
                interpreter._get_client()
        finally:
            if original_ollama is not None:
                sys.modules["ollama"] = original_ollama
            else:
                sys.modules.pop("ollama", None)

    def test_interpret_ollama_connection_error(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.side_effect = ConnectionError("Ollama down")
        interpreter._client = mock_client

        with pytest.raises(LLMInterpreterError, match="LLM call failed"):
            interpreter.interpret("point to player one")

    def test_audit_log(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": json.dumps({
                "type": "unknown",
                "confidence": 0.3,
                "reasoning": "Cannot understand",
                "requires_confirmation": True,
            })}
        }
        interpreter._client = mock_client

        interpreter.interpret("gibberish transcript")
        log = interpreter.get_audit_log()
        assert len(log) == 1
        assert log[0]["transcript"] == "gibberish transcript"
        assert log[0]["proposed_event"]["type"] == "unknown"

    def test_clear_audit_log(self, interpreter):
        interpreter._audit_log.append({"test": True})
        interpreter.clear_audit_log()
        assert len(interpreter.get_audit_log()) == 0

    def test_confidence_clamped(self, interpreter):
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": json.dumps({
                "type": "increment",
                "score_a": 1,
                "score_b": 0,
                "player": "A",
                "confidence": 1.5,  # out of range
                "reasoning": "test",
            })}
        }
        interpreter._client = mock_client

        event = interpreter.interpret("point to player one")
        assert event.confidence == 1.0  # clamped
