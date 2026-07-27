"""
Side-effect queue for deferred commentary/TTS/DB operations.
Uses small primitive snapshots only — no heavy objects in session state.
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from queue import Queue


@dataclass(frozen=True)
class ScoreMutationEvent:
    """Immutable event capturing a score change for later side-effect processing."""
    action_id: str
    match_id: Optional[int]
    match_epoch: str
    revision: int
    source: str  # manual, voice, quick_voice
    action_type: str
    state_before: Dict[str, Any]
    state_after: Dict[str, Any]
    commentary_settings: Dict[str, Any]
    created_at: float


class SideEffectQueue:
    """Bounded side-effect queue for deferred commentary/TTS/DB operations."""

    def __init__(self, maxlen: int = 50):
        self._queue: Queue[ScoreMutationEvent] = Queue(maxsize=maxlen)
        self._epoch = "1"

    def enqueue(
        self,
        source: str,
        action_type: str,
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        match_id: Optional[int] = None,
        match_epoch: Optional[str] = None,
        revision: Optional[int] = None,
        commentary_settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add an event to the queue. Returns the action_id."""
        action_id = str(uuid.uuid4())
        event = ScoreMutationEvent(
            action_id=action_id,
            match_id=match_id,
            match_epoch=match_epoch or self._epoch,
            revision=revision or int(time.time() * 1000) % 1_000_000,
            source=source,
            action_type=action_type,
            state_before=state_before,
            state_after=state_after,
            commentary_settings=commentary_settings or {},
            created_at=time.time(),
        )
        try:
            self._queue.put_nowait(event)
        except Exception:
            pass  # Queue full, drop oldest
        return action_id

    def drain(self, target_epoch: Optional[str] = None) -> List[ScoreMutationEvent]:
        """Remove all events for the current epoch and return them."""
        events = []
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                if target_epoch is None or event.match_epoch == target_epoch:
                    events.append(event)
            except Exception:
                break
        return events

    def clear(self) -> None:
        """Clear all pending events."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    def increment_epoch(self) -> None:
        """Bump epoch to invalidate stale events after reset/match switch."""
        current = int(self._epoch)
        self._epoch = str(current + 1)

    @property
    def size(self) -> int:
        """Current queue size."""
        return self._queue.qsize()

    @property
    def pending_count(self) -> int:
        """Alias for size, for UI display."""
        return self._queue.qsize()