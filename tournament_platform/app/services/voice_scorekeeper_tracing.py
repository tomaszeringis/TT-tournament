"""Voice Scorekeeper latency instrumentation helpers."""

import time
from typing import Optional, Dict, Any
from contextlib import contextmanager

from tournament_platform.app.services.latency_trace import (
    start_span,
    finish_span,
    record_duration,
)
from tournament_platform.services.settings import VOICE_LATENCY_TRACE


@contextmanager
def trace_span(source: str, stage: str, action_id: Optional[str] = None, trace_id: Optional[str] = None, match_id: Optional[int] = None, metadata: Optional[Dict[str, Any]] = None):
    """Context manager for tracing a span."""
    span = start_span(
        source=source,
        stage=stage,
        action_id=action_id,
        trace_id=trace_id,
        match_id=match_id,
        metadata=metadata,
    )
    success = True
    error = None
    try:
        yield span
    except Exception as exc:
        error = exc
        success = False
        raise
    finally:
        finish_span(span, success=success, metadata={"error": str(error)} if error else None)


def record_if_enabled(trace_id: str, action_id: str, source: str, stage: str, started_ns: int, finished_ns: int, success: bool, match_id: Optional[int] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Record latency event if tracing is enabled."""
    if not VOICE_LATENCY_TRACE:
        return
    record_duration(
        trace_id=trace_id,
        action_id=action_id,
        match_id=match_id,
        source=source,
        stage=stage,
        started_ns=started_ns,
        finished_ns=finished_ns,
        success=success,
        metadata=metadata or {},
    )
