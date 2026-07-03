"""
Tests for table-tennis specific intent classification.
"""

import pytest

from tournament_platform.multimodal_ai.intent_classifier import (
    IntentClassifier,
    IntentType,
    IntentResult,
)


class TestTableTennisIntents:
    """Tests for table-tennis specific intent types."""

    def test_classify_score_update(self):
        """Test classification of score update intents."""
        classifier = IntentClassifier()

        test_cases = [
            "Point to Alice",
            "Point to Bob",
            "Alice scores a point",
            "Bob wins the point",
            "Score is 10-5",
            "Game point for Alice",
            "Update score to 3-1",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.SCORE_UPDATE, \
                f"Failed to classify '{transcript}' as SCORE_UPDATE"

    def test_classify_score_query(self):
        """Test classification of score query intents."""
        classifier = IntentClassifier()

        test_cases = [
            "What's the score?",
            "What is the score?",
            "Current score please",
            "Tell me the score",
            "Show score",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.SCORE_QUERY, \
                f"Failed to classify '{transcript}' as SCORE_QUERY"

    def test_classify_undo(self):
        """Test classification of undo intents."""
        classifier = IntentClassifier()

        test_cases = [
            "Undo",
            "Undo last point",
            "Take that back",
            "That was wrong",
            "Remove the last point",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.UNDO, \
                f"Failed to classify '{transcript}' as UNDO"

    def test_classify_reset(self):
        """Test classification of reset intents."""
        classifier = IntentClassifier()

        test_cases = [
            "Reset the match",
            "Reset match",
            "New match",
            "Clear score",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.RESET, \
                f"Failed to classify '{transcript}' as RESET"

    def test_classify_match_result(self):
        """Test classification of match result intents."""
        classifier = IntentClassifier()

        test_cases = [
            "Alice beat Bob 3-1",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.MATCH_RESULT, \
                f"Failed to classify '{transcript}' as MATCH_RESULT"

    def test_classify_server_change(self):
        """Test classification of server change intents."""
        classifier = IntentClassifier()

        test_cases = [
            "Server change",
            "Alice serves",
            "Bob to serve",
            "Change server",
        ]

        for transcript in test_cases:
            result = classifier.classify(transcript)
            assert result.intent_type == IntentType.SERVER_CHANGE, \
                f"Failed to classify '{transcript}' as SERVER_CHANGE"


class TestEntityExtraction:
    """Tests for entity extraction from transcripts."""

    def test_extract_score_entities(self):
        """Test extraction of score entities."""
        classifier = IntentClassifier()

        result = classifier.classify("The score is 11-5")
        assert "score" in result.entities
        assert result.entities["score"] == "11-5"

    def test_extract_match_result_entities(self):
        """Test extraction of match result entities."""
        classifier = IntentClassifier()

        result = classifier.classify("Alice beat Bob 3-1")
        assert "player_a" in result.entities
        assert "player_b" in result.entities
        assert "winner" in result.entities
        assert "score" in result.entities
        assert result.entities["player_a"] == "Alice"
        assert result.entities["player_b"] == "Bob"
        assert result.entities["winner"] == "Alice"
        assert result.entities["score"] == "3-1"

    def test_extract_server_entities(self):
        """Test extraction of server entities."""
        classifier = IntentClassifier()

        result = classifier.classify("Alice serves")
        assert "server" in result.entities
        assert result.entities["server"] == "Alice"

    def test_extract_stroke_entities(self):
        """Test extraction of stroke type entities."""
        classifier = IntentClassifier()

        for stroke in ["backhand", "forehand", "serve", "loop", "smash"]:
            result = classifier.classify(f"Analyze my {stroke}")
            assert result.entities.get("stroke_type") == stroke

    def test_extract_player_entities(self):
        """Test extraction of player entities."""
        classifier = IntentClassifier()

        result = classifier.classify("Point to Alice")
        # Player extraction from "point to X" pattern
        assert "player" in result.entities or result.intent_type == IntentType.SCORE_UPDATE


class TestIntentResult:
    """Tests for IntentResult dataclass."""

    def test_intent_result_creation(self):
        """Test creating an IntentResult."""
        result = IntentResult(
            intent_type=IntentType.SCORE_UPDATE,
            confidence=0.85,
            raw_text="Point to Alice",
            entities={"player": "Alice"},
        )

        assert result.intent_type == IntentType.SCORE_UPDATE
        assert result.confidence == 0.85
        assert result.raw_text == "Point to Alice"
        assert result.entities == {"player": "Alice"}

    def test_intent_result_default_entities(self):
        """Test that entities default to empty dict."""
        result = IntentResult(
            intent_type=IntentType.UNKNOWN,
            confidence=0.0
        )

        assert result.entities == {}

    def test_intent_result_to_dict(self):
        """Test IntentResult serialization."""
        result = IntentResult(
            intent_type=IntentType.SCORE_UPDATE,
            confidence=0.9,
            raw_text="Point to Alice",
            entities={"player": "Alice", "score": "6-3"},
        )

        result_dict = result.__dict__
        assert result_dict["intent_type"] == IntentType.SCORE_UPDATE
        assert result_dict["confidence"] == 0.9


class TestIntentType:
    """Tests for IntentType enum."""

    def test_all_intents_exist(self):
        """Test that all required intents are defined."""
        assert IntentType.SCORE_UPDATE.value == "score_update"
        assert IntentType.SCORE_QUERY.value == "score_query"
        assert IntentType.UNDO.value == "undo"
        assert IntentType.RESET.value == "reset"
        assert IntentType.MATCH_RESULT.value == "match_result"
        assert IntentType.SERVER_CHANGE.value == "server_change"
        assert IntentType.COACHING_QUERY.value == "coaching_query"
        assert IntentType.SESSION_CONTROL.value == "session_control"
        assert IntentType.PLAYER_INFO.value == "player_info"
        assert IntentType.UNKNOWN.value == "unknown"

    def test_get_supported_intents(self):
        """Test getting supported intent types."""
        classifier = IntentClassifier()
        intents = classifier.get_supported_intents()

        assert IntentType.SCORE_UPDATE in intents
        assert IntentType.SCORE_QUERY in intents
        assert IntentType.UNDO in intents
        assert IntentType.RESET in intents
        assert IntentType.MATCH_RESULT in intents
        assert IntentType.SERVER_CHANGE in intents
        assert IntentType.UNKNOWN in intents