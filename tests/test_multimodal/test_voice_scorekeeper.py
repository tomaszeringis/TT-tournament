"""
Tests for voice scorekeeper intent classification and coaching integration.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from tournament_platform.multimodal_ai.intent_classifier import (
    IntentClassifier,
    IntentType,
    IntentResult
)


# Test fixtures
@pytest.fixture
def intent_classifier():
    """Create an IntentClassifier instance for testing."""
    return IntentClassifier(threshold=0.3)


@pytest.fixture
def sample_transcripts():
    """Sample voice command transcripts for testing."""
    return {
        "score_update": [
            "Player A scores a point",
            "Point to player B",
            "Player one wins the point",
            "Score is 10-5",
            "Game point for player A"
        ],
        "coaching_query": [
            "How can I improve my backhand?",
            "What's the right forehand technique?",
            "Give me tips for my serve",
            "Coaching on footwork please"
        ],
        "session_control": [
            "Start a new game",
            "Stop the match",
            "Begin recording",
            "End session"
        ],
        "player_info": [
            "Who is player A?",
            "What's the current score?",
            "Show player stats",
            "Player B rating?"
        ]
    }


class TestIntentClassifier:
    """Tests for IntentClassifier."""
    
    def test_classify_score_update(self, intent_classifier, sample_transcripts):
        """Test classification of score update commands."""
        for transcript in sample_transcripts["score_update"]:
            result = intent_classifier.classify(transcript)
            assert result.intent_type == IntentType.SCORE_UPDATE, \
                f"Failed to classify '{transcript}' as SCORE_UPDATE"
            assert result.confidence > 0, "Confidence should be positive"
    
    def test_classify_coaching_query(self, intent_classifier, sample_transcripts):
        """Test classification of coaching queries."""
        for transcript in sample_transcripts["coaching_query"]:
            result = intent_classifier.classify(transcript)
            assert result.intent_type == IntentType.COACHING_QUERY, \
                f"Failed to classify '{transcript}' as COACHING_QUERY"
    
    def test_classify_session_control(self, intent_classifier, sample_transcripts):
        """Test classification of session control commands."""
        for transcript in sample_transcripts["session_control"]:
            result = intent_classifier.classify(transcript)
            assert result.intent_type == IntentType.SESSION_CONTROL, \
                f"Failed to classify '{transcript}' as SESSION_CONTROL"
    
    def test_classify_player_info(self, intent_classifier, sample_transcripts):
        """Test classification of player info queries."""
        player_info_transcripts = [
            "Who is player A?",
            "Show player stats",
            "Player B rating?"
        ]
        for transcript in player_info_transcripts:
            result = intent_classifier.classify(transcript)
            assert result.intent_type == IntentType.PLAYER_INFO, \
                f"Failed to classify '{transcript}' as PLAYER_INFO"
    
    def test_extract_stroke_type(self, intent_classifier):
        """Test extraction of stroke type from coaching queries."""
        test_cases = [
            ("How can I improve my forehand?", "forehand"),
            ("Tips for backhand technique", "backhand"),
            ("Serve advice please", "serve"),
            ("Footwork coaching", "footwork")
        ]
        
        for transcript, expected_stroke in test_cases:
            result = intent_classifier.classify(transcript)
            assert result.entities.get("stroke_type") == expected_stroke, \
                f"Failed to extract stroke type from '{transcript}'"
    
    def test_confidence_threshold(self, intent_classifier):
        """Test that low confidence results in UNKNOWN intent."""
        high_threshold_classifier = IntentClassifier(threshold=0.9)
        
        result = high_threshold_classifier.classify("Some random text")
        assert result.intent_type == IntentType.UNKNOWN


class TestCoachingServiceIntegration:
    """Tests for CoachingService integration."""
    
    @patch('tournament_platform.services.coaching_service.AIEngine')
    def test_generate_feedback_returns_coaching_feedback(self, mock_ai_engine_class):
        """Test that generate_feedback returns CoachingFeedback."""
        from tournament_platform.services.coaching_service import (
            CoachingService,
            CoachingFeedback,
            CoachingRecommendation
        )
        
        mock_ai_engine = Mock()
        mock_ai_engine.rules_retriever.search_rules.return_value = "Sample coaching context"
        mock_ai_engine._chat_with_fallback.return_value = {
            'message': {
                'content': json.dumps({
                    "feedback_text": "Good forehand technique!",
                    "recommendations": [
                        {"category": "technique", "priority": "high", "suggestion": "Keep practicing"}
                    ]
                })
            }
        }
        mock_ai_engine_class.return_value = mock_ai_engine
        
        service = CoachingService(ai_engine=mock_ai_engine)
        feedback = service.generate_feedback(
            session_id=1,
            transcript="How is my forehand?",
            stroke_type="forehand"
        )
        
        assert isinstance(feedback, CoachingFeedback)
        assert feedback.session_id == 1
        assert "forehand" in feedback.feedback_text.lower() or len(feedback.feedback_text) > 0
        assert isinstance(feedback.recommendations, list)