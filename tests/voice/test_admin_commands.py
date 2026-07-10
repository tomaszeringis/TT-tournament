"""
Tests for Voice Admin Command Handler (Phase 3).
"""

import pytest

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.admin import AdminCommandHandler, ActionResult


class TestAdminCommandHandler:
    def setup_method(self):
        self.handler = AdminCommandHandler()

    def test_admin_call_next_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_CALL_NEXT, {})
        assert result.requires_confirmation is True

    def test_admin_drop_player_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_DROP_PLAYER, {})
        assert result.requires_confirmation is True

    def test_admin_publish_result_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_PUBLISH_RESULT, {})
        assert result.requires_confirmation is True

    def test_admin_mark_no_show_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_MARK_NO_SHOW, {})
        assert result.requires_confirmation is True

    def test_admin_table_ready_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_TABLE_READY, {})
        assert result.requires_confirmation is True

    def test_admin_assign_table_requires_confirmation(self):
        result = self.handler.execute(VoiceIntent.ADMIN_ASSIGN_TABLE, {"table": "1"})
        assert result.requires_confirmation is True
        assert result.payload["table"] == "1"

    def test_destructive_commands_have_warning(self):
        for intent in [VoiceIntent.ADMIN_DROP_PLAYER, VoiceIntent.ADMIN_MARK_NO_SHOW, VoiceIntent.ADMIN_PUBLISH_RESULT]:
            result = self.handler.execute(intent, {})
            assert result.risk == "high"
            assert result.message != ""

    def test_non_destructive_admin_commands_medium_risk(self):
        for intent in [VoiceIntent.ADMIN_CALL_NEXT, VoiceIntent.ADMIN_TABLE_READY]:
            result = self.handler.execute(intent, {})
            assert result.risk in ("medium", "high")

    def test_admin_start_next_round(self):
        result = self.handler.execute(VoiceIntent.ADMIN_START_NEXT_ROUND, {})
        assert result.action == "admin_start_next_round"

    def test_unsupported_admin_intent_returns_error(self):
        result = self.handler.execute(VoiceIntent.UNKNOWN, {})
        assert result.action == "error"
