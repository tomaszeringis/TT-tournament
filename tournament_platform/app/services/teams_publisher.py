"""
Teams webhook publisher service.

Provides a single source of truth for posting notifications to Microsoft Teams
via webhook URL. Supports plain-text, Workflow payload, and adaptive card
publishing, with preview, masking, cooldown, idempotency, and failure handling.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import requests

from tournament_platform.config import settings
from tournament_platform.services.announcement_service import (
    create_announcement,
    is_placeholder_webhook,
)
from tournament_platform.services.audit_service import log_audit
from tournament_platform.app.services.teams_publisher_schemas import (
    TeamsEvent,
    TeamsPostResult,
    TeamsPreview,
    TeamsPostRecord,
)
from tournament_platform.models import SessionLocal, Announcement

logger = logging.getLogger(__name__)

# In-memory caches for cooldown and idempotency (survive Streamlit reruns).
_COOLDOWN_CACHE: Dict[str, datetime] = {}
_IDEMPOTENCY_CACHE: Dict[str, TeamsPostResult] = {}
_IDEMPOTENCY_TTL_SECONDS = 60


class TeamsPublisher:
    """Publish tournament events to Microsoft Teams via webhook."""

    def is_configured(self) -> bool:
        """Return True when a non-placeholder webhook URL is configured."""
        url = (settings.TEAMS_WEBHOOK_URL or "").strip()
        if not url:
            return False
        return not is_placeholder_webhook(url)

    def mask_webhook_url(self, url: Optional[str] = None) -> str:
        """Return a safe representation of the webhook URL for UI/logs."""
        raw = (url or settings.TEAMS_WEBHOOK_URL or "").strip()
        if not raw or is_placeholder_webhook(raw):
            return "Not configured"
        if len(raw) <= 12:
            return "***"
        return f"{raw[:12]}...***"

    def preview_message(self, event: TeamsEvent) -> TeamsPreview:
        """Build a preview of the message that would be posted."""
        text = f"**{event.title}**\n\n{event.body}"
        event_key = self._build_event_key(event)
        return TeamsPreview(
            event_key=event_key,
            text=text,
            event_type=event.event_type,
            posted_at=None,
        )

    def post_plain_text(self, event: TeamsEvent, actor: str) -> TeamsPostResult:
        """Post a plain-text message to Teams."""
        if not actor:
            return TeamsPostResult(
                success=False,
                status="error",
                message="Actor is required to post to Teams.",
                event_key="",
            )
        if not self.is_configured():
            return TeamsPostResult(
                success=False,
                status="skipped",
                message="Teams webhook is not configured.",
                event_key="",
            )

        event_key = self._build_event_key(event)
        cached = self._check_idempotency(event_key)
        if cached:
            return TeamsPostResult(
                success=True,
                status="idempotent_skip",
                message="Duplicate post skipped (idempotency).",
                event_key=event_key,
                posted_at=cached.posted_at,
            )

        if not self._enforce_cooldown(event.event_type, event.tournament_id):
            return TeamsPostResult(
                success=False,
                status="cooldown",
                message=f"Cooldown active (>{settings.TEAMS_POST_COOLDOWN_SECONDS}s since last identical event).",
                event_key=event_key,
            )

        text = f"**{event.title}**\n\n{event.body}"
        payload = {"text": text}

        return self._send(
            event=event,
            actor=actor,
            event_key=event_key,
            payload=payload,
            channel_note="plain_text",
        )

    def post_workflow_payload(self, event: TeamsEvent, payload: Dict[str, Any], actor: str) -> TeamsPostResult:
        """Post a raw payload to a Teams Workflow / Power Automate webhook."""
        if not actor:
            return TeamsPostResult(
                success=False,
                status="error",
                message="Actor is required to post to Teams.",
                event_key="",
            )
        if not self.is_configured():
            return TeamsPostResult(
                success=False,
                status="skipped",
                message="Teams webhook is not configured.",
                event_key="",
            )

        event_key = self._build_event_key(event)
        cached = self._check_idempotency(event_key)
        if cached:
            return TeamsPostResult(
                success=True,
                status="idempotent_skip",
                message="Duplicate post skipped (idempotency).",
                event_key=event_key,
                posted_at=cached.posted_at,
            )

        if not self._enforce_cooldown(event.event_type, event.tournament_id):
            return TeamsPostResult(
                success=False,
                status="cooldown",
                message=f"Cooldown active (>{settings.TEAMS_POST_COOLDOWN_SECONDS}s since last identical event).",
                event_key=event_key,
            )

        return self._send(
            event=event,
            actor=actor,
            event_key=event_key,
            payload=payload,
            channel_note="workflow",
        )

    def post_adaptive_card(self, event: TeamsEvent, card: Dict[str, Any], actor: str) -> TeamsPostResult:
        """Post an Adaptive Card to Teams (future path, not used by default)."""
        if not actor:
            return TeamsPostResult(
                success=False,
                status="error",
                message="Actor is required to post to Teams.",
                event_key="",
            )
        if not self.is_configured():
            return TeamsPostResult(
                success=False,
                status="skipped",
                message="Teams webhook is not configured.",
                event_key="",
            )

        event_key = self._build_event_key(event)
        cached = self._check_idempotency(event_key)
        if cached:
            return TeamsPostResult(
                success=True,
                status="idempotent_skip",
                message="Duplicate post skipped (idempotency).",
                event_key=event_key,
                posted_at=cached.posted_at,
            )

        if not self._enforce_cooldown(event.event_type, event.tournament_id):
            return TeamsPostResult(
                success=False,
                status="cooldown",
                message=f"Cooldown active (>{settings.TEAMS_POST_COOLDOWN_SECONDS}s since last identical event).",
                event_key=event_key,
            )

        return self._send(
            event=event,
            actor=actor,
            event_key=event_key,
            payload=card,
            channel_note="adaptive_card",
        )

    def get_post_history(self, limit: int = 50) -> List[TeamsPostRecord]:
        """Return recent Teams post history from the announcements table."""
        db = SessionLocal()
        try:
            rows = (
                db.query(Announcement)
                .filter(Announcement.channel == "teams")
                .order_by(Announcement.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                TeamsPostRecord(
                    id=r.id,
                    event_type=None,
                    status=r.sent_status or "unknown",
                    error=r.error,
                    posted_at=r.created_at or datetime.now(timezone.utc),
                    event_key="",
                )
                for r in rows
            ]
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_event_key(self, event: TeamsEvent) -> str:
        return (
            f"{event.event_type}:{event.tournament_id}:{event.match_id or 0}"
        )

    def _check_idempotency(self, event_key: str) -> Optional[TeamsPostResult]:
        now = datetime.now(timezone.utc)
        cached = _IDEMPOTENCY_CACHE.get(event_key)
        if cached and cached.posted_at:
            age = (now - cached.posted_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age < _IDEMPOTENCY_TTL_SECONDS:
                return cached
        return None

    def _store_idempotency(self, event_key: str, result: TeamsPostResult):
        _IDEMPOTENCY_CACHE[event_key] = result

    def _enforce_cooldown(self, event_type: str, tournament_id: int) -> bool:
        cool_key = f"{event_type}:{tournament_id}"
        now = datetime.now(timezone.utc)
        last = _COOLDOWN_CACHE.get(cool_key)
        if last and (now - last).total_seconds() < settings.TEAMS_POST_COOLDOWN_SECONDS:
            return False
        _COOLDOWN_CACHE[cool_key] = now
        return True

    def _send(
        self,
        event: TeamsEvent,
        actor: str,
        event_key: str,
        payload: Dict[str, Any],
        channel_note: str,
    ) -> TeamsPostResult:
        webhook_url = (settings.TEAMS_WEBHOOK_URL or "").strip()

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10,
            )

            posted_at = datetime.now(timezone.utc)

            if response.status_code in (200, 202):
                result = TeamsPostResult(
                    success=True,
                    status="success",
                    message="Posted successfully.",
                    event_key=event_key,
                    posted_at=posted_at,
                )
                self._store_idempotency(event_key, result)
                self._persist_success(event, actor, event_key, posted_at, response.status_code)
                return result

            error_text = response.text[:500] if response.text else f"HTTP {response.status_code}"
            result = TeamsPostResult(
                success=False,
                status="failed",
                message=f"HTTP {response.status_code}: {error_text}",
                event_key=event_key,
                posted_at=posted_at,
            )
            self._persist_failure(event, actor, event_key, result.message)
            return result

        except requests.exceptions.Timeout:
            return TeamsPostResult(
                success=False,
                status="failed",
                message="Request timed out after 10s.",
                event_key=event_key,
            )
        except requests.exceptions.RequestException as e:
            return TeamsPostResult(
                success=False,
                status="failed",
                message=f"Network error: {e}",
                event_key=event_key,
            )
        except Exception as e:
            logger.exception("Unexpected error posting to Teams")
            return TeamsPostResult(
                success=False,
                status="failed",
                message=f"Unexpected error: {e}",
                event_key=event_key,
            )

    def _persist_success(self, event: TeamsEvent, actor: str, event_key: str, posted_at: datetime, status_code: int):
        db = SessionLocal()
        try:
            text = f"**{event.title}**\n\n{event.body}"
            create_announcement(
                db,
                message=text,
                match_id=event.match_id,
                tournament_id=event.tournament_id,
                channel="teams",
            )
            log_audit(
                db,
                action="teams_post",
                entity_type="teams_post",
                entity_id=None,
                payload={
                    "event_type": event.event_type,
                    "event_key": event_key,
                    "posted_at": posted_at.isoformat(),
                    "actor": actor,
                    "status_code": status_code,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist successful Teams post")
        finally:
            db.close()

    def _persist_failure(self, event: TeamsEvent, actor: str, event_key: str, error_message: str):
        db = SessionLocal()
        try:
            text = f"**{event.title}**\n\n{event.body}"
            ann = create_announcement(
                db,
                message=text,
                match_id=event.match_id,
                tournament_id=event.tournament_id,
                channel="teams",
            )
            ann.sent_status = "failed"
            ann.error = error_message[:500]
            db.commit()

            log_audit(
                db,
                action="teams_post_failed",
                entity_type="teams_post",
                entity_id=ann.id,
                payload={
                    "event_type": event.event_type,
                    "event_key": event_key,
                    "actor": actor,
                    "error": error_message[:500],
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist failed Teams post")
        finally:
            db.close()


# Singleton instance
teams_publisher = TeamsPublisher()
