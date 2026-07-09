"""
Voice Event Repository

SQLAlchemy-backed persistence for voice scoring events and dataset samples.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from tournament_platform.models import SessionLocal, VoiceEvent, VoiceCommand
from tournament_platform.services.settings import VOICE_RETENTION_DAYS

logger = logging.getLogger(__name__)


class VoiceEventRepository:
    """Persist and query voice scoring events."""

    @staticmethod
    def _session():
        return SessionLocal()

    @classmethod
    def record(cls, payload: Dict[str, Any], db: Any = None) -> VoiceEvent:
        """Insert a new voice event."""
        close = False
        if db is None:
            db = cls._session()
            close = True
        try:
            event = VoiceEvent(
                match_id=payload.get("match_id"),
                intent=payload.get("intent", ""),
                raw_transcript=payload.get("raw_transcript", ""),
                normalized_text=payload.get("normalized_text", ""),
                parsed_slots=json.dumps(payload.get("slots", {})) if payload.get("slots") else None,
                confidence=float(payload.get("confidence", 0.0)),
                asr_latency_ms=payload.get("asr_latency_ms"),
                noise_rms=payload.get("noise_rms"),
                score_before=payload.get("predicted_score_before") or payload.get("score_before"),
                score_after=payload.get("predicted_score_after") or payload.get("score_after"),
                status=payload.get("status", "pending_confirm"),
                disposition=payload.get("disposition"),
                source=payload.get("source", "asr"),
                speaker_label=payload.get("speaker_label"),
                created_at=payload.get("created_at") or datetime.utcnow(),
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            return event
        except Exception as exc:
            db.rollback()
            logger.error("Failed to record voice event: %s", exc)
            raise
        finally:
            if close:
                db.close()

    @classmethod
    def get_by_match(cls, match_id: int, limit: int = 100, db: Any = None) -> List[VoiceEvent]:
        close = False
        if db is None:
            db = cls._session()
            close = True
        try:
            return (
                db.query(VoiceEvent)
                .filter(VoiceEvent.match_id == match_id)
                .order_by(VoiceEvent.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            if close:
                db.close()

    @classmethod
    def mark_undone(cls, event_id: int, undone_by_event_id: int, db: Any = None) -> None:
        close = False
        if db is None:
            db = cls._session()
            close = True
        try:
            event = db.query(VoiceEvent).filter(VoiceEvent.id == event_id).first()
            if event:
                event.status = "undone"
                event.undone_by = undone_by_event_id
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Failed to mark voice event undone: %s", exc)
        finally:
            if close:
                db.close()

    @classmethod
    def cleanup_old(cls, db: Any = None) -> int:
        if VOICE_RETENTION_DAYS <= 0:
            return 0
        close = False
        if db is None:
            db = cls._session()
            close = True
        cutoff = datetime.utcnow() - timedelta(days=VOICE_RETENTION_DAYS)
        try:
            deleted = (
                db.query(VoiceEvent)
                .filter(VoiceEvent.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted
        except Exception as exc:
            db.rollback()
            logger.error("Failed to cleanup old voice events: %s", exc)
            return 0
        finally:
            if close:
                db.close()


class VoiceCommandRepository:
    """Persist and query dataset recorder samples."""

    @staticmethod
    def _session():
        return SessionLocal()

    @classmethod
    def record(cls, payload: Dict[str, Any], db: Any = None) -> VoiceCommand:
        close = False
        if db is None:
            db = cls._session()
            close = True
        try:
            cmd = VoiceCommand(
                match_id=payload.get("match_id"),
                transcript=payload.get("transcript", ""),
                parsed_intent=payload.get("parsed_intent"),
                expected_intent=payload.get("expected_intent"),
                matched=payload.get("matched"),
                correction=payload.get("correction"),
                match_context=json.dumps(payload.get("match_context")) if payload.get("match_context") else None,
                mic_type=payload.get("mic_type"),
                noise_condition=payload.get("noise_condition"),
                audio_stored=bool(payload.get("audio_stored", False)),
                created_at=datetime.utcnow(),
            )
            db.add(cmd)
            db.commit()
            db.refresh(cmd)
            return cmd
        except Exception as exc:
            db.rollback()
            logger.error("Failed to record voice command sample: %s", exc)
            raise
        finally:
            if close:
                db.close()
