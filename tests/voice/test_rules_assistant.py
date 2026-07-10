"""
Tests for Voice Rules Assistant Handler (Phase 3).
"""

import pytest

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.rules_assistant import RulesAssistantHandler, ActionResult


class TestRulesAssistantHandler:
    def setup_method(self):
        self.handler = RulesAssistantHandler()

    def test_rules_query_does_not_mutate_score(self):
        result = self.handler.execute(VoiceIntent.RULES_QUERY, {"question": "What is deuce?"})
        assert result.action == "rules_answer"
        assert result.risk == "low"

    def test_empty_question_returns_error(self):
        result = self.handler.execute(VoiceIntent.RULES_QUERY, {})
        assert result.action == "error"
