"""
Tests to verify voice_scorekeeper imports and module structure.
Ensures all required modules can be imported without errors.
"""

import pytest
import importlib


class TestVoiceScorekeeperImports:
    """Test that all voice scorekeeper modules can be imported."""

    def test_import_voice_scorekeeper_page(self):
        """Test importing the voice scorekeeper page module."""
        try:
            from tournament_platform.app.pages import voice_scorekeeper
            assert voice_scorekeeper is not None
        except ImportError as e:
            pytest.fail(f"Failed to import voice_scorekeeper page: {e}")

    def test_import_commentary_service(self):
        """Test importing the commentary service module."""
        try:
            from tournament_platform.services import commentary_service
            assert commentary_service is not None
        except ImportError as e:
            pytest.fail(f"Failed to import commentary_service: {e}")

    def test_import_spoken_commentary_component(self):
        """Test importing the spoken commentary component module."""
        try:
            from tournament_platform.app.components import spoken_commentary
            assert spoken_commentary is not None
        except ImportError as e:
            pytest.fail(f"Failed to import spoken_commentary component: {e}")

    def test_import_intent_classifier(self):
        """Test importing the intent classifier module."""
        try:
            from tournament_platform.multimodal_ai import intent_classifier
            assert intent_classifier is not None
        except ImportError as e:
            pytest.fail(f"Failed to import intent_classifier: {e}")

    def test_import_voice_event_schema(self):
        """Test importing the voice event schema module."""
        try:
            from tournament_platform.services import voice_event_schema
            assert voice_event_schema is not None
        except ImportError as e:
            pytest.fail(f"Failed to import voice_event_schema: {e}")

    def test_import_voice_command_dataset(self):
        """Test importing the voice command dataset module."""
        try:
            from tournament_platform.services import voice_command_dataset
            assert voice_command_dataset is not None
        except ImportError as e:
            pytest.fail(f"Failed to import voice_command_dataset: {e}")

    def test_import_match_manager(self):
        """Test importing the match manager module."""
        try:
            from tournament_platform.services import match_manager
            assert match_manager is not None
        except ImportError as e:
            pytest.fail(f"Failed to import match_manager: {e}")


class TestCommentaryServiceStructure:
    """Test the structure of the commentary service."""

    def test_commentary_service_has_build_method(self):
        """Test that CommentaryService has a build_score_commentary method."""
        from tournament_platform.services.commentary_service import CommentaryService
        service = CommentaryService()
        assert hasattr(service, 'build_score_commentary')

    def test_commentary_service_has_templates(self):
        """Test that CommentaryService has template methods."""
        from tournament_platform.services.commentary_service import CommentaryService
        service = CommentaryService()
        # Check for template-related attributes
        assert hasattr(service, 'TEMPLATES')

    def test_commentary_service_can_generate_from_state(self):
        """Test that CommentaryService can generate from SpokenScoreState."""
        from tournament_platform.services.commentary_service import (
            CommentaryService,
            SpokenScoreState,
            CommentarySettings,
        )

        service = CommentaryService()
        state = SpokenScoreState(
            score_a=6,
            score_b=3,
            sets_a=0,
            sets_b=0,
            current_set=1,
            player_a="Alice",
            player_b="Bob",
            player_a_id=None,
            player_b_id=None,
        )

        # Should be able to build commentary
        result = service.build_score_commentary(
            event_type="point_a",
            state=state,
            settings=CommentarySettings(),
            event_id="test-id",
        )
        assert result is not None
        assert hasattr(result, 'text')


class TestSpokenCommentaryComponent:
    """Test the spoken commentary component structure."""

    def test_spoken_commentary_has_speak_method(self):
        """Test that spoken_commentary has speak functionality."""
        from tournament_platform.app.components.spoken_commentary import speak_commentary
        assert callable(speak_commentary)

    def test_spoken_commentary_has_get_voices_method(self):
        """Test that spoken_commentary has get_available_voices functionality."""
        from tournament_platform.app.components.spoken_commentary import get_available_voices
        assert callable(get_available_voices)


class TestIntentClassifierStructure:
    """Test the structure of the intent classifier."""

    def test_intent_classifier_has_classify_method(self):
        """Test that IntentClassifier has classify method."""
        from tournament_platform.multimodal_ai.intent_classifier import IntentClassifier
        classifier = IntentClassifier()
        assert hasattr(classifier, 'classify')
        assert callable(classifier.classify)

    def test_intent_classifier_has_intent_types(self):
        """Test that IntentClassifier has access to IntentType enum."""
        from tournament_platform.multimodal_ai.intent_classifier import IntentType
        assert IntentType.SCORE_UPDATE is not None
        assert IntentType.SCORE_QUERY is not None
        assert IntentType.UNDO is not None
        assert IntentType.RESET is not None
        assert IntentType.MATCH_RESULT is not None
        assert IntentType.SERVER_CHANGE is not None


class TestMatchManagerEventMethods:
    """Test that match_manager has event generation methods."""

    def test_match_manager_has_event_methods(self):
        """Test that MatchManager has event generation methods."""
        from tournament_platform.services.match_manager import MatchManager
        manager = MatchManager()

        # Check for event generation methods
        assert hasattr(manager, 'generate_point_event')
        assert hasattr(manager, 'generate_undo_event')
        assert hasattr(manager, 'generate_reset_event')
        assert hasattr(manager, 'generate_score_query_event')
        assert hasattr(manager, 'generate_match_result_event')
        assert hasattr(manager, 'parse_match_result')