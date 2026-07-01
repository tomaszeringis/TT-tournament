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
@dataclass
class MockAudioData:
    """Mock audio data for testing."""
    content: bytes
    
    def read(self):
        return self.content
    
    def seek(self, pos):
        pass


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
            "Undo the last point",
            "Reset the match",
            "Start a new game",
            "Stop the match"
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
        for transcript in sample_transcripts["player_info"]:
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
        # Create classifier with high threshold
        high_threshold_classifier = IntentClassifier(threshold=0.9)
        
        # This should return UNKNOWN due to high threshold
        result = high_threshold_classifier.classify("Some random text")
        assert result.intent_type == IntentType.UNKNOWN


class TestVoiceScorekeeperIntegration:
    """Tests for voice scorekeeper integration."""
    
    @patch('tournament_platform.app.pages.voice_scorekeeper.UmpireEngine')
    @patch('tournament_platform.app.pages.voice_scorekeeper.IntentClassifier')
    def test_process_voice_command_returns_tuple(
        self, mock_classifier_class, mock_umpire_class
    ):
        """Test that process_voice_command returns a 3-tuple."""
        # This test verifies the signature change
        from tournament_platform.app.pages.voice_scorekeeper import process_voice_command
        
        # Create mock instances
        mock_umpire = Mock()
        mock_umpire.transcribe_audio_file.return_value = "Player A scores"
        mock_umpire_class.return_value = mock_umpire
        
        mock_classifier = Mock()
        mock_classifier.classify.return_value = IntentResult(
            intent_type=IntentType.SCORE_UPDATE,
            confidence=0.9,
            raw_text="Player A scores"
        )
        mock_classifier_class.return_value = mock_classifier
        
        # Create mock audio bytes
        audio_bytes = b"fake_audio_data"
        
        # Process the command
        result = process_voice_command(audio_bytes)
        
        # Verify it returns a 3-tuple
        assert isinstance(result, tuple), "Should return a tuple"
        assert len(result) == 3, "Should return 3 elements"
        transcript, response, intent_result = result
        
        assert isinstance(transcript, str), "First element should be transcript string"
        assert isinstance(response, str), "Second element should be response string"
        assert isinstance(intent_result, IntentResult), "Third element should be IntentResult"
    
    def test_intent_result_dataclass(self):
        """Test IntentResult dataclass structure."""
        result = IntentResult(
            intent_type=IntentType.SCORE_UPDATE,
            confidence=0.85,
            raw_text="Player A scores",
            entities={"player": "A"}
        )
        
        assert result.intent_type == IntentType.SCORE_UPDATE
        assert result.confidence == 0.85
        assert result.raw_text == "Player A scores"
        assert result.entities == {"player": "A"}


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
        
        # Create mock AI engine
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
        
        # Create service and generate feedback
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