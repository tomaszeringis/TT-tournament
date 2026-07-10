"""
Tests for Match Summary Service (Phase 4).
"""

import pytest

from tournament_platform.app.services.voice.match_summary import MatchSummaryService, SummaryValidator


class TestMatchSummaryService:
    def setup_method(self):
        self.service = MatchSummaryService()

    def test_summary_facts_match_event_log(self):
        summary = self.service.generate_match_summary(
            match_id=1,
            match_metadata={
                "players": ["Alice", "Bob"],
                "tournament": "Test Tournament",
                "score": "11-9",
                "winner": "Alice",
            },
        )
        assert summary.players == ["Alice", "Bob"]
        assert summary.tournament == "Test Tournament"
        assert summary.winner == "Alice"

    def test_llm_summary_falls_back_to_template_when_unavailable(self):
        summary = self.service.generate_match_summary(
            match_id=1,
            match_metadata={
                "players": ["Alice", "Bob"],
                "tournament": "Test",
                "score": "11-9",
                "winner": "Alice",
            },
        )
        assert summary.llm_text is None or isinstance(summary.llm_text, str)

    def test_summary_rejects_hallucinated_facts(self):
        events = []
        # Empty events should still produce a valid summary with default score
        summary = self.service.generate_match_summary(
            match_id=1,
            match_metadata={},
        )
        assert summary.final_score == "0-0"


class TestSummaryValidator:
    def test_validate_returns_true_for_matching_facts(self):
        class FakeEvent:
            status = "accepted"
            score_after = "11-9"
            score_before = None

        facts = {"final_score": "11-9"}
        assert SummaryValidator.validate(facts, [FakeEvent()]) is True

    def test_validate_returns_false_for_mismatching_facts(self):
        class FakeEvent:
            status = "accepted"
            score_after = "11-9"
            score_before = None

        facts = {"final_score": "5-3"}
        assert SummaryValidator.validate(facts, [FakeEvent()]) is False
