"""
Tests for Quick Voice Scoring Engine (PingScore-style rapid scoring).
"""

import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tournament_platform.app.services.voice.quick_voice import QuickVoiceScoringEngine


class TestQuickVoiceCooldown:
    def test_same_player_within_cooldown_ignored(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=1200.0)
        result1 = engine.process("blue", 0, 0)
        assert result1["action"] == "accept"
        result2 = engine.process("blue", 1, 0)
        assert result2["action"] == "ignore"
        assert result2["reason"] == "duplicate"

    def test_same_player_after_cooldown_accepted(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=1200.0)
        engine.process("blue", 0, 0)
        time.sleep(1.3)
        result = engine.process("blue", 1, 0)
        assert result["action"] == "accept"

    def test_different_player_accepted(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=1200.0, global_min_interval_ms=0.0)
        result1 = engine.process("blue", 0, 0)
        assert result1["action"] == "accept"
        result2 = engine.process("red", 1, 0)
        assert result2["action"] == "accept"

    def test_lithuanian_aliases(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=0.0)
        result = engine.process("raudonas", 0, 0)
        assert result["action"] == "accept"
        assert result["player"] == "B"

    def test_unknown_word_rejected(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=0.0)
        result = engine.process("hello", 0, 0)
        assert result["action"] == "reject"

    def test_global_min_interval(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=0.0, global_min_interval_ms=500.0)
        engine.process("blue", 0, 0)
        result = engine.process("red", 1, 0)
        assert result["action"] == "ignore"
        assert result["reason"] == "too_soon"

    def test_empty_transcript_rejected(self):
        engine = QuickVoiceScoringEngine()
        result = engine.process("", 0, 0)
        assert result["action"] == "reject"
        assert result["reason"] == "empty_transcript"

    def test_multiple_lithuanian_aliases_a(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=0.0, global_min_interval_ms=0.0)
        for word in ["melynas", "mėlynas", "zalia", "žalia", "zalias", "žalias"]:
            result = engine.process(word, 0, 0)
            assert result["action"] == "accept"
            assert result["player"] == "A"

    def test_multiple_lithuanian_aliases_b(self):
        engine = QuickVoiceScoringEngine(cooldown_ms=0.0, global_min_interval_ms=0.0)
        for word in ["raudonas", "raudona", "oranzinis", "oranžinis"]:
            result = engine.process(word, 0, 0)
            assert result["action"] == "accept"
            assert result["player"] == "B"
