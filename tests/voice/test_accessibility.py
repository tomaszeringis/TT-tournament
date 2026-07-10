"""
Tests for Voice Accessibility Handler (Phase 3).
"""

import pytest

from tournament_platform.app.services.voice.commands import VoiceIntent
from tournament_platform.app.services.voice.accessibility import AccessibilityCommandHandler, ActionResult


class TestAccessibilityCommandHandler:
    def setup_method(self):
        self.handler = AccessibilityCommandHandler()

    def test_mute_toggles_commentary_muted(self):
        result = self.handler.execute(VoiceIntent.ACCESS_MUTE, {}, {})
        assert result.action == "access_mute"
        assert result.payload["muted"] is True

    def test_unmute_toggles_commentary_muted(self):
        result = self.handler.execute(VoiceIntent.ACCESS_UNMUTE, {}, {})
        assert result.action == "access_mute"
        assert result.payload["muted"] is False

    def test_louder_increases_volume(self):
        result = self.handler.execute(VoiceIntent.ACCESS_LOUDER, {}, {})
        assert result.action == "access_volume_adjust"
        assert result.payload["direction"] == "up"

    def test_quieter_decreases_volume(self):
        result = self.handler.execute(VoiceIntent.ACCESS_QUIETER, {}, {})
        assert result.action == "access_volume_adjust"
        assert result.payload["direction"] == "down"

    def test_slower_adjusts_rate(self):
        result = self.handler.execute(VoiceIntent.ACCESS_SLOWER, {}, {})
        assert result.action == "access_rate_adjust"
        assert result.payload["direction"] == "down"

    def test_faster_adjusts_rate(self):
        result = self.handler.execute(VoiceIntent.ACCESS_FASTER, {}, {})
        assert result.action == "access_rate_adjust"
        assert result.payload["direction"] == "up"

    def test_large_text_sets_flag(self):
        result = self.handler.execute(VoiceIntent.ACCESS_LARGE_TEXT, {}, {})
        assert result.action == "access_large_text"
        assert result.payload["enabled"] is True

    def test_high_contrast_sets_flag(self):
        result = self.handler.execute(VoiceIntent.ACCESS_HIGH_CONTRAST, {}, {})
        assert result.action == "access_high_contrast"
        assert result.payload["enabled"] is True

    def test_repeat_command(self):
        result = self.handler.execute(VoiceIntent.ACCESS_REPEAT, {}, {})
        assert result.action == "access_repeat"

    def test_announce_score_command(self):
        result = self.handler.execute(VoiceIntent.ACCESS_ANNOUNCE_SCORE, {}, {})
        assert result.action == "access_announce_score"

    def test_accessibility_help(self):
        result = self.handler.execute(VoiceIntent.ACCESS_HELP, {}, {})
        assert result.action == "access_help"
        assert "accessibility" in result.message.lower()

    def test_accessibility_commands_do_not_mutate_score(self):
        intents = [
            VoiceIntent.ACCESS_REPEAT,
            VoiceIntent.ACCESS_ANNOUNCE_SCORE,
            VoiceIntent.ACCESS_LOUDER,
            VoiceIntent.ACCESS_QUIETER,
            VoiceIntent.ACCESS_MUTE,
            VoiceIntent.ACCESS_UNMUTE,
            VoiceIntent.ACCESS_SLOWER,
            VoiceIntent.ACCESS_FASTER,
            VoiceIntent.ACCESS_LARGE_TEXT,
            VoiceIntent.ACCESS_HIGH_CONTRAST,
            VoiceIntent.ACCESS_HELP,
        ]
        for intent in intents:
            result = self.handler.execute(intent, {}, {})
            assert result.risk == "low"
            assert result.requires_confirmation is False
