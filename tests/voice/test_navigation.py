"""
Tests for Voice Navigation Handler (Phase 3).
"""

import pytest

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.navigation import NavigationCommandHandler, ActionResult


class TestNavigationCommandHandler:
    def setup_method(self):
        self.handler = NavigationCommandHandler()

    def test_can_navigate_when_idle(self):
        assert self.handler.can_navigate({}) is True

    def test_can_navigate_blocked_by_pending_confirmation(self):
        assert self.handler.can_navigate({"pending_confirmations": [{}]}) is False

    def test_execute_dashboard(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_DASHBOARD, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "dashboard"

    def test_execute_bracket(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_BRACKET, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "bracket"

    def test_execute_rankings(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_RANKINGS, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "rankings"

    def test_execute_public_board(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_PUBLIC_BOARD, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "public_board"

    def test_execute_current_match(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_CURRENT_MATCH, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "current_match"

    def test_execute_scoring(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_SCORING, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "scoring"

    def test_execute_help(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_HELP, {})
        assert result.action == "navigate"
        assert result.payload["target"] == "help"

    def test_navigation_blocked_when_pending(self):
        result = self.handler.execute(VoiceIntent.NAVIGATE_DASHBOARD, {"pending_confirmations": [{}]})
        assert result.action == "blocked"
        assert "pending confirmation" in result.message.lower()
