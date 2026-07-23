"""
Tests for TeamsPublisher service.
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import requests

from tournament_platform.app.services.teams_publisher import TeamsPublisher, TeamsEvent
from tournament_platform.app.services.teams_publisher_schemas import TeamsPostResult
from tournament_platform.config import settings

# Module-level caches that survive across tests unless cleared
def _clear_caches():
    import tournament_platform.app.services.teams_publisher as tp
    tp._IDEMPOTENCY_CACHE.clear()
    tp._COOLDOWN_CACHE.clear()


class TestTeamsPublisher:
    def setup_method(self):
        _clear_caches()
        self.publisher = TeamsPublisher()

    def test_not_configured_when_empty_url(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "")
        assert self.publisher.is_configured() is False

    def test_not_configured_when_placeholder_url(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://example.com/webhook")
        assert self.publisher.is_configured() is False

    def test_configured_for_valid_url(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc/def")
        assert self.publisher.is_configured() is True

    def test_mask_webhook_url_short(self):
        assert self.publisher.mask_webhook_url("abc") == "***"

    def test_mask_webhook_url_long(self):
        masked = self.publisher.mask_webhook_url("https://outlook.office.com/webhook/abc/def/ghi")
        assert "***" in masked
        assert "outlook.office.com/webhook/abc/def" not in masked

    def test_mask_webhook_url_not_configured(self):
        masked = self.publisher.mask_webhook_url("")
        assert masked == "Not configured"

    def test_post_plain_text_skips_when_not_configured(self):
        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_plain_text(event, actor="operator")
        assert result.success is False
        assert result.status == "skipped"

    def test_post_plain_text_requires_actor(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_plain_text(event, actor="")
        assert result.success is False
        assert result.status == "error"

    @patch("tournament_platform.app.services.teams_publisher.requests.post")
    def test_post_plain_text_success(self, mock_post, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"

        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_plain_text(event, actor="operator")
        assert result.success is True
        assert result.status == "success"
        assert result.posted_at is not None

    @patch("tournament_platform.app.services.teams_publisher.requests.post")
    def test_post_plain_text_failure_non_200(self, mock_post, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"

        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_plain_text(event, actor="operator")
        assert result.success is False
        assert result.status == "failed"
        assert "500" in result.message

    @patch("tournament_platform.app.services.teams_publisher.requests.post", side_effect=requests.exceptions.Timeout)
    def test_post_plain_text_timeout(self, mock_post, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")

        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_plain_text(event, actor="operator")
        assert result.success is False
        assert result.status == "failed"
        assert "timed out" in result.message.lower() or "timeout" in result.message.lower()

    def test_post_workflow_payload_skips_when_not_configured(self):
        event = TeamsEvent(
            event_type="daily_digest",
            tournament_id=1,
            match_id=None,
            title="Digest",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_workflow_payload(event, payload={}, actor="operator")
        assert result.success is False
        assert result.status == "skipped"

    @patch("tournament_platform.app.services.teams_publisher.requests.post")
    def test_post_adaptive_card_success(self, mock_post, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"

        event = TeamsEvent(
            event_type="custom",
            tournament_id=1,
            match_id=None,
            title="Custom",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        result = self.publisher.post_adaptive_card(event, card={"type": "message", "text": "hello"}, actor="operator")
        assert result.success is True
        assert result.status == "success"

    def test_preview_message_contains_title_and_body(self):
        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Title",
            body="Body text",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        preview = self.publisher.preview_message(event)
        assert "Title" in preview.text
        assert "Body text" in preview.text
        assert preview.event_type == "match_completed"

    def test_cooldown_enforced(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        monkeypatch.setattr(settings, "TEAMS_POST_COOLDOWN_SECONDS", 60)

        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )

        with patch("tournament_platform.app.services.teams_publisher.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = "OK"
            event1 = TeamsEvent(
                event_type="match_completed",
                tournament_id=1,
                match_id=10,
                title="Test",
                body="body",
                facts={},
                created_at=datetime.now(timezone.utc),
            )
            event2 = TeamsEvent(
                event_type="match_completed",
                tournament_id=1,
                match_id=11,
                title="Test",
                body="body",
                facts={},
                created_at=datetime.now(timezone.utc),
            )
            r1 = self.publisher.post_plain_text(event1, actor="operator")
            assert r1.status == "success"

            r2 = self.publisher.post_plain_text(event2, actor="operator")
            assert r2.status == "cooldown"

    def test_idempotency_skips_duplicate(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")

        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )

        with patch("tournament_platform.app.services.teams_publisher.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = "OK"
            r1 = self.publisher.post_plain_text(event, actor="operator")
            assert r1.status == "success"

            r2 = self.publisher.post_plain_text(event, actor="operator")
            assert r2.status == "idempotent_skip"
            mock_post.assert_called_once()

    def test_masked_url_never_in_preview(self, monkeypatch):
        monkeypatch.setattr(settings, "TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        event = TeamsEvent(
            event_type="match_completed",
            tournament_id=1,
            match_id=10,
            title="Test",
            body="body",
            facts={},
            created_at=datetime.now(timezone.utc),
        )
        preview = self.publisher.preview_message(event)
        assert settings.TEAMS_WEBHOOK_URL not in preview.text
