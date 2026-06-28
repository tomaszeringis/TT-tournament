"""
Tests for the announcement service.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from tournament_platform.models import SessionLocal, Announcement, init_db
from tournament_platform.services.announcement_service import (
    is_placeholder_webhook,
    create_announcement,
    get_announcements,
    generate_match_call_message,
    generate_semifinal_start_message,
    generate_final_start_message,
)


class TestIsPlaceholderWebhook:
    """Tests for is_placeholder_webhook function."""

    def test_empty_url_is_placeholder(self):
        assert is_placeholder_webhook("") is True
        assert is_placeholder_webhook(None) is True

    def test_example_urls_are_placeholders(self):
        assert is_placeholder_webhook("https://example.com/webhook") is True
        assert is_placeholder_webhook("https://your-webhook-url-here") is True
        assert is_placeholder_webhook("https://teams.microsoft.com/placeholder") is True

    def test_real_url_is_not_placeholder(self):
        assert is_placeholder_webhook("https://teams.microsoft.com/webhook/abc123") is False
        assert is_placeholder_webhook("https://hooks.slack.com/services/xxx") is False

    def test_case_insensitive(self):
        assert is_placeholder_webhook("HTTPS://EXAMPLE.COM/WEBHOOK") is True


class TestCreateAnnouncement:
    """Tests for create_announcement function."""

    def test_create_announcement_basic(self):
        """Test creating a basic announcement."""
        init_db()
        db = SessionLocal()
        try:
            announcement = create_announcement(
                db,
                message="Test announcement",
                match_id=None,
                tournament_id=None,
                channel="local",
            )
            assert announcement.id is not None
            assert announcement.message == "Test announcement"
            assert announcement.channel == "local"
            assert announcement.sent_status == "pending"
        finally:
            db.close()

    def test_create_announcement_with_match(self):
        """Test creating an announcement with match association."""
        init_db()
        db = SessionLocal()
        try:
            announcement = create_announcement(
                db,
                message="Match called: Alice vs Bob",
                match_id=1,
                tournament_id=1,
                channel="local",
            )
            assert announcement.match_id == 1
            assert announcement.tournament_id == 1
        finally:
            db.close()


class TestGetAnnouncements:
    """Tests for get_announcements function."""

    def test_get_announcements_empty(self):
        """Test getting announcements when none exist."""
        init_db()
        db = SessionLocal()
        try:
            announcements = get_announcements(db, limit=10)
            assert isinstance(announcements, list)
        finally:
            db.close()

    def test_get_announcements_with_data(self):
        """Test getting announcements with data."""
        init_db()
        db = SessionLocal()
        try:
            # Create a test announcement
            ann = Announcement(
                message="Test",
                channel="local",
                sent_status="pending",
            )
            db.add(ann)
            db.commit()

            announcements = get_announcements(db, limit=10)
            assert len(announcements) >= 1
            assert any(a["message"] == "Test" for a in announcements)
        finally:
            db.close()

    def test_get_announcements_filter_by_channel(self):
        """Test filtering announcements by channel."""
        init_db()
        db = SessionLocal()
        try:
            # Create announcements with different channels
            ann1 = Announcement(message="Test1", channel="local", sent_status="pending")
            ann2 = Announcement(message="Test2", channel="webhook", sent_status="pending")
            db.add(ann1)
            db.add(ann2)
            db.commit()

            local_anns = get_announcements(db, limit=10, channel="local")
            assert all(a["channel"] == "local" for a in local_anns)
        finally:
            db.close()


class TestGenerateMessages:
    """Tests for message generation functions."""

    def test_generate_match_call_message(self):
        """Test match call message generation."""
        from tournament_platform.models import Match
        match = MagicMock()
        match.player1 = "Alice"
        match.player2 = "Bob"

        msg = generate_match_call_message(match, "Table 1")
        assert "Alice" in msg
        assert "Bob" in msg
        assert "Table 1" in msg

    def test_generate_match_call_message_no_table(self):
        """Test match call message without table."""
        from tournament_platform.models import Match
        match = MagicMock()
        match.player1 = "Alice"
        match.player2 = "Bob"

        msg = generate_match_call_message(match, None)
        assert "Alice" in msg
        assert "Bob" in msg
        assert "Table" not in msg

    def test_generate_semifinal_start_message(self):
        """Test semifinal start message generation."""
        from tournament_platform.models import Tournament
        tournament = MagicMock()
        tournament.name = "Test Tournament"

        msg = generate_semifinal_start_message(tournament)
        assert "Semifinals" in msg
        assert "Test Tournament" in msg

    def test_generate_final_start_message(self):
        """Test final start message generation."""
        from tournament_platform.models import Tournament
        tournament = MagicMock()
        tournament.name = "Test Tournament"

        msg = generate_final_start_message(tournament)
        assert "Final" in msg
        assert "Test Tournament" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])