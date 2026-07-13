"""
Tests for CommentaryRewriter safety and fallback behavior.
"""

import pytest
from unittest.mock import Mock, patch

from tournament_platform.services.commentary_service import CommentaryRewriter


class TestCommentaryRewriterDisabled:
    def test_returns_base_text_when_disabled(self):
        rewriter = CommentaryRewriter(enabled=False)
        text, used = rewriter.rewrite(
            base_text="Point for Alice. 1 to 0.",
            facts={"player_a": "Alice", "player_b": "Bob", "score_a": 1, "score_b": 0},
            style="neutral",
            language="en",
            event_type="point_scored",
        )
        assert text == "Point for Alice. 1 to 0."
        assert used is False


class TestCommentaryRewriterCache:
    def test_cache_hit_returns_cached_text(self):
        rewriter = CommentaryRewriter(enabled=True, model="llama3:latest", timeout=2.0)
        with patch.object(rewriter, "_cache_key", return_value="testkey"):
            rewriter._cache["testkey"] = "cached text"
            with patch.object(rewriter, "_call_ollama", side_effect=AssertionError("should not call ollama")):
                text, used = rewriter.rewrite(
                    base_text="base",
                    facts={},
                    style="neutral",
                    language="en",
                    event_type="point_scored",
                )
        assert text == "cached text"
        assert used is True


class TestCommentaryRewriterValidation:
    def test_rejects_empty_output(self):
        rewriter = CommentaryRewriter(enabled=True)
        with patch.object(rewriter, "_call_ollama", return_value=""):
            text, used = rewriter.rewrite(
                base_text="base",
                facts={"player_a": "Alice"},
                style="neutral",
                language="en",
                event_type="point_scored",
            )
        assert text == "base"
        assert used is False

    def test_rejects_too_long_output(self):
        rewriter = CommentaryRewriter(enabled=True)
        with patch.object(rewriter, "_call_ollama", return_value="x" * 201):
            text, used = rewriter.rewrite(
                base_text="base",
                facts={"player_a": "Alice"},
                style="neutral",
                language="en",
                event_type="point_scored",
            )
        assert text == "base"
        assert used is False

    def test_rejects_missing_player_a(self):
        rewriter = CommentaryRewriter(enabled=True)
        with patch.object(rewriter, "_call_ollama", return_value="Point for Bob. 1 to 0."):
            text, used = rewriter.rewrite(
                base_text="base",
                facts={"player_a": "Alice", "player_b": "Bob"},
                style="neutral",
                language="en",
                event_type="point_scored",
            )
        assert text == "base"
        assert used is False

    def test_rejects_missing_player_b(self):
        rewriter = CommentaryRewriter(enabled=True)
        with patch.object(rewriter, "_call_ollama", return_value="Point for Alice. 1 to 0."):
            text, used = rewriter.rewrite(
                base_text="base",
                facts={"player_a": "Alice", "player_b": "Bob"},
                style="neutral",
                language="en",
                event_type="point_scored",
            )
        assert text == "base"
        assert used is False

    def test_falls_back_on_timeout(self):
        rewriter = CommentaryRewriter(enabled=True, timeout=0.01)
        with patch.object(rewriter, "_call_ollama", side_effect=TimeoutError("timeout")):
            text, used = rewriter.rewrite(
                base_text="base",
                facts={},
                style="neutral",
                language="en",
                event_type="point_scored",
            )
        assert text == "base"
        assert used is False


class TestCommentaryRewriterPrompt:
    def test_prompt_contains_facts(self):
        rewriter = CommentaryRewriter(enabled=True)
        prompt = rewriter._build_prompt("base text", {"player_a": "Alice", "player_b": "Bob", "score_a": 1, "score_b": 0})
        assert "Alice" in prompt
        assert "Bob" in prompt
        assert "1-0" in prompt
        assert "base text" in prompt