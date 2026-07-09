"""
Tests for the voice vocabulary and transcript post-processor (Phase 6).
"""

import json
import os
import re
import tempfile

import pytest

from tournament_platform.app.services.voice_vocab import (
    VoiceVocabulary,
    TranscriptPostProcessor,
)


class TestVoiceVocabulary:
    """Tests for VoiceVocabulary loading and behavior."""

    def test_empty_vocabulary_defaults(self):
        vocab = VoiceVocabulary()
        assert vocab.score_words == []
        assert vocab.commands == []
        assert vocab.player_names == []
        assert vocab.team_names == []
        assert vocab.corrections == {}
        assert vocab.initial_prompt == ""
        assert vocab.get_initial_prompt() == ""
        assert vocab.get_biasing_words() == []

    def test_load_from_json_file(self):
        data = {
            "score_words": ["love", "zero", "one"],
            "commands": ["point", "undo"],
            "player_names": ["Alice", "Bob"],
            "team_names": ["Team Alpha"],
            "corrections": {"read": "red", "for": "four"},
            "initial_prompt": "Table tennis score",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = f.name

        try:
            vocab = VoiceVocabulary.load(path)
            assert vocab.score_words == ["love", "zero", "one"]
            assert vocab.commands == ["point", "undo"]
            assert vocab.player_names == ["Alice", "Bob"]
            assert vocab.team_names == ["Team Alpha"]
            assert vocab.corrections == {"read": "red", "for": "four"}
            assert vocab.initial_prompt == "Table tennis score"
            assert vocab.get_initial_prompt() == "Table tennis score"
            assert set(vocab.get_biasing_words()) == {
                "love", "zero", "one", "point", "undo", "Alice", "Bob", "Team Alpha"
            }
        finally:
            os.unlink(path)

    def test_load_missing_file_returns_empty(self):
        vocab = VoiceVocabulary.load("/nonexistent/path/vocab.json")
        assert vocab.score_words == []

    def test_load_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("not json")
            path = f.name

        try:
            vocab = VoiceVocabulary.load(path)
            assert vocab.score_words == []
        finally:
            os.unlink(path)

    def test_load_no_path_returns_empty(self):
        vocab = VoiceVocabulary.load("")
        assert vocab.score_words == []

    def test_corrections_compiled_case_insensitive(self):
        vocab = VoiceVocabulary(corrections={"read": "red"})
        assert len(vocab._compiled_corrections) == 1
        pattern = list(vocab._compiled_corrections.keys())[0]
        assert pattern.pattern == r"\bread\b"
        assert pattern.flags & re.IGNORECASE


class TestTranscriptPostProcessor:
    """Tests for TranscriptPostProcessor."""

    @pytest.fixture
    def vocab(self):
        return VoiceVocabulary(
            score_words=["love", "zero"],
            commands=["point", "undo"],
            player_names=["Alice", "Bob"],
            team_names=["Team Alpha"],
            corrections={"read": "red", "for": "four"},
            initial_prompt="",
        )

    @pytest.fixture
    def processor(self, vocab):
        return TranscriptPostProcessor(vocab)

    def test_empty_transcript_unchanged(self, processor):
        assert processor.process("") == ""
        assert processor.process("   ") == ""  # whitespace collapsed

    def test_corrections_applied(self, processor):
        assert processor.process("read scores") == "red scores"
        assert processor.process("for points") == "four points"
        assert processor.process("READ scores") == "red scores"  # case-insensitive

    def test_player_names_normalized(self, processor):
        assert processor.process("alice scores") == "Alice scores"
        assert processor.process("bob wins") == "Bob wins"

    def test_team_names_normalized(self, processor):
        assert processor.process("team alpha plays") == "Team Alpha plays"

    def test_whitespace_collapsed(self, processor):
        assert processor.process("  hello   world  ") == "hello world"

    def test_no_vocabulary_noop(self):
        processor = TranscriptPostProcessor()
        text = "point to player one"
        assert processor.process(text) == text

    def test_extract_entities(self, processor):
        entities = processor.extract_entities("Alice scores four love")
        assert "Alice" in entities["player_names"]
        assert "love" in entities["score_words"]
        assert "point" not in entities["commands"]

    def test_extract_entities_case_insensitive(self, processor):
        entities = processor.extract_entities("alice scores")
        assert "Alice" in entities["player_names"]
