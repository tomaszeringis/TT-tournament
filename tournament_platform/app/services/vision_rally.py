"""
Rally State Machine — deterministic, event-driven rally lifecycle.

States:
    IDLE -> SERVING -> ACTIVE -> ENDED -> IDLE
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from tournament_platform.app.services.vision_events import VisionEvent, VisionEventType

logger = logging.getLogger(__name__)


class RallyState(str, Enum):
    IDLE = "idle"
    SERVING = "serving"
    ACTIVE = "active"
    ENDED = "ended"


@dataclass
class RallyContext:
    rally_id: str
    state: RallyState = RallyState.IDLE
    start_monotonic: float = 0.0
    start_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_monotonic: float = 0.0
    end_utc: Optional[datetime] = None
    events: List[VisionEvent] = field(default_factory=list)
    point_count: int = 0

    def to_dict(self) -> dict:
        return {
            "rally_id": self.rally_id,
            "state": self.state.value,
            "start_monotonic": self.start_monotonic,
            "start_utc": self.start_utc.isoformat(),
            "end_monotonic": self.end_monotonic,
            "end_utc": self.end_utc.isoformat() if self.end_utc else None,
            "events": [e.event_type.value for e in self.events],
            "point_count": self.point_count,
        }


class RallyStateMachine:
    """Event-driven rally state machine."""

    def __init__(self, rally_id: str) -> None:
        self._ctx = RallyContext(rally_id=rally_id)

    @property
    def context(self) -> RallyContext:
        return self._ctx

    def feed(self, event: VisionEvent) -> None:
        self._ctx.events.append(event)
        if self._ctx.state == RallyState.IDLE:
            if event.event_type == VisionEventType.RALLY_STARTED:
                self._ctx.state = RallyState.ACTIVE
                self._ctx.start_monotonic = event.monotonic_timestamp
                self._ctx.start_utc = event.utc_timestamp
        elif self._ctx.state == RallyState.ACTIVE:
            if event.event_type == VisionEventType.BOUNCE:
                self._ctx.point_count += 1
            elif event.event_type == VisionEventType.RALLY_ENDED:
                self._ctx.state = RallyState.ENDED
                self._ctx.end_monotonic = event.monotonic_timestamp
                self._ctx.end_utc = event.utc_timestamp
        elif self._ctx.state == RallyState.ENDED:
            if event.event_type == VisionEventType.RALLY_STARTED:
                self._ctx = RallyContext(rally_id=self._ctx.rally_id)
                self._ctx.state = RallyState.ACTIVE
                self._ctx.start_monotonic = event.monotonic_timestamp
                self._ctx.start_utc = event.utc_timestamp
