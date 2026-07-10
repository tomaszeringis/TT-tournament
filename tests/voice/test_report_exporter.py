"""
Tests for Match Report Exporter (Phase 4).
"""

import pytest

from tournament_platform.app.services.voice.report_exporter import MatchReportExporter


class TestMatchReportExporter:
    def setup_method(self):
        self.exporter = MatchReportExporter()

    def test_export_contains_correct_score(self):
        report = self.exporter.export_match_report(
            match_id=1,
            match_metadata={
                "players": ["Alice", "Bob"],
                "tournament": "Test Tournament",
                "score": "11-9",
                "winner": "Alice",
            },
            include_summary=False,
            include_commentary=False,
        )
        assert "11-9" in report
        assert "Alice" in report
        assert "Bob" in report

    def test_export_excludes_debug_transcripts_by_default(self):
        report = self.exporter.export_match_report(
            match_id=1,
            match_metadata={},
            include_summary=False,
            include_commentary=False,
        )
        assert "raw_transcript" not in report

    def test_export_includes_summary_when_requested(self):
        report = self.exporter.export_match_report(
            match_id=1,
            match_metadata={
                "players": ["Alice", "Bob"],
                "tournament": "Test",
                "score": "11-9",
                "winner": "Alice",
            },
            include_summary=True,
            include_commentary=False,
        )
        assert "Match Report" in report
        assert "Alice" in report
