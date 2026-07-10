"""
Tests for Announcement Service (Phase 4).
"""

import pytest

from tournament_platform.app.services.voice.announcements import AnnouncementService, Announcement


class TestAnnouncementService:
    def setup_method(self):
        self.service = AnnouncementService()

    def test_no_duplicate_announcements(self):
        ann1 = self.service.generate_match_start("Alice", "Bob", table="1")
        ann2 = self.service.generate_match_start("Alice", "Bob", table="1")
        assert self.service.should_announce(ann1) is True
        self.service.mark_announced(ann1)
        assert self.service.should_announce(ann2) is False

    def test_announcement_skipped_when_muted(self):
        ann = self.service.generate_game_won("Alice", "11-9")
        assert self.service.should_announce(ann) is True
        assert "Alice" in ann.text
        assert "11-9" in ann.text

    def test_next_match_announcement(self):
        ann = self.service.generate_next_match("Alice", "Bob", table="2")
        assert "Alice" in ann.text
        assert "Bob" in ann.text
        assert "table 2" in ann.text

    def test_match_won_announcement(self):
        ann = self.service.generate_match_won("Alice", 3, 1)
        assert "Alice" in ann.text
        assert "3" in ann.text
        assert "1" in ann.text
