"""Tests for the Intent Classifier."""

import pytest

from tournament_platform.multimodal_ai.intent_classifier import (
    IntentClassifier,
    IntentResult,
    IntentType,
)


class TestIntentClassifier:
    """Tests for IntentClassifier class."""

    def test_classify_score_update(self):
        """Test classification of score update intents."""
        classifier = IntentClassifier()
        
        # Test various score update patterns
        result = classifier.classify("Player A scores 11-9")
        assert result.intent_type == IntentType.SCORE_UPDATE
        assert result.confidence > 0.5
        
        result = classifier.classify("Update the score to 3-1")
        assert result.intent_type == IntentType.SCORE_UPDATE
        
        result = classifier.classify("Game point for player one")
        assert result.intent_type == IntentType.SCORE_UPDATE

    def test_classify_coaching_query(self):
        """Test classification of coaching query intents."""
        classifier = IntentClassifier()
        
        result = classifier.classify("Analyze my backhand")
        assert result.intent_type == IntentType.COACHING_QUERY
        assert "stroke_type" in result.entities
        assert result.entities["stroke_type"] == "backhand"
        
        result = classifier.classify("Show me coaching tips")
        assert result.intent_type == IntentType.COACHING_QUERY
        
        result = classifier.classify("What's my technique?")
        assert result.intent_type == IntentType.COACHING_QUERY

    def test_classify_session_control(self):
        """Test classification of session control intents."""
        classifier = IntentClassifier()
        
        result = classifier.classify("Start recording session")
        assert result.intent_type == IntentType.SESSION_CONTROL
        assert result.entities.get("action") == "start"
        
        result = classifier.classify("Stop the session")
        assert result.intent_type == IntentType.SESSION_CONTROL
        assert result.entities.get("action") == "stop"

    def test_classify_player_info(self):
        """Test classification of player info intents."""
        classifier = IntentClassifier()
        
        result = classifier.classify("What's player John's rating?")
        assert result.intent_type == IntentType.PLAYER_INFO
        
        result = classifier.classify("Show me my win rate")
        assert result.intent_type == IntentType.PLAYER_INFO

    def test_classify_unknown(self):
        """Test classification of unknown intents."""
        classifier = IntentClassifier()
        
        result = classifier.classify("Hello there")
        assert result.intent_type == IntentType.UNKNOWN
        
        result = classifier.classify("")
        assert result.intent_type == IntentType.UNKNOWN
        
        result = classifier.classify("   ")
        assert result.intent_type == IntentType.UNKNOWN

    def test_extract_score_entities(self):
        """Test extraction of score entities."""
        classifier = IntentClassifier()
        
        result = classifier.classify("The score is 11-5")
        assert "score" in result.entities
        assert result.entities["score"] == "11-5"

    def test_extract_stroke_entities(self):
        """Test extraction of stroke type entities."""
        classifier = IntentClassifier()
        
        for stroke in ["backhand", "forehand", "serve", "loop", "smash"]:
            result = classifier.classify(f"Analyze my {stroke}")
            assert result.entities.get("stroke_type") == stroke

    def test_threshold_behavior(self):
        """Test that threshold affects classification."""
        classifier = IntentClassifier(threshold=0.9)
        
        # Low confidence match should be unknown
        result = classifier.classify("Hello")
        assert result.intent_type == IntentType.UNKNOWN

    def test_get_supported_intents(self):
        """Test getting supported intent types."""
        classifier = IntentClassifier()
        
        intents = classifier.get_supported_intents()
        assert IntentType.SCORE_UPDATE in intents
        assert IntentType.COACHING_QUERY in intents
        assert IntentType.SESSION_CONTROL in intents
        assert IntentType.PLAYER_INFO in intents
        assert IntentType.UNKNOWN in intents

    def test_get_patterns(self):
        """Test getting classification patterns."""
        classifier = IntentClassifier()
        
        patterns = classifier.get_patterns()
        assert IntentType.SCORE_UPDATE in patterns
        assert len(patterns[IntentType.SCORE_UPDATE]) > 0


class TestIntentResult:
    """Tests for IntentResult dataclass."""

    def test_intent_result_creation(self):
        """Test creating an IntentResult."""
        result = IntentResult(
            intent_type=IntentType.SCORE_UPDATE,
            confidence=0.85,
            entities={"score": "11-5"},
            raw_text="The score is 11-5"
        )
        
        assert result.intent_type == IntentType.SCORE_UPDATE
        assert result.confidence == 0.85
        assert result.entities["score"] == "11-5"
        assert result.raw_text == "The score is 11-5"

    def test_intent_result_default_entities(self):
        """Test that entities default to empty dict."""
        result = IntentResult(
            intent_type=IntentType.UNKNOWN,
            confidence=0.0
        )
        
        assert result.entities == {}