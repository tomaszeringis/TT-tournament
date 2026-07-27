"""Phase 0: Latency event tracing with bounded history."""

import time
import threading
import uuid
import csv
import io
import json
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import deque


def _validate_history_size(size: int) -> int:
    """Clamp history size to the safe range 20-2000."""
    if size < 20:
        return 20
    if size > 2000:
        return 2000
    return size


# Module-level bounded history (thread-safe via GIL for append, maxlen prevents unbounded growth)
_DEFAULT_MAXLEN = 200
_LATENCY_EVENTS: deque["LatencyEvent"] = deque(maxlen=_DEFAULT_MAXLEN)
_events_lock = threading.Lock()


def _get_configured_maxlen() -> int:
    """Read VOICE_LATENCY_HISTORY_SIZE from settings with validation."""
    from tournament_platform.services.settings import VOICE_LATENCY_HISTORY_SIZE
    return _validate_history_size(VOICE_LATENCY_HISTORY_SIZE)


def resize_history(new_maxlen: int) -> None:
    """Resize the bounded history deque, preserving existing events."""
    global _LATENCY_EVENTS
    new_maxlen = _validate_history_size(new_maxlen)
    with _events_lock:
        old_events = list(_LATENCY_EVENTS)
        _LATENCY_EVENTS = deque(old_events, maxlen=new_maxlen)


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile from a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


@dataclass(frozen=True)
class LatencyEvent:
    """Immutable record of a latency-measured operation."""
    trace_id: str
    action_id: str
    match_id: Optional[int]
    source: str  # manual, voice, quick_voice, push_to_talk, continuous_voice
    stage: str   # button_click, score_apply, db_persist, tts_enqueue, etc.
    started_ns: int
    finished_ns: int
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        return (self.finished_ns - self.started_ns) / 1_000_000


def start_span(
    source: str,
    stage: str,
    action_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    match_id: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Start a new latency span. Returns a span context dict."""
    if trace_id is None:
        trace_id = str(uuid.uuid4())
    if action_id is None:
        action_id = str(uuid.uuid4())
    return {
        "trace_id": trace_id,
        "action_id": action_id,
        "match_id": match_id,
        "source": source,
        "stage": stage,
        "started_ns": time.perf_counter_ns(),
        "metadata": metadata or {},
    }


def finish_span(span: dict[str, Any], success: bool = True, metadata: Optional[dict[str, Any]] = None) -> None:
    """Finish a span and record it if tracing is enabled."""
    from tournament_platform.services.settings import VOICE_LATENCY_TRACE
    if not VOICE_LATENCY_TRACE:
        return
    finished_ns = time.perf_counter_ns()
    merged_meta = dict(span.get("metadata", {}))
    if metadata:
        merged_meta.update(metadata)
    event = LatencyEvent(
        trace_id=span["trace_id"],
        action_id=span["action_id"],
        match_id=span.get("match_id"),
        source=span["source"],
        stage=span["stage"],
        started_ns=span["started_ns"],
        finished_ns=finished_ns,
        success=success,
        metadata=merged_meta,
    )
    with _events_lock:
        _LATENCY_EVENTS.append(event)


def record_duration(
    trace_id: str,
    action_id: str,
    match_id: Optional[int],
    source: str,
    stage: str,
    started_ns: int,
    finished_ns: int,
    success: bool,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Record a completed latency event directly."""
    from tournament_platform.services.settings import VOICE_LATENCY_TRACE
    if not VOICE_LATENCY_TRACE:
        return
    event = LatencyEvent(
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
    with _events_lock:
        _LATENCY_EVENTS.append(event)


def get_recent_spans(limit: int = 20, source: Optional[str] = None, stage: Optional[str] = None) -> list[dict[str, Any]]:
    """Get recent latency events as dicts for diagnostics display."""
    with _events_lock:
        events = list(_LATENCY_EVENTS)

    if source is not None:
        events = [e for e in events if e.source == source]
    if stage is not None:
        events = [e for e in events if e.stage == stage]

    events = events[-limit:]

    return [
        {
            "trace_id": e.trace_id[:8],
            "action_id": e.action_id[:8],
            "match_id": e.match_id,
            "source": e.source,
            "stage": e.stage,
            "duration_ms": round(e.duration_ms, 1),
            "success": e.success,
            "metadata": e.metadata if e.metadata else {},
        }
        for e in events
    ]


def get_summary(source: Optional[str] = None, stage: Optional[str] = None) -> dict[str, Any]:
    """Calculate summary statistics for filtered events."""
    with _events_lock:
        events = list(_LATENCY_EVENTS)

    filtered = [
        e for e in events
        if (source is None or e.source == source) and (stage is None or e.stage == stage)
    ]

    if not filtered:
        return {
            "count": 0,
            "latest_ms": 0.0,
            "min_ms": 0.0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }

    durations = [e.duration_ms for e in filtered]
    durations_sorted = sorted(durations)
    n = len(durations_sorted)

    return {
        "count": n,
        "latest_ms": round(durations_sorted[-1], 1),
        "min_ms": round(durations_sorted[0], 1),
        "mean_ms": round(sum(durations) / n, 1),
        "median_ms": round(durations_sorted[n // 2], 1),
        "p50_ms": round(percentile(durations, 50), 1),
        "p95_ms": round(percentile(durations, 95), 1),
        "max_ms": round(max(durations), 1),
    }


def get_all_sources() -> list[str]:
    """Return the set of sources currently in the history."""
    with _events_lock:
        return sorted(set(e.source for e in _LATENCY_EVENTS))


def get_all_stages() -> list[str]:
    """Return the set of stages currently in the history."""
    with _events_lock:
        return sorted(set(e.stage for e in _LATENCY_EVENTS))


def get_span_count() -> int:
    """Return the total number of recorded spans."""
    with _events_lock:
        return len(_LATENCY_EVENTS)


def get_failed_count() -> int:
    """Return the number of failed spans."""
    with _events_lock:
        return sum(1 for e in _LATENCY_EVENTS if not e.success)


def get_history_maxlen() -> int:
    """Return the current bounded history maxlen."""
    with _events_lock:
        return _LATENCY_EVENTS.maxlen


def clear_history() -> None:
    """Clear all recorded latency events."""
    with _events_lock:
        _LATENCY_EVENTS.clear()


def export_json() -> str:
    """Export all recorded events as a JSON string with safe metadata only."""
    with _events_lock:
        events = list(_LATENCY_EVENTS)
    records = [
        {
            "trace_id": e.trace_id,
            "action_id": e.action_id,
            "match_id": e.match_id,
            "source": e.source,
            "stage": e.stage,
            "started_ns": e.started_ns,
            "finished_ns": e.finished_ns,
            "duration_ms": round(e.duration_ms, 3),
            "success": e.success,
            "metadata": {k: v for k, v in e.metadata.items() if isinstance(v, (str, int, float, bool, type(None)))}
            if e.metadata else {},
        }
        for e in events
    ]
    return json.dumps(records, indent=2, default=str)


def export_csv() -> str:
    """Export all recorded events as a CSV string with safe metadata only."""
    with _events_lock:
        events = list(_LATENCY_EVENTS)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["trace_id", "action_id", "match_id", "source", "stage", "started_ns", "finished_ns", "duration_ms", "success", "metadata"])
    for e in events:
        safe_meta = {k: v for k, v in e.metadata.items() if isinstance(v, (str, int, float, bool, type(None)))} if e.metadata else {}
        writer.writerow([
            e.trace_id,
            e.action_id,
            e.match_id or "",
            e.source,
            e.stage,
            e.started_ns,
            e.finished_ns,
            round(e.duration_ms, 3),
            e.success,
            json.dumps(safe_meta, default=str),
        ])
    return output.getvalue()


# Backward-compatible aliases
record_latency = record_duration
latency_stats = get_summary
recent_events = get_recent_spans