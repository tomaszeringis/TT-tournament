"""
Tests for AI insight card safety (Phase 4):
- disabled by default (flag off -> nothing rendered)
- offline / error -> gracefully returns None (never blocks, never overrides)
- labeled as not the official result
"""

import pytest

from tournament_platform.config import settings
from tournament_platform.app.components import ai_insight_card


class TestAiInsightSafety:
    def test_flag_off_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_AI_MATCH_INSIGHTS", False)
        assert ai_insight_card.get_match_insight({"id": 1, "score": "3-1"}) is None

    def test_offline_returns_none_gracefully(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_AI_MATCH_INSIGHTS", True)

        def boom(*a, **k):
            raise ConnectionError("ollama down")
        monkeypatch.setattr(ai_insight_card, "_cached_insight", boom)
        result = ai_insight_card.get_match_insight({"id": 1, "score": "3-1"})
        assert result is None

    def test_engine_failure_does_not_override_winner(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_AI_MATCH_INSIGHTS", True)
        monkeypatch.setattr(
            ai_insight_card, "_cached_insight",
            lambda *a, **k: {"summary": "x", "key_play": "y", "predicted_winner": "Bob"},
        )
        official = {"id": 7, "player1": "Alice", "player2": "Bob", "score": "3-1", "winner": "Alice"}
        insight = ai_insight_card.get_match_insight(dict(official))
        assert official["winner"] == "Alice"
        assert insight["predicted_winner"] == "Bob"
