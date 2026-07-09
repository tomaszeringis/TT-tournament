"""
Voice Event Audit / Observability (Phase 1)

A lightweight, in-memory ring buffer of structured voice events plus optional
file logging. This is the foundation for Phase 9 (full observability/operations)
and is safe to use anywhere in the pipeline.

Design notes:
- Stores the hardened `VoiceScoreEvent` (timestamp, source, confidence, etc.).
- Records the scoring outcome (accepted/rejected, previous/new score) so
  operators can later diagnose *why* a score changed.
- Gated by `VOICE_DEBUG_EVENTS` in the UI; the logger itself is always safe.
- No audio or transcripts are persisted unless an explicit file path is given.
"""

import json
import logging
import time
from collections import deque
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from tournament_platform.app.services.voice_parser import VoiceScoreEvent

logger = logging.getLogger(__name__)

DEFAULT_MAX_EVENTS = 200


class EventLogger:
    """Stores recent voice events for debugging and audit export."""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS, file_path: Optional[str] = None):
        self._max_events = max_events
        self._events: deque = deque(maxlen=max_events)
        self._file_path = file_path

    def record(
        self,
        event: VoiceScoreEvent,
        *,
        accepted: bool,
        previous_score: str = "",
        new_score: str = "",
        note: str = "",
    ) -> None:
        """Record a voice event together with its scoring outcome.

        Args:
            event: The hardened voice event produced by the parser/pipeline.
            accepted: Whether the score state machine applied the event.
            previous_score: Score string before the action (e.g., "5-3").
            new_score: Score string after the action (e.g., "6-3").
            note: Free-text note (e.g., rejection reason or warning).
        """
        entry = self._to_dict(event)
        entry.update(
            {
                "accepted": accepted,
                "previous_score": previous_score,
                "new_score": new_score,
                "note": note,
                "logged_at": time.time(),
            }
        )
        self._events.append(entry)
        if self._file_path:
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
            except OSError as e:
                logger.warning("Failed to write voice event log: %s", e)

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent events (oldest first within the window)."""
        events = list(self._events)
        return events[-limit:]

    def clear(self) -> None:
        """Clear retained events from memory."""
        self._events.clear()

    def export(self) -> List[Dict[str, Any]]:
        """Export all retained events (for per-match audit export)."""
        return list(self._events)

    @staticmethod
    def _to_dict(event: VoiceScoreEvent) -> Dict[str, Any]:
        if is_dataclass(event):
            return asdict(event)
        return dict(event)
