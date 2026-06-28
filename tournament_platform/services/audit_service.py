"""
Audit service for logging operator state-changing actions.

This service provides a safe, non-crashing way to log all operator actions
for audit trail purposes. Failures are logged but do not interrupt the main action.
"""

import json
import logging
from typing import Optional, Any, Dict, List

from sqlalchemy.orm import Session

from tournament_platform.models import AuditLog

logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    actor: str = "operator",
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """
    Log an operator action to the audit trail.

    This function never raises exceptions - failures are logged and None is returned.

    Args:
        db: SQLAlchemy database session
        action: The action performed (e.g., "call_match", "reschedule_match")
        entity_type: The type of entity affected (e.g., "match", "tournament")
        entity_id: The ID of the entity affected (optional)
        actor: Who performed the action (default: "operator")
        payload: Additional data about the action (optional, will be JSON serialized)

    Returns:
        The created AuditLog entry, or None if logging failed
    """
    try:
        payload_json = None
        if payload is not None:
            try:
                payload_json = json.dumps(payload)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to serialize audit payload: {e}")
                payload_json = str(payload)  # Fallback to string representation

        audit_entry = AuditLog(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_json=payload_json,
        )
        db.add(audit_entry)
        db.commit()
        db.refresh(audit_entry)
        logger.info(f"Audit log created: {action} on {entity_type} {entity_id}")
        return audit_entry

    except Exception as e:
        # Never crash the main action - just log the failure
        logger.error(f"Failed to create audit log entry: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def get_audit_logs(
    db: Session,
    limit: int = 100,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve audit log entries.

    Args:
        db: SQLAlchemy database session
        limit: Maximum number of entries to return (default: 100)
        entity_type: Filter by entity type (optional)
        entity_id: Filter by entity ID (optional)

    Returns:
        List of audit log entries as dictionaries
    """
    try:
        query = db.query(AuditLog)
        if entity_type is not None:
            query = query.filter(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            query = query.filter(AuditLog.entity_id == entity_id)
        entries = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
        # Convert to dictionaries for consistent API
        result = []
        for entry in entries:
            payload = None
            if entry.payload_json:
                try:
                    payload = json.loads(entry.payload_json)
                except (json.JSONDecodeError, TypeError):
                    payload = entry.payload_json
            result.append({
                "id": entry.id,
                "action": entry.action,
                "actor": entry.actor,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "payload": payload,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            })
        return result
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}", exc_info=True)
        return []