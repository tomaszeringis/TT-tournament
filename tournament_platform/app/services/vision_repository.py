"""
Vision Event Repository — persistence for vision_events table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from tournament_platform.models import SessionLocal, VisionEvent as DBVisionEvent
from tournament_platform.app.services.vision_events import (
    BallObservation,
    CandidateStatus,
    PointCandidate,
    VisionEvent,
    VisionEventType,
)

logger = logging.getLogger(__name__)


@dataclass
class VisionEventRepository:
    """Persist and query vision events."""

    def record_event(self, event: VisionEvent, match_id: Optional[int] = None) -> DBVisionEvent:
        """Persist a VisionEvent to the database."""
        db = SessionLocal()
        try:
            db_event = DBVisionEvent(
                match_id=match_id,
                event_type=event.event_type.value,
                ball_x=event.x,
                ball_y=event.y,
                confidence=event.confidence,
                monotonic_timestamp=event.monotonic_timestamp,
                utc_timestamp=event.utc_timestamp,
                detected_events_json=None,
                source="upload",
            )
            db.add(db_event)
            db.commit()
            db.refresh(db_event)
            return db_event
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to persist vision event: %s", exc)
            raise
        finally:
            db.close()

    def record_point_candidate(self, candidate: PointCandidate, match_id: Optional[int] = None) -> DBVisionEvent:
        """Persist a PointCandidate as a POINT_CANDIDATE event."""
        db = SessionLocal()
        try:
            db_event = DBVisionEvent(
                match_id=match_id or candidate.match_id,
                rally_id=candidate.rally_id,
                candidate_id=candidate.candidate_id,
                event_type="POINT_CANDIDATE",
                suggested_winner=candidate.suggested_winner,
                confidence=candidate.confidence,
                status=candidate.status.value,
                monotonic_timestamp=candidate.monotonic_timestamp,
                utc_timestamp=candidate.utc_timestamp,
                detected_events_json=None,
                source="upload",
            )
            db.add(db_event)
            db.commit()
            db.refresh(db_event)
            return db_event
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to persist point candidate: %s", exc)
            raise
        finally:
            db.close()

    def list_events_for_match(self, match_id: int, limit: int = 100) -> List[DBVisionEvent]:
        """Return recent vision events for a match."""
        db = SessionLocal()
        try:
            return (
                db.query(DBVisionEvent)
                .filter(DBVisionEvent.match_id == match_id)
                .order_by(DBVisionEvent.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            db.close()
