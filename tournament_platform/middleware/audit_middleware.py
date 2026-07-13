"""
Audit Middleware

Provides decorators and context managers for automatically logging
audit entries for write operations.
"""

from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager

from sqlalchemy.orm import Session

from tournament_platform.services.audit_service import log_structured


def audit_write(
    action: str,
    entity_type: str,
    actor: str = "system",
    tournament_id: Optional[int] = None,
    match_id: Optional[int] = None,
):
    """
    Decorator to automatically log audit entries for write operations.

    Args:
        action: The action being performed
        entity_type: The type of entity being modified
        actor: Who performed the action
        tournament_id: Optional tournament ID
        match_id: Optional match ID

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(db: Session, *args, **kwargs) -> Any:
            result = func(db, *args, **kwargs)

            try:
                log_structured(
                    db,
                    action=action,
                    entity_type=entity_type,
                    entity_id=kwargs.get("entity_id"),
                    actor=actor,
                    tournament_id=tournament_id,
                    match_id=match_id,
                    after=kwargs.get("payload"),
                )
            except Exception:
                pass

            return result
        return wrapper
    return decorator


@contextmanager
def audit_context(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    actor: str = "system",
    tournament_id: Optional[int] = None,
    match_id: Optional[int] = None,
    before: Optional[Dict[str, Any]] = None,
):
    """
    Context manager for logging audit entries around a write operation.

    Usage:
        with audit_context(db, "update_match", "match", entity_id=1) as ctx:
            # perform write operation
            ctx["after"] = {"status": "completed"}
    """
    ctx: Dict[str, Any] = {"before": before, "after": None}

    try:
        yield ctx
    except Exception as e:
        ctx["error"] = str(e)
        raise
    finally:
        try:
            log_structured(
                db,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor=actor,
                tournament_id=tournament_id,
                match_id=match_id,
                before=ctx.get("before"),
                after=ctx.get("after"),
                metadata={"error": ctx.get("error")} if ctx.get("error") else None,
            )
        except Exception:
            pass
